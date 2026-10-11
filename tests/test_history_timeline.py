from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from grid_server import create_server
from grid_worker import GridWorker
from history_timeline import HistoryTimeline, recorder_utc, recorder_wall, timestamp
from live_sessions import LiveSessions, SessionError

BEGIN, END = "2026-10-11T10:00:00Z", "2026-10-11T11:00:00Z"


class TimelineWorker:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.config = {"timezone":"Africa/Johannesburg"}
        self.cameras = {"camera-1":{"id":"camera-1", "channel":1, "online":False}}
        self.sources, self.calls = {}, []
        self.result = dict(recorder_now="2026-10-11T13:00:00",
            recordings=dict(state="ready", complete=True, source="NET_DVR_FindFile_V30", intervals=[
                dict(start="2026-10-11T11:50:00", end="2026-10-11T12:20:00", recording_type=0)]),
            motion=dict(state="ready", complete=True, source="NET_DVR_FindFileByEvent", intervals=[
                dict(start="2026-10-11T12:10:00", end="2026-10-11T12:10:00", recording_type=1)]))
        self.gate = threading.Event(); self.gate.set()

    def ensure_ready(self): pass

    def query_timeline(self, camera_id, begin, end):
        self.calls.append((camera_id, begin, end))
        self.gate.wait(2)
        return deepcopy(self.result)


