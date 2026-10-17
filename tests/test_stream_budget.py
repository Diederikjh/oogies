"""Capacity ownership tested independently of recorder, HTTP and browser."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
sys.path.insert(0, str(ROOT/"docker/hikvision-sdk"))
from stream_budget import StreamBudget
from live_sessions import LiveSessions
from playback_sessions import PlaybackSessions
from export_jobs import ExportJobs
from grid_server import create_server
from maintenance import maintenance_tick, run_maintenance
from service_errors import SessionError
from test_live_quality import Recorder, selection
from test_export_jobs import Capture


class StreamBudgetTests(unittest.TestCase):
    def setUp(self):
        self.condition = threading.Condition(threading.RLock())
        self.occupancy = {}
        self.budget = StreamBudget(self.condition, limit=10, high_limit=2)
        self.budget.bind_live_usage(lambda:dict(self.occupancy))

    def test_snapshot_counts_distinct_live_sources_and_reservations(self):
        self.occupancy.update({f"camera-{n}":"overview" for n in range(7)})
        self.occupancy.update({f"camera-{n}-high":"high" for n in range(2)})
        token = self.budget.try_reserve("playback", "viewer")
        snapshot = self.budget.snapshot()
        self.assertEqual((snapshot.overview,snapshot.high,snapshot.playback,snapshot.exports), (7,2,1,0))
        self.assertEqual((snapshot.used,snapshot.available,snapshot.reserved), (10,0,1))
        with self.assertRaises(FrozenInstanceError): snapshot.overview = 0
        self.budget.release(token)
        self.assertEqual(snapshot.used,10)
        self.assertEqual(self.budget.snapshot().used,9)

    def test_live_capacity_distinguishes_total_and_high_limits(self):
        self.budget.high_limit = 0
        self.assertEqual(self.budget.check_live("high"),"high_quality_limit")
        self.assertIsNone(self.budget.check_live("overview"))
        self.budget.high_limit = 2
        self.occupancy.update({f"camera-{n}-high":"high" for n in range(2)})
        self.assertEqual(self.budget.check_live("high"),"high_quality_limit")
        self.occupancy.clear(); self.occupancy.update({str(n):"overview" for n in range(10)})
        for quality in ("overview","high"):
            self.assertEqual(self.budget.check_live(quality),"source_limit")
        self.assertIsNone(self.budget.try_reserve("export","job"))

    def test_reservation_is_idempotent_for_same_owner(self):
        first = self.budget.try_reserve("playback","same")
        self.assertIs(self.budget.try_reserve("playback","same"),first)
        second = self.budget.try_reserve("export","same")
        self.assertIsNot(first,second)
        self.assertEqual(self.budget.snapshot().reserved,2)
        self.budget.limit = 2
        self.assertIs(self.budget.try_reserve("export","same"),second)
        self.assertIsNone(self.budget.try_reserve("export","different"))

    def test_duplicate_stale_or_foreign_release_cannot_free_another_slot(self):
        old = self.budget.try_reserve("playback","viewer")
        other = self.budget.try_reserve("export","job")
        self.assertTrue(self.budget.release(old))
        fresh = self.budget.try_reserve("playback","viewer")
        foreign_budget = StreamBudget(self.condition); foreign_budget.bind_live_usage(dict)
        foreign = foreign_budget.try_reserve("playback","viewer")
        for token in (old,foreign,None):
            self.assertFalse(self.budget.release(token))
            self.assertEqual(self.budget.snapshot().reserved,2)
        self.assertTrue(self.budget.release(fresh)); self.assertFalse(self.budget.release(fresh))
        self.assertTrue(self.budget.release(other)); self.assertEqual(self.budget.snapshot().used,0)

    def test_competing_reservations_cannot_exceed_last_slot(self):
        self.budget.limit = 1
        barrier = threading.Barrier(3); results = []
        def reserve(kind):
            barrier.wait(timeout=3)
            results.append(self.budget.try_reserve(kind,kind))
        threads = [threading.Thread(target=reserve,args=(kind,)) for kind in ("playback","export")]
        for thread in threads: thread.start()
        barrier.wait(timeout=3)
        for thread in threads: thread.join(timeout=3); self.assertFalse(thread.is_alive())
        self.assertEqual(sum(token is not None for token in results),1)
        self.assertEqual(self.budget.snapshot().used,1)

    def test_release_refreshes_once_before_notifying_waiters(self):
        refreshed, waiting, woke = (threading.Event() for _ in range(3))
        budget = StreamBudget(self.condition,1)
        snapshots = []
        def refresh(): snapshots.append(budget.snapshot()); refreshed.set()
        budget.bind_live_usage(dict,refresh)
        token = budget.try_reserve("export","job")
        def wait():
            with self.condition:
                waiting.set()
                if self.condition.wait(timeout=3):
                    if refreshed.is_set(): woke.set()
        thread = threading.Thread(target=wait); thread.start()
        self.assertTrue(waiting.wait(3))
        self.assertTrue(budget.release(token)); thread.join(timeout=3)
        self.assertFalse(thread.is_alive()); self.assertTrue(woke.is_set())
        self.assertEqual(snapshots[0].used,0)
        self.assertFalse(budget.release(token)); self.assertEqual(len(snapshots),1)

    def test_release_keeps_accounting_correct_if_refresh_raises(self):
        waiting, woke = threading.Event(), threading.Event()
        budget = StreamBudget(self.condition)
        def fail(): raise OSError("Refresh failed")
        budget.bind_live_usage(dict,fail)
        token = budget.try_reserve("playback","viewer")
        other = budget.try_reserve("export","job")
        def wait():
            with self.condition:
                waiting.set()
                if self.condition.wait(timeout=3): woke.set()
        thread = threading.Thread(target=wait); thread.start(); self.assertTrue(waiting.wait(3))
        with self.assertRaisesRegex(OSError,"Refresh failed"): budget.release(token)
        thread.join(timeout=3); self.assertFalse(thread.is_alive()); self.assertTrue(woke.is_set())
        self.assertEqual(budget.snapshot().reserved,1)
        self.assertFalse(budget.release(token))
        self.assertIs(budget.try_reserve("export","job"),other)

    def test_binding_is_required_before_admission_and_can_happen_only_once(self):
        budget = StreamBudget(self.condition)
        for operation in (budget.snapshot,lambda:budget.try_reserve("export","job"),lambda:budget.check_live("high")):
            with self.assertRaisesRegex(ValueError,"Bind live occupancy"): operation()
        budget.bind_live_usage(dict)
        with self.assertRaisesRegex(ValueError,"already bound"): budget.bind_live_usage(dict)

    def test_invalid_limits_and_owner_types_are_rejected(self):
        for limits in ((0,1),(17,1),(True,1),(8,-1),(8,17),(8,True)):
            with self.assertRaises(ValueError): StreamBudget(self.condition,*limits)
        for kind,owner in (("live","camera"),("export",None),("export","")):
            with self.assertRaises(ValueError): self.budget.try_reserve(kind,owner)


class BudgetOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.worker = Recorder(); self.now = 0
        self.live = LiveSessions(self.worker,limit=4,high_limit=2,clock=lambda:self.now)
        self.budget = self.live.budget
        self.playback = PlaybackSessions(self.worker,self.budget,limit=2,lease_seconds=10,clock=lambda:self.now)
        self.addCleanup(self.live.close); self.addCleanup(self.playback.close)

    def play(self):
        return self.playback.create(dict(camera_id="camera-1", **{
            "from":"2026-10-11T10:00:00Z","to":"2026-10-11T11:00:00Z"}))

    def test_closing_live_source_counts_until_current_stop_ack(self):
        self.budget.limit = 2
        view = self.live.create(selection(("camera-1","high")))
        self.worker.frame(); self.worker.frame(quality="high")
        self.worker.ack_stops = False
        self.live.patch(view["id"],selection(("camera-1","overview")))
        self.assertEqual(self.budget.snapshot().used,2)
        self.assertEqual(self.budget.snapshot().high,1)
        self.assertIsNone(self.budget.try_reserve("export","job"))
        self.worker._event(dict(type="stopped",channel=1,quality="high",generation=0))
        self.assertEqual(self.budget.snapshot().used,2)
        self.worker._event(dict(type="stopped",channel=1,quality="high",generation=1))
        self.assertEqual(self.budget.snapshot().used,1)
        self.live.maintain(); self.assertNotIn("camera-1-high",self.live.wanted)
        self.live.patch(view["id"],selection(("camera-1","high")))
        self.assertEqual(self.worker.sources["camera-1-high"]["generation"],2)

    def test_live_and_playback_compete_atomically_for_last_slot(self):
        self.budget.limit = 1
        barrier = threading.Barrier(3); errors = []
        def admit(playback):
            try:
                barrier.wait(timeout=3)
                if playback: self.play()
                else: self.live.create(selection(("camera-1","overview")))
            except SessionError as error: errors.append(error)
            except Exception as error: errors.append(error)
        threads = [threading.Thread(target=admit,args=(choice,)) for choice in (False,True)]
        for thread in threads: thread.start()
        barrier.wait(timeout=3)
        for thread in threads: thread.join(timeout=3); self.assertFalse(thread.is_alive())
        self.assertTrue(all(isinstance(error,SessionError) and error.status==409 for error in errors))
        self.assertEqual(self.budget.snapshot().used,1)
        self.assertEqual(len([c for c in self.worker.commands if c.startswith(("start ","playback-start "))]),1)
        self.assertEqual(self.worker.login_calls,1)

    def test_playback_start_failure_rolls_back_its_handle(self):
        export = self.budget.try_reserve("export","independent")
        self.addCleanup(self.budget.release,export)
        with patch.object(self.worker,"start_playback",side_effect=ValueError("Start failed")):
            with self.assertRaises(SessionError): self.play()
        self.assertEqual(self.playback.sessions,{})
        self.assertEqual(self.budget.snapshot().playback,0)
        self.assertIs(self.budget.try_reserve("export","independent"),export)
        self.assertEqual(self.worker.login_calls,1)

    def test_seek_rate_range_and_pause_reuse_playback_reservation(self):
        session = self.play(); identifier = session["id"]
        token = self.playback.sessions[identifier]["reservation"]
        self.worker.playbacks[identifier].update(state="playing",position=session["from"])
        for update in ({"rate":2},{"state":"paused"},{"position":"2026-10-11T10:10:00Z","state":"paused"},
                       {"from":"2026-10-11T09:00:00Z","to":"2026-10-11T12:00:00Z","position":"2026-10-11T11:00:00Z","rate":4}):
            self.playback.patch(identifier,update)
            self.assertIs(self.playback.sessions[identifier]["reservation"],token)
            self.assertEqual(self.budget.snapshot().playback,1)
        self.playback.delete(identifier); self.playback.delete(identifier)
        self.assertEqual(self.budget.snapshot().reserved,0)

    def test_release_recovers_overview_immediately_without_retrying_refused_high(self):
        self.budget.limit = 2
        playback = self.play()
        view = self.live.create(selection(("camera-1","high"),("camera-2","overview")))
        self.assertEqual(len(self.live.wanted),1)
        self.playback.delete(playback["id"])
        self.assertEqual(self.live.wanted,{"camera-1","camera-2"})
        self.assertNotIn("camera-1-high",self.live.wanted)
        self.assertEqual(self.budget.snapshot().reserved,0)
        self.assertEqual(self.live.get(view["id"])["cameras"][0]["upgrade_state"],"capacity_limited")

    def test_maintenance_expires_playback_without_live_viewers(self):
        self.play(); self.live.close()
        export = self.budget.try_reserve("export","active-job")
        self.addCleanup(self.budget.release,export)
        self.now = 11; maintenance_tick(self.live,self.playback)
        self.assertEqual(self.playback.sessions,{})
        self.assertEqual(self.budget.snapshot().playback,0)
        self.assertIs(self.budget.try_reserve("export","active-job"),export)
        stop = threading.Event(); ticked = threading.Event()
        def tick(live,playback):
            maintenance_tick(live,playback); ticked.set(); stop.set()
        with patch("maintenance.maintenance_tick",side_effect=tick):
            thread = threading.Thread(target=run_maintenance,args=(self.live,self.playback,stop))
            thread.start(); thread.join(timeout=3)
        self.assertFalse(thread.is_alive()); self.assertTrue(ticked.is_set())

    def test_services_reject_unbound_or_mismatched_budgets_before_startup(self):
        budget = StreamBudget(self.worker.condition)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,"Bind live occupancy"):
                ExportJobs(self.worker,budget,Path(directory)/"unused")
            self.assertFalse((Path(directory)/"unused").exists())
        with self.assertRaisesRegex(ValueError,"Bind live occupancy"): PlaybackSessions(self.worker,budget)
        budget.bind_live_usage(dict)
        other = PlaybackSessions(self.worker,budget)
        with self.assertRaisesRegex(ValueError,"share one stream budget"):
            create_server(self.worker,self.live,address=("127.0.0.1",0),web="/unused",recording="/unused",playback=other)

    def test_status_preserves_existing_capacity_fields(self):
        self.play()
        export = self.budget.try_reserve("export","job")
        self.addCleanup(self.budget.release,export)
        view = self.live.create(selection(("camera-1","high")))
        self.worker.frame(); self.worker.frame(quality="high")
        self.worker.ack_stops = False
        self.live.patch(view["id"],selection(("camera-1","overview")))
        server = create_server(self.worker,self.live,address=("127.0.0.1",0),web="/unused",recording="/unused",playback=self.playback)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        self.addCleanup(thread.join,3); self.addCleanup(server.shutdown)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/status",timeout=3) as response:
            status = json.load(response)
        self.assertEqual(status["reserved_sources"],2)
        self.assertEqual(status["occupied_source_slots"],4)
        self.assertEqual(status["sources_by_quality"],dict(overview=1,high=1))
        self.assertEqual(status["high_quality_limit"],2)
        self.assertEqual(status["source_limit"],4)
        self.assertEqual(status["sdk_login_calls"],1)

    def test_playback_and_export_cancellation_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Capture(); started = threading.Event()
            original = capture.capture
            def begin(*args): started.set(); return original(*args)
            capture.capture = begin
            jobs = ExportJobs(self.worker,self.budget,directory,encoder=capture)
            try:
                first = self.play()
                job = jobs.create(dict(camera_id="camera-1",aspect_ratio="16:9", **{
                    "from":"2026-10-11T10:00:00Z","to":"2026-10-11T10:00:10Z"}))
                self.assertTrue(started.wait(3)); self.assertEqual(self.budget.snapshot().reserved,2)
                self.playback.delete(first["id"])
                self.assertEqual(jobs.get(job["id"])["state"],"running")
                second = self.play(); token = self.playback.sessions[second["id"]]["reservation"]
                jobs.delete(job["id"])
                with self.worker.condition:
                    self.assertTrue(self.worker.condition.wait_for(lambda:jobs.active is None,timeout=3))
                self.assertEqual(self.budget.snapshot().exports,0)
                self.assertIs(self.playback.sessions[second["id"]]["reservation"],token)
                self.assertIn(second["id"],self.worker.playbacks)
                self.assertEqual(self.budget.snapshot().playback,1)
            finally: jobs.close()

