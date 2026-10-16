"""Independent viewer leases referring to shared, quality-specific live sources."""

from datetime import datetime, timezone
import json
import threading
import time
import uuid
from live_sources import source_key, source_identity


class SessionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LiveSessions:
    def __init__(self, worker, limit=8, lease_seconds=90, clock=time.monotonic, high_limit=1):
        self.worker, self.limit, self.lease_seconds, self.clock = worker, limit, lease_seconds, clock
        self.lock = worker.condition
        self.sessions, self.keys, self.wanted = {}, {}, set()
        self.closed = False
        self.reserved_sources = 0
        self.playback_sessions = None
        self.high_limit = high_limit
        self.upgrade_refusals = self.upgrade_failures = 0
        self.recent_upgrade_events = []

    def selection(self, body):
        if not isinstance(body, dict) or set(body) != {"cameras"} or not isinstance(body["cameras"], list):
            raise SessionError("A cameras array is required.")
        identifiers, seen = [], set()
        for camera in body["cameras"]:
            if not isinstance(camera, dict) or set(camera) != {"id", "quality"}:
                raise SessionError("Invalid camera selection.")
            identifier = camera["id"]
            if not isinstance(identifier, str) or identifier not in self.worker.cameras:
                raise SessionError("Unknown camera.", 404)
            quality = camera["quality"]
            if quality not in ("overview", "high"):
                raise SessionError("Unknown live quality.", 422)
            if identifier in seen:
                raise SessionError("Duplicate camera.")
            seen.add(identifier)
            identifiers.append((identifier, quality))
        return tuple(sorted(identifiers))

    def _active(self, cameras):
        return {key for key, quality in cameras if self.worker.cameras[key]["online"] is not False}

    def occupied_sources(self):
        """Include native stops not yet acknowledged, under the shared lock."""
        return self.wanted | {key for key, source in self.worker.sources.items() if source.get("state") == "stopping"}

    def used_sources(self):
        return len(self.occupied_sources()) + self.reserved_sources

    def _upgrade_result(self, session, camera, state, reason=None):
        previous = session["upgrades"].get(camera, {})
        session["upgrades"][camera] = dict(state=state, reason=reason)
        if state in ("capacity_limited", "unsupported", "error", "offline") and previous.get("state") != state:
            if state == "error": self.upgrade_failures += 1
            else: self.upgrade_refusals += 1
            self.recent_upgrade_events.append(dict(camera_id=camera, state=state, reason=reason,
                                                   at=datetime.now(timezone.utc).isoformat()))
            del self.recent_upgrade_events[:-20]

    def _request_upgrades(self, session, retry=None):
        old = session.get("upgrades", {})
        session["upgrades"] = {camera:old[camera] if camera in old and
                                (old[camera]["state"] in ("pending", "active") or (retry is not None and camera not in retry))
                                else dict(state="requested", reason=None)
                                for camera, quality in session["cameras"] if quality == "high"}

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
                expires=self.clock() + self.lease_seconds, key=key, revision=1)
            self._request_upgrades(self.sessions[identifier])
            if key is not None:
                self.keys[key] = identifier
            self._reconcile()
            return self.get(identifier)

    def _reconcile(self, notify=True):
        desired = set().union(*(self._active(session["cameras"]) for session in self.sessions.values())) if self.sessions else set()
        # A failed/stalled high source falls back for all of its subscribers.
        for session in self.sessions.values():
            for camera, upgrade in list(session["upgrades"].items()):
                if upgrade["state"] not in ("pending", "active"): continue
                source = self.worker.sources.get(source_key(camera, "high"), {})
                if source.get("state") in ("error", "capacity_limited", "stale", "stopped") or (source.get("last_frame") and time.monotonic() - source["last_frame"] > 5):
                    self._upgrade_result(session, camera, "error", dict(code="stream_failed",
                        message=source.get("error") or "High-quality video stopped arriving."))
                elif self.worker.cameras[camera]["online"] is False:
                    self._upgrade_result(session, camera, "offline", dict(code="offline", message="Camera is offline."))
                elif source.get("state") == "live" and source.get("frame"):
                    upgrade["state"] = "active"
        high_desired = {source_key(camera, "high") for session in self.sessions.values()
                        for camera, upgrade in session["upgrades"].items() if upgrade["state"] in ("pending", "active")}
        desired |= high_desired
        # Retain working sources first. Extra requested cameras remain labeled.
        retained = self.wanted & desired
        for identifier in sorted(self.wanted - retained):
            self.worker.stop_source(identifier)
        self.wanted = retained
        available = max(0, self.limit - self.used_sources())
        additions = set(sorted(desired - self.occupied_sources())[:available])
        for identifier in sorted(additions):
            self.worker.start_source(identifier)
        self.wanted |= additions
        for session in self.sessions.values():
            for camera, upgrade in list(session["upgrades"].items()):
                if upgrade["state"] != "requested": continue
                key = source_key(camera, "high")
                high_used = sum(source_identity(item)[1] == "high" for item in self.occupied_sources())
                if self.worker.cameras[camera]["online"] is False:
                    self._upgrade_result(session, camera, "offline", dict(code="offline", message="Camera is offline."))
                elif "high" not in self.worker.cameras[camera].get("live_qualities", ["overview", "high"]):
                    self._upgrade_result(session, camera, "unsupported", dict(code="unsupported", message="Main-stream viewing is unsupported."))
                elif camera not in self.wanted:
                    self._upgrade_result(session, camera, "capacity_limited", dict(code="source_limit", message="No overview fallback slot is available."))
                elif key in self.wanted:
                    upgrade["state"] = "pending"
                elif high_used >= self.high_limit or self.used_sources() >= self.limit or key in self.occupied_sources():
                    self._upgrade_result(session, camera, "capacity_limited", dict(code="high_quality_limit" if high_used >= self.high_limit else "source_limit",
                        message="High-quality capacity is unavailable; showing overview."))
                else:
                    self.worker.start_source(key); self.wanted.add(key)
                    upgrade["state"] = "pending"
        if notify: self.lock.notify_all()

    def get(self, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
            if session is None or session["expires"] <= self.clock():
                raise SessionError("Viewer session expired or missing.", 404)
            self._reconcile(notify=False)
            cameras = []
            for camera, requested in session["cameras"]:
                upgrade = session["upgrades"].get(camera, dict(state="overview", reason=None))
                high = self.worker.sources.get(source_key(camera, "high"), {})
                quality = "high" if upgrade["state"] in ("pending", "active") and high.get("state") == "live" and high.get("frame") else "overview"
                key = source_key(camera, quality)
                source = self.worker.sources.get(key, {})
                state = "offline" if self.worker.cameras[camera]["online"] is False else source.get("state", "capacity_limited")
                if key not in self.wanted and state not in ("offline", "error"):
                    state = "capacity_limited"
                cameras.append(dict(id=camera, quality=quality, requested_quality=requested,
                    upgrade_state="active" if quality == "high" else upgrade["state"], quality_reason=upgrade["reason"], state=state,
                    frames=source.get("received", 0), width=source.get("width", 0), height=source.get("height", 0),
                    last_frame_received_at=source.get("last_frame_received_at"),
                    frame_age_seconds=round(time.monotonic() - source["last_frame"], 2) if source.get("last_frame") else None,
                    error=source.get("error")))
            expires = datetime.fromtimestamp(time.time() + session["expires"] - self.clock(), timezone.utc).isoformat()
            return dict(id=identifier, selection_revision=session["revision"], expires_at=expires, lease_seconds=self.lease_seconds, cameras=cameras,
                media={"transport": "jpeg-frames-v1", "url": f"/media/live/{identifier}/frames"})

    def patch(self, identifier, body):
        with self.lock:
            if not isinstance(body, dict) or set(body) - {"cameras", "retry_high"} or ("retry_high" in body and "cameras" not in body):
                raise SessionError("Invalid session update.")
            self.get(identifier)
            session = self.sessions[identifier]
            if "cameras" in body:
                cameras = self.selection({"cameras":body["cameras"]})
                retry = body.get("retry_high")
                if "retry_high" in body and (not isinstance(retry, list) or any(not isinstance(camera, str) for camera in retry) or
                    len(set(retry)) != len(retry) or set(retry) - {camera for camera, quality in cameras if quality == "high"}):
                    raise SessionError("retry_high must list distinct cameras selected at high quality.")
                session["cameras"] = cameras
                session["revision"] += 1
                self._request_upgrades(session, retry)
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

    def _new_frames(self, session, seen):
        for camera in session["cameras"]:
            camera_id = camera["id"]
            key = source_key(camera_id, camera["quality"])
            source = self.worker.sources.get(key, {})
            version = (camera["quality"], source.get("generation"), source.get("sequence"), session["selection_revision"])
            if key in self.wanted and camera["state"] == "live" and source.get("frame") and version != seen.get(camera_id):
                yield camera, source, version

    def next_frames(self, identifier, seen):
        with self.lock:
            self.get(identifier)
            def changed():
                return identifier not in self.sessions or any(self._new_frames(self.get(identifier), seen))
            self.lock.wait_for(changed, timeout=1)
            session = self.get(identifier)
            packets = []
            for camera, source, version in self._new_frames(session, seen):
                camera_id = camera["id"]
                header = json.dumps({"camera_id": camera_id, "quality":camera["quality"], "generation":source.get("generation"),
                    "sequence":source.get("sequence"), "selection_revision":session["selection_revision"]}, separators=(",", ":")).encode()
                frame = source["frame"]
                packet = len(header).to_bytes(2, "big") + header + frame
                packets.append(len(packet).to_bytes(4, "big") + packet)
                seen[camera_id] = version
            return packets

    def quality_status(self):
        with self.lock:
            self._reconcile(notify=False)
            occupied = self.occupied_sources()
            high = [key for key in occupied if source_identity(key)[1] == "high"]
            metrics = []
            for key in sorted(occupied):
                camera, quality = source_identity(key); source = self.worker.sources.get(key, {})
                age = time.monotonic() - source["last_frame"] if source.get("last_frame") else None
                metrics.append(dict(camera_id=camera, quality=quality, state=source.get("state"),
                    width=source.get("width", 0), height=source.get("height", 0),
                    frame_age_seconds=round(age, 3) if age is not None else None,
                    decoded_fps=source.get("decoded_fps"), delivered_fps=source.get("delivered_fps"),
                    jpeg_bytes_per_second=source.get("jpeg_bytes_per_second"),
                    stream_bytes_per_second=source.get("stream_bytes_per_second"),
                    first_frame_seconds=source.get("first_frame_seconds")))
            return dict(high_quality_limit=self.high_limit, high_quality_requested=sum(len(s["upgrades"]) for s in self.sessions.values()),
                high_quality_starting=sum(self.worker.sources[key].get("state") == "starting" for key in high),
                high_quality_active=sum(self.worker.sources[key].get("state") == "live" for key in high),
                sources_by_quality={"overview":len(occupied)-len(high), "high":len(high)},
                reserved_sources=self.reserved_sources, occupied_source_slots=self.used_sources(),
                upgrade_refusals=self.upgrade_refusals, upgrade_failures=self.upgrade_failures,
                recent_upgrade_events=list(self.recent_upgrade_events), live_source_metrics=metrics)

    def close(self):
        with self.lock:
            self.closed = True
            for identifier in list(self.sessions):
                self.delete(identifier)
