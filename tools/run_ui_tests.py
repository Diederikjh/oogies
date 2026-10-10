#!/usr/bin/env python3
"""Run synthetic-recorder UI acceptance tests in Docker, with networking disabled."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cam-hik-sdk-browser:local"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build the browser image first")
    parser.add_argument("tests", nargs="*", help="Optional unittest names, e.g. test_viewer_ui.ViewerUITests.test_fresh_install_without_a_recording")
    args = parser.parse_args()
    if args.build:
        subprocess.run(["docker", "build", "--target", "download-browser", "--tag", IMAGE,
                        str(ROOT / "docker/hikvision-sdk")], check=True)
    available = subprocess.run(["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    if available.returncode:
        parser.error("browser image missing; rerun with --build")
    output = ROOT / ".local/ui-test-results"
    output.mkdir(parents=True, exist_ok=True); output.chmod(0o700)
    command = ["docker", "run", "--rm", "--init", "--network", "none", "--read-only",
               "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--cpus=2", "--memory=2g", "--memory-swap=2g", "--pids-limit=512",
               "--tmpfs", "/tmp:rw,exec,nosuid,size=256m", "--env", "XDG_CONFIG_HOME=/tmp/config",
               "--env", "XDG_CACHE_HOME=/tmp/cache", "--env", "PYTHONPATH=/support:/probe:/ui"]
    for source, target, readonly in ((ROOT / "tools", "/support", True),
            (ROOT / "docker/hikvision-sdk", "/probe", True), (ROOT / "web", "/web", True),
            (ROOT / "tests/ui", "/ui", True), (output, "/output", False)):
        command.extend(["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")])
    command.extend([IMAGE, "python3", "/ui/run.py", *args.tests])
    result = subprocess.run(command)
    print(f"UI report and screenshots: {output}", flush=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
