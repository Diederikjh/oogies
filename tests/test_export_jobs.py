from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import errno
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from zoneinfo import ZoneInfo
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from export_jobs import ExportJobs
from export_encoder import FrameClock, ExportFailure, ExportCancelled, validate_video
from grid_worker import GridWorker
from live_sessions import LiveSessions
from service_errors import SessionError
from nvr_config import export_limits
from grid_server import create_server


class Worker(GridWorker):
    def __init__(self):
        super().__init__(None, None, {}, "/tmp/unused-export-worker")
        self.state = "ready"; self.ensure_calls = 0
        self.cameras = {"camera-1":dict(channel=1, name="Camera <one>", online=False)}
    def ensure_ready(self): self.ensure_calls += 1
    def _command(self, command): pass


class Capture:
    def __init__(self): self.gate = threading.Event(); self.calls = []; self.failure = False
    def capture(self, job, directory, cancel, progress):
        self.calls.append(job)
        (directory / "clip.partial.mp4").write_bytes(b"partial")
        while not self.gate.wait(.01):
            if cancel.is_set(): raise ExportCancelled()
        if self.failure: raise ExportFailure("Simulated encoder failure.")
        if cancel.is_set(): raise ExportCancelled()
        (directory / "clip.mp4").write_bytes(b"synthetic-mp4")
        (directory / "clip.partial.mp4").unlink()
        return dict(bytes=13, actual_duration_seconds=job["duration_seconds"], frames=10, position_precision="second")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.worker = Worker(); self.live = LiveSessions(self.worker, limit=2)
        self.capture = Capture(); self.now = datetime(2026,10,11,20,tzinfo=timezone.utc).timestamp()
        self.jobs = ExportJobs(self.worker, self.live.budget, self.temporary.name, encoder=self.capture, clock=lambda:self.now)
        self.addCleanup(self.jobs.close)
        self.body = dict(camera_id="camera-1", aspect_ratio="16:9", **{"from":"2026-10-11T10:00:00Z", "to":"2026-10-11T10:00:10Z"})

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline: self.fail("Export state did not settle")
            time.sleep(.01)

    def ready(self):
        job = self.jobs.create(self.body); self.capture.gate.set()
        self.wait(lambda:self.jobs.get(job["id"])["state"] == "ready")
        self.wait(lambda:self.live.budget.snapshot().reserved == 0)
        return job["id"]

    def assert_removed(self, identifier):
        self.assertFalse((self.jobs.directory / identifier).exists())
        self.assertNotIn(identifier, self.jobs.jobs)
        self.assertNotIn(identifier, [job["id"] for job in self.jobs.list()["jobs"]])
        self.assertNotIn(identifier, [job["id"] for job in json.loads(self.jobs.manifest.read_text())["jobs"]])
        with self.assertRaises(SessionError) as error: self.jobs.get(identifier)
        self.assertEqual(error.exception.status, 404)

    def test_invalid_ranges_options_and_future_dates_do_not_touch_sdk(self):
        cases = [{**self.body,"to":self.body["from"]}, {**self.body,"to":"2026-10-11T10:10:01Z"},
                 {**self.body,"from":"2026-10-11T10:00:00.1Z"}, {**self.body,"aspect_ratio":"bad"},
                 {**self.body,"from":"2026-10-12T10:00:00Z","to":"2026-10-12T10:00:10Z"}]
        for body in cases:
            with self.assertRaises(SessionError): self.jobs.create(body)
        self.assertEqual(self.worker.ensure_calls, 0); self.assertEqual(self.capture.calls, [])

    def test_idempotency_immutable_request_and_offline_camera_export(self):
        first = self.jobs.create(self.body, "same-request")
        self.body["aspect_ratio"] = "4:3"
        with self.assertRaises(SessionError): self.jobs.create(self.body, "same-request")
        self.body["aspect_ratio"] = "16:9"
        self.assertEqual(self.jobs.create(self.body, "same-request")["id"], first["id"])
        self.wait(lambda:len(self.capture.calls) == 1)
        self.assertEqual(self.capture.calls[0]["aspect_ratio"], "16:9")
        self.assertEqual(self.live.budget.snapshot().reserved, 1)
        self.jobs.delete(first["id"]); self.jobs.delete(first["id"])
        self.wait(lambda:self.live.budget.snapshot().reserved == 0)
        self.assertEqual(self.jobs.get(first["id"])["state"], "cancelled")

    def test_ten_minute_boundary_and_owner_lower_limit(self):
        job = self.jobs.create({**self.body,"to":"2026-10-11T10:10:00Z"})
        self.assertEqual(job["duration_seconds"],600)
        self.jobs.delete(job["id"])
        self.jobs.limits["max_duration_seconds"] = 120
        with self.assertRaises(SessionError): self.jobs.create({**self.body,"to":"2026-10-11T10:02:01Z"})

    def test_full_source_budget_waits_without_native_retry_and_starts_after_release(self):
        self.live.wanted = {"camera-1", "camera-2"}
        first = self.jobs.create(self.body)
        self.wait(lambda:self.jobs.get(first["id"])["waiting_reason"] is not None)
        self.assertEqual(self.capture.calls, []); self.assertEqual(self.live.budget.snapshot().reserved, 0)
        self.live.wanted.clear()
        with self.worker.condition: self.worker.condition.notify_all()
        self.wait(lambda:len(self.capture.calls) == 1)
        self.jobs.delete(first["id"]); self.wait(lambda:self.live.budget.snapshot().reserved == 0)

    def test_queue_bound_fifo_and_cancelled_waiter(self):
        first = self.jobs.create(self.body); self.wait(lambda:self.jobs.active == first["id"])
        queued = [self.jobs.create(self.body) for _ in range(3)]
        with self.assertRaises(SessionError) as error: self.jobs.create(self.body)
        self.assertEqual(error.exception.status, 429)
        self.jobs.delete(queued[1]["id"]); self.capture.gate.set()
        self.wait(lambda:all(job["state"] in ("ready", "cancelled") for job in self.jobs.list()["jobs"]))
        self.assertEqual([job["id"] for job in self.capture.calls], [first["id"], queued[0]["id"], queued[2]["id"]])
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_failed_encoder_removes_partial_and_releases_slot_once(self):
        self.capture.failure = True; self.capture.gate.set(); first = self.jobs.create(self.body)
        self.wait(lambda:self.jobs.get(first["id"])["state"] == "failed" and self.live.budget.snapshot().reserved == 0)
        self.assertFalse((Path(self.temporary.name) / first["id"]).exists())
        self.jobs.remove_entry(first["id"]); self.jobs.remove_entry(first["id"])
        self.assert_removed(first["id"])
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_cancelled_waiter_can_be_removed_without_starting_capture(self):
        self.live.wanted = {"camera-1", "camera-2"}
        job = self.jobs.create(self.body)
        self.jobs.delete(job["id"])
        self.assertEqual(self.jobs.get(job["id"])["state"], "cancelled")
        self.jobs.remove_entry(job["id"])
        self.assert_removed(job["id"])
        self.assertEqual(self.capture.calls, [])
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_removing_cancelled_capture_cannot_be_restored_by_late_worker_completion(self):
        for outcome in (ExportCancelled(), ExportFailure("Late encoder error")):
            with self.subTest(outcome=type(outcome).__name__):
                entered = threading.Event(); finish = threading.Event()
                self.addCleanup(finish.set)
                def delayed_capture(job, directory, cancel, progress):
                    entered.set()
                    if not finish.wait(3): raise ExportFailure("Test capture was not released")
                    raise outcome
                with patch.object(self.capture, "capture", side_effect=delayed_capture):
                    job = self.jobs.create(self.body)
                    self.assertTrue(entered.wait(3))
                    self.jobs.delete(job["id"])
                    self.assertEqual(self.jobs.get(job["id"])["state"], "cancelled")
                    self.jobs.remove_entry(job["id"])
                    self.jobs.remove_entry(job["id"])
                    self.jobs.delete(job["id"])  # An old cancellation retry cannot restore the row.
                    self.assertEqual(self.jobs.list()["jobs"], [])
                    self.assertEqual(self.live.budget.snapshot().reserved, 1)
                    finish.set()
                    self.wait(lambda:job["id"] not in self.jobs.jobs and self.live.budget.snapshot().reserved == 0)
                self.assert_removed(job["id"])

    def test_remove_entry_rejects_waiting_and_ready_exports(self):
        self.live.wanted = {"camera-1", "camera-2"}
        job = self.jobs.create(self.body)
        with self.assertRaises(SessionError) as error: self.jobs.remove_entry(job["id"])
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.jobs.get(job["id"])["state"], "queued")
        self.assertEqual(self.capture.calls, [])
        self.live.wanted.clear(); self.capture.gate.set()
        with self.worker.condition: self.worker.condition.notify_all()
        self.wait(lambda:self.jobs.get(job["id"])["state"] == "ready" and self.live.budget.snapshot().reserved == 0)
        with self.assertRaises(SessionError) as error: self.jobs.remove_entry(job["id"])
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.jobs.get(job["id"])["state"], "ready")
        with self.jobs.download(job["id"]) as (file, _): self.assertEqual(file.read(), b"synthetic-mp4")

    def test_restart_keeps_ready_and_queued_and_fails_interrupted_capture(self):
        identifier = self.ready(); self.jobs.close()
        data = json.loads(self.jobs.manifest.read_text()); ready = data["jobs"][0]
        queued = {**ready,"id":"a"*32,"state":"queued"}; running = {**ready,"id":"b"*32,"state":"running"}
        data["jobs"].extend([queued,running]); self.jobs.manifest.write_text(json.dumps(data))
        recovered = ExportJobs(self.worker, self.live.budget, self.temporary.name, start=False, clock=lambda:self.now)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.get(identifier)["state"], "ready")
        self.assertEqual(recovered.get("a"*32)["state"], "queued")
        self.assertEqual(recovered.get("b"*32)["state"], "failed")
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_expiry_and_delete_defer_unlink_until_download_finishes(self):
        identifier = self.ready()
        with self.jobs.download(identifier) as (file, name):
            self.assertTrue(name.endswith("10s.mp4")); self.jobs.delete(identifier)
            self.assertEqual(file.read(), b"synthetic-mp4")
            self.assertEqual(self.jobs.list()["storage_used_bytes"],13)
            self.assertEqual(self.jobs.list()["jobs"], [])
            self.assertTrue(self.jobs._clip(identifier).is_file())
            with self.assertRaises(SessionError) as error:
                with self.jobs.download(identifier): pass
            self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.jobs.list()["storage_used_bytes"],0)
        self.assert_removed(identifier)
        other = self.ready(); self.now += 24*3600
        self.assertEqual(self.jobs.list()["jobs"], [])
        self.assert_removed(other)

    def test_retention_removes_file_and_manifest_entry_at_exact_expiry(self):
        identifier = self.ready()
        expires_at = self.jobs.jobs[identifier]["expires_at"]
        self.now = expires_at - .001
        self.assertEqual(self.jobs.get(identifier)["state"], "ready")
        self.assertTrue(self.jobs._clip(identifier).is_file())
        self.now = expires_at
        self.assertEqual(self.jobs.list()["jobs"], [])
        self.assert_removed(identifier)
        self.assertEqual(self.jobs.list()["storage_used_bytes"], 0)

    def test_expiry_defers_cleanup_until_last_download_finishes(self):
        identifier = self.ready()
        with self.jobs.download(identifier) as (first, _):
            with self.jobs.download(identifier) as (second, _):
                self.now = self.jobs.jobs[identifier]["expires_at"]
                self.assertEqual(self.jobs.list()["jobs"], [])
                self.assertEqual(first.read(), b"synthetic-mp4")
                self.assertEqual(second.read(), b"synthetic-mp4")
                with self.assertRaises(SessionError) as error:
                    with self.jobs.download(identifier): pass
                self.assertEqual(error.exception.status, 410)
            self.assertTrue(self.jobs._clip(identifier).is_file())
            self.assertIn(identifier, self.jobs.jobs)
            self.assertEqual(self.jobs.list()["storage_used_bytes"], 13)
        self.assert_removed(identifier)

    def test_restart_removes_old_expired_missing_and_overdue_entries(self):
        identifier = self.ready(); self.jobs.close()
        data = json.loads(self.jobs.manifest.read_text()); ready = data["jobs"][0]
        legacy, missing, overdue = "a"*32, "b"*32, "c"*32
        data["jobs"].extend([{**ready, "id":legacy, "state":"expired"},
                             {**ready, "id":missing},
                             {**ready, "id":overdue, "expires_at":self.now}])
        for value in (legacy, overdue):
            path = self.jobs.directory / value; path.mkdir()
            (path / "clip.mp4").write_bytes(b"old-clip")
        self.jobs.manifest.write_text(json.dumps(data))
        recovered = ExportJobs(self.worker, self.live.budget, self.temporary.name,
                               start=False, clock=lambda:self.now)
        self.addCleanup(recovered.close)
        self.assertEqual([job["id"] for job in recovered.list()["jobs"]], [identifier])
        self.assertEqual([job["id"] for job in json.loads(recovered.manifest.read_text())["jobs"]], [identifier])
        for value in (legacy, missing, overdue):
            self.assertNotIn(value, recovered.jobs)
            self.assertFalse((recovered.directory / value).exists())

    def test_failed_file_cleanup_keeps_entry_until_cleanup_can_complete(self):
        identifier = self.ready(); self.jobs.close()
        with patch("export_jobs.shutil.rmtree", side_effect=PermissionError("Cannot remove clip")):
            with self.assertRaises(PermissionError): self.jobs.delete(identifier)
        self.assertIn(identifier, self.jobs.jobs)
        self.assertTrue(self.jobs._clip(identifier).is_file())
        self.jobs.list()
        self.assert_removed(identifier)

    def test_storage_limit_keeps_completed_clip_and_rejects_admission(self):
        identifier = self.ready(); self.jobs.limits["storage_bytes"] = 2*self.jobs.limits["max_file_bytes"]
        with self.assertRaises(SessionError): self.jobs.create(self.body)
        self.assertEqual(self.jobs.get(identifier)["state"], "ready")

    def test_missing_file_and_pruned_download_are_gone(self):
        identifier = self.ready(); self.jobs._clip(identifier).unlink()
        self.assertEqual(self.jobs.list()["jobs"], [])
        self.assert_removed(identifier)
        for value in (identifier,"f"*32):
            with self.assertRaises(SessionError) as error:
                with self.jobs.download(value): pass
            self.assertEqual(error.exception.status,410)

    def test_deleting_at_history_bound_allows_new_jobs(self):
        identifier = self.ready()
        with self.worker.condition:
            original = dict(self.jobs.jobs[identifier])
            for index in range(1,100):
                other=f"{index:032x}"; self.jobs.jobs[other]={**original,"id":other}
                directory=self.jobs.directory/other; directory.mkdir()
                (directory/"clip.mp4").write_bytes(b"synthetic-mp4")
        with self.assertRaises(SessionError): self.jobs.create(self.body)
        self.jobs.delete(identifier)
        result=self.jobs.create(self.body)
        self.assertIn(result["state"],("queued","running")); self.assertLessEqual(len(self.jobs.jobs),100)

    def test_http_attachment_ranges_idempotency_and_expired_download(self):
        server = create_server(self.worker,self.live,address=("127.0.0.1",0),web=ROOT/"web",
                               recording=Path(self.temporary.name)/"unused.mp4",exports=self.jobs)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base=f"http://127.0.0.1:{server.server_port}"
        self.capture.gate.set()
        request=Request(base+"/api/exports",data=json.dumps(self.body).encode(),method="POST",
                        headers={"Content-Type":"application/json","Idempotency-Key":"http-job"})
        with urlopen(request,timeout=3) as response:
            self.assertEqual(response.status,202); identifier=json.load(response)["id"]
        with urlopen(request,timeout=3) as response: self.assertEqual(json.load(response)["id"],identifier)
        self.wait(lambda:self.jobs.get(identifier)["state"]=="ready")
        url=base+f"/media/exports/{identifier}.mp4"
        with urlopen(Request(url,headers={"Range":"bytes=2-5"}),timeout=3) as response:
            self.assertEqual(response.status,206); self.assertEqual(response.read(),b"nthe")
            self.assertEqual(response.headers["Content-Range"],"bytes 2-5/13")
            self.assertIn('attachment; filename="oogies-camera-1_',response.headers["Content-Disposition"])
        with urlopen(Request(url,headers={"Range":"bytes=-3"}),timeout=3) as response: self.assertEqual(response.read(),b"mp4")
        with self.assertRaises(HTTPError) as error: urlopen(Request(url,headers={"Range":"bytes=100-"}),timeout=3)
        self.assertEqual(error.exception.code,416)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(base+f"/api/exports/{identifier}",method="DELETE",headers={"Origin":"https://example.com"}),timeout=3)
        self.assertEqual(error.exception.code,403)
        with urlopen(Request(base+f"/api/exports/{identifier}",method="DELETE"),timeout=3) as response: self.assertEqual(response.status,204)
        with urlopen(base+"/api/exports",timeout=3) as response: self.assertEqual(json.load(response)["jobs"], [])
        with self.assertRaises(HTTPError) as error: urlopen(base+f"/api/exports/{identifier}",timeout=3)
        self.assertEqual(error.exception.code,404)
        with urlopen(Request(base+f"/api/exports/{identifier}",method="DELETE"),timeout=3) as response: self.assertEqual(response.status,204)
        self.assert_removed(identifier)
        with self.assertRaises(HTTPError) as error: urlopen(url,timeout=3)
        self.assertEqual(error.exception.code,410)

    def test_shutdown_releases_capture_slot_and_leaves_queue_durable(self):
        first = self.jobs.create(self.body); self.wait(lambda:self.jobs.active == first["id"])
        second = self.jobs.create(self.body); self.jobs.close()
        self.assertEqual(self.live.budget.snapshot().reserved, 0)
        self.assertEqual(self.jobs.get(first["id"])["state"], "failed")
        self.assertEqual(self.jobs.get(second["id"])["state"], "queued")

    def test_export_failure_after_acquire_releases_once(self):
        for stage in ("persistence","startup","encoding","cleanup"):
            with self.subTest(stage=stage):
                capture = Capture(); capture.gate.set()
                jobs = ExportJobs(self.worker,self.live.budget,Path(self.temporary.name)/stage,
                                  encoder=capture,clock=lambda:self.now,start=False)
                independent = None
                try:
                    job = jobs.create(self.body)
                    independent = self.live.budget.try_reserve("playback","independent")
                    self.assertIsNotNone(independent)
                    fired = threading.Event(); original_save = jobs._save; original_expire = jobs._expire
                    original_release = jobs.budget.release
                    def release(token):
                        try: return original_release(token)
                        finally: jobs.closed = True
                    def save():
                        if stage == "persistence" and jobs.active and not fired.is_set():
                            fired.set(); raise OSError("Manifest write failed")
                        return original_save()
                    def expire():
                        if stage == "cleanup" and jobs.active is None and jobs.jobs[job["id"]]["state"] == "ready":
                            fired.set(); raise OSError("Cleanup failed")
                        return original_expire()
                    def fail_start(): fired.set(); raise ValueError("Capture startup failed")
                    def fail_encode(*args): fired.set(); raise ExportFailure("Encoding failed")
                    with ExitStack() as patches:
                        patches.enter_context(patch.object(jobs,"_save",side_effect=save))
                        patches.enter_context(patch.object(jobs,"_expire",side_effect=expire))
                        released = patches.enter_context(patch.object(jobs.budget,"release",side_effect=release))
                        if stage == "startup": patches.enter_context(patch.object(self.worker,"ensure_ready",side_effect=fail_start))
                        if stage == "encoding": patches.enter_context(patch.object(capture,"capture",side_effect=fail_encode))
                        if stage == "cleanup":
                            with self.assertRaisesRegex(OSError,"Cleanup failed"): jobs._run()
                        else:
                            jobs._run()
                            self.assertEqual(jobs.get(job["id"])["state"],"failed")
                        self.assertTrue(fired.is_set())
                        self.assertEqual(released.call_count,1)
                        self.assertEqual(released.call_args.args[0].owner_id,job["id"])
                    self.assertEqual(jobs.budget.snapshot().exports,0)
                    self.assertEqual(jobs.budget.snapshot().playback,1)
                    self.assertIs(jobs.budget.try_reserve("playback","independent"),independent)
                    self.assertIsNone(jobs.active)
                finally:
                    jobs.close()
                    self.live.budget.release(independent)

    def test_storage_waiting_export_holds_no_slot_then_starts_after_space_is_freed(self):
        budget = self.live.budget
        first = budget.try_reserve("playback","one"); second = budget.try_reserve("playback","two")
        try:
            self.jobs.limits["storage_bytes"] = 2 * self.jobs.limits["max_file_bytes"]
            job = self.jobs.create(self.body)
            directory = Path(self.temporary.name)/("a"*32); directory.mkdir()
            clip = directory/"clip.mp4"; clip.write_bytes(b"occupied storage")
            budget.release(first)
            self.wait(lambda:"storage" in (self.jobs.get(job["id"])["waiting_reason"] or "").lower())
            self.assertEqual(budget.snapshot().exports,0)
            self.assertEqual(self.capture.calls,[])
            clip.unlink(); self.capture.gate.set()
            with self.worker.condition: self.worker.condition.notify_all()
            self.wait(lambda:self.jobs.get(job["id"])["state"] == "ready" and budget.snapshot().exports == 0)
            self.assertEqual([item["id"] for item in self.capture.calls],[job["id"]])
        finally:
            budget.release(first); budget.release(second)


class ExportAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.worker = Worker(); self.live = LiveSessions(self.worker, limit=2)
        self.capture = Capture()
        self.now = datetime(2026,10,11,20,tzinfo=timezone.utc).timestamp()
        self.jobs = ExportJobs(self.worker, self.live.budget, self.temporary.name,
                               encoder=self.capture, clock=lambda:self.now, start=False)
        self.addCleanup(self.jobs.close)
        self.body = dict(camera_id="camera-1", aspect_ratio="16:9",
                         **{"from":"2026-10-11T10:00:00Z", "to":"2026-10-11T10:00:10Z"})

    def clip(self, identifier, name, content):
        directory = self.jobs.directory / identifier
        directory.mkdir(exist_ok=True)
        path = directory / name; path.write_bytes(content)
        return path

    @contextmanager
    def during_metadata(self, target, change, *, after=True, thread=None):
        """Change a real path at a precise observation, without replacing accounting."""
        original = Path.stat; fired = threading.Event()
        def observe(path, *args, **kwargs):
            if path != target or fired.is_set() or (thread is not None and threading.current_thread() is not thread):
                return original(path, *args, **kwargs)
            result = original(path, *args, **kwargs) if after else None
            fired.set(); change()
            return result if after else original(path, *args, **kwargs)
        with patch.object(Path, "stat", observe):
            yield fired

    def runner(self):
        failures = []
        def run():
            try: self.jobs._run()
            except Exception as error:
                failures.append(error)
                with self.worker.condition: self.worker.condition.notify_all()
        self.jobs.thread = threading.Thread(target=run, daemon=True)
        return self.jobs.thread, failures

    def test_accounting_survives_partial_rename_after_metadata_read(self):
        partial = self.clip("a"*32, "clip.partial.mp4", b"partial")
        self.clip("b"*32, "clip.mp4", b"survivor")
        final = partial.with_name("clip.mp4")
        with self.during_metadata(partial, lambda:partial.replace(final)) as fired:
            self.assertGreaterEqual(self.jobs._used_bytes(), 8)
        self.assertTrue(fired.is_set(), "The rename must occur during accounting")
        self.assertFalse(partial.exists()); self.assertTrue(final.is_file())
        self.assertEqual(self.jobs._used_bytes(), 15)

    def test_accounting_skips_disappearing_candidates_and_keeps_survivors(self):
        self.clip("b"*32, "clip.mp4", b"survivor")
        for remove_directory in (False, True):
            with self.subTest(remove_directory=remove_directory):
                partial = self.clip("a"*32, "clip.partial.mp4", b"partial")
                def remove():
                    partial.unlink()
                    if remove_directory: partial.parent.rmdir()
                with self.during_metadata(partial, remove, after=False) as fired:
                    self.assertEqual(self.jobs._used_bytes(), 8)
                self.assertTrue(fired.is_set())
                self.assertEqual(self.jobs._used_bytes(), 8)

    def test_accounting_counts_matching_regular_files(self):
        self.assertEqual(self.jobs._used_bytes(), 0)
        self.clip("a"*32, "clip.mp4", b"final")
        self.clip("b"*32, "clip.partial.mp4", b"partial")
        self.clip("b"*32, "clip.additional.mp4", b"more")
        self.clip("b"*32, "unrelated.mp4", b"ignore me")
        self.clip("b"*32, "clip.txt", b"ignore me too")
        (self.jobs.directory / ("a"*32) / "clip.directory.mp4").mkdir()
        self.assertEqual(self.jobs._used_bytes(), 16)

    def test_accounting_preserves_unexpected_io_errors(self):
        partial = self.clip("a"*32, "clip.partial.mp4", b"partial")
        for error in (PermissionError(errno.EACCES, "Denied"), OSError(errno.EIO, "I/O failure")):
            with self.subTest(error=type(error).__name__):
                def fail(): raise error
                with self.during_metadata(partial, fail, after=False) as fired:
                    with self.assertRaises(type(error)) as caught: self.jobs._used_bytes()
                self.assertTrue(fired.is_set())
                self.assertEqual(caught.exception.errno, error.errno)

    def test_http_export_list_succeeds_during_finalization(self):
        prepared, finalize, published = (threading.Event() for _ in range(3))
        class AtomicCapture:
            def capture(_, job, directory, cancel, progress):
                partial = directory / "clip.partial.mp4"; partial.write_bytes(b"synthetic-mp4")
                prepared.set()
                if not finalize.wait(5): raise ExportFailure("Test finalization gate timed out")
                if cancel.is_set(): raise ExportCancelled()
                partial.replace(directory / "clip.mp4"); published.set()
                return dict(bytes=13, actual_duration_seconds=job["duration_seconds"], frames=10)
        self.jobs.encoder = AtomicCapture()
        job = self.jobs.create(self.body)
        server = create_server(self.worker, self.live, address=("127.0.0.1",0), web=ROOT/"web",
                               recording=Path(self.temporary.name)/"unused.mp4", exports=self.jobs)
        self.addCleanup(server.server_close)
        http = threading.Thread(target=server.serve_forever, daemon=True); http.start()
        self.addCleanup(http.join, 3); self.addCleanup(server.shutdown)
        self.addCleanup(finalize.set)
        runner, failures = self.runner(); runner.start()
        self.assertTrue(prepared.wait(3))
        def publish():
            finalize.set()
            self.assertTrue(published.wait(3), "Capture must rename outside the shared lock")
        partial = self.jobs.directory / job["id"] / "clip.partial.mp4"
        url = f"http://127.0.0.1:{server.server_port}/api/exports"
        with self.during_metadata(partial, publish) as fired:
            with urlopen(url, timeout=5) as response:
                self.assertEqual(response.status, 200); data = json.load(response)
        self.assertTrue(fired.is_set())
        self.assertIsInstance(data["storage_used_bytes"], int)
        with self.worker.condition:
            self.assertTrue(self.worker.condition.wait_for(
                lambda:self.jobs.jobs[job["id"]]["state"] == "ready" or failures, timeout=3))
        self.assertEqual(failures, [])
        with urlopen(url, timeout=3) as response:
            self.assertEqual(json.load(response)["storage_used_bytes"], 13)
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_create_preserves_storage_limit_when_candidate_disappears(self):
        partial = self.clip("a"*32, "clip.partial.mp4", b"partial")
        self.clip("b"*32, "clip.mp4", b"survivor")
        self.jobs.limits["storage_bytes"] = 2 * self.jobs.limits["max_file_bytes"]
        with self.during_metadata(partial, partial.unlink, after=False) as fired:
            with self.assertRaises(SessionError) as caught: self.jobs.create(self.body)
        self.assertTrue(fired.is_set()); self.assertEqual(caught.exception.status, 409)
        self.assertIn("storage", str(caught.exception).lower())
        self.assertEqual(self.worker.ensure_calls, 0)
        self.assertEqual(self.jobs.jobs, {}); self.assertEqual(self.capture.calls, [])
        self.assertEqual(self.live.budget.snapshot().reserved, 0)

    def test_queue_continues_after_accounting_candidate_disappears(self):
        first = self.jobs.create(self.body); second = self.jobs.create(self.body)
        partial = self.clip("a"*32, "clip.partial.mp4", b"partial")
        runner, failures = self.runner()
        self.capture.gate.set()
        with patch.object(self.jobs.budget, "try_reserve", wraps=self.jobs.budget.try_reserve) as acquire, \
             patch.object(self.jobs.budget, "release", wraps=self.jobs.budget.release) as release, \
             self.during_metadata(partial, partial.unlink, thread=runner) as fired:
            runner.start()
            self.assertTrue(fired.wait(3), "Fault must occur in the runner's storage check")
            with self.worker.condition:
                self.assertTrue(self.worker.condition.wait_for(lambda:failures or
                    all(job["state"] == "ready" for job in self.jobs.jobs.values()), timeout=3))
        self.assertEqual(failures, [])
        self.assertTrue(runner.is_alive())
        self.assertEqual([job["id"] for job in self.capture.calls], [first["id"], second["id"]])
        self.assertEqual([call.args for call in acquire.call_args_list],
                         [("export",first["id"]),("export",second["id"])])
        self.assertEqual([call.args[0].owner_id for call in release.call_args_list], [first["id"],second["id"]])
        self.assertEqual(self.live.budget.snapshot().reserved, 0)
        self.assertEqual(self.jobs.list()["storage_used_bytes"], 26)


