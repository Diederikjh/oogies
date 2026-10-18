#!/usr/bin/env python3
"""Check the exact local release image offline, without any owner configuration."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]

NATIVE_CHECK = '''
import os, subprocess
from sdk_adapters import get_sdk_adapter
adapter = get_sdk_adapter()
binary = adapter.resolve_live_bridge(os.environ['OOGIES_LIVE_BRIDGE'])
invocation = adapter.invocation(binary, check=True)
raise SystemExit(subprocess.run(invocation.command, input=invocation.stdin,
    text=True, cwd=invocation.cwd, env=invocation.env).returncode)
'''

# This script runs inside the image over stdin, never by mounting application code.
HTTP_CHECK = r'''
import hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen

deadline = time.monotonic() + 20
while True:
    try:
        with urlopen('http://127.0.0.1:8088/', timeout=2) as response:
            assert response.status == 200
        break
    except Exception:
        if time.monotonic() >= deadline: raise SystemExit('HTTP startup deadline exceeded')
        time.sleep(.1)
metadata = json.loads(Path('/opt/oogies/release.json').read_text())
assert os.getuid() != 0
for command in ('g++', 'gcc', 'c++', 'cc', 'make', 'chromium', 'node', 'unzip', 'curl'):
    assert shutil.which(command) is None, command
assert not Path('/sdk/incEn').exists() and not Path('/sdk/QtDemo').exists()
assert not list(Path('/probe').glob('*.cpp')) and not list(Path('/probe').glob('*.h'))
assert not Path('/credentials/nvr.json').exists()
assert list(Path('/sdk/notices').glob('*.txt'))
missing = subprocess.run([sys.executable, '/probe/grid_server.py', '--bridge', '/missing-bridge'],
    capture_output=True, text=True, timeout=5)
assert missing.returncode != 0 and 'Packaged live bridge' in missing.stderr
for command in ('ffmpeg', 'ffprobe'):
    subprocess.run([command, '-version'], capture_output=True, check=True, timeout=5)
subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=32x32:r=5',
    '-frames:v', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '1',
    '-filter_threads', '1', '-movflags', '+faststart', '/output/synthetic.mp4'],
    capture_output=True, check=True, timeout=10)
probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
    '-count_frames', '-show_entries', 'stream=codec_name,nb_read_frames', '-of', 'json',
    '/output/synthetic.mp4'], text=True, timeout=5))
assert probe['streams'][0]['codec_name'] == 'h264' and probe['streams'][0]['nb_read_frames'] == '2'
assets = 0
for relative, expected in metadata['files'].items():
    if relative.startswith('web/'):
        name = relative[4:]
        path = '/' if name == 'index.html' else '/' + name
        with urlopen('http://127.0.0.1:8088' + path, timeout=3) as response:
            assert hashlib.sha256(response.read()).hexdigest() == expected, relative
        assets += 1
    elif relative.startswith(('app/', 'support/')):
        path = Path('/probe' if relative.startswith('app/') else '/support') / relative.split('/', 1)[1]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
with urlopen('http://127.0.0.1:8088/api/status', timeout=3) as response:
    status = json.load(response)
assert status['state'] == 'stopped' and status['sdk_login_calls'] == 0
assert status['active_live_sources'] == 0 and status['active_exports'] == 0
with urlopen('http://127.0.0.1:8088/api/exports', timeout=3) as response:
    assert json.load(response)['jobs'] == []
Path('/output/release-check.txt').write_text('external writable output\n')
assert Path('/exports/jobs.json').is_file()
print(json.dumps({'version': metadata['version'], 'revision': metadata['revision'],
    'dirty': metadata['dirty'], 'sdk_profile': metadata['sdk_profile'], 'assets_checked': assets,
    'login_calls': 0, 'non_root': True, 'runtime_compiler': False,
    'http_ready': True, 'bundled_sources_match_manifest': True, 'synthetic_h264_encoded': True}))
'''


def runtime_options():
    return ["--network", "none", "--read-only", "--user", f"{os.getuid()}:{os.getgid()}",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--cpus=2", "--memory=2g",
            "--memory-swap=2g", "--pids-limit=512", "--tmpfs", "/tmp:rw,exec,nosuid,size=128m"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Local image/tag; defaults to the exact ID from the last build report")
    args = parser.parse_args(argv)
    if os.getuid() == 0: parser.error("Run checks as your normal non-root Docker user, without sudo")
    output = ROOT / ".local/releases"; output.mkdir(parents=True, exist_ok=True, mode=0o700)
    image = args.image
    if image is None:
        report = output / "last-build.json"
        if not report.is_file(): parser.error("Build an image with tools/build_release.py first, or select --image")
        image = json.loads(report.read_text())["image_id"]
    identifier = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    labels = json.loads(subprocess.check_output(["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", identifier], text=True))
    name = "oogies-release-check-" + uuid.uuid4().hex[:12]
    native_name = name + "-sdk"
    result = {"image_id":identifier, "passed":False}
    try:
        checked = subprocess.run(["docker", "run", "--name", native_name, "--rm", "--init", *runtime_options(), identifier,
            "python3", "-c", NATIVE_CHECK], capture_output=True, text=True, timeout=30)
        (output / "last-native-check.log").write_text(checked.stdout + checked.stderr)
        checked.check_returncode()
        events = [json.loads(line[len("GRID_EVENT "):]) for line in checked.stdout.splitlines() if line.startswith("GRID_EVENT ")]
        assert any(event.get("type") == "check" and event.get("decoder_ready") is True and event.get("login_calls") == 0 for event in events)
        result["sdk_decoder_check"] = True
        with tempfile.TemporaryDirectory(prefix="check-", dir=output) as temporary:
            temporary = Path(temporary)
            config = temporary / "nvr.json"
            config.write_text(json.dumps({"host":"192.0.2.10", "timezone":"Africa/Johannesburg"})+"\n")
            config.chmod(0o600)
            exports = temporary / "exports"; exports.mkdir(mode=0o700)
            runtime = temporary / "output"; runtime.mkdir(mode=0o700)
            command = ["docker", "run", "--detach", "--init", "--name", name, *runtime_options()]
            for source, target, readonly in ((config, "/configuration/nvr.json", True), (exports, "/exports", False), (runtime, "/output", False)):
                command.extend(["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")])
            subprocess.run([*command, identifier], stdout=subprocess.DEVNULL, check=True)
            try:
                checked = subprocess.run(["docker", "exec", "-i", name, "python3", "-"], input=HTTP_CHECK,
                    capture_output=True, text=True, timeout=35)
                (output / "last-http-check.log").write_text(checked.stdout + checked.stderr)
                checked.check_returncode()
                result.update(json.loads(checked.stdout))
                assert labels["org.opencontainers.image.version"] == result["version"]
                assert labels["org.opencontainers.image.revision"] == result["revision"]
                assert labels["oogies.sdk-profile"] == result["sdk_profile"]
                assert (runtime / "release-check.txt").is_file()
                assert json.loads((exports / "jobs.json").read_text())["jobs"] == []
                subprocess.run(["docker", "stop", "--timeout", "15", name], stdout=subprocess.DEVNULL, check=True, timeout=25)
                exit_code = subprocess.check_output(["docker", "inspect", "--format", "{{.State.ExitCode}}", name], text=True).strip()
                assert exit_code == "0", "Server did not stop gracefully"
                result.update(passed=True, graceful_stop=True, external_state_verified=True)
            finally:
                with (output / "last-check-container.log").open("w") as log:
                    subprocess.run(["docker", "logs", name], stdout=log, stderr=subprocess.STDOUT)
                subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError, AssertionError, subprocess.SubprocessError) as error:
        # Raw native/container output remains private; print no config/SDK logs.
        result["error"] = type(error).__name__
        print(f"Release check failed: {type(error).__name__}; see .local/releases/last-check.json", file=sys.stderr)
    finally:
        for container in (native_name, name):
            subprocess.run(["docker", "rm", "--force", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (output / "last-check.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
