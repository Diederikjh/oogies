#!/usr/bin/env python3
"""Focused TCP connect scan of the home recorder; no protocol or login data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import errno
import json
from pathlib import Path
import socket
import time

HOST = "192.0.2.10"
PORTS = (80, 443, 554, 8000, 8001, 8080, 8443, 8554, 10554)
ROOT = Path(__file__).resolve().parents[1]


def scan(port):
    start = time.monotonic()
    try:
        with socket.create_connection((HOST, port), timeout=3):
            state = "open"
    except ConnectionRefusedError:
        state = "closed (connection refused)"
    except TimeoutError:
        state = "no response (timeout)"
    except OSError as error:
        state = "network unreachable" if error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH) else f"error: {type(error).__name__}"
    return {"port": port, "state": state, "elapsed_seconds": round(time.monotonic() - start, 3)}


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(scan, PORTS))
    report = {
        "host": HOST, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "focused TCP connect scan", "login_attempts": 0, "ports": results,
    }
    output = json.dumps(report, indent=2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = ROOT / f".local/port-scan-{stamp}.json"
    target.write_text(output + "\n")
    target.chmod(0o600)
    print(output)


if __name__ == "__main__":
    main()
