#!/usr/bin/env python3
"""Explicit bounded check of the running viewer, with Docker resource monitoring.

Uses the service's existing SDK login. Requires an idle localhost:8088 viewer,
one high-quality slot and room for the reported online grid plus History.
No SDK or credentials are mounted into the diagnostic browser container.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "cam-browser-viewer"


def status():
    with urlopen("http://localhost:8088/api/status",timeout=5) as response:
        return json.load(response)


def resources():
    result=subprocess.run(["docker","stats","--no-stream","--format","{{json .}}",SERVICE],
        capture_output=True,text=True,check=True,timeout=10)
    sample=json.loads(result.stdout)
    return dict(cpu_percent=float(sample["CPUPerc"].rstrip("%")),
        memory_percent=float(sample["MemPerc"].rstrip("%")),memory=sample["MemUsage"],
        pids=int(sample["PIDs"]),network=sample["NetIO"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=int,default=300)
    args=parser.parse_args()
    if not 180<=args.seconds<=900: parser.error("duration must be 180-900 seconds")
    initial=status()
    if any(initial[key] for key in ("viewer_sessions","playback_sessions","active_exports","occupied_source_slots","active_media_feeds")):
        parser.error("viewer must be idle; close camera views and wait for cleanup first")
    if initial["high_quality_limit"]!=1: parser.error("keep the high-quality cap at one")
    if initial["state"]!="ready": parser.error("start and verify the service login before this check; no login retries")
    os.umask(0o077)
    output=ROOT/".local/live-reliability-check"/time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True,mode=0o700)
    name="oogies-reliability-"+uuid.uuid4().hex[:8]
    command=["docker","run","--rm","--init","--name",name,"--network","container:"+SERVICE,
        "--read-only","--user",f"{os.getuid()}:{os.getgid()}","--cap-drop=ALL","--security-opt=no-new-privileges",
        "--cpus=2","--memory=2g","--memory-swap=2g","--pids-limit=512",
        "--tmpfs","/tmp:rw,exec,nosuid,size=256m","--env","XDG_CONFIG_HOME=/tmp/config",
        "--env","XDG_CACHE_HOME=/tmp/cache","--mount",f"type=bind,source={ROOT}/tools,target=/support,readonly",
        "--mount",f"type=bind,source={output},target=/output",
        "cam-hik-sdk-browser:local","python3","/support/check_live_grid.py","--output","/output",
        "--sustain-seconds",str(args.seconds)]
    report=dict(passed=False,requested_seconds=args.seconds,resource_samples=[],initial_resources=resources())
    started=time.monotonic(); deadline=started+args.seconds+240
    process=None; hot_since=None
    try:
        with (output/"browser.log").open("w") as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            while process.poll() is None:
                if time.monotonic()>deadline: raise RuntimeError("Overall check deadline exceeded")
                sample=resources()
                cpu=sample["cpu_percent"]; memory=sample["memory_percent"]
                current=status()
                report["resource_samples"].append(dict(seconds=round(time.monotonic()-started,2),
                    **sample,occupied_source_slots=current["occupied_source_slots"]))
                (output/"resource-check.json").write_text(json.dumps(report,indent=2)+"\n")
                if memory>75 or sample["pids"]>450: raise RuntimeError("Service resource headroom exhausted")
                hot_since=(hot_since or time.monotonic()) if cpu>180 else None
                if hot_since and time.monotonic()-hot_since>30: raise RuntimeError("Sustained service CPU pressure")
                if current["sdk_login_calls"]!=initial["sdk_login_calls"]: raise RuntimeError("Unexpected SDK login")
                if current["sources_by_quality"]["high"]>1: raise RuntimeError("Unexpected extra main stream")
                if current["occupied_source_slots"]>current["source_limit"]: raise RuntimeError("Source budget exceeded")
                time.sleep(5)
            if process.returncode: raise RuntimeError("Browser check failed; inspect private browser.log")
        final=status()
        if any(final[key] for key in ("viewer_sessions","playback_sessions","active_exports","occupied_source_slots","active_media_feeds")):
            raise RuntimeError("Resources did not return to idle")
        browser=json.loads((output/"grid-check.json").read_text())
        report.update(passed=True,final_status=final,final_resources=resources(),reliability=browser["reliability"],
            total_seconds=round(time.monotonic()-started,2))
    except BaseException as error:
        report["error"]=str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            try:
                subprocess.run(["docker","stop","--timeout","15",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=25)
            except subprocess.TimeoutExpired:
                report["cleanup_error"]="Diagnostic container stop timed out; leases remain the cleanup fallback"
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        try: report["cleanup_status"]=status()
        except OSError: report["cleanup_status_error"]="Service status unavailable after browser cleanup"
        (output/"resource-check.json").write_text(json.dumps(report,indent=2)+"\n")
        print(f"Private evidence: {output.relative_to(ROOT)}",flush=True)
    samples=report["resource_samples"]
    print(json.dumps(dict(passed=True,measured_seconds=report["reliability"]["measured_seconds"],
        mean_sampled_cpu_percent=round(sum(s["cpu_percent"] for s in samples)/len(samples),1),
        peak_memory_percent=max(s["memory_percent"] for s in samples),peak_pids=max(s["pids"] for s in samples),
        final_source_slots=report["final_status"]["occupied_source_slots"],sdk_login_calls=initial["sdk_login_calls"])))


if __name__=="__main__": main()
