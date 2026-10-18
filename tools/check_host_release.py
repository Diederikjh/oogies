#!/usr/bin/env python3
"""Verify Compose readiness, recovery and persistent state with synthetic data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

from install_release import prepare_installation

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = "c" * 32
CLIP = b"synthetic persisted export fixture"


def command(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=60, **kwargs)


def wait_healthy(container, restarts=0):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        value = json.loads(command(["docker", "inspect", container]))[0]
        if value["RestartCount"] >= restarts and value["State"].get("Health", {}).get("Status") == "healthy": return value
        time.sleep(.3)
    raise ValueError("Compose container did not become healthy or recover within 45 seconds")


def verify_state(container):
    script = f'''
import hashlib,json
from pathlib import Path
from urllib.request import urlopen
with urlopen('http://127.0.0.1:8088/api/status',timeout=3) as response: status=json.load(response)
assert status['sdk_login_calls']==0 and status['state']=='stopped'
assert status['active_live_sources']==0 and status['active_exports']==0
with urlopen('http://127.0.0.1:8088/api/exports',timeout=3) as response: jobs=json.load(response)['jobs']
assert len(jobs)==1 and jobs[0]['id']=='{IDENTIFIER}' and jobs[0]['state']=='ready'
with urlopen('http://127.0.0.1:8088'+jobs[0]['media']['url'],timeout=3) as response: clip=response.read()
assert hashlib.sha256(clip).hexdigest()=='{hashlib.sha256(CLIP).hexdigest()}'
assert Path('/output/persistent-check.txt').read_text()=='persisted'
print(json.dumps({{'login_calls':0,'ready_exports':len(jobs)}}))
'''
    return json.loads(command(["docker", "exec", "-i", container, "python3", "-"], input=script))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Defaults to the last local build's exact image ID")
    args = parser.parse_args(argv)
    output = ROOT / ".local/releases"; output.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {"passed":False}
    log_path = output / "last-host-check.log"
    try:
        selected = args.image or json.loads((output / "last-build.json").read_text())["image_id"]
        image = command(["docker", "image", "inspect", "--format", "{{.Id}}", selected]).strip()
        result["image_id"] = image
        with tempfile.TemporaryDirectory(prefix="oogies-host-check-") as temporary, log_path.open("w") as log:
            temporary = Path(temporary); source = temporary / "source"; source.mkdir(mode=0o700)
            (source / "nvr-config.json").write_text(json.dumps({"host":"192.0.2.10"}))
            (source / "nvr-credentials.json").write_text(json.dumps({"username":"synthetic", "password":"synthetic", "verification_code":"synthetic"}))
            clip = source / "exports" / IDENTIFIER / "clip.mp4"; clip.parent.mkdir(parents=True); clip.write_bytes(CLIP)
            now = time.time()
            job = dict(id=IDENTIFIER, state="ready", camera_name="Synthetic camera", progress=100,
                duration_seconds=2, created_at=now, expires_at=now+86400, error=None,
                request={"camera_id":"camera-1", "from":"2026-01-01T00:00:00Z", "to":"2026-01-01T00:00:02Z", "aspect_ratio":"16:9"})
            (source / "exports/jobs.json").write_text(json.dumps({"version":1,"jobs":[job]}))
            directory = temporary / "installed"
            prepare_installation(source, directory, image, project="oogies-check-"+uuid.uuid4().hex[:10])
            (directory / ".local/output/persistent-check.txt").write_text("persisted")
            # Render the actual shipped Compose file. Only isolate networking for
            # this check; readiness/restart/mount/resource settings stay unchanged.
            environment = {key:value for key,value in os.environ.items() if not key.startswith("OOGIES_")}
            rendered = json.loads(command(["docker", "compose", "config", "--format", "json"], cwd=directory, env=environment))
            viewer = rendered["services"]["viewer"]
            assert viewer["read_only"] and viewer["init"] and viewer["restart"] == "unless-stopped"
            assert len(viewer["ports"]) == 2
            assert {port["host_ip"] for port in viewer["ports"]} == {"127.0.0.1", "::1"}
            assert viewer["pull_policy"] == "never" and viewer["user"] == f"{os.getuid()}:{os.getgid()}"
            assert len(viewer["volumes"]) == 4 and int(viewer["mem_limit"]) == 2*1024**3 and viewer["cpus"] == 2
            assert viewer["logging"]["options"] == {"max-size":"5m", "max-file":"2"}
            result["compose_contract"] = True
            viewer.pop("ports", None); viewer.pop("networks", None); viewer["network_mode"] = "none"
            rendered.pop("networks", None)
            isolated = directory / "isolated.json"; isolated.write_text(json.dumps(rendered))
            compose = ["docker", "compose", "-f", str(isolated)]
            try:
                subprocess.run([*compose, "up", "-d", "--wait", "--wait-timeout", "45"], check=True, stdout=log, stderr=log, timeout=60)
                container = command([*compose, "ps", "--quiet", "viewer"]).strip()
                before = wait_healthy(container); result.update(verify_state(container))
                # Kill the application from inside the container rather than
                # manually stopping it, so Docker exercises its restart policy.
                crash = '''
import os, signal
from pathlib import Path
pids = []
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try: args = path.read_bytes().split(b'\\0')[:2]
    except (FileNotFoundError, ProcessLookupError): continue
    if args == [b'python3', b'/probe/grid_server.py']: pids.append(int(path.parent.name))
assert len(pids) == 1
os.kill(pids[0], signal.SIGKILL)
'''
                killed = subprocess.run(["docker", "exec", container, "python3", "-c", crash], stdout=log, stderr=log, timeout=10)
                # Tini can exit before exec returns after its child is killed.
                # Exit 137 is expected here; actual recovery is proved below.
                if killed.returncode not in (0, 137): killed.check_returncode()
                wait_healthy(container, before["RestartCount"]+1); verify_state(container)
                result["process_restart_verified"] = True
                subprocess.run([*compose, "stop"], check=True, stdout=log, stderr=log, timeout=45)
                stopped = json.loads(command(["docker", "inspect", container]))[0]
                assert not stopped["State"]["Running"] and stopped["State"]["ExitCode"] == 0
                subprocess.run([*compose, "up", "-d", "--wait", "--wait-timeout", "45"], check=True, stdout=log, stderr=log, timeout=60)
                wait_healthy(container); verify_state(container)
                result.update(passed=True, graceful_stop=True, persistence_verified=True, network_disabled=True)
            finally:
                subprocess.run([*compose, "logs", "--no-color"], stdout=log, stderr=log, timeout=10)
                subprocess.run([*compose, "down", "--timeout", "30"], stdout=log, stderr=log, timeout=45, check=True)
    except (OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as error:
        with log_path.open("a") as log: traceback.print_exc(file=log)
        result["error"] = type(error).__name__
        print("Host release check failed; inspect .local/releases/last-host-check.log", file=sys.stderr)
    (output / "last-host-check.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__": sys.exit(main())
