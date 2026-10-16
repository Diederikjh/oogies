import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from live_sessions import LiveSessions, SessionError
from nvr_config import load_config
from grid_worker import GridWorker
from types import SimpleNamespace
from unittest.mock import Mock


class FakeWorker:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.cameras = {f"camera-{channel}": {"id":f"camera-{channel}", "channel":channel, "online":channel != 3} for channel in (1, 2, 3)}
        self.sources, self.started, self.stopped = {}, [], []
    def ensure_ready(self): pass
    def refresh_availability(self): pass
    def start_source(self, key):
        self.started.append(key)
        self.sources[key] = {"state":"starting", "frame":None, "sequence":0, "generation":1}
    def stop_source(self, key):
        self.stopped.append(key)
        self.sources[key].update(state="stopped", frame=None)


def selection(*channels):
    return {"cameras":[{"id":f"camera-{channel}", "quality":"overview"} for channel in channels]}


class LiveSessionTests(unittest.TestCase):
    def test_views_share_sources_and_release_independently(self):
        worker = FakeWorker(); sessions = LiveSessions(worker)
        first = sessions.create(selection(1, 2, 3))
        second = sessions.create(selection(1, 2))
        self.assertEqual(worker.started, ["camera-1", "camera-2"])
        self.assertEqual(first["cameras"][2]["state"], "offline")
        sessions.delete(first["id"])
        self.assertEqual(worker.stopped, [])
        sessions.delete(second["id"])
        self.assertEqual(worker.stopped, ["camera-1", "camera-2"])
        sessions.delete(second["id"])

    def test_dead_view_expires_without_stopping_other_view(self):
        now = [0]; worker = FakeWorker()
        sessions = LiveSessions(worker, lease_seconds=10, clock=lambda:now[0])
        abandoned = sessions.create(selection(1))
        other = sessions.create(selection(1, 2))
        now[0] = 6
        sessions.patch(other["id"], {})
        now[0] = 11; sessions.reap()
        with self.assertRaises(SessionError): sessions.get(abandoned["id"])
        self.assertEqual(worker.stopped, [])
        now[0] = 17; sessions.reap()
        self.assertEqual(set(worker.stopped), {"camera-1", "camera-2"})

    def test_idempotency_and_selection_updates_do_not_duplicate_sources(self):
        worker = FakeWorker(); sessions = LiveSessions(worker)
        first = sessions.create(selection(1), "same-view")
        self.assertEqual(first["id"], sessions.create(selection(1), "same-view")["id"])
        with self.assertRaises(SessionError): sessions.create(selection(2), "same-view")
        sessions.patch(first["id"], selection(2))
        self.assertEqual(worker.started, ["camera-1", "camera-2"])
        self.assertEqual(worker.stopped, ["camera-1"])

    def test_capacity_and_camera_failure_are_per_tile(self):
        worker = FakeWorker(); sessions = LiveSessions(worker, limit=1)
        first = sessions.create(selection(1, 2))
        self.assertEqual([camera["state"] for camera in first["cameras"]], ["starting", "capacity_limited"])
        worker.sources["camera-1"].update(state="error", error="synthetic source failure")
        self.assertEqual(sessions.get(first["id"])["cameras"][0]["state"], "error")
        with self.assertRaises(SessionError): sessions.patch(first["id"], {"cameras":[{"id":"camera-1","quality":"detail"}]})

    def test_frame_feed_contains_only_this_views_cameras_and_skips_old_frames(self):
        worker = FakeWorker(); sessions = LiveSessions(worker)
        view = sessions.create(selection(1))
        sessions.create(selection(2))
        frame = b"\xff\xd8synthetic\xff\xd9"
        for source in worker.sources.values(): source.update(frame=frame, sequence=1, state="live")
        seen = {}; packets = sessions.next_frames(view["id"], seen)
        self.assertEqual(len(packets), 1)
        packet = packets[0]
        self.assertEqual(int.from_bytes(packet[:4], "big"), len(packet) - 4)
        length = int.from_bytes(packet[4:6], "big")
        self.assertEqual(json.loads(packet[6:6+length])["camera_id"], "camera-1")
        self.assertEqual(packet[6+length:], frame)
        self.assertEqual(sessions.next_frames(view["id"], seen), [])


class RecorderConfigTests(unittest.TestCase):
    def test_owner_host_and_overrides_are_preserved_and_sdk_policy_is_not_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            value = {"host":"192.0.2.10", "sdk_port":8123,
                     "camera_overrides":{"2":{"name":"Side door", "aspect_ratio":"4:3", "enabled":False}}}
            path.write_text(json.dumps(value)); original = path.read_bytes()
            config = load_config(path)
            self.assertEqual(config["host"], value["host"])
            self.assertEqual(config["camera_overrides"], value["camera_overrides"])
            self.assertEqual(path.read_bytes(), original)
            for invalid in ({"host":"invalid address"}, {"host":"192.0.2.10","max_live_sources":True},
                            {"host":"192.0.2.10","sdk_profile":"missing"},
                            {"host":"192.0.2.10","login_password_max_chars":16}):
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError): load_config(path)