class HistoryTimelineTests(unittest.TestCase):
    def setUp(self):
        self.worker = TimelineWorker()
        self.now = 0
        self.timeline = HistoryTimeline(self.worker, clock=lambda:self.now)
        self.addCleanup(self.timeline.close)

    def loaded(self, begin=BEGIN, end=END):
        self.timeline.query("camera-1", begin, end)
        entry = next(reversed(self.timeline.entries.values()))
        entry["future"].result(timeout=3)
        return self.timeline.query("camera-1", begin, end)[0]

    def test_utc_conversion_and_offline_camera_preserve_sdk_granularity(self):
        result = self.loaded()
        self.assertEqual(self.worker.calls, [("camera-1", "2026-10-11T12:00:00", "2026-10-11T13:00:00")])
        recording = result["recordings"]["intervals"][0]
        self.assertEqual(recording["start"], BEGIN)
        self.assertEqual(recording["source_start"], "2026-10-11T09:50:00Z")
        self.assertEqual(recording["granularity"], "recording")
        motion = result["motion"]["intervals"][0]
        self.assertEqual(motion["start"], motion["end"])
        self.assertEqual(motion["granularity"], "sdk_interval")
        self.assertEqual(result["recorder_now"], END)

    def test_empty_unavailable_and_partial_coverage_remain_distinct(self):
        self.worker.result["recordings"].update(intervals=[], complete=False)
        self.worker.result["motion"] = dict(state="unsupported", sdk_error=23)
        result = self.loaded()
        self.assertEqual(result["recordings"]["intervals"], [])
        self.assertFalse(result["recordings"]["complete"])
        self.assertIsNone(result["motion"]["intervals"])
        self.assertEqual(result["motion"]["state"], "unsupported")

    def test_duplicate_events_and_query_boundary_point(self):
        item = self.worker.result["motion"]["intervals"][0]
        self.worker.result["motion"]["intervals"] += [dict(item),
            dict(start="2026-10-11T13:00:00", end="2026-10-11T13:00:00", recording_type=1)]
        self.assertEqual(len(self.loaded()["motion"]["intervals"]), 1)

    def test_ids_stay_stable_across_overlapping_ranges(self):
        first = self.loaded()["recordings"]["intervals"][0]
        second = self.loaded("2026-10-11T09:55:00Z", END)["recordings"]["intervals"][0]
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["start"], second["start"])

    def test_invalid_sdk_interval_is_an_error_instead_of_an_empty_result(self):
        self.worker.result["motion"]["intervals"][0]["start"] = "invalid"
        result = self.loaded()
        self.assertEqual(result["recordings"]["state"], "ready")
        self.assertEqual(result["motion"]["state"], "error")
        self.assertIsNone(result["motion"]["intervals"])

    def test_cache_boundary_and_concurrent_pending_queries_share_work(self):
        self.worker.gate.clear()
        first, code = self.timeline.query("camera-1", BEGIN, END)
        self.assertEqual(code, 202)
        self.assertEqual(first["recordings"]["state"], "pending")
        for _ in range(5): self.timeline.query("camera-1", BEGIN, END, refresh=True)
        self.worker.gate.set()
        result = self.loaded()
        self.assertEqual(len(self.worker.calls), 1)
        self.now = 59.999
        self.assertEqual(self.timeline.query("camera-1", BEGIN, END)[1], 200)
        self.now = 60
        self.assertEqual(self.timeline.query("camera-1", BEGIN, END)[1], 202)
        self.loaded()
        self.assertEqual(len(self.worker.calls), 2)
        self.assertEqual(result["camera_id"], "camera-1")

    def test_explicit_refresh_and_failed_queries_are_bounded(self):
        self.worker.result["motion"] = dict(state="error", sdk_error=11)
        self.loaded()
        self.timeline.query("camera-1", BEGIN, END, refresh=True)
        self.loaded()
        self.assertEqual(len(self.worker.calls), 2)
        self.assertEqual(self.timeline.query("camera-1", BEGIN, END)[0]["motion"]["state"], "error")

    def test_cache_age_starts_on_completion_even_when_first_read_is_later(self):
        self.timeline.query("camera-1", BEGIN, END)
        entry = next(iter(self.timeline.entries.values()))
        entry["future"].result(timeout=3)
        with self.timeline.lock:
            pass
        self.now = 30
        self.assertEqual(self.timeline.query("camera-1", BEGIN, END)[1], 200)
        self.now = 60
        self.assertEqual(self.timeline.query("camera-1", BEGIN, END)[1], 202)

    def test_queue_limit_does_not_admit_unbounded_queries(self):
        self.worker.gate.clear()
        self.addCleanup(self.worker.gate.set)
        for minute in range(4):
            self.timeline.query("camera-1", BEGIN, f"2026-10-11T11:0{minute}:00Z")
        with self.assertRaises(SessionError) as failure:
            self.timeline.query("camera-1", BEGIN, "2026-10-11T11:05:00Z")
        self.assertEqual(failure.exception.status, 409)

    def test_invalid_range_and_missing_camera_are_rejected(self):
        for start, stop in [(END, BEGIN), (BEGIN, BEGIN), (BEGIN, "2026-10-11T17:00:00Z"),
                            ("2026-10-11T10:00:00", END), ("bad", END)]:
            with self.assertRaises(SessionError): self.timeline.query("camera-1", start, stop)
        with self.assertRaises(SessionError) as failure: self.timeline.query("camera-2", BEGIN, END)
        self.assertEqual(failure.exception.status, 404)
        self.assertEqual(self.worker.calls, [])

    def test_timezone_round_trip_midnight_and_ambiguous_dst(self):
        zone = ZoneInfo("Africa/Johannesburg")
        utc = timestamp("2026-10-11T00:15:00+02:00")
        self.assertEqual(utc.day, 10)
        self.assertEqual(recorder_utc(recorder_wall(utc, zone), zone), utc)
        zone = ZoneInfo("America/New_York")
        with self.assertRaises(SessionError): recorder_wall(datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc), zone)
        with self.assertRaises(ValueError): recorder_utc("2026-03-08T02:30:00", zone)

    def test_local_navigation_uses_recorder_timezone_and_centres_older_window(self):
        self.timeline.wall_clock = lambda:datetime(2026, 10, 11, 11, tzinfo=timezone.utc)
        result, status = self.timeline.query_local("camera-1", "2026-10-09T00:15:30", "3")
        self.assertEqual(status, 202)
        self.assertEqual(result["selected_time"], "2026-10-08T22:15:30Z")
        self.assertEqual(result["from"], "2026-10-08T20:45:30Z")
        self.assertEqual(result["to"], "2026-10-08T23:45:30Z")
        entry = next(iter(self.timeline.entries.values())); entry["future"].result(timeout=3)
        normal, status = self.timeline.query("camera-1", result["from"], result["to"])
        self.assertEqual(status, 200)
        self.assertNotIn("selected_time", normal, "Navigation must not mutate a cached range response")
        self.assertEqual(len(self.worker.calls), 1)

    def test_local_navigation_clips_near_now_and_accepts_minute_input(self):
        self.timeline.wall_clock = lambda:datetime(2026, 10, 11, 11, tzinfo=timezone.utc)
        result, _ = self.timeline.query_local("camera-1", "2026-10-11T12:59", "1")
        self.assertEqual(result["selected_time"], "2026-10-11T10:59:00Z")
        self.assertEqual(result["from"], BEGIN)
        self.assertEqual(result["to"], END)
        self.assertLess(timestamp(result["selected_time"]), timestamp(result["to"]))

    def test_local_navigation_invalid_future_and_dst_times_do_not_query_recorder(self):
        self.timeline.wall_clock = lambda:datetime(2026, 10, 11, 11, tzinfo=timezone.utc)
        for value, hours in (("", "3"), ("2026-02-30T12:00", "3"), ("2026-10-11T13:00", "3"),
            ("2026-10-11T13:00:01", "3"), ("2026-10-09T12:00+02:00", "3"),
            ("2026-10-09T12:00Z", "3"), ("2026-10-09T12:00", "24"), (None, "3"),
            ("0001-01-01T00:00", "3"), ("9999-12-31T23:59", "3")):
            with self.assertRaises(SessionError): self.timeline.query_local("camera-1", value, hours)
        self.timeline.zone = ZoneInfo("America/New_York")
        self.timeline.wall_clock = lambda:datetime(2026, 12, 1, tzinfo=timezone.utc)
        for value in ("2026-03-08T02:30", "2026-11-01T01:30"):
            with self.assertRaises(SessionError) as failure: self.timeline.query_local("camera-1", value, "1")
            self.assertEqual(failure.exception.status, 422)
        self.assertEqual(self.worker.calls, [])

    def test_http_local_navigation_and_mixed_duplicate_parameters(self):
        self.timeline.wall_clock = lambda:datetime(2026, 10, 11, 11, tzinfo=timezone.utc)
        server = create_server(self.worker, LiveSessions(self.worker), address=("127.0.0.1", 0),
            web=ROOT / "web", recording=ROOT / ".local/not-used.mp4", timeline=self.timeline)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/api/cameras/camera-1/timeline?"
        query = urlencode(dict(local_time="2026-10-09T00:15:30", hours="3"))
        with urlopen(base + query, timeout=2) as response:
            result = json.load(response)
            self.assertEqual(response.status, 202)
            self.assertEqual(result["selected_time"], "2026-10-08T22:15:30Z")
        for suffix in ("&local_time=bad", "&from=" + BEGIN, "&hours=1"):
            with self.assertRaises(HTTPError) as failure: urlopen(base + query + suffix, timeout=2)
            self.assertEqual(failure.exception.code, 400)

    def test_http_contract_encodes_offsets_and_rejects_repeated_parameters(self):
        sessions = LiveSessions(self.worker)
        server = create_server(self.worker, sessions, address=("127.0.0.1", 0),
            web=ROOT / "web", recording=ROOT / ".local/not-used.mp4", timeline=self.timeline)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/api/cameras/camera-1/timeline?"
        query = urlencode({"from":"2026-10-11T12:00:00+02:00", "to":"2026-10-11T13:00:00+02:00"})
        with urlopen(base + query, timeout=2) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(json.load(response)["from"], BEGIN)
        self.loaded()
        with urlopen(base + query, timeout=2) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as failure: urlopen(base + query + "&from=bad", timeout=2)
        self.assertEqual(failure.exception.code, 400)


