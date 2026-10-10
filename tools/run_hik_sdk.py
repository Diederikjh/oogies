#!/usr/bin/env python3
"""Run the containerized Hikvision diagnostic with narrowly scoped mounts."""

import argparse
from pathlib import Path
import subprocess
import uuid

from credentials import DEFAULT_CREDENTIALS_FILE

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "probe"))
    parser.add_argument("--capture-seconds", type=int, default=0)
    parser.add_argument("--sdk-log", action="store_true", help="Save private SDK debug logs")
    parser.add_argument("--decrypt", action="store_true", help="Decode with PlayCtrl and the full verification code")
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 60:
        parser.error("capture must be 0–60 seconds")
    if args.mode == "probe" and args.decrypt and args.capture_seconds == 0:
        parser.error("--decrypt requires a positive --capture-seconds for a live probe")
    sdk = ROOT / ".local/hik-sdk/sdk"
    if not (sdk / "lib/libhcnetsdk.so").is_file():
        parser.error("place the Linux 64-bit SDK (lib and header directories) in .local/hik-sdk/sdk")
    output = ROOT / ".local/hik-sdk/results"
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    container_name = "cam-sdk-" + uuid.uuid4().hex[:12]
    command = ["docker", "run", "--name", container_name, "--rm", "--read-only", "--cap-drop=ALL",
               "--user", f"{output.stat().st_uid}:{output.stat().st_gid}",
               "--cpus=2", "--memory=2g", "--memory-swap=2g", "--pids-limit=512",
               "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,exec,nosuid,size=128m",
               "--network", "none" if args.mode == "check" else "bridge",
               "--mount", f"type=bind,source={sdk},target=/sdk,readonly",
               "--mount", f"type=bind,source={ROOT / 'docker/hikvision-sdk'},target=/probe,readonly",
               "--mount", f"type=bind,source={ROOT / 'tools/credentials.py'},target=/support/credentials.py,readonly",
               "--env", "PYTHONPATH=/support",
               "--mount", f"type=bind,source={output},target=/output"]
    if args.mode == "probe":
        credentials = DEFAULT_CREDENTIALS_FILE
        if not credentials.is_file():
            parser.error("credential file is missing")
        command.extend(["--mount", f"type=bind,source={credentials},target=/credentials/nvr.json,readonly"])
    command.extend(["cam-hik-sdk-runtime:local", "python3", "/probe/run_probe.py", args.mode,
                    "--capture-seconds", str(args.capture_seconds)])
    if args.sdk_log:
        command.append("--sdk-log")
    if args.decrypt:
        command.append("--decrypt")
    try:
        completed = subprocess.run(command, timeout=80 + args.capture_seconds)
    except subprocess.TimeoutExpired:
        # The inner native-process deadline normally stops first; do not retry.
        subprocess.run(["docker", "rm", "--force", container_name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        parser.exit(2, "Container deadline exceeded; no retry performed.\n")
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