class GridWorkerLifecycleTests(unittest.TestCase):
    def test_delayed_stop_does_not_erase_restarted_source_or_watchdog_error(self):
        worker = GridWorker(None, None, {}, "/tmp")
        worker.sources["camera-1"] = {"state":"starting", "frame":None, "generation":2}
        worker._event({"type":"started", "channel":1, "quality":"overview", "generation":2})
        worker._event({"type":"stopped", "channel":1, "quality":"overview", "generation":1})
        self.assertEqual(worker.sources["camera-1"]["state"], "starting")
        self.assertEqual(worker.sources["camera-1"]["generation"], 2)
        worker.sources["camera-1"].update(state="error", error="No decoded frames")
        worker._event({"type":"stopped", "channel":1, "quality":"overview", "generation":1})
        self.assertEqual(worker.sources["camera-1"]["state"], "error")

    def test_broken_command_pipe_invalidates_all_cached_live_frames(self):
        class BrokenPipe:
            def write(self, command):
                raise BrokenPipeError()
        worker = GridWorker(None, None, {}, "/tmp")
        worker.process = SimpleNamespace(stdin=BrokenPipe())
        worker.cameras["camera-1"] = {"channel":1}
        worker.sources = {key: {"state":"live", "frame":b"old frame", "generation":1}
                          for key in ("camera-1", "camera-2")}
        worker.send("start", "camera-1")
        self.assertEqual(worker.state, "error")
        self.assertTrue(all(source["state"] == "error" and source["frame"] is None
                            for source in worker.sources.values()))


class CameraAvailabilityCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.spawn = Mock(side_effect=AssertionError("Availability refresh must not spawn/login"))
        self.worker = GridWorker(None, None, {"camera_overrides": {}}, "/tmp",
                                 spawn=self.spawn, clock=lambda: self.now)
        self.worker.process = SimpleNamespace(stdin=io.BytesIO())
        self.worker._event({"type":"ready", "protocol":2, "login_calls":1,
            "cameras":[{"channel":1,"name":"Driveway","online":True},
                       {"channel":3,"name":"Storage","online":False}]})

    def commands(self):
        return self.worker.process.stdin.getvalue().decode().splitlines()

    def test_expires_at_one_minute_and_parallel_callers_share_one_refresh(self):
        self.now = 59.999
        self.worker.refresh_availability()
        self.assertEqual(self.commands(), [])
        self.now = 60
        callers = [threading.Thread(target=self.worker.refresh_availability) for _ in range(8)]
        for caller in callers: caller.start()
        for caller in callers: caller.join()
        self.assertEqual(self.commands(), ["refresh"])
        self.assertFalse(self.worker.cameras["camera-3"]["online"])
        self.assertEqual(self.worker.login_calls, 1)
        self.spawn.assert_not_called()

    def test_offline_camera_recovers_in_existing_views_without_restarting_healthy_source(self):
        sessions = LiveSessions(self.worker, clock=lambda:self.now)
        first = sessions.create(selection(1,3))
        second = sessions.create(selection(1,3))
        self.assertEqual(self.commands(), ["start 1 overview 1"])
        self.now = 59.999
        sessions.maintain()
        self.assertEqual(self.commands(), ["start 1 overview 1"])
        self.now = 60
        sessions.maintain()
        self.assertEqual(self.commands(), ["start 1 overview 1", "refresh"])
        self.worker._event({"type":"availability", "cameras":[{"channel":3,"online":True}]})
        sessions.maintain()
        self.worker._event({"type":"started","channel":3,"quality":"overview","generation":1})
        self.worker.sources["camera-3"].update(state="live", frame=b"\xff\xd8fixture\xff\xd9",
                                               received=1, sequence=1, last_frame=time.monotonic())
        for view in (first, second):
            self.assertEqual(sessions.get(view["id"])["cameras"][1]["state"], "live")
            self.assertEqual(len(sessions.next_frames(view["id"], {})), 1)
        self.assertEqual(self.commands(), ["start 1 overview 1", "refresh", "start 3 overview 1"])
        self.assertEqual(self.worker.cameras["camera-3"]["name"], "Storage")
        self.assertEqual(self.worker.login_calls, 1)
        self.spawn.assert_not_called()

    def test_still_offline_and_failed_status_do_not_probe_or_query_every_tick(self):
        sessions = LiveSessions(self.worker, lease_seconds=300, clock=lambda:self.now)
        view = sessions.create(selection(3))
        self.now = 60
        sessions.maintain()
        self.worker._event({"type":"availability", "cameras":[{"channel":3,"online":None}]})
        self.now = 119.999
        sessions.maintain()
        self.assertEqual(self.commands(), ["refresh"])
        self.assertEqual(sessions.get(view["id"])["cameras"][0]["state"], "offline")
        self.now = 120
        sessions.maintain()
        self.worker._event({"type":"availability", "cameras":[{"channel":3,"online":False}]})
        sessions.maintain()
        self.assertEqual(self.commands(), ["refresh", "refresh"])
        self.assertEqual(self.worker.login_calls, 1)

    def test_refresh_preserves_fresh_video_and_releases_only_confirmed_offline_source(self):
        self.worker.cameras["camera-3"]["online"] = True
        sessions = LiveSessions(self.worker, clock=lambda:self.now)
        view = sessions.create(selection(1,3))
        self.worker.sources["camera-1"].update(state="live", frame=b"healthy-frame", last_frame=time.monotonic())
        self.worker._event({"type":"availability", "cameras":[
            {"channel":1,"online":False},{"channel":3,"online":False}]})
        sessions.maintain()
        self.assertTrue(self.worker.cameras["camera-1"]["online"])
        self.assertEqual([c["state"] for c in sessions.get(view["id"])["cameras"]], ["live","offline"])
        self.assertEqual(self.commands(), ["start 1 overview 1","start 3 overview 1","stop 3 overview 1"])

    def test_no_active_view_does_not_refresh_or_retry_a_rejected_login(self):
        sessions = LiveSessions(self.worker, clock=lambda:self.now)
        self.now = 60
        sessions.maintain()
        self.assertEqual(self.commands(), [])
        self.worker.state = "error"
        self.worker.refresh_availability()
        self.assertEqual(self.commands(), [])
        self.spawn.assert_not_called()
