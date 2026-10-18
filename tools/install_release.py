#!/usr/bin/env python3
"""Prepare a new independent installation; never stop/start a service implicitly."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from credentials import load_credentials
from nvr_config import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = Path.home() / ".local/share/oogies"


def reject_symlinks(path, *, recursive=True):
    for item in (path, *path.parents):
        if item.is_symlink(): raise ValueError("State paths must not contain symlinks")
    if recursive and path.is_dir() and any(item.is_symlink() for item in path.rglob("*")):
        raise ValueError("State must not contain symlinks")


def require_stopped(source):
    """Refuse state copied from a running container, including parent bind mounts."""
    identifiers = subprocess.check_output(["docker", "ps", "--quiet"], text=True).split()
    if not identifiers: return
    containers = json.loads(subprocess.check_output(["docker", "inspect", *identifiers], text=True))
    source = source.resolve()
    for container in containers:
        for mount in container.get("Mounts", []):
            if mount.get("Type") != "bind": continue
            mounted = Path(mount["Source"]).resolve()
            if mounted == source or mounted in source.parents or source in mounted.parents:
                raise ValueError("Stop containers using the source state before preparing an installation")


def validate_state(source):
    reject_symlinks(source, recursive=False)
    for name in ("nvr-config.json", "nvr-credentials.json", "exports"):
        reject_symlinks(source / name)
    load_config(source / "nvr-config.json")
    load_credentials(source / "nvr-credentials.json")
    manifest = source / "exports/jobs.json"
    if not manifest.exists():
        if (source / "exports").exists() and any((source / "exports").iterdir()):
            raise ValueError("Export storage has files but no manifest")
        return {}
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("jobs"), list):
        raise ValueError("Unsupported export manifest")
    hashes = {}
    for job in data["jobs"]:
        if not isinstance(job, dict): raise ValueError("Invalid export manifest entry")
        if job.get("state") in ("queued", "running"):
            raise ValueError("Finish or cancel pending exports before cutover")
        identifier = job.get("id", "")
        if not re.fullmatch(r"[a-f0-9]{32}", identifier): raise ValueError("Invalid export identifier")
        if job.get("state") == "ready":
            clip = source / "exports" / identifier / "clip.mp4"
            if not clip.is_file(): raise ValueError("A ready export file is missing")
            with clip.open("rb") as file:
                digest = hashlib.sha256()
                for chunk in iter(lambda: file.read(1024 * 1024), b""): digest.update(chunk)
            hashes[identifier] = digest.hexdigest()
    return hashes


def prepare_installation(source, directory, image, *, port=8088, project="oogies"):
    source, directory = Path(os.path.abspath(source)), Path(os.path.abspath(directory))
    reject_symlinks(directory)
    if directory.exists(): raise ValueError("Installation directory already exists; refusing to replace state")
    if ROOT == directory or ROOT in directory.parents:
        raise ValueError("Choose an installation directory outside the development checkout")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image): raise ValueError("Use the resolved local image ID")
    if not 1024 <= port <= 65535: raise ValueError("Choose a port from 1024 to 65535")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project): raise ValueError("Invalid Compose project name")
    if os.getuid() == 0: raise ValueError("Prepare the installation as the normal Docker user, without sudo")
    if source == directory or directory in source.parents or source in directory.parents:
        raise ValueError("Source and installation state must be separate")
    require_stopped(source)
    hashes = validate_state(source)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".oogies-prepare-", dir=directory.parent) as temporary:
        staged = Path(temporary) / "installation"; staged.mkdir(mode=0o700)
        state = staged / ".local"; state.mkdir(mode=0o700)
        for name in ("nvr-config.json", "nvr-credentials.json"):
            shutil.copyfile(source / name, state / name); (state / name).chmod(0o600)
        if (source / "exports").is_dir(): shutil.copytree(source / "exports", state / "exports")
        else: (state / "exports").mkdir(mode=0o700)
        for item in (state / "exports", *(state / "exports").rglob("*")):
            item.chmod(0o700 if item.is_dir() else 0o600)
        (state / "output").mkdir(mode=0o700)
        if validate_state(state) != hashes: raise ValueError("Export copy verification failed")
        shutil.copyfile(ROOT / "docker/release/compose.yaml", staged / "compose.yaml")
        (staged / ".env").write_text(f"OOGIES_IMAGE={image}\nOOGIES_UID={os.getuid()}\nOOGIES_GID={os.getgid()}\nOOGIES_PORT={port}\nOOGIES_PROJECT={project}\n")
        (staged / ".env").chmod(0o600)
        record = dict(image_id=image, ready_exports=hashes, port=port, project=project)
        (state / "installation.json").write_text(json.dumps(record, indent=2)+"\n")
        (state / "installation.json").chmod(0o600)
        if directory.exists(): raise ValueError("Installation directory appeared during preparation")
        staged.rename(directory)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--source-state", type=Path, default=ROOT / ".local")
    parser.add_argument("--image", help="Local image reference; defaults to the last build's exact ID")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--project", default="oogies")
    args = parser.parse_args(argv)
    try:
        subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL, check=True)
        image = args.image or json.loads((ROOT / ".local/releases/last-build.json").read_text())["image_id"]
        inspected = json.loads(subprocess.check_output(["docker", "image", "inspect", image], text=True))[0]
        if inspected.get("Os") != "linux" or inspected.get("Architecture") != "amd64":
            raise ValueError("Installation requires a Linux amd64 release image")
        profile = inspected.get("Config", {}).get("Labels", {}).get("oogies.sdk-profile")
        if profile != load_config(args.source_state / "nvr-config.json")["sdk_profile"]:
            raise ValueError("Release image and recorder SDK profiles differ")
        image = inspected["Id"]
        result = prepare_installation(args.source_state, args.directory, image, port=args.port, project=args.project)
        print(f"Installation prepared; {len(result['ready_exports'])} ready exports verified. No service started.")
        print("Run docker compose up -d --wait from the installation directory.")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Never echo configuration/credential contents or raw Docker diagnostics.
        parser.exit(1, f"Installation preparation failed ({type(error).__name__}). {error if isinstance(error, ValueError) else 'Check source state, Docker access and image availability.'}\n")
    return 0


if __name__ == "__main__": sys.exit(main())
