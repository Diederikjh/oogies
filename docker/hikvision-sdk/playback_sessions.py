"""Independent historical positions and leases sharing the recorder worker."""

from datetime import datetime, timedelta, timezone
import json
import time
import uuid
from zoneinfo import ZoneInfo

from history_timeline import timestamp, utc_text, recorder_wall
from live_sessions import SessionError

RATES = (0.5, 1, 2, 4)

def playback_rate(value):
    if type(value) not in (int, float) or value not in RATES:
        raise SessionError("Choose a playback speed of 0.5, 1, 2 or 4.", 422)
    return value

class PlaybackSessions:
    def __init__(self, worker, live, limit=1, lease_seconds=90, clock=time.monotonic):
        self.worker, self.live, self.limit = worker, live, limit
        self.lease_seconds, self.clock = lease_seconds, clock
        self.lock = worker.condition
        self.zone = ZoneInfo(worker.config.get("timezone", "Africa/Johannesburg"))
        self.sessions = {}
        self.closed = False

    def create(self, body):
        if not isinstance(body, dict) or set(body) - {"camera_id", "from", "to", "position", "rate"} or not {"camera_id", "from", "to"} <= body.keys():
            raise SessionError("Camera and from/to range are required.")
        rate = playback_rate(body.get("rate", 1))
        begin, end = timestamp(body["from"]), timestamp(body["to"])
        if not begin < end or end - begin > timedelta(hours=6):
            raise SessionError("Choose a positive playback range of at most six hours.", 422)
        position = timestamp(body.get("position", body["from"]))
        if not begin <= position < end:
            raise SessionError("Playback position must be inside its range.", 422)
        cursor = begin
        while cursor < end:
            recorder_wall(cursor, self.zone); cursor += timedelta(minutes=1)
        recorder_wall(end, self.zone)
        self.worker.ensure_ready()
        with self.lock:
            self.reap()
            camera = body["camera_id"]
            if not isinstance(camera, str) or camera not in self.worker.cameras:
                raise SessionError("Unknown camera.", 404)
            if self.closed or self.worker.shutdown:
                raise SessionError("Playback service stopped.", 503)
            if len(self.sessions) >= self.limit or len(self.live.wanted) + self.live.reserved_sources >= self.live.limit:
                raise SessionError("No historical playback slot is available. Pause an unused live view first.", 409)
            identifier = uuid.uuid4().hex
            session = dict(id=identifier, camera_id=camera, begin=begin, end=end, generation=1,
                           requested_position=position,
                           expires=self.clock() + self.lease_seconds)
            self.sessions[identifier] = session
            self.live.reserved_sources += 1
            try:
                self.worker.start_playback(identifier, camera, recorder_wall(position, self.zone), recorder_wall(end, self.zone), 1, rate=rate)
            except (OSError, ValueError):
                self.delete(identifier)
                raise SessionError("Historical playback could not start.", 503) from None
            return self.get(identifier)

    def get(self, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
            if session is None or session["expires"] <= self.clock():
                raise SessionError("Playback session expired or missing.", 404)
            source = self.worker.playbacks.get(identifier, {})
            expires = datetime.fromtimestamp(time.time() + session["expires"] - self.clock(), timezone.utc)
            return dict(id=identifier, camera_id=session["camera_id"],
                **{"from":utc_text(session["begin"]), "to":utc_text(session["end"])},
                position=source.get("position"), position_precision="second", generation=session["generation"],
                state=source.get("state", "error"), error=source.get("error"), frames=source.get("received", 0),
                rate=source.get("rate", 1), requested_rate=source.get("requested_rate", 1),
                supported_rates=list(RATES), rate_error=source.get("rate_error"),
                width=source.get("width", 0), height=source.get("height", 0),
                supported_controls=["pause", "resume", "seek", "rate"], expires_at=utc_text(expires), lease_seconds=self.lease_seconds,
                media={"transport":"jpeg-frames-v1", "url":f"/media/playback/{identifier}"})

    def patch(self, identifier, body):
        if not isinstance(body, dict) or set(body) - {"state", "position", "rate"}:
            raise SessionError("Invalid playback update.")
        if "rate" in body: playback_rate(body["rate"])
        if "state" in body and body["state"] not in ("paused", "playing"):
            raise SessionError("Choose paused or playing.", 422)
        with self.lock:
            current = self.get(identifier)
            session = self.sessions[identifier]
            rate = body.get("rate", current["requested_rate"])
            if "rate" in body and "position" not in body and current["state"] in ("ended", "error"):
                raise SessionError("Select a time to restart playback.", 409)
            restarted = False
            if "position" in body:
                position = timestamp(body["position"])
                if not session["begin"] <= position < session["end"]:
                    raise SessionError("Seek target must be inside the playback range.", 422)
                wall = recorder_wall(position, self.zone)
                paused = body.get("state", "paused" if current["state"] in ("paused", "pausing") else "playing") == "paused"
                session["generation"] += 1
                session["requested_position"] = position
                self.worker.start_playback(identifier, session["camera_id"], wall, recorder_wall(session["end"], self.zone),
                                           session["generation"], paused=paused, rate=rate)
                restarted = True
            elif "state" in body:
                if current["state"] in ("ended", "error"):
                    raise SessionError("Select a time to restart playback.", 409)
                if body["state"] == "playing" and current["state"] in ("paused", "pausing"):
                    position = timestamp(current["position"]) if current["position"] else session["requested_position"]
                    position = max(session["begin"], min(session["end"] - timedelta(seconds=1), position))
                    session["generation"] += 1
                    session["requested_position"] = position
                    self.worker.start_playback(identifier, session["camera_id"], recorder_wall(position, self.zone),
                                               recorder_wall(session["end"], self.zone), session["generation"], rate=rate)
                    restarted = True
                elif body["state"] == "paused" and current["state"] not in ("paused", "pausing"):
                    self.worker.control_playback(identifier, True)
            if "rate" in body and not restarted: self.worker.set_playback_rate(identifier, rate)
            session["expires"] = self.clock() + self.lease_seconds
            return self.get(identifier)

    def delete(self, identifier):
        with self.lock:
            session = self.sessions.pop(identifier, None)
            if session is None: return
            try:
                self.worker.stop_playback(identifier)
            finally:
                self.live.reserved_sources -= 1
                self.live._reconcile()
                self.lock.notify_all()

    def reap(self):
        with self.lock:
            for identifier in list(self.sessions):
                if self.sessions[identifier]["expires"] <= self.clock(): self.delete(identifier)

    def next_frames(self, identifier, seen):
        with self.lock:
            self.get(identifier)
            def changed():
                source = self.worker.playbacks.get(identifier, {})
                return identifier not in self.sessions or (source.get("frame") is not None and
                    (source.get("generation"), source.get("sequence")) != seen.get(identifier))
            self.lock.wait_for(changed, timeout=1)
            session = self.get(identifier)
            source = self.worker.playbacks.get(identifier, {})
            version = source.get("generation"), source.get("sequence")
            if not source.get("frame") or version == seen.get(identifier): return []
            header = json.dumps(dict(camera_id=session["camera_id"], generation=version[0], sequence=version[1],
                position=source.get("position")), separators=(",", ":")).encode()
            packet = len(header).to_bytes(2, "big") + header + source["frame"]
            seen[identifier] = version
            return [len(packet).to_bytes(4, "big") + packet]

    def close(self):
        with self.lock:
            self.closed = True
            for identifier in list(self.sessions): self.delete(identifier)
