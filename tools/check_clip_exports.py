#!/usr/bin/env python3
"""Explicit real-recorder export check through the viewer's public API.

No credentials are read here. Output clips/reports stay under ignored .local.
Only this check's own live and history leases are removed on completion.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", nargs="+", type=int, default=[10])
    parser.add_argument("--with-views", action="store_true")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--from", dest="begin", help="Optional timezone-aware start time for reproducing a specific range")
    args = parser.parse_args()
    if any(not 1 <= value <= 600 for value in args.seconds): parser.error("use 1–600 seconds")
    base = f"http://localhost:{args.port}"
    def api(path, method="GET", body=None):
        request = Request(base+path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={} if body is None else {"Content-Type":"application/json"})
        with urlopen(request, timeout=40) as response:
            return None if response.status == 204 else json.load(response)
    output = ROOT / ".local/export-checks"
    output.mkdir(mode=0o700, parents=True, exist_ok=True); output.chmod(0o700)
    live = playback = None; reports = []
    begin = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)
    if args.begin:
        try:
            begin = datetime.fromisoformat(args.begin.replace("Z", "+00:00"))
            if begin.tzinfo is None: raise ValueError()
            begin = begin.astimezone(timezone.utc).replace(microsecond=0)
        except ValueError: parser.error("--from must include a timezone")
    try:
        if args.with_views:
            live = api("/api/live/sessions", "POST", {"cameras":[{"id":"camera-1", "quality":"overview"}]})
            playback = api("/api/playback/sessions", "POST", dict(camera_id="camera-1", **{"from":begin.isoformat(), "to":(begin+timedelta(minutes=15)).isoformat()}))
        for seconds in args.seconds:
            job = api("/api/exports", "POST", dict(camera_id="camera-1", aspect_ratio="16:9",
                       **{"from":begin.isoformat(), "to":(begin+timedelta(seconds=seconds)).isoformat()}))
            print(f"Export {seconds}s queued: {job['id']}", flush=True)
            deadline = time.monotonic()+seconds*2+90; next_renew = 0; next_report = 0
            while job["state"] in ("queued", "running"):
                if time.monotonic()>deadline: raise RuntimeError("Export check timed out")
                if time.monotonic()>=next_renew:
                    if live: api("/api/live/sessions/"+live["id"], "PATCH", {})
                    if playback: api("/api/playback/sessions/"+playback["id"], "PATCH", {})
                    next_renew = time.monotonic()+5
                if time.monotonic()>=next_report:
                    print(f"{job['state']}: {job.get('progress',0):.0%} {job.get('waiting_reason') or ''}", flush=True)
                    next_report = time.monotonic()+20
                time.sleep(.5); job = api("/api/exports/"+job["id"])
            reports.append(job)
            if job["state"] != "ready": raise RuntimeError(job.get("error") or job["state"])
            with urlopen(base+job["media"]["url"], timeout=15) as response, (output / job["media"]["filename"]).open("wb") as file:
                while chunk := response.read(65536): file.write(chunk)
            status = api("/api/status")
            summary = {key:job.get(key) for key in ("id", "state", "actual_duration_seconds", "frames", "width", "height", "display_aspect_ratio", "position_precision")}
            summary["sdk_login_calls"] = status["sdk_login_calls"]
            if playback:
                view = api("/api/playback/sessions/"+playback["id"])
                summary["viewer_state"], summary["viewer_frames"] = view["state"], view["frames"]
                if view["state"] != "playing": raise RuntimeError("Viewing playback failed during export")
            print(json.dumps(summary), flush=True)
    finally:
        for kind, session in (("live",live),("playback",playback)):
            if session: api(f"/api/{kind}/sessions/{session['id']}", "DELETE")
        (output / "latest.json").write_text(json.dumps(reports, indent=2)+"\n")


if __name__ == "__main__": main()
