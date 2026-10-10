"""One native recorder connection, with independent latest-frame source caches."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid


class GridWorker:
    def __init__(self, binary, adapter, config, output, spawn=subprocess.Popen):
        self.binary, self.adapter, self.config = binary, adapter, config
        self.output, self.spawn = Path(output), spawn
        self.condition = threading.Condition(threading.RLock())
        self.writer = threading.Lock()
        self.process = None
        self.state, self.error = "stopped", None
        self.cameras, self.sources = {}, {}
        self.login_calls = self.tested_capacity = 0
        self.shutdown = False

    def ensure_ready(self):
        with self.condition:
            if self.state == "stopped":
                self.state = "starting"
                try:
                    credentials = self.adapter.load_credentials("/credentials/nvr.json")
                    self.directory = self.output / ("grid-" + uuid.uuid4().hex)
                    self.directory.mkdir(mode=0o700, parents=True)
                    invocation = self.adapter.invocation(self.binary, credentials=credentials,
                        host=self.config["host"], port=self.config["sdk_port"], decrypt=True,
                        capture_dir=self.directory)
                    self.process = self.spawn(invocation.command, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=invocation.cwd,
                        env=invocation.env, bufsize=0)
                    self.process.stdin.write(invocation.stdin.encode())
                    threading.Thread(target=self._read, daemon=True).start()
                    threading.Thread(target=self._stderr, daemon=True).start()
                    threading.Thread(target=self._frames, daemon=True).start()
                except (OSError, ValueError):
                    self.state, self.error = "error", "Recorder configuration or worker startup failed."
            if not self.condition.wait_for(lambda: self.state != "starting", timeout=30):
                self.state, self.error = "error", "Recorder discovery timed out; no automatic retry."
                if self.process:
                    self.process.terminate()
            if self.state != "ready":
                raise ValueError(self.error or "Recorder unavailable")

    def _stderr(self):
        with (self.directory / "native.stderr.log").open("wb") as log:
            written = 0
            while True:
                chunk = self.process.stderr.read(4096)
                if not chunk:
                    return
                if written < 5 * 1024 * 1024:
                    log.write(chunk[:5 * 1024 * 1024 - written]); written += len(chunk)

    def _read(self):
        with (self.directory / "native.stdout.log").open("wb") as log:
            written = 0
            for raw in iter(lambda: self.process.stdout.readline(65536), b""):
                if written < 5 * 1024 * 1024:
                    log.write(raw[:5 * 1024 * 1024 - written]); written += len(raw)
                if not raw.startswith(b"GRID_EVENT "):
                    continue
                try:
                    self._event(json.loads(raw[len(b"GRID_EVENT "):].decode("utf-8", errors="replace")))
                except (ValueError, KeyError, TypeError):
                    continue
        self.process.wait()
        with self.condition:
            if not self.shutdown and self.state != "error":
                self.state, self.error = "error", "Recorder worker ended; no automatic retry."
            for source in self.sources.values():
                source["state"], source["frame"] = "error", None
            self.condition.notify_all()

    def _event(self, event):
        with self.condition:
            kind = event["type"]
            if kind == "ready":
                if event.get("protocol") != 1:
                    self.state, self.error = "error", "Unsupported worker protocol."
                    self.process.terminate()
                else:
                    self.login_calls = event["login_calls"]
                    for camera in event["cameras"]:
                        channel = camera["channel"]
                        override = self.config["camera_overrides"].get(str(channel), {})
                        if override.get("enabled") is False:
                            continue
                        identifier = f"camera-{channel}"
                        self.cameras[identifier] = dict(camera, id=identifier,
                            name=override.get("name", camera["name"]),
                            aspect_ratio=override.get("aspect_ratio", "16:9"), live_qualities=["overview"],
                            capabilities={"time_playback": "unknown", "motion_timeline": "unknown"})
                    self.state = "ready"
            elif kind == "fatal":
                self.login_calls = event.get("login_calls", 0)
                self.state, self.error = "error", f"Recorder connection failed (SDK code {event.get('error')}); no automatic retry."
            elif kind in ("started", "source_error", "stopped"):
                identifier = f"camera-{event['channel']}"
                source = self.sources.get(identifier)
                if source:
                    if kind == "stopped" and source["state"] == "stopping":
                        source["state"], source["frame"] = "stopped", None
                    elif kind == "stopped":
                        pass
                    elif event.get("error"):
                        source["state"] = "capacity_limited" if event["error"] == 5 else "error"
                        source["error"] = f"Camera stream failed (SDK/decoder code {event['error']})."
                    else:
                        source["generation"] = event["generation"]
                        source["state"] = "starting"
            self.condition.notify_all()

    def send(self, operation, camera_id):
        channel = self.cameras[camera_id]["channel"]
        with self.condition, self.writer:
            try:
                self.process.stdin.write(f"{operation} {channel}\n".encode())
            except OSError:
                self.state, self.error = "error", "Recorder worker ended; no automatic retry."
                for source in self.sources.values():
                    source["state"], source["frame"] = "error", None
                self.condition.notify_all()

    def start_source(self, camera_id):
        with self.condition:
            self.sources[camera_id] = dict(state="starting", frame=None, sequence=0,
                generation=None, width=0, height=0, received=0, last_frame=0,
                requested_at=time.monotonic(), error=None)
            self.send("start", camera_id)

    def stop_source(self, camera_id):
        with self.condition:
            source = self.sources[camera_id]
            source["state"], source["frame"] = "stopping", None
            self.send("stop", camera_id)

    def _frames(self):
        while not self.shutdown and self.process.poll() is None:
            with self.condition:
                identifiers = [key for key, source in self.sources.items() if source["state"] in ("starting", "live", "stale")]
            for identifier in identifiers:
                directory = self.directory / identifier
                try:
                    metadata = json.loads((directory / "frame.json").read_text())
                    with self.condition:
                        source = self.sources[identifier]
                        if metadata["generation"] != source["generation"] or metadata["sequence"] == source["sequence"]:
                            continue
                    frame = (directory / "frame.jpg").read_bytes()
                    if len(frame) > 4 * 1024 * 1024 or not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
                        continue
                    with self.condition:
                        if source["state"] not in ("starting", "live", "stale"):
                            continue
                        source.update(state="live", frame=frame, sequence=metadata["sequence"],
                            width=metadata["width"], height=metadata["height"], last_frame=time.monotonic(),
                            last_frame_received_at=datetime.now(timezone.utc).isoformat(),
                            decoded_frames=metadata["decoded_frames"], jpeg_frames=metadata["jpeg_frames"])
                        source["received"] += 1
                        self.cameras[identifier]["online"] = True
                        self.condition.notify_all()
                except (OSError, ValueError, KeyError):
                    pass
            with self.condition:
                for identifier, source in self.sources.items():
                    if source["state"] == "starting" and time.monotonic() - source["requested_at"] > 15:
                        self.send("stop", identifier)
                        source["state"], source["error"] = "error", "No decoded frames arrived within 15 seconds."
                    elif source["state"] in ("live", "stale"):
                        source["state"] = "stale" if time.monotonic() - source["last_frame"] > 5 else "live"
                fresh = sum(source["state"] == "live" for source in self.sources.values())
                self.tested_capacity = max(self.tested_capacity, fresh)
            time.sleep(0.05)

    def close(self):
        with self.condition:
            self.shutdown = True
            self.condition.notify_all()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
