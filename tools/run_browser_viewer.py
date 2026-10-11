#!/usr/bin/env python3
"""Start the local live grid; opening its page subscribes to cameras."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from sdk_adapters import get_sdk_adapter
from nvr_config import load_config

ROOT = Path(__file__).resolve().parents[1]
NAME = "cam-browser-viewer"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    adapter = get_sdk_adapter()
    if args.stop:
        subprocess.run(["docker", "stop", "--timeout", "20", NAME], check=True)
        # Docker may return before --rm has released the name.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            check = subprocess.run(["docker", "container", "inspect", NAME],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if check.returncode:
                return
            time.sleep(0.1)
        parser.exit(2, "Viewer stopped; Docker cleanup is still in progress.\n")
        return
    config = load_config()
    adapter = get_sdk_adapter(config["sdk_profile"])
    if not 1024 <= args.port <= 65535:
        parser.error("invalid HTTP port")
    sdk = ROOT / ".local/hik-sdk/sdk"
    credentials = ROOT / ".local/nvr-credentials.json"
    if not (sdk / "lib/libhcnetsdk.so").is_file() or not credentials.is_file():
        parser.error("SDK or private credentials missing; see README")
    existing = subprocess.run(["docker", "ps", "--filter", "name=^/" + NAME + "$", "--format", "{{.Names}}"],
                              capture_output=True, text=True, check=True)
    if existing.stdout.strip():
        parser.exit(2, "Browser viewer is already running; stop it before changing its settings.\n")
    output = ROOT / ".local/browser-viewer"
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o700)
    exports = ROOT / ".local/exports"
    exports.mkdir(parents=True, exist_ok=True); exports.chmod(0o700)
    command = ["docker", "run", "--detach", "--rm", "--init", "--name", NAME,
               "--read-only", "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop=ALL",
               "--security-opt=no-new-privileges", "--cpus=2", "--memory=2g", "--memory-swap=2g",
               "--pids-limit=512", "--tmpfs", "/tmp:rw,exec,nosuid,size=128m",
               "--publish", f"127.0.0.1:{args.port}:{args.port}", "--env", "PYTHONPATH=/support:/probe",
               "--log-opt", "max-size=5m", "--log-opt", "max-file=2"]
    for source, target, writable in ((sdk, "/sdk", False), (credentials, "/credentials/nvr.json", False),
            (ROOT / "tools/credentials.py", "/support/credentials.py", False),
            (ROOT / "tools/sdk_adapters", "/support/sdk_adapters", False),
            (ROOT / "tools/nvr_config.py", "/support/nvr_config.py", False),
            (ROOT / ".local/nvr-config.json", "/configuration/nvr.json", False),
            (ROOT / "docker/hikvision-sdk", "/probe", False), (ROOT / "web", "/web", False),
            (output, "/output", True), (exports, "/exports", True)):
        command.extend(["--mount", f"type=bind,source={source},target={target}" + ("" if writable else ",readonly")])
    recordings = sorted((ROOT / ".local/hik-sdk/results").glob("sdk-capture-*/historical-clip.mp4"))
    if recordings:
        command.extend(["--mount", f"type=bind,source={recordings[-1]},target=/recording/historical-clip.mp4,readonly"])
        for report in sorted((ROOT / ".local/hik-sdk/results").glob("sdk-probe-*.json"), reverse=True):
            try:
                metadata = json.loads(report.read_text())
            except (OSError, ValueError):
                continue
            if metadata.get("capture_directory") == recordings[-1].parent.name and metadata.get("mp4_encoded"):
                for key, value in (("CAM_RECORDING_BEGIN", metadata["requested_begin"]),
                                   ("CAM_RECORDING_END", metadata["requested_end"]),
                                   ("CAM_RECORDING_SECONDS", str(metadata["clip_duration_seconds"]))):
                    command.extend(["--env", key + "=" + value])
                break
    command.extend([adapter.runtime_image, "python3", "/probe/grid_server.py", "--port", str(args.port)])
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    print(f"Open http://localhost:{args.port}/ for the automatic live grid.")


if __name__ == "__main__":
    main()
