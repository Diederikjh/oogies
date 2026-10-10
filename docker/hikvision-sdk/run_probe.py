#!/usr/bin/env python3
"""Compile against vendor headers in Docker; execute a bounded SDK diagnostic."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import urllib.parse
import uuid

from sdk_adapters import get_sdk_adapter

ERRORS = {
    0: "success", 1: "username/password rejected", 2: "operation not authorized",
    3: "SDK not initialized", 6: "SDK/device version mismatch", 7: "connection failed",
    8: "network send failed", 9: "network receive failed", 10: "network receive timeout",
    11: "unsupported request data or invalid received data",
    13: "operation not authorized", 17: "parameter error",
    23: "function not supported", 33: "no recording for requested playback", 34: "capture file creation failed",
    41: "resource allocation failed",
    55: "source IP mismatch", 56: "source MAC mismatch",
    152: "username does not exist", 153: "username locked",
    155: "login version too low", 156: "crypto library load failed",
    157: "TLS library load failed", 1113: "IP address banned",
}


def sanitize(text, credentials):
    for key in ("username", "password", "verification_code"):
        value = credentials.get(key, "")
        if value:
            text = text.replace(value, "[redacted]")
            text = text.replace(urllib.parse.quote(value, safe=""), "[redacted]")
    return text


def compile_probe(adapter=None):
    """Build through the selected Python adapter, preserving diagnostic output."""
    try:
        return (adapter if adapter is not None else get_sdk_adapter()).compile_bridge()
    except subprocess.CalledProcessError as error:
        print(json.dumps({"stage": "compile", "login_calls": 0,
                          "diagnostics": (error.stderr or "")[-8000:]}, indent=2))
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "probe"))
    parser.add_argument("--capture-seconds", type=int, default=0)
    parser.add_argument("--sdk-log", action="store_true", help="Save private SDK debug logs")
    parser.add_argument("--decrypt", action="store_true")
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 60:
        parser.error("capture must be between 0 and 60 seconds")
    if args.mode == "probe" and args.decrypt and not args.capture_seconds:
        parser.error("decryption requires a positive capture duration")
    if args.historical and (not args.decrypt or (args.mode == "probe" and not 1 <= args.capture_seconds <= 10)):
        parser.error("historical extraction requires --decrypt and 1–10 capture seconds")
    if args.skip_search and not args.historical:
        parser.error("--skip-search requires --historical")
    adapter = get_sdk_adapter()
    try:
        binary = compile_probe(adapter)
    except ValueError as error:
        parser.error(str(error))
    credentials = {}
    if args.mode == "probe":
        try:
            credentials = adapter.load_credentials("/credentials/nvr.json")
        except ValueError as error:
            parser.error(str(error))
    os.umask(0o077)
    log_dir = None
    capture_dir = None
    if args.mode == "probe" and args.capture_seconds:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        capture_dir = Path("/output") / f"sdk-capture-{stamp}-{uuid.uuid4().hex[:8]}"
        capture_dir.mkdir(mode=0o700)
    if args.sdk_log:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_dir = Path("/output") / f"sdk-{args.mode}-{stamp}-{uuid.uuid4().hex[:8]}-logs"
        log_dir.mkdir(mode=0o700)
    try:
        invocation = adapter.invocation(binary, credentials=credentials,
            host="192.0.2.10", port=8000, seconds=args.capture_seconds,
            check=args.mode == "check", decrypt=args.decrypt,
            historical=args.historical, skip_search=args.skip_search,
            capture_dir=capture_dir, log_dir=log_dir)
    except ValueError as error:
        parser.error(str(error))
    try:
        process = subprocess.run(invocation.command, input=invocation.stdin, capture_output=True,
                                 text=True, env=invocation.env, cwd=invocation.cwd,
                                 timeout=(70 if args.historical else 25) + args.capture_seconds)
        reports = [line.removeprefix("CAM_SDK_REPORT ") for line in process.stdout.splitlines()
                   if line.startswith("CAM_SDK_REPORT ")]
        if reports:
            report = json.loads(reports[-1])
            if "sdk_build" in report:
                version = report["sdk_build"]
                report["sdk_version"] = ".".join(str((version >> shift) & 255) for shift in (24, 16, 8, 0))
            if "sdk_error" in report:
                report["sdk_error_meaning"] = ERRORS.get(report["sdk_error"], "see vendor SDK error reference")
            if "historical_error" in report:
                report["historical_error_meaning"] = ERRORS.get(report["historical_error"], "see vendor SDK error reference")
        else:
            report = {"stage": "native runtime", "returncode": process.returncode,
                      "diagnostics": sanitize(process.stderr + process.stdout, credentials)[-6000:]}
        report["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        report.setdefault("verification_code_used", False)
        if capture_dir:
            report["capture_directory"] = capture_dir.name
        if args.mode == "probe" and args.historical and process.returncode == 0 and report.get("clip_frames", 0) > 0:
            dimensions = f'{report["frame_width"]}x{report["frame_height"]}'
            clip = capture_dir / "historical-clip.mp4"
            encoded = subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "2",
                "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", dimensions,
                "-framerate", str(report["clip_fps"]), "-i", str(capture_dir / "clip.yv12"),
                "-vf", "swapuv", "-filter_threads", "1", "-an", "-c:v", "libx264",
                "-threads", "2", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(clip)], capture_output=True, text=True, timeout=90)
            report["mp4_encoded"] = encoded.returncode == 0
            if encoded.returncode:
                report["encode_diagnostics"] = sanitize(encoded.stderr, credentials)[-2000:]
            else:
                clip.chmod(0o600)
                report["clip_bytes"] = clip.stat().st_size
                report["clip_file"] = clip.name
                report["clip_duration_seconds"] = report["clip_frames"] / report["clip_fps"]
        if args.mode == "probe":
            report["password_first_16"] = getattr(adapter, "login_password_max_chars", None) == 16
        report["sdk_adapter"] = adapter.sdk_id
        if log_dir:
            files = [p for p in log_dir.rglob("*") if p.is_file()]
            for path in files:
                path.chmod(0o600)
            report["sdk_log_directory"] = log_dir.name
            report["sdk_log_file_count"] = len(files)
            report["sdk_log_bytes"] = sum(p.stat().st_size for p in files)
        output = json.dumps(report, indent=2)
        target = Path("/output") / ("sdk-" + args.mode + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
        target.write_text(output + "\n")
        target.chmod(0o600)
        print(output, flush=True)
        if process.returncode:
            raise SystemExit(process.returncode)
        if report.get("mp4_encoded") is False:
            raise SystemExit(2)
    except subprocess.TimeoutExpired:
        print(json.dumps({"stage": "native runtime", "error": "overall timeout; no retry performed"}), flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
