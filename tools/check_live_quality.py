#!/usr/bin/env python3
"""Bounded, explicit real-recorder quality check; run in the SDK Docker runtime.

One login, one high source maximum, no automatic retries. Mount private config
at /configuration/nvr.json and credentials at /credentials/nvr.json. Output is
private footage/diagnostics and must stay under .local on the host.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time

from grid_worker import GridWorker
from live_sessions import LiveSessions
from playback_sessions import PlaybackSessions
from nvr_config import load_config
from sdk_adapters import get_sdk_adapter


def counters():
    cpu = dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())
    traffic = [line.split(":",1)[1].split() for line in Path("/proc/net/dev").read_text().splitlines()
               if ":" in line and line.split(":",1)[0].strip() != "lo"]
    return dict(at=time.monotonic(), cpu_us=int(cpu["usage_usec"]),
        memory_bytes=int(Path("/sys/fs/cgroup/memory.current").read_text()),
        pids=int(Path("/sys/fs/cgroup/pids.current").read_text()),
        rx=sum(int(row[0]) for row in traffic), tx=sum(int(row[8]) for row in traffic))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=int,default=8)
    parser.add_argument("--output",default="/output/quality-check")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 20: parser.error("sample duration must be 5-20 seconds")
    os.umask(0o077)
    output = Path(args.output); output.mkdir(parents=True,exist_ok=True,mode=0o700)
    config = load_config("/configuration/nvr.json")
    if config["max_high_quality_sources"] < 1: parser.error("high quality is disabled by owner configuration")
    adapter = get_sdk_adapter(config["sdk_profile"])
    worker = GridWorker(adapter.compile_live_bridge(),adapter,config,output)
    live = LiveSessions(worker,limit=config["max_live_sources"],high_limit=1)
    playback = PlaybackSessions(worker,live.budget)
    report = dict(passed=False, samples=[])
    deadline = time.monotonic()+180

    def wait(predicate, seconds=20):
        until = min(deadline,time.monotonic()+seconds)
        while time.monotonic()<until:
            live.maintain()
            if worker.state == "error": raise RuntimeError(worker.error)
            if predicate(): return
            time.sleep(.1)
        raise RuntimeError("Quality verification deadline exceeded")

    def selection(cameras, high=None):
        return {"cameras":[dict(id=camera,quality="high" if camera==high else "overview") for camera in cameras]}

    def ready(view, high=None):
        status = live.get(view["id"])
        for camera in status["cameras"]:
            if camera["state"] in ("error","stale"): raise RuntimeError(camera["error"] or "Live source stalled")
            if camera["requested_quality"]=="high" and camera["upgrade_state"] not in ("pending","active"):
                raise RuntimeError("High-quality request did not start: "+camera["upgrade_state"])
        return all(camera["state"]=="live" and camera["frames"]>=3 and
                   (camera["id"]!=high or camera["quality"]=="high") for camera in status["cameras"])

    def sample(name):
        before = counters(); peak = before["memory_bytes"]; hashes = {}
        start_frames = {key:source["received"] for key,source in worker.sources.items() if key in live.wanted}
        while time.monotonic()-before["at"]<args.seconds:
            if time.monotonic()>deadline: raise RuntimeError("Overall verification deadline exceeded")
            for identifier in list(live.sessions): live.patch(identifier,{})
            live.maintain()
            for key in live.wanted:
                source = worker.sources[key]
                if source["state"] in ("error","stale"): raise RuntimeError("A measured live source stopped delivering frames")
                if source.get("frame"):
                    import hashlib
                    hashes.setdefault(key,set()).add(hashlib.sha256(source["frame"]).hexdigest())
            current = counters(); peak = max(peak,current["memory_bytes"])
            if peak>1536*1024**2 or current["pids"]>450: raise RuntimeError("Verification resource headroom exhausted")
            time.sleep(.5)
        after = counters(); elapsed = after["at"]-before["at"]
        if any(worker.sources[key]["received"]<=count or len(hashes.get(key,()))<2 for key,count in start_frames.items()):
            raise RuntimeError("Moving live pictures were not sustained")
        report["samples"].append(dict(stage=name,seconds=round(elapsed,2),
            cpu_percent=round((after["cpu_us"]-before["cpu_us"])/elapsed/10000,1),peak_memory_bytes=peak,
            pids=after["pids"],network_rx_bytes_per_second=round((after["rx"]-before["rx"])/elapsed),
            network_tx_bytes_per_second=round((after["tx"]-before["tx"])/elapsed),**live.quality_status()))
        print("Verified "+name,flush=True)

    try:
        worker.ensure_ready()
        cameras = [key for key,camera in worker.cameras.items() if camera["online"] is not False]
        if not cameras: raise RuntimeError("No online inputs discovered")
        primary = cameras[0]; report["online_cameras"] = len(cameras)
        view = live.create(selection([primary])); wait(lambda:ready(view)); sample("one_overview")
        overview = live.get(view["id"])["cameras"][0]
        live.patch(view["id"],selection([primary],primary)); wait(lambda:ready(view,primary)); sample("one_overview_plus_high")
        high = live.get(view["id"])["cameras"][0]
        report["resolution"] = dict(overview=[overview["width"],overview["height"]],high=[high["width"],high["height"]])
        other = live.create(selection([primary],primary))
        assert live.quality_status()["sources_by_quality"]==dict(overview=1,high=1)
        live.patch(view["id"],selection([primary])); assert ready(other,primary)
        live.delete(other["id"]); wait(lambda:live.used_sources()==1)
        report["sharing_and_independent_release"] = True
        grid = cameras[:live.limit]
        live.patch(view["id"],selection(grid)); wait(lambda:ready(view)); sample("full_overview")
        live.patch(view["id"],selection(grid,primary))
        if len(grid)+1<=live.limit:
            wait(lambda:ready(view,primary)); sample("full_overview_plus_high")
        else:
            assert live.get(view["id"])["cameras"][0]["upgrade_state"]=="capacity_limited"
            report["full_grid_high_capacity_limited"] = True
        if live.limit>=3:
            reduced = cameras[:max(1,live.limit-2)]
            live.patch(view["id"],selection(reduced,primary))
            # Stops are asynchronous. If denied while closing, retry explicitly
            # only after native acknowledgements free the required slot.
            wait(lambda:not any(s["state"]=="stopping" for s in worker.sources.values()))
            live.patch(view["id"],selection(reduced,primary)); wait(lambda:ready(view,primary))
            position = (datetime.now(timezone.utc)-timedelta(hours=1)).replace(microsecond=0)
            historical = playback.create(dict(camera_id=primary, **{"from":position.isoformat(),"to":(position+timedelta(minutes=1)).isoformat()}))
            wait(lambda:playback.get(historical["id"])["state"]=="playing" and playback.get(historical["id"])["frames"]>=3)
            before = playback.get(historical["id"])["frames"]
            sample("overview_plus_high_and_history")
            assert playback.get(historical["id"])["frames"]>before
            playback.delete(historical["id"])
            report["history_coexistence"] = True
        live.close(); wait(lambda:live.used_sources()==0)
        report.update(passed=True,sdk_login_calls=worker.login_calls,cleanup_source_slots=live.used_sources())
        assert worker.login_calls==1
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        playback.close(); live.close(); worker.close()
        (output/"quality-check.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(dict(passed=report["passed"],resolution=report["resolution"],sdk_login_calls=worker.login_calls)))


if __name__=="__main__": main()
