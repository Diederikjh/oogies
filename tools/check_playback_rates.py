#!/usr/bin/env python3
"""Bounded real-recorder speed check through the public playback API."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8088")
    parser.add_argument("--camera", default="camera-1")
    parser.add_argument("--seconds-per-rate", type=int, default=10)
    args = parser.parse_args()
    if not 8 <= args.seconds_per_rate <= 30: parser.error("choose 8–30 seconds per rate")
    def api(path, method="GET", body=None):
        request = Request(args.url + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={} if body is None else {"Content-Type":"application/json"})
        with urlopen(request, timeout=20) as response:
            return None if response.status == 204 else json.load(response)
    def clock(text): return datetime.fromisoformat(text.replace("Z", "+00:00"))
    def text(value): return value.isoformat().replace("+00:00", "Z")
    position = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    session = api("/api/playback/sessions", "POST", dict(camera_id=args.camera,
        **{"from":text(position - timedelta(hours=2)), "to":text(position + timedelta(hours=1))}, position=text(position)))
    path = "/api/playback/sessions/" + session["id"]
    try:
        def wait(predicate, seconds=15):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                status = api(path)
                if status["state"] == "error" or status["rate_error"]:
                    raise RuntimeError(status["error"] or status["rate_error"])
                if predicate(status): return status
                time.sleep(.1)
            raise RuntimeError("Playback rate check timed out")
        wait(lambda s:s["state"] == "playing" and s["frames"] >= 5)
        samples = []
        for rate in (.5, 1, 2, 4, 1):
            api(path, "PATCH", {"rate":rate})
            wait(lambda s:s["rate"] == rate and s["requested_rate"] == rate)
            # Let the decoder's displayed clock settle after an in-place change.
            time.sleep(1)
            begin = api(path); started = time.monotonic()
            api(path, "PATCH", {})
            while time.monotonic() - started < args.seconds_per_rate:
                status = api(path)
                if status["state"] != "playing" or status["rate_error"]:
                    raise RuntimeError(status["error"] or status["rate_error"] or "Playback stopped")
                time.sleep(.25)
            end = api(path); elapsed = time.monotonic() - started
            advanced = (clock(end["position"]) - clock(begin["position"])).total_seconds()
            if abs(advanced - elapsed * rate) > max(2, elapsed * rate * .2):
                raise RuntimeError(f"Recorded clock did not match requested {rate}x playback: {advanced}s in {elapsed:.1f}s")
            if end["frames"] <= begin["frames"] or end["generation"] != session["generation"]:
                raise RuntimeError("Speed change stalled or reopened playback")
            samples.append(dict(rate=rate, elapsed_seconds=round(elapsed, 2), recorded_seconds=advanced,
                                frames=end["frames"] - begin["frames"], generation=end["generation"]))
        api(path, "PATCH", {"state":"paused"}); paused = wait(lambda s:s["state"] == "paused")
        api(path, "PATCH", {"rate":4}); time.sleep(.5)
        held = api(path)
        if held["state"] != "paused" or (held["position"], held["frames"]) != (paused["position"], paused["frames"]):
            raise RuntimeError("Changing paused speed advanced the recording")
        api(path, "PATCH", {"state":"playing"})
        wait(lambda s:s["state"] == "playing" and s["rate"] == 4 and s["frames"] >= 3)
        api(path, "PATCH", {"position":text(position + timedelta(minutes=5))})
        wait(lambda s:s["state"] == "playing" and s["rate"] == 4 and s["frames"] >= 3)
        report = dict(camera_id=args.camera, rates=samples, paused_rate_preserved=True,
                      resume_seek_rate_preserved=True, sdk_login_calls=api("/api/status")["sdk_login_calls"])
        output = Path(__file__).resolve().parents[1] / ".local/browser-viewer" / ("rates-check-" + uuid.uuid4().hex)
        output.mkdir(mode=0o700, parents=True)
        file = output / "report.json"; file.write_text(json.dumps(report, indent=2) + "\n"); file.chmod(0o600)
        print(json.dumps(report))
    finally:
        api(path, "DELETE")


if __name__ == "__main__": main()
