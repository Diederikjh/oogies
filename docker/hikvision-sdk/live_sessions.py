"""Independent viewer leases referring to shared overview sources."""

from datetime import datetime, timezone
import json
import threading
import time
import uuid


class SessionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LiveSessions:
    def __init__(self, worker, limit=8, lease_seconds=90, clock=time.monotonic):
        self.worker, self.limit, self.lease_seconds, self.clock = worker, limit, lease_seconds, clock
        self.lock = worker.condition
        self.sessions, self.keys, self.wanted = {}, {}, set()
        self.closed = False
        self.reserved_sources = 0
        self.playback_sessions = None

    def selection(self, body):
        if not isinstance(body, dict) or set(body) != {"cameras"} or not isinstance(body["cameras"], list):
            raise SessionError("A cameras array is required.")
        identifiers = []
        for camera in body["cameras"]:
            if not isinstance(camera, dict) or set(camera) != {"id", "quality"}:
                raise SessionError("Invalid camera selection.")
            identifier = camera["id"]
            if not isinstance(identifier, str) or identifier not in self.worker.cameras:
                raise SessionError("Unknown camera.", 404)
            if camera["quality"] != "overview":
                raise SessionError("Only overview substreams are verified.", 422)
            if identifier in identifiers:
                raise SessionError("Duplicate camera.")
            identifiers.append(identifier)
        return tuple(sorted(identifiers))

    def _active(self, cameras):
        return {key for key in cameras if self.worker.cameras[key]["online"] is not False}

    def create(self, body, key=None):
        self.worker.ensure_ready()
        with self.lock:
            self.reap()
            cameras = self.selection(body)
            if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 100):
                raise SessionError("Invalid idempotency key.")
            if key in self.keys:
                existing = self.sessions[self.keys[key]]
                if existing["cameras"] != cameras:
                    raise SessionError("Idempotency key already has another selection.", 409)
                existing["expires"] = self.clock() + self.lease_seconds
                return self.get(existing["id"])
            if len(self.sessions) >= 8:
                raise SessionError("Viewer limit reached.", 409)
            identifier = uuid.uuid4().hex
            self.sessions[identifier] = dict(id=identifier, cameras=cameras,
                expires=self.clock() + self.lease_seconds, key=key)
            if key is not None:
                self.keys[key] = identifier
            self._reconcile()
            return self.get(identifier)

    def _reconcile(self):
        desired = set().union(*(self._active(session["cameras"]) for session in self.sessions.values())) if self.sessions else set()
        # Retain working sources first. Extra requested cameras remain labeled.
        admitted = (self.wanted & desired) | set(sorted(desired - self.wanted)[:max(0, self.limit - self.reserved_sources - len(self.wanted & desired))])
        for identifier in sorted(self.wanted - admitted):
            self.worker.stop_source(identifier)
        for identifier in sorted(admitted - self.wanted):
            self.worker.start_source(identifier)
        self.wanted = admitted
        self.lock.notify_all()

    def get(self, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
            if session is None or session["expires"] <= self.clock():
                raise SessionError("Viewer session expired or missing.", 404)
            cameras = []
            for key in session["cameras"]:
                source = self.worker.sources.get(key, {})
                state = "offline" if self.worker.cameras[key]["online"] is False else source.get("state", "capacity_limited")
                if key not in self.wanted and state not in ("offline", "error"):
                    state = "capacity_limited"
                cameras.append(dict(id=key, quality="overview", state=state,
                    frames=source.get("received", 0), width=source.get("width", 0), height=source.get("height", 0),
                    last_frame_received_at=source.get("last_frame_received_at"),
                    frame_age_seconds=round(time.monotonic() - source["last_frame"], 2) if source.get("last_frame") else None,
                    error=source.get("error")))
            expires = datetime.fromtimestamp(time.time() + session["expires"] - self.clock(), timezone.utc).isoformat()
            return dict(id=identifier, expires_at=expires, lease_seconds=self.lease_seconds, cameras=cameras,
                media={"transport": "jpeg-frames-v1", "url": f"/media/live/{identifier}/frames"})

    def patch(self, identifier, body):
        with self.lock:
            if not isinstance(body, dict) or set(body) - {"cameras"}:
                raise SessionError("Invalid session update.")
            self.get(identifier)
            session = self.sessions[identifier]
            if "cameras" in body:
                session["cameras"] = self.selection(body)
            session["expires"] = self.clock() + self.lease_seconds
            self._reconcile()
            return self.get(identifier)

    def delete(self, identifier):
        with self.lock:
            session = self.sessions.pop(identifier, None)
            if session is not None:
                if session["key"] is not None:
                    self.keys.pop(session["key"], None)
                self._reconcile()

    def reap(self):
        with self.lock:
            for identifier in list(self.sessions):
                if self.sessions[identifier]["expires"] <= self.clock():
                    self.delete(identifier)

    def run_reaper(self):
        while not self.closed:
            self.maintain()
            if self.playback_sessions: self.playback_sessions.reap()
            time.sleep(1)

    def maintain(self):
        with self.lock:
            self.reap()
            if self.sessions:
                self.worker.refresh_availability()
                self._reconcile()

    def next_frames(self, identifier, seen):
        with self.lock:
            self.get(identifier)
            def changed():
                return identifier not in self.sessions or any(
                    self.worker.sources.get(key, {}).get("frame") is not None and
                    (self.worker.sources[key].get("generation"), self.worker.sources[key].get("sequence")) != seen.get(key)
                    for key in self.sessions[identifier]["cameras"])
            self.lock.wait_for(changed, timeout=1)
            session = self.get(identifier)
            packets = []
            for camera in session["cameras"]:
                key = camera["id"]; source = self.worker.sources.get(key, {})
                version = (source.get("generation"), source.get("sequence"))
                if key not in self.wanted or not source.get("frame") or version == seen.get(key):
                    continue
                header = json.dumps({"camera_id": key, "sequence": version[1]}, separators=(",", ":")).encode()
                frame = source["frame"]
                packet = len(header).to_bytes(2, "big") + header + frame
                packets.append(len(packet).to_bytes(4, "big") + packet)
                seen[key] = version
            return packets

    def close(self):
        with self.lock:
            self.closed = True
            for identifier in list(self.sessions):
                self.delete(identifier)
