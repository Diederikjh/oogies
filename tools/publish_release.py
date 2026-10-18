#!/usr/bin/env python3
"""Validate a GitHub version-tag build and publish only its checked image ID."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from build_release import ROOT, SDK_SHA256
from sdk_adapters import DEFAULT_SDK_ID


def release_target(repository, ref, revision):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise ValueError("Expected a GitHub owner/repository")
    match = re.fullmatch(r"refs/tags/v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)", ref)
    if not match or len(match[1]) > 120:
        raise ValueError("Use a version tag vMAJOR.MINOR.PATCH with an optional prerelease suffix")
    version = match[1]
    if "-" in version and any(part.isdigit() and len(part)>1 and part.startswith("0") for part in version.split("-",1)[1].split(".")):
        raise ValueError("Numeric prerelease identifiers must not have leading zeroes")
    if not re.fullmatch(r"[a-f0-9]{40}", revision): raise ValueError("Expected the full source commit SHA")
    image = "ghcr.io/"+repository.lower()
    return dict(version=version, image=image, tag=image+":"+version, revision=revision,
                ref=ref, source_url="https://github.com/"+repository)


def require_source(root, target):
    revision = subprocess.check_output(["git","rev-parse","HEAD"], cwd=root, text=True).strip()
    tagged = subprocess.check_output(["git","rev-parse",target["ref"]+"^{}"], cwd=root, text=True).strip()
    if revision != target["revision"] or tagged != revision:
        raise ValueError("The version tag, checked-out commit and GitHub revision must agree")
    if subprocess.check_output(["git","status","--porcelain","--untracked-files=normal"], cwd=root):
        raise ValueError("Publishing requires a clean checkout")


def validate_reports(target, build, artifact, host):
    expected = dict(version=target["version"], revision=target["revision"], source_url=target["source_url"],
                    sdk_profile=DEFAULT_SDK_ID, sdk_archive_sha256=SDK_SHA256, platform="linux/amd64", tag=target["tag"])
    if build.get("dirty") is not False or any(build.get(key) != value for key,value in expected.items()):
        raise ValueError("Build metadata does not match the clean version-tag release")
    identifier = build.get("image_id", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier): raise ValueError("Missing exact built image ID")
    for report in (artifact, host):
        if report.get("passed") is not True or report.get("image_id") != identifier or report.get("login_calls") != 0:
            raise ValueError("Both offline checks must pass with zero logins for the exact built image")
    for key in ("sdk_decoder_check", "non_root", "http_ready", "bundled_sources_match_manifest",
                "synthetic_h264_encoded", "graceful_stop", "external_state_verified"):
        if artifact.get(key) is not True: raise ValueError("Incomplete offline artifact verification")
    if artifact.get("runtime_compiler") is not False or artifact.get("dirty") is not False:
        raise ValueError("Artifact must be clean and require no runtime compiler")
    for key in ("version", "revision", "sdk_profile"):
        if artifact.get(key) != build[key]: raise ValueError("Artifact identity differs from the build report")
    for key in ("compose_contract", "process_restart_verified", "graceful_stop", "persistence_verified", "network_disabled"):
        if host.get(key) is not True: raise ValueError("Incomplete offline Compose verification")
    return identifier


def inspect_image(identifier, target):
    image = json.loads(subprocess.check_output(["docker","image","inspect",identifier], text=True))[0]
    labels = image.get("Config",{}).get("Labels") or {}
    expected = {"org.opencontainers.image.version":target["version"],
                "org.opencontainers.image.revision":target["revision"],
                "org.opencontainers.image.source":target["source_url"], "oogies.sdk-profile":DEFAULT_SDK_ID}
    if image["Id"] != identifier or image.get("Os") != "linux" or image.get("Architecture") != "amd64" or any(labels.get(k)!=v for k,v in expected.items()):
        raise ValueError("Docker image identity, labels or platform differ from the checked build")


def push_image(identifier, tag, output):
    existing = subprocess.run(["docker","manifest","inspect",tag], capture_output=True, text=True)
    if existing.returncode == 0:
        raise ValueError("This image version already exists; choose a new release version")
    error = (existing.stdout+existing.stderr).lower()
    if not any(message in error for message in ("manifest unknown", "no such manifest")):
        raise ValueError("Could not establish that the registry version is unused; refusing to push")
    subprocess.run(["docker","tag",identifier,tag], check=True)
    pushed = subprocess.run(["docker","push",tag], capture_output=True, text=True)
    (output / "last-push.log").write_text(pushed.stdout+pushed.stderr)
    pushed.check_returncode()
    digests = re.findall(r"\bdigest:\s*(sha256:[a-f0-9]{64})\b", pushed.stdout+pushed.stderr)
    if not digests: raise ValueError("Docker push did not report a registry manifest digest")
    return tag.rsplit(":",1)[0]+"@"+digests[-1]


def publish(target, output, root=ROOT):
    require_source(root, target)
    read = lambda name: json.loads((output / name).read_text())
    build, artifact, host = (read(name) for name in ("last-build.json","last-check.json","last-host-check.json"))
    identifier = validate_reports(target, build, artifact, host)
    inspect_image(identifier, target)
    reference = push_image(identifier, target["tag"], output)
    report = {**target, "image_id":identifier, "reference":reference, "digest":reference.rsplit("@",1)[1],
              "sdk_profile":build["sdk_profile"], "sdk_archive_sha256":build["sdk_archive_sha256"],
              "platform":build["platform"], "verified_after_pull":False}
    destination = output / "publication.json"
    # A failed post-push verification must still retain the published digest.
    destination.write_text(json.dumps(report, indent=2)+"\n")
    subprocess.run(["docker","pull",reference], check=True)
    pulled = subprocess.check_output(["docker","image","inspect","--format","{{.Id}}",reference], text=True).strip()
    if pulled != identifier: raise ValueError("Pulled digest does not identify the tested image")
    for tool in ("check_release_image.py","check_host_release.py"):
        subprocess.run([sys.executable,str(root / "tools" / tool),"--image",reference], check=True)
    validate_reports(target, build, read("last-check.json"), read("last-host-check.json"))
    report["verified_after_pull"] = True
    destination.write_text(json.dumps(report, indent=2)+"\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare","publish"))
    args = parser.parse_args(argv)
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_EVENT_NAME") != "push":
            raise ValueError("Use this command in the version-tag GitHub Actions workflow")
        target = release_target(os.environ.get("GITHUB_REPOSITORY",""),os.environ.get("GITHUB_REF",""),os.environ.get("GITHUB_SHA",""))
        output = ROOT / ".local/releases"; output.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.action == "prepare":
            require_source(ROOT, target)
            (output / "target.json").write_text(json.dumps(target, indent=2)+"\n")
            if os.environ.get("GITHUB_OUTPUT"):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a") as file:
                    for name in ("version","image","source_url"): file.write(f"{name}={target[name]}\n")
            print(json.dumps(target, indent=2))
        else:
            if json.loads((output / "target.json").read_text()) != target:
                raise ValueError("Prepared release target differs from the publishing context")
            report = publish(target, output)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as file:
                    file.write(f"Published `{report['tag']}`\n\nVerified digest: `{report['reference']}`\n\nSource: `{report['revision']}`\n")
            print(json.dumps(report, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release publication failed ({type(error).__name__}): {error if isinstance(error, ValueError) else 'Inspect the workflow and release reports.'}\n")
    return 0


if __name__ == "__main__": sys.exit(main())
