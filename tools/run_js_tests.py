#!/usr/bin/env python3
"""Run frontend logic tests with native Node 22 or a restricted Docker runtime."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392"


def select_tests(root, paths):
    root = root.resolve()
    directory = root / "tests/js"
    candidates = [root / path for path in paths] if paths else sorted(directory.rglob("*.test.mjs"))
    selected = set()
    for candidate in candidates:
        path = candidate.resolve()
        try:
            path.relative_to(directory)
        except ValueError:
            raise ValueError("Select only .test.mjs files inside tests/js.") from None
        if not path.is_file() or not path.name.endswith(".test.mjs"):
            raise ValueError(f"JavaScript test file not found: {candidate.relative_to(root)}")
        selected.add(path.relative_to(root))
    if not selected:
        raise ValueError("No JavaScript test files selected under tests/js.")
    return sorted(selected)


def native_node():
    node = shutil.which("node")
    if node:
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        if re.fullmatch(r"v22\.\d+\.\d+", version):
            return node
    raise ValueError("Native Node 22 is required; reuse an existing installation or run with --docker (no host installation needed).")


def docker_command(root):
    command = ["docker", "run", "--rm", "--init", "--pull=never", "--network", "none", "--read-only",
               "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--cpus=1", "--memory=256m", "--memory-swap=256m", "--pids-limit=128",
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m", "--workdir", "/work"]
    for relative in ("web", "tests/js"):
        command.extend(["--mount", f"type=bind,source={root / relative},target=/work/{relative},readonly"])
    return [*command, IMAGE, "node"]


def stream_tests(command, report, cwd):
    report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as output:
        with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            for line in process.stdout:
                output.write(line)
                sys.stdout.write(line)
                sys.stdout.flush()
            code = process.wait()
    return code if code >= 0 else 128 - code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="Use the pinned Node image instead of native Node")
    parser.add_argument("--pull", action="store_true", help="With --docker, retrieve the pinned image and exit without running tests")
    parser.add_argument("tests", nargs="*", help="Optional .test.mjs file paths under tests/js")
    args = parser.parse_args(argv)
    if args.pull and (not args.docker or args.tests):
        parser.error("--pull requires --docker and cannot select tests; run tests separately after pulling")
    try:
        if args.pull:
            return subprocess.run(["docker", "pull", IMAGE], check=True).returncode
        tests = select_tests(ROOT, args.tests)
        if args.docker:
            available = subprocess.run(["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            if available.returncode:
                raise ValueError("Pinned Node image unavailable; run python3 tools/run_js_tests.py --docker --pull first.")
            command = docker_command(ROOT)
        else:
            command = [native_node()]
        command.extend(["--test", "--test-reporter=tap", "--test-timeout=10000", "--test-concurrency=1",
                        *(path.as_posix() for path in tests)])
        report = ROOT / ".local/js-test-results/tests.tap"
        code = stream_tests(command, report, ROOT)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(f"JavaScript TAP report: {report}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
