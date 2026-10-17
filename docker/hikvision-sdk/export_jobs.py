"""Shared bounded export queue, private durable artifacts and source admission."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from export_encoder import ExportEncoder, ExportFailure, ExportCancelled
from history_timeline import timestamp, utc_text, recorder_wall
from live_sessions import SessionError
from nvr_config import export_limits


class ExportJobs:
    def __init__(self, worker, live, directory, *, encoder=None, clock=time.time, start=True):
        self.worker, self.live, self.directory = worker, live, Path(directory)
        self.lock = worker.condition; self.clock = clock
        self.zone = ZoneInfo(worker.config.get("timezone", "Africa/Johannesburg"))
        self.limits = export_limits(worker.config.get("exports"))
        self.encoder = encoder or ExportEncoder(worker, self.zone, self.limits["max_file_bytes"])
        self.jobs = {}; self.readers = {}; self.active = None; self.cancel = None
        self.closed = False; self.thread = None
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True); self.directory.chmod(0o700)
        self.manifest = self.directory / "jobs.json"
        self._restore()
        if start:
            self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()

    def _save(self):
        temporary = self.directory / "jobs.tmp.json"
        with temporary.open("w") as file:
            json.dump({"version":1, "jobs":list(self.jobs.values())}, file)
            file.flush()
            import os
            os.fsync(file.fileno())
        temporary.chmod(0o600); temporary.replace(self.manifest)

    def _restore(self):
        if self.manifest.exists():
            data = json.loads(self.manifest.read_text())
            if data.get("version") != 1: raise ValueError("Unsupported export manifest version")
            for job in data["jobs"]:
                if not re.fullmatch(r"[a-f0-9]{32}", job["id"]): raise ValueError("Invalid export manifest")
                self.jobs[job["id"]] = job
                if job["state"] == "running":
                    job.update(state="failed", error="Export interrupted by service restart.", finished_at=self.clock())
                if job["state"] == "ready" and not self._clip(job["id"]).is_file():
                    job.update(state="expired", error="Export file is missing.")
        for directory in self.directory.iterdir():
            if not directory.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", directory.name): continue
            for file in directory.iterdir():
                if file.name != "clip.mp4": file.unlink(missing_ok=True)
            if directory.name not in self.jobs or self.jobs[directory.name]["state"] != "ready":
                shutil.rmtree(directory)
        self._expire(); self._save()

    def _clip(self, identifier): return self.directory / identifier / "clip.mp4"

    def _expire(self):
        changed = False
        for identifier, job in self.jobs.items():
            if job["state"] == "ready" and (job["expires_at"] <= self.clock() or not self._clip(identifier).is_file()):
                job.update(state="expired", error="Export expired or file is missing."); changed = True
            if job["state"] in ("expired", "failed", "cancelled") and identifier != self.active and not self.readers.get(identifier):
                directory = self.directory / identifier
                if directory.exists(): shutil.rmtree(directory)
        # Keep ready/queued jobs, plus a bounded recent terminal history.
        terminal = [job for job in self.jobs.values() if job["state"] in ("expired", "failed", "cancelled")]
        excess = max(0, len(terminal) - 50, len(self.jobs) - 99)
        for job in sorted(terminal, key=lambda item:item["created_at"])[:excess]:
            if job["id"] != self.active and not self.readers.get(job["id"]): del self.jobs[job["id"]]; changed = True
        if changed: self._save()

    def _used_bytes(self):
        total = 0
        for path in self.directory.glob("*/clip*.mp4"):
            try:
                metadata = path.stat()
            except FileNotFoundError:
                # Capture can rename/remove a partial after directory enumeration.
                continue
            if stat.S_ISREG(metadata.st_mode): total += metadata.st_size
        return total

    def create(self, body, key=None):
        if not isinstance(body, dict) or set(body) != {"camera_id", "from", "to", "aspect_ratio"}:
            raise SessionError("Camera, from/to range and aspect_ratio are required.", 422)
        begin, end = timestamp(body["from"]), timestamp(body["to"])
        if any(datetime.fromisoformat(body[name].replace("Z", "+00:00")).microsecond for name in ("from", "to")):
            raise SessionError("Clip marks must use whole seconds.", 422)
        seconds = (end - begin).total_seconds()
        if begin.microsecond or end.microsecond or not 1 <= seconds <= self.limits["max_duration_seconds"]:
            raise SessionError(f"Choose whole seconds and a clip of 1-{self.limits['max_duration_seconds']} seconds.", 422)
        if end > datetime.fromtimestamp(self.clock(), timezone.utc):
            raise SessionError("Choose a recorded range in the past.", 422)
        cursor = begin
        while cursor <= end: recorder_wall(cursor, self.zone); cursor += timedelta(seconds=30)
        recorder_wall(end, self.zone)
        if body["aspect_ratio"] not in ("16:9", "4:3", "original") or not isinstance(body["camera_id"], str):
            raise SessionError("Invalid camera or picture proportions.", 422)
        if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key)):
            raise SessionError("Invalid idempotency key.", 422)
        request = dict(camera_id=body["camera_id"], **{"from":utc_text(begin), "to":utc_text(end)}, aspect_ratio=body["aspect_ratio"])
        with self.lock:
            self._expire()
            for job in self.jobs.values():
                if key and job.get("key") == key:
                    if job["request"] != request: raise SessionError("Idempotency key already used for a different clip.", 409)
                    return self._public(job)
            if self.closed: raise SessionError("Export service stopped.", 503)
            if sum(job["state"] == "queued" for job in self.jobs.values()) >= self.limits["max_waiting_jobs"]:
                raise SessionError("Export queue is full. Wait for a job to finish.", 429)
            if len(self.jobs) >= 100 or self._used_bytes() + 2 * self.limits["max_file_bytes"] > self.limits["storage_bytes"]:
                raise SessionError("Export storage is full. Delete a completed clip first.", 409)
        self.worker.ensure_ready()
        with self.lock:
            # Recheck admission after discovery, since simultaneous requests may
            # have filled the queue while the worker was starting.
            for job in self.jobs.values():
                if key and job.get("key") == key:
                    if job["request"] != request: raise SessionError("Idempotency key already used.", 409)
                    return self._public(job)
            if body["camera_id"] not in self.worker.cameras: raise SessionError("Unknown camera.", 404)
            if self.closed: raise SessionError("Export service stopped.", 503)
            if sum(job["state"] == "queued" for job in self.jobs.values()) >= self.limits["max_waiting_jobs"]: raise SessionError("Export queue is full.", 429)
            if len(self.jobs) >= 100: raise SessionError("Export history is full. Delete a completed clip first.", 409)
            identifier = uuid.uuid4().hex
            job = dict(id=identifier, request=request, key=key, camera_name=self.worker.cameras[body["camera_id"]]["name"],
                       state="queued", progress=0, duration_seconds=seconds, created_at=self.clock(), error=None, waiting_reason=None)
            self.jobs[identifier] = job; self._save(); self.lock.notify_all()
            return self._public(job)

    def _public(self, job):
        value = {key:item for key,item in job.items() if key not in ("key", "request", "created_at", "finished_at", "expires_at")}
        value.update(job["request"], created_at=utc_text(datetime.fromtimestamp(job["created_at"], timezone.utc)))
        value["timezone"] = self.zone.key
        if job.get("expires_at"):
            value["expires_at"] = utc_text(datetime.fromtimestamp(job["expires_at"], timezone.utc))
        if job["state"] == "ready":
            value["media"] = {"url":f"/media/exports/{job['id']}.mp4", "filename":self.filename(job)}
        return value

    def filename(self, job):
        stamp = timestamp(job["request"]["from"]).strftime("%Y%m%dT%H%M%SZ")
        return f"oogies-{job['request']['camera_id']}_{stamp}_{int(job['duration_seconds'])}s.mp4"

    def list(self):
        with self.lock:
            self._expire()
            return dict(jobs=[self._public(job) for job in sorted(self.jobs.values(), key=lambda item:item["created_at"], reverse=True)],
                        limits={**self.limits, "active_workers":1}, storage_used_bytes=self._used_bytes())

    def get(self, identifier):
        with self.lock:
            self._expire()
            if identifier not in self.jobs: raise SessionError("Export not found.", 404)
            return self._public(self.jobs[identifier])

    def delete(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job: return
            if identifier == self.active:
                self.cancel.set(); job.update(state="cancelled", error=None)
            elif job["state"] == "queued": job.update(state="cancelled", error=None)
            elif job["state"] == "ready": job.update(state="expired", error="Export deleted.")
            self._expire(); self._save(); self.lock.notify_all()

    @contextmanager
    def download(self, identifier):
        with self.lock:
            self._expire()
            if identifier not in self.jobs: raise SessionError("Export expired or missing.", 410)
            job = self.jobs[identifier]
            if job["state"] == "expired": raise SessionError("Export expired or deleted.", 410)
            if job["state"] != "ready": raise SessionError("Export is not ready to download.", 409)
            file = self._clip(identifier).open("rb")
            self.readers[identifier] = self.readers.get(identifier, 0) + 1
            filename = self.filename(job)
        try: yield file, filename
        finally:
            file.close()
            with self.lock:
                self.readers[identifier] -= 1; self._expire(); self.lock.notify_all()

    def _run(self):
        while True:
            with self.lock:
                self._expire()
                if self.closed: return
                job = next((job for job in self.jobs.values() if job["state"] == "queued"), None)
                if job is None: self.lock.wait(timeout=1); continue
                if self.live.used_sources() >= self.live.limit:
                    job["waiting_reason"] = "Waiting for a recorder stream slot. Pause an unused live view."; self.lock.wait(timeout=1); continue
                if self._used_bytes() + 2 * self.limits["max_file_bytes"] > self.limits["storage_bytes"]:
                    job["waiting_reason"] = "Waiting for export storage. Delete a completed clip."; self.lock.wait(timeout=1); continue
                self.active = job["id"]; self.cancel = threading.Event(); self.live.reserved_sources += 1
                job.update(state="running", waiting_reason=None); self._save()
            try:
                self.worker.ensure_ready()
                directory = self.directory / job["id"]; directory.mkdir(mode=0o700, exist_ok=True)
                capture = {**job, **job["request"], "begin":timestamp(job["request"]["from"]), "end":timestamp(job["request"]["to"])}
                def progress(value):
                    with self.lock: job["progress"] = value
                result = self.encoder.capture(capture, directory, self.cancel, progress)
                with self.lock:
                    if self.cancel.is_set(): raise ExportCancelled()
                    job.update(state="ready", progress=1, finished_at=self.clock(),
                               expires_at=self.clock() + self.limits["retention_hours"] * 3600, **result)
            except ExportCancelled:
                with self.lock:
                    interrupted = self.closed and job["state"] != "cancelled"
                    job.update(state="failed" if interrupted else "cancelled",
                               error="Export interrupted by service shutdown." if interrupted else None, finished_at=self.clock())
            except (ExportFailure, OSError, ValueError) as error:
                with self.lock:
                    job.update(state="cancelled" if self.cancel.is_set() else "failed",
                               error=None if self.cancel.is_set() else str(error) if isinstance(error, ExportFailure) else "Export could not start.", finished_at=self.clock())
            finally:
                with self.lock:
                    self.live.reserved_sources -= 1; self.active = None; self.cancel = None
                    self._expire(); self._save(); self.live._reconcile(); self.lock.notify_all()

    def close(self):
        with self.lock:
            self.closed = True
            if self.cancel: self.cancel.set()
            self.lock.notify_all()
        if self.thread: self.thread.join(timeout=30)