class HistoryWorkerTests(unittest.TestCase):
    def worker(self):
        worker = GridWorker(None, None, {}, "/tmp/unused-history-fixture")
        worker.state, worker.login_calls = "ready", 1
        worker.cameras = {"camera-34":{"channel":34}}
        worker.sources = {"camera-34":{"state":"live", "frame":b"synthetic"}}
        worker.process = SimpleNamespace(stdin=Mock())
        return worker

    def test_native_command_uses_discovered_channel_and_cleans_response(self):
        worker = self.worker()
        def reply(command):
            parts = command.decode().split()
            self.assertEqual(parts[0:2], ["timeline", "34"])
            self.assertEqual(parts[3:], ["2026-10-11T12:00:00", "2026-10-11T13:00:00"])
            worker._event(dict(type="timeline", id=parts[2], recordings={"state":"ready"}))
        worker.process.stdin.write.side_effect = reply
        result = worker.query_timeline("camera-34", "2026-10-11T12:00:00", "2026-10-11T13:00:00")
        self.assertEqual(result["recordings"]["state"], "ready")
        self.assertEqual(worker.history_results, {})
        self.assertEqual(worker.login_calls, 1)
        self.assertEqual(worker.sources["camera-34"]["frame"], b"synthetic")

    def test_timeout_cleans_waiter_and_late_event_does_not_accumulate(self):
        worker = self.worker()
        with patch.object(worker.condition, "wait_for", side_effect=lambda predicate, timeout:predicate()):
            with self.assertRaises(ValueError): worker.query_timeline("camera-34", "begin", "end")
        worker._event(dict(type="timeline", id="unwanted-result"))
        self.assertEqual(worker.history_results, {})
        self.assertEqual(worker.process.stdin.write.call_count, 1)
        self.assertEqual(worker.state, "ready")


if __name__ == "__main__": unittest.main()
