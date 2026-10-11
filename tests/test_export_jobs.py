from datetime import datetime, timedelta, timezone
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from export_jobs import ExportJobs
from export_encoder import FrameClock, ExportFailure, ExportCancelled, validate_video
from grid_worker import GridWorker
from live_sessions import LiveSessions, SessionError
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
        self.jobs = ExportJobs(self.worker, self.live, self.temporary.name, encoder=self.capture, clock=lambda:self.now)
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
        self.wait(lambda:self.live.reserved_sources == 0)
        return job["id"]

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
        self.assertEqual(self.live.reserved_sources, 1)
        self.jobs.delete(first["id"]); self.jobs.delete(first["id"])
        self.wait(lambda:self.live.reserved_sources == 0)
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
        self.assertEqual(self.capture.calls, []); self.assertEqual(self.live.reserved_sources, 0)
        self.live.wanted.clear()
        with self.worker.condition: self.worker.condition.notify_all()
        self.wait(lambda:len(self.capture.calls) == 1)
        self.jobs.delete(first["id"]); self.wait(lambda:self.live.reserved_sources == 0)

    def test_queue_bound_fifo_and_cancelled_waiter(self):
        first = self.jobs.create(self.body); self.wait(lambda:self.jobs.active == first["id"])
        queued = [self.jobs.create(self.body) for _ in range(3)]
        with self.assertRaises(SessionError) as error: self.jobs.create(self.body)
        self.assertEqual(error.exception.status, 429)
        self.jobs.delete(queued[1]["id"]); self.capture.gate.set()
        self.wait(lambda:all(job["state"] in ("ready", "cancelled") for job in self.jobs.list()["jobs"]))
        self.assertEqual([job["id"] for job in self.capture.calls], [first["id"], queued[0]["id"], queued[2]["id"]])
        self.assertEqual(self.live.reserved_sources, 0)

    def test_failed_encoder_removes_partial_and_releases_slot_once(self):
        self.capture.failure = True; self.capture.gate.set(); first = self.jobs.create(self.body)
        self.wait(lambda:self.jobs.get(first["id"])["state"] == "failed" and self.live.reserved_sources == 0)
        self.assertFalse((Path(self.temporary.name) / first["id"]).exists())
        self.jobs.delete(first["id"]); self.assertEqual(self.live.reserved_sources, 0)

    def test_restart_keeps_ready_and_queued_and_fails_interrupted_capture(self):
        identifier = self.ready(); self.jobs.close()
        data = json.loads(self.jobs.manifest.read_text()); ready = data["jobs"][0]
        queued = {**ready,"id":"a"*32,"state":"queued"}; running = {**ready,"id":"b"*32,"state":"running"}
        data["jobs"].extend([queued,running]); self.jobs.manifest.write_text(json.dumps(data))
        recovered = ExportJobs(self.worker, self.live, self.temporary.name, start=False, clock=lambda:self.now)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.get(identifier)["state"], "ready")
        self.assertEqual(recovered.get("a"*32)["state"], "queued")
        self.assertEqual(recovered.get("b"*32)["state"], "failed")
        self.assertEqual(self.live.reserved_sources, 0)

    def test_expiry_and_delete_defer_unlink_until_download_finishes(self):
        identifier = self.ready()
        with self.jobs.download(identifier) as (file, name):
            self.assertTrue(name.endswith("10s.mp4")); self.jobs.delete(identifier)
            self.assertEqual(file.read(), b"synthetic-mp4")
            self.assertEqual(self.jobs.list()["storage_used_bytes"],13)
            with self.assertRaises(SessionError) as error:
                with self.jobs.download(identifier): pass
            self.assertEqual(error.exception.status, 410)
        self.assertEqual(self.jobs.list()["storage_used_bytes"],0)
        other = self.ready(); self.now += 24*3600
        self.assertEqual(self.jobs.get(other)["state"], "expired")

    def test_storage_limit_keeps_completed_clip_and_rejects_admission(self):
        identifier = self.ready(); self.jobs.limits["storage_bytes"] = 2*self.jobs.limits["max_file_bytes"]
        with self.assertRaises(SessionError): self.jobs.create(self.body)
        self.assertEqual(self.jobs.get(identifier)["state"], "ready")

    def test_missing_file_and_pruned_download_are_gone(self):
        identifier = self.ready(); self.jobs._clip(identifier).unlink()
        self.assertEqual(self.jobs.get(identifier)["state"],"expired")
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
        with self.assertRaises(HTTPError) as error: urlopen(url,timeout=3)
        self.assertEqual(error.exception.code,410)

    def test_shutdown_releases_capture_slot_and_leaves_queue_durable(self):
        first = self.jobs.create(self.body); self.wait(lambda:self.jobs.active == first["id"])
        second = self.jobs.create(self.body); self.jobs.close()
        self.assertEqual(self.live.reserved_sources, 0)
        self.assertEqual(self.jobs.get(first["id"])["state"], "failed")
        self.assertEqual(self.jobs.get(second["id"])["state"], "queued")


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
