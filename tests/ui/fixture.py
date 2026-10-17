"""A recorder substitute for browser tests; only the worker boundary is fake."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import os
import json
import select
import threading
import time
from types import SimpleNamespace

from grid_server import create_server
from grid_worker import GridWorker
from live_sessions import LiveSessions
from playback_sessions import PlaybackSessions
from maintenance import run_maintenance
from recorder_time import recorder_utc, utc_text
from live_sources import source_identity


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
        self._ffmpeg("-framerate", "5", "-i", str(self.directory / "source-%02d.ppm"),
                     "-vf", "scale=704:576,negate", "-frames:v", "16", "-threads", "1", str(self.directory / "high-%02d.jpg"))
        self.high_frames = {f"camera-{channel}": [(self.directory / f"high-{(channel-1)*2+phase+1:02d}.jpg").read_bytes()
                             for phase in range(2)] for channel in range(1,9)}
        raw = self.directory / "frames.yv12"
        self._ffmpeg("-framerate", "5", "-i", str(self.directory / "source-%02d.ppm"), "-frames:v", "16",
                     "-vf", "swapuv", "-pix_fmt", "yuv420p", "-threads", "1", "-f", "rawvideo", str(raw))
        data = raw.read_bytes(); size = 352 * 288 * 3 // 2
        self.raw_frames = {f"camera-{channel}":[data[((channel-1)*2+phase)*size:((channel-1)*2+phase+1)*size]
            for phase in range(2)] for channel in range(1,9)}
        self.recording = self.directory / "recording.mp4"
        self._ffmpeg("-framerate", "5", "-i", str(self.directory / "source-%02d.ppm"),
                     "-t", "2", "-threads", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
                     "-movflags", "+faststart", str(self.recording))

    def _ffmpeg(self, *args):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                       check=True, timeout=30, capture_output=True)


class FakeRecorderWorker(GridWorker):
    def __init__(self, media, *, failure=False, delayed=False, failed_camera=None, offline_camera=None, exports_config=None):
        self.cache_now = 0
        super().__init__(None, SimpleNamespace(sdk_id="ui-fixture"), {"camera_overrides": {}, "exports":exports_config or {}},
                         media.directory, clock=lambda:self.cache_now)
        self.media = media
        self.condition = threading.Condition(threading.RLock())
        self.adapter = SimpleNamespace(sdk_id="ui-fixture")
        self.state, self.error = "stopped", None
        self.sdk_login_calls = self.login_calls = self.tested_capacity = 0
        self.connection_attempts = self.ensure_calls = 0
        self.cameras, self.sources = {}, {}
        self.started, self.stopped = Counter(), Counter()
        self.failure, self.failed_camera = failure, failed_camera
        self.offline_camera = offline_camera
        self.device_online, self.refresh_calls = {}, 0
        self.timeline_calls = []
        self.timeline_states = {}
        self.timeline_gate = threading.Event(); self.timeline_gate.set()
        self.playback_commands = []
        self.rate_failure = False
        self.high_gate = threading.Event(); self.high_gate.set()
        self.export_commands = []; self.export_stops = {}; self.export_gate = threading.Event(); self.export_gate.set()
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
                        online=channel != 9, aspect_ratio="16:9", live_qualities=["overview", "high"],
                        capabilities={"time_playback":"unknown", "motion_timeline":"unknown"})
                        for channel in range(1, 10)}
                    self.state = "ready"
                    for key, camera in self.cameras.items():
                        camera["online"] = camera["online"] and key != self.offline_camera
                        self.device_online[key] = camera["online"]
                    self.next_availability_refresh = self.clock() + self.availability_cache_seconds
            if self.state != "ready":
                raise ValueError(self.error)

    def _command(self, command):
        # Reuse the production cache/event logic; substitute only SDK transport.
        parts = command.split()
        if parts[0].startswith("playback-"):
            self.playback_commands.append(command)
            identifier, generation = parts[2], int(parts[3])
            source = self.playbacks.get(identifier)
            if source and source["generation"] == generation:
                if parts[0] == "playback-start":
                    source.update(ready_at=time.monotonic() + .15,
                        rate=source["requested_rate"],
                        play_time=recorder_utc(parts[4], self.zone), end_time=recorder_utc(parts[5], self.zone),
                        pause_on_frame=parts[6] == "1")
                    self._event(dict(type="playback", id=identifier, generation=generation, state="starting", error=0))
                elif parts[0] in ("playback-pause", "playback-resume"):
                    self._event(dict(type="playback", id=identifier, generation=generation,
                        state="paused" if parts[0] == "playback-pause" else "playing", error=0))
                elif parts[0] == "playback-rate":
                    self._event(dict(type="playback_rate", id=identifier, generation=generation,
                        requested_rate=source["requested_rate"],
                        rate=source["rate"] if self.rate_failure else source["requested_rate"],
                        error=2 if self.rate_failure else 0))
            return
        if command != "refresh":
            raise AssertionError("Unexpected fake SDK command")
        self.refresh_calls += 1
        self._event({"type":"availability", "cameras":[
            {"channel":camera["channel"], "online":self.device_online[key]}
            for key,camera in self.cameras.items()]})

    def query_timeline(self, camera_id, begin, end):
        self.timeline_calls.append((camera_id, begin, end))
        if not self.timeline_gate.wait(10):
            raise ValueError("Fixture history gate was not released")
        start, stop = datetime.fromisoformat(begin), datetime.fromisoformat(end)
        span = stop - start
        wall = lambda fraction:(start + span * fraction).isoformat(timespec="seconds")
        recording = lambda left,right:dict(start=wall(left), end=wall(right), recording_type=0)
        motion = lambda left,right:dict(start=wall(left), end=wall(right), recording_type=1)
        recordings = dict(state="ready", complete=True, source="NET_DVR_FindFile_V30",
                          intervals=[recording(0,.4), recording(.6,1)])
        state = self.timeline_states.get(camera_id, "ready")
        events = [motion(.15,.17), motion(.65,.65), motion(.85,.88)] if state == "ready" else []
        result = dict(state="ready" if state == "empty" else state, complete=True,
                      source="NET_DVR_FindFileByEvent", intervals=events)
        if state in ("unsupported", "error"):
            result.update(intervals=None, complete=False, sdk_error=23 if state == "unsupported" else 11)
        return dict(recordings=recordings, motion=result)

    def start_source(self, key):
        self.started[key] += 1
        self.sources[key] = dict(state="starting", frame=None, sequence=0, generation=self.started[key],
                                 width=0, height=0, received=0, last_frame=0, error=None,
                                 ready_at=time.monotonic() + 0.15)
        if key == self.failed_camera:
            self.sources[key].update(state="error", error="Simulated camera stream failure.")

    def start_export(self, identifier, camera_id, begin, end):
        self.export_commands.append((identifier, camera_id, begin, end)); self.exports[identifier] = None
        stop = threading.Event(); self.export_stops[identifier] = stop
        def send():
            fd = os.open(self.export_directory / identifier / "frames.pipe", os.O_WRONLY | os.O_NONBLOCK)
            start, finish = recorder_utc(begin, self.zone), recorder_utc(end, self.zone)
            try:
                index = -2
                while not stop.is_set():
                    if not self.export_gate.wait(.1): continue
                    position = start + timedelta(seconds=index / 5)
                    frame = self.media.raw_frames.get(camera_id, self.media.raw_frames["camera-1"])[index % 2]
                    header = dict(size=len(frame), width=352, height=288, fps=5, stamp=(index + 2)*200,
                                  position=position.astimezone(self.zone).isoformat(timespec="seconds").split("+")[0],
                                  ms=position.microsecond // 1000)
                    packet = memoryview(json.dumps(header).encode() + b"\n" + frame)
                    while packet and not stop.is_set():
                        if not select.select([], [fd], [], .1)[1]: continue
                        try: size = os.write(fd, packet)
                        except BlockingIOError: continue
                        packet = packet[size:]
                    if position >= finish: break
                    index += 1
                    stop.wait(.04)
            except BrokenPipeError: pass
            finally:
                os.close(fd); self._event(dict(type="export", id=identifier, error=0))
        threading.Thread(target=send, daemon=True).start()

    def stop_export(self, identifier):
        if identifier in self.export_stops: self.export_stops[identifier].set()

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
                    camera, quality = source_identity(key)
                    if quality == "high" and not self.high_gate.is_set(): continue
                    frames = self.media.high_frames if quality == "high" else self.media.frames
                    source.update(state="live", frame=frames[camera][source["sequence"] % 2],
                        width=704 if quality == "high" else 352, height=576 if quality == "high" else 288,
                        received=source["sequence"], last_frame=time.monotonic(),
                        last_frame_received_at=datetime.now(timezone.utc).isoformat())
                self.tested_capacity = max(self.tested_capacity, sum(s["state"] == "live" for s in self.sources.values()))
                for identifier, source in self.playbacks.items():
                    if source["state"] not in ("starting", "seeking", "playing") or time.monotonic() < source["ready_at"]: continue
                    if source["play_time"] >= source["end_time"]:
                        self._event(dict(type="playback", id=identifier, generation=source["generation"], state="ended", error=0)); continue
                    source["sequence"] += 1
                    key = source["camera_id"] if source["camera_id"] in self.media.frames else "camera-1"
                    source.update(state="playing", frame=self.media.frames[key][source["sequence"] % 2],
                        width=352, height=288, received=source["sequence"], last_frame=time.monotonic(), position=utc_text(source["play_time"].replace(microsecond=0)))
                    source["play_time"] += timedelta(seconds=.2 * source["rate"])
                    if source["pause_on_frame"]:
                        source["pause_on_frame"] = False
                        self._event(dict(type="playback", id=identifier, generation=source["generation"], state="paused", error=0))
                self.condition.notify_all()

    def close(self):
        self.shutdown = True
        self.discovery_gate.set()
        self.timeline_gate.set()
        self.export_gate.set()
        for stop in self.export_stops.values(): stop.set()
        self.closed.set()
        self.thread.join(timeout=2)


class ViewerFixture:
    def __init__(self, media, *, limit=8, lease=10, recording=True, playback_limit=1, high_limit=1, **worker_options):
        self.worker = FakeRecorderWorker(media, **worker_options)
        self.sessions = LiveSessions(self.worker, limit=limit, lease_seconds=lease, high_limit=high_limit)
        self.server = create_server(self.worker, self.sessions, address=("127.0.0.1", 0), web="/web",
            recording=media.recording if recording else media.directory / "missing.mp4",
            playback=PlaybackSessions(self.worker, self.sessions.budget, limit=playback_limit, lease_seconds=lease))
        self.worker.export_directory = self.server.exports.directory
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.reaper = threading.Thread(target=run_maintenance,
            args=(self.sessions, self.server.playback, self.server.maintenance_stop), daemon=True)
        self.reaper.start()

    def snapshot(self):
        with self.worker.condition:
            return dict(viewers=len(self.sessions.sessions), sources=len(self.sessions.wanted),
                        started=dict(self.worker.started), stopped=dict(self.worker.stopped),
                        attempts=self.worker.connection_attempts)

    def close(self):
        self.server.maintenance_stop.set()
        self.worker.discovery_gate.set()
        self.worker.timeline_gate.set()
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.sessions.close()
        self.server.playback.close()
        self.server.timeline.close()
        self.server.server_close()
        self.reaper.join(timeout=2)
        self.worker.close()
