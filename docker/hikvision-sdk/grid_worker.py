"""One native recorder connection, with independent latest-frame source caches."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from history_timeline import recorder_utc, utc_text


class GridWorker:
    availability_cache_seconds = 60

    def __init__(self, binary, adapter, config, output, spawn=subprocess.Popen, clock=time.monotonic):
        self.binary, self.adapter, self.config = binary, adapter, config
        self.output, self.spawn = Path(output), spawn
        self.condition = threading.Condition(threading.RLock())
        self.writer = threading.Lock()
        self.process = None
        self.state, self.error = "stopped", None
        self.cameras, self.sources = {}, {}
        self.login_calls = self.tested_capacity = 0
        self.shutdown = False
        self.clock = clock
        self.next_availability_refresh = 0
        self.history_results = {}
        self.history_lock = threading.Lock()
        self.playbacks = {}
        self.zone = ZoneInfo(config.get("timezone", "Africa/Johannesburg"))

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
            for raw in iter(lambda: self.process.stdout.readline(262144), b""):
                if written < 5 * 1024 * 1024:
                    log.write(raw[:5 * 1024 * 1024 - written]); written += len(raw)
                    if raw.startswith(b"GRID_EVENT "): log.flush()
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
            for source in list(self.sources.values()) + list(self.playbacks.values()):
                source["state"], source["frame"] = "error", None
            self.condition.notify_all()

    def _event(self, event):
        with self.condition:
            kind = event["type"]
            if kind == "playback":
                source = self.playbacks.get(event["id"])
                if source and source["generation"] == event["generation"]:
                    if event.get("error"):
                        source.update(state="error", frame=None, error=f"Historical playback failed (SDK/decoder code {event['error']}).")
                    elif source["state"] not in ("error", "ended"):
                        state = event["state"]
                        if source["state"] == "seeking" and state == "starting": state = "seeking"
                        source["state"] = state
                self.condition.notify_all()
                return
            if kind == "timeline":
                if event["id"] in self.history_results:
                    self.history_results[event["id"]] = event
                self.condition.notify_all()
                return
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
                    self.next_availability_refresh = self.clock() + self.availability_cache_seconds
            elif kind == "availability":
                for camera in event["cameras"]:
                    identifier = f"camera-{camera['channel']}"
                    if identifier not in self.cameras or type(camera.get("online")) is not bool:
                        continue
                    source = self.sources.get(identifier, {})
                    # Fresh decoded video is stronger evidence than a status hint.
                    fresh = source.get("frame") is not None and time.monotonic() - source.get("last_frame", 0) <= 5
                    self.cameras[identifier]["online"] = camera["online"] or fresh
                self.next_availability_refresh = self.clock() + self.availability_cache_seconds
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

    def refresh_availability(self):
        with self.condition:
            if self.shutdown or self.state != "ready" or self.clock() < self.next_availability_refresh:
                return
            # Advance before writing so simultaneous tabs share one query. A
            # missing response is retried at most once a minute, without login.
            self.next_availability_refresh = self.clock() + self.availability_cache_seconds
            self._command("refresh")

    def query_timeline(self, camera_id, begin, end):
        """Serialize metadata jobs; native searches run away from frame delivery."""
        with self.history_lock:
            self.ensure_ready()
            identifier = uuid.uuid4().hex
            with self.condition:
                self.history_results[identifier] = None
                try:
                    self._command(f"timeline {self.cameras[camera_id]['channel']} {identifier} {begin} {end}")
                    ready = self.condition.wait_for(lambda: self.history_results[identifier] is not None or
                        self.state != "ready" or self.shutdown, timeout=25)
                    result = self.history_results[identifier]
                    if not ready or result is None or result.get("busy"):
                        raise ValueError("Recorder history query did not complete.")
                    return result
                finally:
                    del self.history_results[identifier]

    def _command(self, command):
        with self.condition, self.writer:
            try:
                self.process.stdin.write((command + "\n").encode())
            except OSError:
                self.state, self.error = "error", "Recorder worker ended; no automatic retry."
                for source in list(self.sources.values()) + list(self.playbacks.values()):
                    source["state"], source["frame"] = "error", None
                self.condition.notify_all()

    def send(self, operation, camera_id):
        self._command(f"{operation} {self.cameras[camera_id]['channel']}")

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

    def start_playback(self, identifier, camera_id, begin, end, generation, paused=False):
        with self.condition:
            self.playbacks[identifier] = dict(camera_id=camera_id, generation=generation,
                state="starting" if generation == 1 else "seeking", frame=None, position=None,
                sequence=0, received=0, width=0, height=0, last_frame=0, requested_at=time.monotonic(), error=None)
            self._command(f"playback-start {self.cameras[camera_id]['channel']} {identifier} {generation} {begin} {end} {int(paused)}")
            self.condition.notify_all()

    def control_playback(self, identifier, paused):
        with self.condition:
            source = self.playbacks[identifier]
            source["state"] = "pausing" if paused else "resuming"
            self._command(f"playback-{'pause' if paused else 'resume'} 0 {identifier} {source['generation']}")

    def stop_playback(self, identifier):
        with self.condition:
            source = self.playbacks.pop(identifier, None)
            if source: self._command(f"playback-stop 0 {identifier} {source['generation']}")
            self.condition.notify_all()

    def _playback_frames(self):
        with self.condition:
            identifiers = list(self.playbacks)
        for identifier in identifiers:
            directory = self.directory / ("playback-" + identifier)
            try:
                metadata = json.loads((directory / "frame.json").read_text())
                frame = (directory / "frame.jpg").read_bytes()
                if metadata != json.loads((directory / "frame.json").read_text()): continue
                if len(frame) > 4 * 1024 * 1024 or not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"): continue
                position = utc_text(recorder_utc(metadata["position"], self.zone)) if metadata.get("position") else None
                with self.condition:
                    source = self.playbacks.get(identifier)
                    if not source or source["state"] in ("error", "ended") or metadata["generation"] != source["generation"] or metadata["sequence"] == source["sequence"]: continue
                    source.update(frame=frame, sequence=metadata["sequence"], position=position,
                        width=metadata["width"], height=metadata["height"], last_frame=time.monotonic())
                    source["received"] += 1
                    if source["state"] not in ("paused", "pausing", "resuming"): source["state"] = "playing"
                    self.condition.notify_all()
            except (OSError, ValueError, KeyError): pass
        with self.condition:
            for identifier, source in self.playbacks.items():
                if source["state"] in ("starting", "seeking") and time.monotonic() - source["requested_at"] > 15:
                    source.update(state="error", error="No historical frames arrived within 15 seconds.", frame=None)
                    self._command(f"playback-stop 0 {identifier} {source['generation']}")
                elif source["state"] == "playing" and source["last_frame"] and time.monotonic() - source["last_frame"] > 15:
                    source.update(state="error", error="Historical playback stopped delivering frames.", frame=None)
                    self._command(f"playback-stop 0 {identifier} {source['generation']}")

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
            self._playback_frames()
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
