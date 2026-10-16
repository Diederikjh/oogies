#!/usr/bin/env python3
"""One bounded real-recorder playback check through the service's public API."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--camera", default="camera-1")
    parser.add_argument("--continuous-seconds", type=int, default=60,
                        help="Continuous playback before control checks (15-180 seconds)")
    parser.add_argument("--with-live", action="store_true", help="Also verify one live preview keeps advancing")
    args = parser.parse_args()
    if not 15 <= args.continuous_seconds <= 180: parser.error("choose 15-180 continuous seconds")
    output = Path(__file__).resolve().parents[1] / ".local/browser-viewer" / ("playback-check-" + uuid.uuid4().hex)
    output.mkdir(parents=True, mode=0o700)
    def api(path, method="GET", body=None):
        request = Request(args.url + path, method=method, data=None if body is None else json.dumps(body).encode(),
                          headers={} if body is None else {"Content-Type":"application/json"})
        with urlopen(request, timeout=35) as response: return None if response.status == 204 else json.load(response)
    position = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    text = lambda value:value.isoformat().replace("+00:00", "Z")
    session = api("/api/playback/sessions", "POST", dict(camera_id=args.camera,
        **{"from":text(position - timedelta(hours=2)), "to":text(position + timedelta(hours=1))}, position=text(position)))
    identifier = session["id"]; path = "/api/playback/sessions/" + identifier
    packets, failures, stop = [], [], threading.Event()
    media = None
    live_path, live_initial, live_last = None, None, None
    try:
        if args.with_live:
            live = api("/api/live/sessions", "POST", {"cameras":[{"id":args.camera, "quality":"overview"}]})
            live_path = "/api/live/sessions/" + live["id"]
        media = urlopen(args.url + session["media"]["url"], timeout=15)
        def read_exact(count):
            data = b""
            while len(data) < count:
                chunk = media.read(count - len(data))
                if not chunk: raise EOFError("Frame feed ended")
                data += chunk
            return data
        def consume():
            try:
                while not stop.is_set():
                    size = int.from_bytes(read_exact(4), "big")
                    if not 3 <= size <= 4 * 1024 * 1024 + 1024: raise ValueError("Invalid frame size")
                    packet = read_exact(size); length = int.from_bytes(packet[:2], "big")
                    header = json.loads(packet[2:2+length]); frame = packet[2+length:]
                    if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"): raise ValueError("Invalid JPEG")
                    packets.append(dict(header, sha256=hashlib.sha256(frame).hexdigest()))
                    if len(packets) == 1:
                        image = output / "first-frame.jpg"; image.write_bytes(frame); image.chmod(0o600)
            except (OSError, ValueError, EOFError) as error:
                if not stop.is_set(): failures.append(type(error).__name__)
        reader = threading.Thread(target=consume, daemon=True); reader.start()
        def wait(predicate, seconds=15):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                status = api(path)
                if status["state"] == "error": raise RuntimeError(status["error"] or "Playback failed")
                if predicate(status): return status
                time.sleep(.1)
            raise RuntimeError("Playback check deadline exceeded")
        initial = wait(lambda status:status["state"] == "playing" and status["frames"] >= 4 and len(packets) >= 3)
        first_time = packets[0].get("position")
        if not first_time or abs((datetime.fromisoformat(first_time.replace("Z", "+00:00")) - position).total_seconds()) > 3:
            raise RuntimeError("First frame clock does not match the selected time")
        started = time.monotonic(); renewed = started
        if live_path: live_initial = api(live_path)["cameras"][0]
        while time.monotonic() - started < args.continuous_seconds:
            continuous = api(path)
            if continuous["state"] != "playing": raise RuntimeError(continuous["error"] or "Continuous playback stopped")
            if time.monotonic() - renewed >= min(10, session["lease_seconds"] / 3):
                api(path, "PATCH", {}); renewed = time.monotonic()
                if live_path:
                    live_last = api(live_path, "PATCH", {})["cameras"][0]
                    if live_last["state"] != "live": raise RuntimeError("Concurrent live preview stopped")
            time.sleep(.5)
        continuous = api(path)
        advanced = (datetime.fromisoformat(continuous["position"].replace("Z", "+00:00")) -
                    datetime.fromisoformat(initial["position"].replace("Z", "+00:00"))).total_seconds()
        if not args.continuous_seconds - 5 <= advanced <= args.continuous_seconds + 5:
            raise RuntimeError("Recorded clock did not advance at normal speed")
        if live_path:
            live_last = api(live_path)["cameras"][0]
            if live_last["frames"] <= live_initial["frames"]: raise RuntimeError("Concurrent live preview did not advance")
        api(path, "PATCH", {"state":"paused"}); wait(lambda status:status["state"] == "paused", 5)
        time.sleep(.3); paused = api(path); time.sleep(.8); still = api(path)
        if (paused["frames"], paused["position"]) != (still["frames"], still["position"]): raise RuntimeError("Paused playback advanced")
        resumed_request = api(path, "PATCH", {"state":"playing"})
        resumed = wait(lambda status:status["generation"] == resumed_request["generation"] and status["state"] == "playing" and status["frames"] >= 2, 15)
        target = position + timedelta(seconds=20)
        seek_request = api(path, "PATCH", {"position":text(target)})
        seeked = wait(lambda status:status["generation"] == seek_request["generation"] and status["state"] == "playing" and status["frames"] >= 2)
        actual = datetime.fromisoformat(seeked["position"].replace("Z", "+00:00"))
        if not target <= actual <= target + timedelta(seconds=5): raise RuntimeError("Seek frame clock is incorrect")
        api(path, "PATCH", {"state":"paused"}); wait(lambda status:status["state"] == "paused", 5)
        target += timedelta(seconds=10)
        paused_request = api(path, "PATCH", {"position":text(target)})
        paused_seek = wait(lambda status:status["generation"] == paused_request["generation"] and status["state"] == "paused" and status["frames"] >= 1)
        actual = datetime.fromisoformat(paused_seek["position"].replace("Z", "+00:00"))
        if abs((actual - target).total_seconds()) > 3: raise RuntimeError("Paused seek frame clock is incorrect")
        backend = api("/api/status")
        report = dict(camera_id=args.camera, sdk_login_calls=backend["sdk_login_calls"],
            continuous_seconds=args.continuous_seconds, continuous_frames=continuous["frames"],
            recorded_seconds_advanced=advanced,
            initial_frames=initial["frames"], first_frame_time=first_time, selected_time=text(position),
            paused_frames=paused["frames"], resumed_frames=resumed["frames"],
            seek_position=seeked["position"], paused_seek_position=paused_seek["position"],
            received_packets=len(packets), distinct_images=len({packet["sha256"] for packet in packets}),
            frame_width=initial["width"], frame_height=initial["height"], feed_errors=failures)
        if live_path: report.update(live_frames_before=live_initial["frames"], live_frames_after=live_last["frames"],
                                    live_state=live_last["state"])
        if failures or report["distinct_images"] < 2: raise RuntimeError("Historical frames did not move cleanly")
        file = output / "report.json"; file.write_text(json.dumps(report, indent=2)); file.chmod(0o600)
        print(json.dumps(report))
    finally:
        stop.set(); api(path, "DELETE")
        if live_path: api(live_path, "DELETE")
        if media: media.close()


if __name__ == "__main__": main()
