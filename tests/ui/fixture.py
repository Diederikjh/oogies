"""A recorder substitute for browser tests; only the worker boundary is fake."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

from grid_server import create_server
from live_sessions import LiveSessions


COLORS = [(190, 35, 45), (35, 140, 65), (40, 70, 195), (185, 135, 30),
          (155, 45, 175), (30, 145, 175), (175, 80, 35), (80, 110, 170)]


class SyntheticMedia:
    """Generate valid, distinct and changing fixtures with Docker's FFmpeg."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True)
        for channel, color in enumerate(COLORS, 1):
            for phase in range(2):
                pixels = bytearray(bytes(color) * 352 * 288)
                left = 110 + 50 * phase
                for y in range(110, 155):
                    offset = (y * 352 + left) * 3
                    pixels[offset:offset + 40 * 3] = b'\xff\xff\xff' * 40
                index = (channel - 1) * 2 + phase + 1
                (self.directory / f"source-{index:02d}.ppm").write_bytes(b"P6\n352 288\n255\n" + pixels)
        self._ffmpeg("-framerate", "5", "-i", str(self.directory / "source-%02d.ppm"),
                     "-frames:v", "16", "-threads", "1", str(self.directory / "frame-%02d.jpg"))
        self.frames = {f"camera-{channel}": [(self.directory / f"frame-{(channel-1)*2+phase+1:02d}.jpg").read_bytes()
                        for phase in range(2)] for channel in range(1, 9)}
        self.recording = self.directory / "recording.mp4"
        self._ffmpeg("-framerate", "5", "-i", str(self.directory / "source-%02d.ppm"),
                     "-t", "2", "-threads", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                     "-movflags", "+faststart", str(self.recording))

    def _ffmpeg(self, *args):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                       check=True, timeout=30, capture_output=True)


class FakeRecorderWorker:
    def __init__(self, media, *, failure=False, delayed=False, failed_camera=None):
        self.media = media
        self.condition = threading.Condition(threading.RLock())
        self.adapter = SimpleNamespace(sdk_id="ui-fixture")
        self.state, self.error = "stopped", None
        self.sdk_login_calls = self.login_calls = self.tested_capacity = 0
        self.connection_attempts = self.ensure_calls = 0
        self.cameras, self.sources = {}, {}
        self.started, self.stopped = Counter(), Counter()
        self.failure, self.failed_camera = failure, failed_camera
        self.discovery_gate = threading.Event()
        if not delayed:
            self.discovery_gate.set()
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def ensure_ready(self):
        with self.condition:
            self.ensure_calls += 1
        if not self.discovery_gate.wait(10):
            raise ValueError("Fixture discovery gate was not released")
        with self.condition:
            if self.state == "stopped":
                self.connection_attempts += 1
                if self.failure:
                    self.state, self.error = "error", "Simulated recorder rejection; no automatic retry."
                else:
                    self.cameras = {f"camera-{channel}": dict(id=f"camera-{channel}", channel=channel,
                        name="Driveway" if channel == 1 else ("Front <porch> & gate" if channel == 2 else f"Camera {channel}"),
                        online=channel != 9, aspect_ratio="16:9", live_qualities=["overview"],
                        capabilities={"time_playback":"unknown", "motion_timeline":"unknown"})
                        for channel in range(1, 10)}
                    self.state = "ready"
            if self.state != "ready":
                raise ValueError(self.error)

    def start_source(self, key):
        self.started[key] += 1
        self.sources[key] = dict(state="starting", frame=None, sequence=0, generation=self.started[key],
                                 width=0, height=0, received=0, last_frame=0, error=None,
                                 ready_at=time.monotonic() + 0.15)
        if key == self.failed_camera:
            self.sources[key].update(state="error", error="Simulated camera stream failure.")

    def stop_source(self, key):
        self.stopped[key] += 1
        self.sources[key].update(state="stopped", frame=None)

    def set_state(self, key, state):
        with self.condition:
            self.sources[key].update(state=state, error="Simulated camera stream failure." if state == "error" else None)
            self.condition.notify_all()

    def _animate(self):
        while not self.closed.wait(0.2):
            with self.condition:
                for key, source in self.sources.items():
                    if source["state"] not in ("starting", "live") or time.monotonic() < source["ready_at"]:
                        continue
                    source["sequence"] += 1
                    source.update(state="live", frame=self.media.frames[key][source["sequence"] % 2],
                        width=352, height=288, received=source["sequence"], last_frame=time.monotonic(),
                        last_frame_received_at=datetime.now(timezone.utc).isoformat())
                self.tested_capacity = max(self.tested_capacity, sum(s["state"] == "live" for s in self.sources.values()))
                self.condition.notify_all()

    def close(self):
        self.discovery_gate.set()
        self.closed.set()
        self.thread.join(timeout=2)


class ViewerFixture:
    def __init__(self, media, *, limit=8, lease=10, recording=True, **worker_options):
        self.worker = FakeRecorderWorker(media, **worker_options)
        self.sessions = LiveSessions(self.worker, limit=limit, lease_seconds=lease)
        self.server = create_server(self.worker, self.sessions, address=("127.0.0.1", 0), web="/web",
            recording=media.recording if recording else media.directory / "missing.mp4")
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.reaper = threading.Thread(target=self.sessions.run_reaper, daemon=True)
        self.reaper.start()

    def snapshot(self):
        with self.worker.condition:
            return dict(viewers=len(self.sessions.sessions), sources=len(self.sessions.wanted),
                        started=dict(self.worker.started), stopped=dict(self.worker.stopped),
                        attempts=self.worker.connection_attempts)

    def close(self):
        self.worker.discovery_gate.set()
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.sessions.close()
        self.server.server_close()
        self.reaper.join(timeout=2)
        self.worker.close()