class ExportClockTests(unittest.TestCase):
    def test_encoded_duration_matches_second_precision_and_frame_count(self):
        metadata=dict(streams=[dict(codec_type="video",codec_name="h264",width=960,height=1088,nb_frames="8992")],format={"duration":"599.467"})
        video,duration=validate_video(metadata,(960,1088,15),600,8992)
        self.assertEqual(duration,599.467)
        self.assertEqual(video["codec_name"],"h264")
        with self.assertRaises(ExportFailure): validate_video(metadata,(960,1088,15),600,8993)

    def test_truncated_and_wrong_format_clips_still_fail(self):
        metadata=dict(streams=[dict(codec_type="video",codec_name="h264",width=960,height=1088,nb_frames="8980")],format={"duration":"598.667"})
        with self.assertRaises(ExportFailure): validate_video(metadata,(960,1088,15),600,8980)
        metadata["format"]["duration"]="600"; metadata["streams"][0]["codec_name"]="mpeg4"
        with self.assertRaises(ExportFailure): validate_video(metadata,(960,1088,15),600,8980)
    def test_decoder_stamp_wrap_and_clock_mapping(self):
        clock = FrameClock(ZoneInfo("Africa/Johannesburg"))
        first = dict(position="2026-10-11T12:00:00", ms=0, stamp=0xfffffff0, fps=15)
        a = clock.position(first); b = clock.position({**first,"stamp":64,"ms":80})
        self.assertEqual((b-a).total_seconds(), .08)
        self.assertEqual(a.hour,10)

    def test_missing_clock_gaps_and_reverse_frames_fail(self):
        base = dict(position="2026-10-11T12:00:00", ms=0, stamp=0, fps=15)
        for update in ({"position":None},{"stamp":1000},{"stamp":0},{"stamp":-1},{"position":"2026-10-11T12:00:10","stamp":80}):
            clock = FrameClock(ZoneInfo("UTC")); clock.position(base)
            with self.assertRaises(ExportFailure): clock.position({**base,**update})

    def test_export_config_validation_and_defaults(self):
        self.assertEqual(export_limits()["max_duration_seconds"],600)
        for value in ({"max_duration_seconds":601},{"max_waiting_jobs":True},{"unknown":1},{"storage_bytes":1024**2}):
            with self.assertRaises(ValueError): export_limits(value)
