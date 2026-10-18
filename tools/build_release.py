#!/usr/bin/env python3
"""Build a local release from an explicit tar context; never send the checkout."""

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid

from sdk_adapters import DEFAULT_SDK_ID

ROOT = Path(__file__).resolve().parents[1]
SDK_ARCHIVE = "vendor/hikvision/EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip"
SDK_SHA256 = "8de553fb2e8dbb0ac441ee1bd73c5ecb73d720c1359396750479a6e169abf93f"
APP_MODULES = (
    "browser_server.py", "export_encoder.py", "export_jobs.py", "grid_server.py", "grid_worker.py",
    "history_timeline.py", "live_sessions.py", "live_sources.py", "maintenance.py",
    "playback_sessions.py", "recorder_time.py", "service_errors.py", "stream_budget.py",
)
NATIVE_SOURCES = (
    "live_grid.cpp", "export_capture.h", "history_queries.h", "history_playback.h",
    "live_source_limits.h", "playback_buffer.h",
)
SUPPORT_MODULES = ("credentials.py", "nvr_config.py", "sdk_adapters/__init__.py", "sdk_adapters/hcnet_61948.py")


def source_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Build input must be a relative file within the checkout")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink(): raise ValueError(f"Symlink is not a release input: {relative}")
    if not path.is_file(): raise ValueError(f"Release input missing: {relative}")
    return path


def validate_archive(path, expected=SDK_SHA256):
    with path.open("rb") as archive:
        digest = hashlib.file_digest(archive, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else None
    if digest is None:
        checksum = hashlib.sha256()
        with path.open("rb") as archive:
            for chunk in iter(lambda: archive.read(1024 * 1024), b""): checksum.update(chunk)
        digest = checksum.hexdigest()
    if digest != expected:
        raise ValueError("SDK archive checksum mismatch; retrieve the verified SDK with git lfs pull")


def build_metadata(root, version=None):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root))
    version = version or f"dev-{revision[:12]}" + ("-dirty" if dirty else "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", version):
        raise ValueError("Use a version containing only letters, digits, dot, underscore and hyphen")
    return dict(version=version, revision=revision, dirty=dirty, sdk_profile=DEFAULT_SDK_ID,
                platform="linux/amd64", sdk_archive_sha256=SDK_SHA256)


def context_inputs(root):
    inputs = {"Dockerfile":"docker/release/Dockerfile", "sdk.zip":SDK_ARCHIVE,
              "vendor-README.md":"vendor/hikvision/README.md"}
    inputs.update({"app/"+name:"docker/hikvision-sdk/"+name for name in APP_MODULES})
    inputs.update({"native/"+name:"docker/hikvision-sdk/"+name for name in NATIVE_SOURCES})
    inputs.update({"support/"+name:"tools/"+name for name in SUPPORT_MODULES})
    # The HTTP asset allowlist is the authoritative set of public frontend files.
    tree = ast.parse(source_file(root, "docker/hikvision-sdk/grid_server.py").read_text())
    assets = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "ASSETS" for target in node.targets))
    for name, _ in assets.values():
        inputs["web/"+name] = "web/"+name
    for relative in inputs.values(): source_file(root, relative)
    return inputs


def create_context(root, destination, metadata):
    inputs = context_inputs(root)
    validate_archive(source_file(root, SDK_ARCHIVE))
    # Snapshot small source inputs once, so recorded hashes match the tar bytes.
    contents = {target:source_file(root, source).read_bytes() for target, source in inputs.items() if target != "sdk.zip"}
    metadata = {**metadata, "files":{target:hashlib.sha256(data).hexdigest() for target, data in contents.items()}}
    contents["release.json"] = (json.dumps(metadata, indent=2, sort_keys=True)+"\n").encode()
    with tarfile.open(destination, "w") as archive:
        for name, data in sorted(contents.items()):
            entry = tarfile.TarInfo(name); entry.size = len(data); entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(data))
        entry = tarfile.TarInfo("sdk.zip"); entry.size = source_file(root, SDK_ARCHIVE).stat().st_size; entry.mode = 0o644
        with source_file(root, SDK_ARCHIVE).open("rb") as sdk: archive.addfile(entry, sdk)
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Local version; defaults to dev-<revision>[-dirty]")
    parser.add_argument("--tag", help="Local Docker tag; defaults to oogies:<version>")
    args = parser.parse_args(argv)
    try:
        metadata = build_metadata(ROOT, args.version)
        tag = args.tag or "oogies:" + metadata["version"]
        subprocess.run([sys.executable, str(ROOT / "tools/check_publication.py")], check=True)
        output = ROOT / ".local/releases"; output.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="build-", dir=output) as temporary:
            temporary = Path(temporary); context = temporary / "context.tar"; iid = temporary / "image-id"
            metadata = create_context(ROOT, context, metadata)
            print(f"Building {tag}; dirty sources: {metadata['dirty']}; SDK: {metadata['sdk_profile']}", flush=True)
            with context.open("rb") as source:
                subprocess.run(["docker", "build", "--platform", "linux/amd64", "--tag", tag,
                    "--build-arg", "APP_VERSION="+metadata["version"], "--build-arg", "SOURCE_REVISION="+metadata["revision"],
                    "--iidfile", str(iid), "-"], stdin=source, check=True)
            image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", tag], text=True).strip()
            report = {**metadata, "tag":tag, "image_id":image_id, "build_digest":iid.read_text().strip()}
        name = f"build-{metadata['version']}-{uuid.uuid4().hex[:8]}.json"
        (output / name).write_text(json.dumps(report, indent=2)+"\n")
        (output / "last-build.json").write_text(json.dumps(report, indent=2)+"\n")
        print(f"Local release built: {tag}\nImage ID: {report['image_id']}\nReport: .local/releases/{name}")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release build failed: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
