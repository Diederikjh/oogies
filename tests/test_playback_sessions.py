from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from grid_worker import GridWorker
from live_sessions import LiveSessions, SessionError
from playback_sessions import PlaybackSessions

BEGIN, END = "2026-10-11T10:00:00Z", "2026-10-11T11:00:00Z"


class PlaybackWorker(GridWorker):
    def __init__(self):
        super().__init__(None, None, {}, "/tmp/unused-playback-fixture")
        self.state, self.login_calls = "ready", 1
        self.cameras = {f"camera-{number}":dict(channel=number, online=number == 1) for number in (1, 2, 3)}
        self.commands = []

    def _command(self, command): self.commands.append(command)
    def start_source(self, camera): self.sources[camera] = dict(state="live", frame=None)
    def stop_source(self, camera): self.sources[camera]["state"] = "stopped"


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.worker = PlaybackWorker()
        self.now = 0
        self.live = LiveSessions(self.worker, limit=3, lease_seconds=10, clock=lambda:self.now)
        self.playback = PlaybackSessions(self.worker, self.live, limit=2, lease_seconds=10, clock=lambda:self.now)
        self.addCleanup(self.live.close)
        self.addCleanup(self.playback.close)

    def create(self, camera="camera-1", position=BEGIN):
        return self.playback.create(dict(camera_id=camera, **{"from":BEGIN, "to":END}, position=position))

    def test_selected_position_maps_to_sdk_channel_wall_clock_and_full_range(self):
        result = self.create("camera-3", "2026-10-11T10:20:00Z")
        self.assertEqual(result["from"], BEGIN)
        self.assertEqual(result["position"], None)
        self.assertEqual(result["generation"], 1)
        self.assertIn("playback-start 3", self.worker.commands[0])
        self.assertTrue(self.worker.commands[0].endswith("2026-10-11T12:20:00 2026-10-11T13:00:00 0 0"))
        self.assertEqual(self.worker.login_calls, 1)

    def test_seek_clears_old_frame_and_discards_old_generation_events(self):
        result = self.create(); identifier = result["id"]
        self.worker.playbacks[identifier].update(state="playing", frame=b"old", position=BEGIN)
        seeked = self.playback.patch(identifier, {"position":"2026-10-11T10:25:00Z"})
        self.assertEqual(seeked["generation"], 2)
        self.assertEqual(seeked["state"], "seeking")
        self.assertIsNone(self.worker.playbacks[identifier]["frame"])
        self.worker._event(dict(type="playback", id=identifier, generation=1, state="error", error=33))
        self.assertEqual(self.playback.get(identifier)["state"], "seeking")

    def test_pause_seek_preserves_pause_and_new_native_events_confirm_state(self):
        result = self.create(); identifier = result["id"]
        self.worker.playbacks[identifier]["state"] = "playing"
        self.assertEqual(self.playback.patch(identifier, {"state":"paused"})["state"], "pausing")
        self.worker._event(dict(type="playback", id=identifier, generation=1, state="paused", error=0))
        self.assertEqual(self.playback.get(identifier)["state"], "paused")
        self.playback.patch(identifier, {"position":"2026-10-11T10:15:00Z"})
        self.assertTrue(self.worker.commands[-1].endswith(" 1 0"))
        self.worker._event(dict(type="playback", id=identifier, generation=2, state="paused", error=0))
        self.assertEqual(self.playback.get(identifier)["state"], "paused")

    def test_resume_reopens_at_confirmed_time_and_repeated_pause_is_idempotent(self):
        session = self.create(); identifier = session["id"]
        source = self.worker.playbacks[identifier]
        source.update(state="paused", position="2026-10-11T10:17:05Z", frame=b"retained")
        commands = len(self.worker.commands)
        self.playback.patch(identifier, {"state":"paused"})
        self.assertEqual(len(self.worker.commands), commands)
        resumed = self.playback.patch(identifier, {"state":"playing"})
        self.assertEqual(resumed["generation"], 2)
        self.assertIsNone(self.worker.playbacks[identifier]["frame"])
        self.assertTrue(self.worker.commands[-1].endswith("2026-10-11T12:17:05 2026-10-11T13:00:00 0 0"))

    def test_rate_changes_use_decoder_command_and_preserve_position_generation(self):
        session = self.create(); identifier = session["id"]
        source = self.worker.playbacks[identifier]
        source.update(state="playing", position=BEGIN, frame=b"picture")
        changed = self.playback.patch(identifier, {"rate":4})
        self.assertEqual((changed["rate"], changed["requested_rate"]), (1, 4))
        self.assertEqual(changed["generation"], 1)
        self.assertEqual(source["frame"], b"picture")
        self.assertTrue(self.worker.commands[-1].endswith(" 1 2"))
        self.worker._event(dict(type="playback_rate", id=identifier, generation=1, rate=4, requested_rate=4, error=0))
        self.assertEqual(self.playback.get(identifier)["rate"], 4)
        seek = self.playback.patch(identifier, {"position":"2026-10-11T10:10:00Z"})
        self.assertEqual(seek["requested_rate"], 4)
        self.assertTrue(self.worker.commands[-1].endswith(" 0 2"))
        self.assertEqual(self.worker.login_calls, 1)

    def test_paused_speed_applies_on_resume_and_paused_seek(self):
        session = self.create(); identifier = session["id"]
        source = self.worker.playbacks[identifier]
        source.update(state="paused", position=BEGIN)
        count = len(self.worker.commands)
        changed = self.playback.patch(identifier, {"rate":0.5})
        self.assertEqual((changed["state"], changed["rate"]), ("paused", 0.5))
        self.assertEqual(len(self.worker.commands), count)
        self.playback.patch(identifier, {"position":"2026-10-11T10:15:00Z"})
        self.assertTrue(self.worker.commands[-1].endswith(" 1 -1"))
        self.worker.playbacks[identifier].update(state="paused", position=BEGIN)
        self.playback.patch(identifier, {"state":"playing"})
        self.assertTrue(self.worker.commands[-1].endswith(" 0 -1"))

    def test_rate_rejection_and_stale_ack_keep_playback_and_other_view_unchanged(self):
        first, second = self.create(), self.create(position="2026-10-11T10:30:00Z")
        source = self.worker.playbacks[first["id"]]
        source.update(state="playing", frame=b"picture")
        self.playback.patch(first["id"], {"rate":4})
        self.worker._event(dict(type="playback_rate", id=first["id"], generation=1, rate=2, requested_rate=2, error=0))
        self.assertEqual(source["requested_rate"], 4)
        self.worker._event(dict(type="playback_rate", id=first["id"], generation=1, rate=1, requested_rate=4, error=2))
        rejected = self.playback.get(first["id"])
        self.assertEqual(rejected["state"], "playing")
        self.assertEqual((rejected["rate"], rejected["requested_rate"]), (1, 1))
        self.assertIn("decoder code 2", rejected["rate_error"])
        self.assertEqual(source["frame"], b"picture")
        self.assertEqual(self.playback.get(second["id"])["rate"], 1)
        self.playback.patch(first["id"], {"position":"2026-10-11T10:10:00Z"})
        self.worker._event(dict(type="playback_rate", id=first["id"], generation=1, rate=4, requested_rate=4, error=0))
        self.assertEqual(self.playback.get(first["id"])["requested_rate"], 1)

    def test_rate_validation_happens_before_native_work(self):
        for rate in (True, False, "2", None, 0, -1, 0.75, 1.5, 8, float("nan"), float("inf")):
            with self.assertRaises(SessionError):
                self.playback.create(dict(camera_id="camera-1", **{"from":BEGIN, "to":END}, rate=rate))
        self.assertEqual(self.worker.commands, [])
        session = self.create()
        for rate in (True, "4", 8, 1.5):
            with self.assertRaises(SessionError): self.playback.patch(session["id"], {"rate":rate})
        self.assertEqual(len(self.worker.commands), 1)

    def test_independent_positions_controls_and_expiry(self):
        first, second = self.create(), self.create(position="2026-10-11T10:30:00Z")
        self.playback.patch(first["id"], {"position":"2026-10-11T10:10:00Z"})
        self.assertEqual(self.playback.get(second["id"])["generation"], 1)
        self.now = 6; self.playback.patch(second["id"], {})
        self.now = 11; self.playback.reap()
        self.assertNotIn(first["id"], self.worker.playbacks)
        self.assertIn(second["id"], self.worker.playbacks)
        self.assertEqual(self.live.reserved_sources, 1)
        self.playback.delete(first["id"])
        self.assertEqual(self.live.reserved_sources, 1)

    def test_playback_capacity_does_not_evict_live_sources(self):
        self.live.limit = 1
        view = self.live.create({"cameras":[{"id":"camera-1", "quality":"overview"}]})
        with self.assertRaises(SessionError) as failure: self.create()
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.live.get(view["id"])["cameras"][0]["state"], "live")
        self.assertEqual(self.worker.commands, [])

    def test_live_recovery_respects_reserved_slot_then_recovers_on_release(self):
        self.live.limit = 2
        self.live.create({"cameras":[{"id":f"camera-{number}", "quality":"overview"} for number in (1, 2)]})
        playback = self.create()
        self.worker.cameras["camera-2"]["online"] = True
        with self.live.lock: self.live._reconcile()
        self.assertEqual(self.live.wanted, {"camera-1"})
        self.playback.delete(playback["id"])
        self.assertEqual(self.live.wanted, {"camera-1", "camera-2"})
        self.assertEqual(self.live.reserved_sources, 0)

    def test_frame_packets_include_absolute_position_and_seek_generation(self):
        result = self.create(); identifier = result["id"]
        self.worker.playbacks[identifier].update(state="playing", frame=b"\xff\xd8synthetic\xff\xd9", sequence=1, position=BEGIN)
        seen = {}
        packet = self.playback.next_frames(identifier, seen)[0]
        length = int.from_bytes(packet[4:6], "big")
        header = json.loads(packet[6:6+length])
        self.assertEqual(header, dict(camera_id="camera-1", generation=1, sequence=1, position=BEGIN))
        self.worker.playbacks[identifier]["generation"] = 2
        self.assertEqual(len(self.playback.next_frames(identifier, seen)), 1)

    def test_invalid_ranges_and_controls_do_not_start_extra_native_jobs(self):
        for body in ([], {}, dict(camera_id="camera-1", **{"from":BEGIN, "to":BEGIN}),
                     dict(camera_id="camera-1", **{"from":BEGIN, "to":END}, position=END)):
            with self.assertRaises(SessionError): self.playback.create(body)
        self.assertEqual(self.worker.commands, [])
        session = self.create()
        for body in ({"rate":8}, {"position":END}, {"state":"invalid"}):
            with self.assertRaises(SessionError): self.playback.patch(session["id"], body)
        self.assertEqual(len(self.worker.commands), 1)

    def test_native_frame_file_rejects_old_generation_and_preserves_paused_state(self):
        session = self.create(); identifier = session["id"]
        self.playback.patch(identifier, {"position":"2026-10-11T10:20:00Z"})
        with tempfile.TemporaryDirectory() as temporary:
            self.worker.directory = Path(temporary)
            directory = Path(temporary) / ("playback-" + identifier); directory.mkdir()
            (directory / "frame.jpg").write_bytes(b"\xff\xd8synthetic\xff\xd9")
            metadata = dict(generation=1, sequence=1, position="2026-10-11T12:00:00", width=352, height=288)
            (directory / "frame.json").write_text(json.dumps(metadata)); self.worker._playback_frames()
            self.assertIsNone(self.worker.playbacks[identifier]["frame"])
            metadata.update(generation=2, position="2026-10-11T12:20:00")
            self.worker.playbacks[identifier]["state"] = "paused"
            (directory / "frame.json").write_text(json.dumps(metadata)); self.worker._playback_frames()
            current = self.playback.get(identifier)
            self.assertEqual(current["position"], "2026-10-11T10:20:00Z")
            self.assertEqual(current["state"], "paused")


if __name__ == "__main__": unittest.main()
