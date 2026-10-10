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

from credentials import load_credentials

ERRORS = {
    0: "success", 1: "username/password rejected", 2: "operation not authorized",
    3: "SDK not initialized", 6: "SDK/device version mismatch", 7: "connection failed",
    8: "network send failed", 9: "network receive failed", 10: "network receive timeout",
    13: "operation not authorized", 17: "parameter error",
    23: "function not supported", 41: "resource allocation failed",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "probe"))
    parser.add_argument("--capture-seconds", type=int, default=0)
    parser.add_argument("--sdk-log", action="store_true", help="Save private SDK debug logs")
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 60:
        parser.error("capture must be between 0 and 60 seconds")
    headers = list(Path("/sdk").rglob("HCNetSDK.h"))
    headers.sort(key=lambda path: ("incEn" not in str(path), str(path)))
    if not headers:
        parser.error("HCNetSDK.h not found in mounted SDK")
    libraries = list(Path("/sdk").rglob("libhcnetsdk.so"))
    if not libraries:
        parser.error("libhcnetsdk.so not found in mounted SDK")
    library_dir = libraries[0].parent
    if library_dir != Path("/sdk/lib"):
        parser.error("SDK must be mounted with its lib directory at /sdk/lib")
    command = ["g++", "-std=c++17", "-D_LINUX_", "-I", str(headers[0].parent),
               "/probe/probe.cpp", "-L/sdk/lib", "-Wl,-rpath,/sdk/lib", "-lhcnetsdk",
               "-lpthread", "-ldl", "-o", "/tmp/cam-sdk-probe"]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if compiled.returncode:
        print(json.dumps({"stage": "compile", "login_calls": 0,
                          "diagnostics": compiled.stderr[-8000:]}, indent=2))
        raise SystemExit(2)
    credentials = {}
    stdin = ""
    if args.mode == "probe":
        try:
            credentials = load_credentials("/credentials/nvr.json")
        except ValueError as error:
            parser.error(str(error))
        stdin = "\n".join(("192.0.2.10", "8000", credentials["username"],
                           credentials["password"], str(args.capture_seconds))) + "\n"
    env = dict(os.environ, LD_LIBRARY_PATH="/sdk/lib:/sdk/lib/HCNetSDKCom")
    os.umask(0o077)
    log_dir = None
    if args.sdk_log:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_dir = Path("/output") / f"sdk-{args.mode}-{stamp}-{uuid.uuid4().hex[:8]}-logs"
        log_dir.mkdir(mode=0o700)
        env["CAM_SDK_LOG_DIR"] = str(log_dir) + "/"
    native_command = ["/tmp/cam-sdk-probe"] + (["check"] if args.mode == "check" else [])
    try:
        process = subprocess.run(native_command, input=stdin, capture_output=True,
                                 text=True, env=env, cwd="/sdk/lib",
                                 timeout=25 + args.capture_seconds)
        reports = [line.removeprefix("CAM_SDK_REPORT ") for line in process.stdout.splitlines()
                   if line.startswith("CAM_SDK_REPORT ")]
        if reports:
            report = json.loads(reports[-1])
            if "sdk_build" in report:
                version = report["sdk_build"]
                report["sdk_version"] = ".".join(str((version >> shift) & 255) for shift in (24, 16, 8, 0))
            if "sdk_error" in report:
                report["sdk_error_meaning"] = ERRORS.get(report["sdk_error"], "see vendor SDK error reference")
        else:
            report = {"stage": "native runtime", "returncode": process.returncode,
                      "diagnostics": sanitize(process.stderr + process.stdout, credentials)[-6000:]}
        report["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        report["verification_code_used"] = False
        if args.mode == "probe":
            report["password_first_16"] = True
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
    except subprocess.TimeoutExpired:
        print(json.dumps({"stage": "native runtime", "error": "overall timeout; no retry performed"}), flush=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
