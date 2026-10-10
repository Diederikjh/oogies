#!/usr/bin/env python3
"""Local browser prototype: one shared SDK session and a latest-frame MJPEG feed."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit
import uuid

from sdk_adapters import get_sdk_adapter
from run_probe import compile_probe


def byte_range(header, size):
    """Resolve a single HTTP byte range; reject malformed/unsatisfiable ranges."""
    if header is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()):
        raise ValueError("invalid range")
    first, last = match.groups()
    if not first:
        count = int(last)
        if count <= 0:
            raise ValueError("invalid suffix")
        return max(0, size - count), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError("unsatisfiable range")
    return start, end


class Camera:
    def __init__(self, binary, output, seconds=600, spawn=subprocess.Popen, adapter=None):
        self.binary, self.output, self.seconds, self.spawn = binary, Path(output), seconds, spawn
        self.adapter = adapter if adapter is not None else get_sdk_adapter()
        self.condition = threading.Condition()
        self.process = None
        self.monitor = None
        self.state = "stopped"
        self.error = None
        self.session = None
        self.frame = None
        self.sequence = 0
        self.width = self.height = 0
        self.last_frame = 0
        self.started = 0
        self.received = 0
        self.viewers = 0

    def status(self):
        with self.condition:
            age = time.monotonic() - self.last_frame if self.frame else None
            state = "stalled" if self.state == "live" and age > 5 else self.state
            return {"state": state, "error": self.error, "session": self.session,
                    "frames": self.received, "width": self.width, "height": self.height,
                    "frame_age_seconds": round(age, 2) if age is not None else None,
                    "viewers": self.viewers, "session_seconds": self.seconds}

    def start(self):
        with self.condition:
            # Includes a process still shutting down: duplicate Start never logs in again.
            if self.process is not None:
                return self.status()
            credentials = self.adapter.load_credentials("/credentials/nvr.json")
            session = uuid.uuid4().hex
            directory = self.output / ("browser-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + session[:8])
            invocation = self.adapter.invocation(self.binary, credentials=credentials,
                host="192.0.2.10", port=8000, seconds=self.seconds,
                decrypt=True, browser_frames=True, capture_dir=directory)
            directory.mkdir(mode=0o700, parents=True)
            stdout = (directory / "native.stdout.log").open("wb")
            stderr = (directory / "native.stderr.log").open("wb")
            try:
                process = self.spawn(invocation.command,
                                     stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                     cwd=invocation.cwd, env=invocation.env)
                process.stdin.write(invocation.stdin.encode())
                process.stdin.close()
            except Exception:
                if "process" in locals():
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                stdout.close()
                stderr.close()
                raise
            self.process, self.session = process, session
            self.state, self.error, self.frame = "connecting", None, None
            self.sequence = self.received = 0
            self.width = self.height = 0
            self.started = time.monotonic()
            self.monitor = threading.Thread(target=self._watch, args=(process, directory, stdout, stderr), daemon=True)
            self.monitor.start()
            self.condition.notify_all()
            return self.status()

    def _watch(self, process, directory, stdout, stderr):
        timed_out = False
        try:
            while process.poll() is None:
                try:
                    metadata = json.loads((directory / "frame.json").read_text())
                    if metadata["sequence"] != self.sequence:
                        frame = (directory / "frame.jpg").read_bytes()
                        if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
                            raise ValueError("incomplete JPEG")
                        with self.condition:
                            self.frame = frame
                            self.sequence = metadata["sequence"]
                            self.width, self.height = metadata["width"], metadata["height"]
                            self.received += 1
                            self.last_frame = time.monotonic()
                            if self.state != "stopping":
                                self.state = "live"
                            self.condition.notify_all()
                except (OSError, ValueError, KeyError):
                    pass
                if not self.frame and time.monotonic() - self.started > 15 and self.state != "stopping":
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    break
                time.sleep(0.05)
            process.wait()
        finally:
            stdout.close()
            stderr.close()
            report = {}
            for line in (directory / "native.stdout.log").read_text(errors="replace").splitlines():
                if line.startswith("CAM_SDK_REPORT "):
                    try:
                        report = json.loads(line.removeprefix("CAM_SDK_REPORT "))
                    except ValueError:
                        pass
            # Reports contain counters and SDK codes, never credentials or raw logs.
            (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            with self.condition:
                stopped = self.state == "stopping"
                self.process = None
                if stopped:
                    self.state = "stopped"
                elif timed_out:
                    self.state, self.error = "error", "No video arrived within 15 seconds."
                elif process.returncode:
                    code = report.get("sdk_error") or report.get("decoder_error") or report.get("preview_error")
                    self.state, self.error = "error", f"Camera session failed (code {code if code is not None else process.returncode})."
                else:
                    self.state = "ended"
                self.condition.notify_all()

    def stop(self):
        with self.condition:
            process, monitor = self.process, self.monitor
            if process is None:
                self.state, self.error = "stopped", None
                return self.status()
            self.state = "stopping"
            process.terminate()
            self.condition.notify_all()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        if monitor:
            monitor.join(timeout=3)
        return self.status()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        super().end_headers()

    def trusted(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self.send_error(403)
            return False
        return True

    def json_response(self, value, code=200):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.trusted():
            return
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers["Host"]:
            self.send_error(403)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1024:
                raise ValueError()
            body = self.rfile.read(length)
            if json.loads(body) != {}:
                raise ValueError()
        except (ValueError, OSError):
            self.send_error(400)
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/start":
                self.json_response(self.server.camera.start())
            elif path == "/api/stop":
                self.json_response(self.server.camera.stop())
            else:
                self.send_error(404)
        except (OSError, ValueError):
            with self.server.camera.condition:
                self.server.camera.state = "error"
                self.server.camera.error = "Could not start the camera. Check the private backend configuration."
            self.json_response(self.server.camera.status(), 503)

    def do_GET(self):
        if not self.trusted():
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            self.json_response(dict(self.server.camera.status(), recording_available=self.server.recording.is_file(),
                                    **self.server.recording_info))
        elif path == "/stream.mjpeg":
            self.stream()
        elif path == "/recording.mp4":
            self.file(self.server.recording, "video/mp4", ranged=True)
        elif path in ("/", "/app.js", "/style.css", "/shared/media-player.js"):
            name, content_type = {"/": ("index.html", "text/html; charset=utf-8"),
                                  "/app.js": ("app.js", "text/javascript"),
                                  "/style.css": ("style.css", "text/css"),
                                  "/shared/media-player.js": ("shared/media-player.js", "text/javascript")}[path]
            self.file(self.server.web / name, content_type)
        else:
            self.send_error(404)

    def file(self, path, content_type, ranged=False):
        if not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        header = self.headers.get("Range") if ranged else None
        try:
            start, end = byte_range(header, size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(206 if header else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1))
        if ranged:
            self.send_header("Accept-Ranges", "bytes")
        if header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as file:
                file.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = file.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def stream(self):
        camera = self.server.camera
        with camera.condition:
            session = camera.session
            if camera.process is None:
                self.json_response({"error": "Start the camera first."}, 409)
                return
            if camera.viewers >= 8:
                self.json_response({"error": "Viewer limit reached."}, 503)
                return
            camera.viewers += 1
        self.connection.settimeout(5)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Connection", "close")
            self.end_headers()
            sequence = 0
            while True:
                with camera.condition:
                    camera.condition.wait_for(lambda: camera.sequence != sequence or camera.process is None
                                              or camera.session != session or camera.state == "stopping", timeout=5)
                    if camera.process is None or camera.session != session or camera.state == "stopping":
                        break
                    frame, current = camera.frame, camera.sequence
                if frame is None or current == sequence:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode()
                                 + b"\r\n\r\n" + frame + b"\r\n")
                self.wfile.flush()
                sequence = current
            self.wfile.write(b"--frame--\r\n")
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            with camera.condition:
                camera.viewers -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--session-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.session_seconds <= 900 or not 1024 <= args.port <= 65535:
        parser.error("session must be 1–900 seconds and port 1024–65535")
    os.umask(0o077)
    adapter = get_sdk_adapter()
    binary = compile_probe(adapter)  # No initialization/login or device request at startup.
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True
    server.allowed_hosts = {f"localhost:{args.port}", f"127.0.0.1:{args.port}"}
    server.camera = Camera(binary, "/output", args.session_seconds, adapter=adapter)
    server.web = Path("/web")
    server.recording = Path("/recording/historical-clip.mp4")
    server.recording_info = {"recording_begin": os.environ.get("CAM_RECORDING_BEGIN"),
                             "recording_end": os.environ.get("CAM_RECORDING_END"),
                             "recording_seconds": os.environ.get("CAM_RECORDING_SECONDS")}
    def shutdown(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"Browser viewer listening on port {args.port}; camera starts on demand.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.camera.stop()
        server.server_close()


if __name__ == "__main__":
    main()
