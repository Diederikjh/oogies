"""Quality admission and frame routing through real worker/session boundaries."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from grid_worker import GridWorker
from grid_server import create_server
from live_sessions import LiveSessions, SessionError
from live_sources import source_key
from playback_sessions import PlaybackSessions
from nvr_config import load_config
from export_jobs import ExportJobs
from export_encoder import ExportCancelled


def selection(*cameras):
    return {"cameras":[{"id":camera, "quality":quality} for camera, quality in cameras]}


class Recorder(GridWorker):
    """Real GridWorker control logic; substitute the native command transport."""
    def __init__(self):
        super().__init__(None, SimpleNamespace(sdk_id="test"), {"camera_overrides":{}}, "/tmp")
        self.commands = []
        self.ack_stops = True
        self._event(dict(type="ready", protocol=2, login_calls=1,
            cameras=[dict(channel=n, name=f"Camera {n}", online=n != 4) for n in range(1,5)]))

    def _command(self, command):
        self.commands.append(command)
        parts = command.split()
        if parts[0] in ("start", "stop"):
            operation, channel, quality, generation = parts
            if operation == "start" or self.ack_stops:
                self._event(dict(type="started" if operation == "start" else "stopped",
                    channel=int(channel), quality=quality, generation=int(generation), error=0))

    def frame(self, camera="camera-1", quality="overview", sequence=1):
        source = self.sources[source_key(camera, quality)]
        source.update(state="live", frame=b"\xff\xd8"+quality.encode()+b"\xff\xd9", width=1920 if quality == "high" else 352,
            height=1080 if quality == "high" else 288, sequence=sequence, received=sequence,
            last_frame=time.monotonic())


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.worker = Recorder()
        self.now = 0
        self.live = LiveSessions(self.worker, limit=6, lease_seconds=10, clock=lambda:self.now)

    def create(self, camera="camera-1", quality="high", key=None):
        return self.live.create(selection((camera,quality)), key)

    def camera(self, view): return self.live.get(view["id"])["cameras"][0]

    def test_shared_high_source_and_independent_downgrade_cleanup(self):
        first, second = self.create(), self.create()
        self.assertEqual(len(self.worker.commands), 2)
        self.assertEqual(self.camera(first)["quality"], "overview")
        self.assertEqual(self.camera(first)["upgrade_state"], "pending")
        self.worker.frame(quality="high")
        self.assertEqual(self.camera(first)["quality"], "high")
        self.assertEqual(self.camera(second)["quality"], "high")
        self.live.patch(first["id"], selection(("camera-1","overview")))
        self.assertEqual(self.camera(first)["quality"], "overview")
        self.assertEqual(self.camera(second)["quality"], "high")
        self.assertEqual(len(self.worker.commands), 2)
        self.live.delete(second["id"])
        self.assertEqual(self.live.wanted, {"camera-1"})
        self.assertIn("stop 1 high 1", self.worker.commands)
        self.live.delete(first["id"]); self.live.delete(first["id"])
        self.assertEqual(self.live.used_sources(), 0)
        self.assertEqual(self.worker.login_calls, 1)

    def test_feed_switches_after_first_frame_and_equal_sequence_is_not_suppressed(self):
        view = self.create(); other = self.create(quality="overview")
        self.worker.frame(); seen = {}
        def packet(session, cache):
            packet = self.live.next_frames(session["id"], cache)[0]
            length = int.from_bytes(packet[4:6], "big")
            return json.loads(packet[6:6+length]), packet[6+length:]
        before, overview = packet(view, seen)
        self.assertEqual(before["quality"], "overview")
        self.worker.frame(quality="high")
        after, high = packet(view, seen)
        self.assertEqual(before["sequence"], after["sequence"])
        self.assertEqual(after["quality"], "high"); self.assertNotEqual(overview,high)
        self.assertEqual(packet(other,{})[0]["quality"], "overview")
        old_revision = after["selection_revision"]
        self.live.patch(view["id"], selection(("camera-1","overview")))
        collapsed, _ = packet(view,seen)
        self.assertGreater(collapsed["selection_revision"],old_revision)
        self.assertEqual(collapsed["quality"],"overview")

    def test_high_limit_refusal_does_not_queue_or_interrupt_overview(self):
        first = self.create(); refused = self.create("camera-2")
        self.worker.frame("camera-2")
        self.assertEqual(self.camera(refused)["state"], "live")
        self.assertEqual(self.camera(refused)["upgrade_state"], "capacity_limited")
        self.assertEqual(self.camera(refused)["quality_reason"]["code"],"high_quality_limit")
        self.live.delete(first["id"])
        self.live.maintain(); self.live.patch(refused["id"], {})
        self.assertNotIn("camera-2-high",self.live.wanted)
        updated = self.live.patch(refused["id"], selection(("camera-2","high")))
        self.assertEqual(updated["cameras"][0]["upgrade_state"],"pending")
        self.assertIn("camera-2-high",self.live.wanted)

    def test_atomic_admission_for_simultaneous_cameras(self):
        barrier = threading.Barrier(3); views = []
        def request(camera):
            barrier.wait(); views.append(self.create(camera))
        threads = [threading.Thread(target=request,args=(f"camera-{n}",)) for n in (1,2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(timeout=2); self.assertFalse(thread.is_alive())
        self.assertEqual(len(views),2)
        self.assertEqual(sum(key.endswith("-high") for key in self.live.wanted),1)
        self.assertEqual(sorted(self.camera(view)["upgrade_state"] for view in views),["capacity_limited","pending"])

    def test_total_budget_and_existing_playback_reservation_win_over_upgrade(self):
        self.live.limit = 2
        playback = PlaybackSessions(self.worker,self.live)
        session = playback.create(dict(camera_id="camera-1", **{"from":"2024-01-01T10:00:00Z","to":"2024-01-01T11:00:00Z"}))
        view = self.create()
        self.assertEqual(self.camera(view)["quality_reason"]["code"], "source_limit")
        self.assertEqual(self.live.used_sources(),2)
        self.assertEqual(self.live.reserved_sources,1)
        playback.delete(session["id"])
        self.assertEqual(self.camera(view)["upgrade_state"],"capacity_limited")
        self.live.patch(view["id"],selection(("camera-1","high")))
        self.assertEqual(self.live.used_sources(),2)
        with self.assertRaises(SessionError):
            playback.create(dict(camera_id="camera-1", **{"from":"2024-01-01T10:00:00Z","to":"2024-01-01T11:00:00Z"}))

    def test_disabled_unsupported_and_offline_requests_have_fallback_reasons(self):
        self.live.high_limit = 0
        disabled = self.create()
        self.assertEqual(self.camera(disabled)["upgrade_state"], "capacity_limited")
        self.live.high_limit = 1
        self.worker.cameras["camera-2"]["live_qualities"] = ["overview"]
        unsupported = self.create("camera-2"); offline = self.create("camera-4")
        self.assertEqual(self.camera(unsupported)["upgrade_state"],"unsupported")
        self.assertEqual(self.camera(offline)["upgrade_state"],"offline")
        self.assertEqual(self.camera(offline)["state"],"offline")
        self.assertFalse(any(" high " in command for command in self.worker.commands))

    def test_scoped_retry_does_not_restart_an_unobserved_failure(self):
        view = self.create(); self.worker.frame(quality="high")
        self.worker.sources["camera-1-high"].update(state="error",error="Decoder failed between polls")
        update = selection(("camera-1","high"),("camera-2","high"))
        self.live.patch(view["id"],{**update,"retry_high":["camera-2"]})
        self.assertEqual(self.camera(view)["upgrade_state"],"error")
        self.assertEqual(self.worker.commands.count("start 1 high 1"),1)
        self.assertNotIn("start 1 high 2",self.worker.commands)
        self.assertIn("camera-2-high",self.live.wanted)
        self.live.patch(view["id"],{**selection(("camera-1","high")),"retry_high":["camera-1"]})
        self.assertIn("start 1 high 2",self.worker.commands)

    def test_invalid_scoped_retry_does_not_mutate_selection(self):
        view = self.create(quality="overview")
        bodies = [{"retry_high":[]}]+[{**selection(("camera-1","high")),"retry_high":value}
                  for value in (None,"camera-1",["camera-2"],["camera-1","camera-1"],[{}])]
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(SessionError): self.live.patch(view["id"],body)
                self.assertEqual(self.live.get(view["id"])["selection_revision"],view["selection_revision"])
                self.assertEqual(self.live.wanted,{"camera-1"})

    def test_export_and_high_quality_share_budget_in_both_directions(self):
        class Capture:
            entered = threading.Event()
            def capture(self, job, directory, cancel, progress):
                self.entered.set()
                cancel.wait(5)
                raise ExportCancelled()
        self.live.limit = 2; capture = Capture()
        with tempfile.TemporaryDirectory() as directory:
            jobs = ExportJobs(self.worker,self.live,directory,encoder=capture)
            try:
                view = self.create()
                job = jobs.create(dict(camera_id="camera-1",aspect_ratio="16:9",
                    **{"from":"2024-01-01T10:00:00Z","to":"2024-01-01T10:00:05Z"}))
                with self.worker.condition:
                    self.assertTrue(self.worker.condition.wait_for(lambda:jobs.get(job["id"])["waiting_reason"] is not None,timeout=2))
                self.assertFalse(capture.entered.is_set())
                self.worker.ack_stops = False
                self.live.patch(view["id"],selection(("camera-1","overview")))
                self.assertEqual(self.live.used_sources(),2)
                self.assertFalse(capture.entered.is_set())
                self.worker._event(dict(type="stopped",channel=1,quality="high",generation=1))
                self.assertTrue(capture.entered.wait(2))
                self.assertEqual(self.live.reserved_sources,1)
                self.live.patch(view["id"],selection(("camera-1","high")))
                self.assertEqual(self.camera(view)["quality_reason"]["code"],"source_limit")
                self.assertEqual(self.live.used_sources(),2)
                jobs.delete(job["id"])
                with self.worker.condition:
                    self.assertTrue(self.worker.condition.wait_for(lambda:self.live.reserved_sources==0,timeout=2))
                self.assertNotIn("camera-1-high",self.live.wanted)
            finally:
                jobs.close()

    def test_stop_acknowledgement_keeps_both_budgets_reserved(self):
        self.live.limit = 3
        view = self.create(); self.worker.ack_stops = False
        self.live.patch(view["id"],selection(("camera-1","overview")))
        self.assertEqual(self.live.used_sources(),2)
        another = self.create("camera-2")
        self.assertEqual(self.camera(another)["upgrade_state"],"capacity_limited")
        self.worker._event(dict(type="stopped", channel=1, quality="high", generation=1))
        self.assertEqual(self.live.used_sources(),2)
        self.assertEqual(self.camera(another)["upgrade_state"],"capacity_limited")
        self.live.patch(another["id"],selection(("camera-2","high")))
        self.assertEqual(self.live.used_sources(),3)

    def test_timeout_and_stall_fall_back_release_and_do_not_retry(self):
        for failure in ("timeout", "stale", "decoder"):
            with self.subTest(failure=failure):
                view = self.create(); self.worker.frame()
                source = self.worker.sources["camera-1-high"]
                if failure == "timeout":
                    source["requested_at"] = time.monotonic()-16
                    self.worker._check_live_sources()
                elif failure == "stale":
                    self.worker.frame(quality="high"); source["last_frame"] -= 6
                else:
                    self.worker._event(dict(type="source_error", channel=1, quality="high", generation=source["generation"], error=43))
                self.assertEqual(self.camera(view)["quality"],"overview")
                self.assertEqual(self.camera(view)["upgrade_state"],"error")
                self.assertEqual(self.camera(view)["state"],"live")
                self.assertNotIn("camera-1-high",self.live.wanted)
                count = len(self.worker.commands)
                self.live.maintain(); self.live.patch(view["id"],{})
                self.assertEqual(len(self.worker.commands),count)
                self.live.delete(view["id"])

    def test_overview_restart_waits_for_its_previous_native_stop(self):
        view = self.create(quality="overview"); self.worker.ack_stops = False
        self.live.delete(view["id"])
        self.create(quality="overview")
        self.assertEqual(self.worker.commands,["start 1 overview 1","stop 1 overview 1"])
        self.assertEqual(self.live.used_sources(),1)
        self.worker._event(dict(type="stopped",channel=1,quality="overview",generation=1))
        self.live.maintain()
        self.assertEqual(self.worker.commands[-1],"start 1 overview 2")

    def test_unchanged_status_reads_do_not_wake_other_media_waiters(self):
        view = self.create()
        with patch.object(self.worker.condition,"notify_all") as notify:
            self.live.get(view["id"]); self.live.quality_status()
        notify.assert_not_called()

    def test_stale_frames_are_not_reported_as_new_media(self):
        view = self.create(quality="overview"); self.worker.frame()
        self.worker.sources["camera-1"]["state"] = "stale"
        self.assertEqual(list(self.live._new_frames(self.live.get(view["id"]),{})),[])

    def test_generation_checks_ignore_late_events_and_cached_files(self):
        with tempfile.TemporaryDirectory() as directory:
            self.worker.directory = Path(directory)
            view = self.create(); self.live.patch(view["id"],selection(("camera-1","overview")))
            self.live.patch(view["id"],selection(("camera-1","high")))
            source = self.worker.sources["camera-1-high"]
            self.assertEqual(source["generation"],2)
            for kind in ("stopped","started","source_error"):
                self.worker._event(dict(type=kind,channel=1,quality="high",generation=1,error=43))
            self.assertEqual(source["state"],"starting")
            path = Path(directory)/"camera-1-high"; path.mkdir()
            metadata = dict(generation=1,sequence=1,width=1920,height=1080,decoded_frames=1,jpeg_frames=1,stream_bytes=2000)
            (path/"frame.json").write_text(json.dumps(metadata)); (path/"frame.jpg").write_bytes(b"\xff\xd8high\xff\xd9")
            self.worker._live_frame("camera-1-high"); self.assertIsNone(source["frame"])
            metadata["generation"] = 2; (path/"frame.json").write_text(json.dumps(metadata))
            source["stats_at"] -= 2
            self.worker._live_frame("camera-1-high")
            self.assertEqual(self.camera(view)["quality"],"high")
            metrics = [m for m in self.live.quality_status()["live_source_metrics"] if m["quality"]=="high"][0]
            self.assertEqual(metrics["width"],1920)
            for name in ("decoded_fps","delivered_fps","jpeg_bytes_per_second","stream_bytes_per_second"):
                self.assertGreater(metrics[name],0)
            self.assertIsNotNone(metrics["first_frame_seconds"])

    def test_idempotency_revision_validation_and_expiry(self):
        view = self.create(key="same")
        self.assertEqual(self.create(key="same")["id"],view["id"])
        with self.assertRaises(SessionError): self.create(quality="overview",key="same")
        with self.assertRaises(SessionError): self.create(quality="invalid")
        revision = view["selection_revision"]
        self.assertEqual(self.live.patch(view["id"],{})["selection_revision"],revision)
        self.now = 6; other = self.create(quality="overview")
        self.now = 11; self.live.reap()
        self.assertEqual(self.live.wanted,{"camera-1"})
        self.assertEqual(self.camera(other)["quality"],"overview")
        self.now = 17; self.live.reap(); self.assertEqual(self.live.used_sources(),0)

    def test_config_validation_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"config.json"
            for value in (None, 0, 1, 16, True, -1, 17, "1"):
                data = {"host":"192.0.2.10"}
                if value is not None: data["max_high_quality_sources"] = value
                path.write_text(json.dumps(data))
                if value is not None and (type(value) is not int or not 0 <= value <= 16):
                    with self.assertRaises(ValueError): load_config(path)
                else:
                    self.assertEqual(load_config(path)["max_high_quality_sources"],1 if value is None else value)

    def test_http_quality_status_and_feed_contract(self):
        server = create_server(self.worker,self.live,address=("127.0.0.1",0),web=ROOT/"web",recording=Path("/missing"))
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def request(path, method="GET", body=None):
            data = json.dumps(body).encode() if body is not None else None
            with urlopen(Request(f"http://127.0.0.1:{server.server_port}"+path,data=data,method=method,
                                 headers={"Content-Type":"application/json"}),timeout=3) as response:
                return json.load(response)
        try:
            view = request("/api/live/sessions","POST",selection(("camera-1","high")))
            self.assertEqual(view["cameras"][0]["upgrade_state"],"pending")
            self.worker.frame(); self.worker.frame(quality="high")
            status = request("/api/status")
            self.assertEqual(status["sources_by_quality"],dict(overview=1,high=1))
            self.assertEqual(status["high_quality_active"],1)
            self.assertEqual(status["sdk_login_calls"],1)
            camera = request("/api/live/sessions/"+view["id"])["cameras"][0]
            self.assertEqual((camera["quality"],camera["width"]),("high",1920))
            updated = request("/api/live/sessions/"+view["id"],"PATCH",selection(("camera-1","overview")))
            self.assertEqual(updated["cameras"][0]["quality"],"overview")
            with self.assertRaises(HTTPError) as caught:
                request("/api/live/sessions/"+view["id"],"PATCH",selection(("camera-1","nonsense")))
            self.assertEqual(caught.exception.code,422)
            self.assertEqual(request("/api/live/sessions/"+view["id"])["selection_revision"],updated["selection_revision"])
        finally:
            server.shutdown(); thread.join(timeout=2); server.timeline.close(); server.playback.close(); server.server_close()


if __name__ == "__main__": unittest.main()
