#!/usr/bin/env python3
"""Local live grid with shared native sources and independent viewer leases."""

import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import threading
from urllib.parse import urlsplit

from browser_server import Handler as BaseHandler
from grid_worker import GridWorker
from live_sessions import LiveSessions, SessionError
from nvr_config import load_config
from sdk_adapters import get_sdk_adapter

ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"),
    "/shared/media-player.js": ("shared/media-player.js", "text/javascript"),
    "/shared/api.js": ("shared/api.js", "text/javascript"),
    "/shared/frame-feed.js": ("shared/frame-feed.js", "text/javascript"),
    "/shared/display-preferences.js": ("shared/display-preferences.js", "text/javascript"),
    "/settings/display-settings.js": ("settings/display-settings.js", "text/javascript"),
    "/live/overview.js": ("live/overview.js", "text/javascript"),
    "/live/camera-tile.js": ("live/camera-tile.js", "text/javascript"),
    "/live/tile-expansion.js": ("live/tile-expansion.js", "text/javascript"),
    "/history/recorded-clip.js": ("history/recorded-clip.js", "text/javascript")}


class Handler(BaseHandler):
    def end_headers(self):
        # Blob URLs hold only JPEGs received from this server's shared feed.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        super(BaseHandler, self).end_headers()

    def body(self):
        if self.headers.get("Origin") not in (None, "http://" + self.headers["Host"]):
            raise SessionError("Invalid origin.", 403)
        if self.headers.get_content_type() != "application/json":
            raise SessionError("JSON request required.", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError()
            self.connection.settimeout(5)
            return json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            self.close_connection = True
            raise SessionError("Invalid request body.") from None

    def control(self, operation):
        if not self.trusted():
            return
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/live/sessions/([a-f0-9]{32})", path)
        try:
            if operation == "POST" and path == "/api/live/sessions":
                result = self.server.sessions.create(self.body(), self.headers.get("Idempotency-Key"))
                self.json_response(result, 201)
            elif operation == "PATCH" and match:
                self.json_response(self.server.sessions.patch(match[1], self.body()))
            elif operation == "DELETE" and match:
                if self.headers.get("Origin") not in (None, "http://" + self.headers["Host"]):
                    raise SessionError("Invalid origin.", 403)
                self.server.sessions.delete(match[1])
                self.send_response(204); self.send_header("Content-Length", "0"); self.end_headers()
            else:
                self.send_error(404)
        except SessionError as error:
            self.json_response({"error": {"code": "session_error", "message": str(error), "retryable": False}}, error.status)
        except (OSError, ValueError):
            self.json_response({"error": {"code": "recorder_unavailable", "message": "Recorder unavailable. Check backend configuration; no automatic login retry.", "retryable": False}}, 503)

    def do_POST(self): self.control("POST")
    def do_PATCH(self): self.control("PATCH")
    def do_DELETE(self): self.control("DELETE")

    def do_GET(self):
        if not self.trusted():
            return
        path = urlsplit(self.path).path
        sessions, worker = self.server.sessions, self.server.worker
        try:
            if path == "/api/cameras":
                worker.ensure_ready()
                worker.refresh_availability()
                with worker.condition:
                    self.json_response({"cameras": list(worker.cameras.values())})
            elif path == "/api/status":
                with worker.condition:
                    self.json_response(dict(state=worker.state, error=worker.error,
                        active_live_sources=len(sessions.wanted), viewer_sessions=len(sessions.sessions),
                        device_stream_limit=None, source_limit=sessions.limit,
                        tested_concurrent_streams=worker.tested_capacity, sdk_login_calls=worker.login_calls,
                        sdk_adapter=worker.adapter.sdk_id, recording_available=self.server.recording.is_file(),
                        **self.server.recording_info))
            elif re.fullmatch(r"/api/live/sessions/[a-f0-9]{32}", path):
                self.json_response(sessions.get(path.rsplit("/", 1)[1]))
            elif (match := re.fullmatch(r"/media/live/([a-f0-9]{32})/frames", path)):
                self.frames(match[1])
            elif path == "/recording.mp4":
                self.file(self.server.recording, "video/mp4", ranged=True)
            elif path in ASSETS:
                name, mime = ASSETS[path]; self.file(self.server.web / name, mime)
            else:
                self.send_error(404)
        except SessionError as error:
            self.json_response({"error": {"code": "session_error", "message": str(error), "retryable": False}}, error.status)
        except (OSError, ValueError):
            self.json_response({"error": {"code": "recorder_unavailable", "message": "Recorder discovery failed; no automatic login retry.", "retryable": False}}, 503)

    def frames(self, identifier):
        self.server.sessions.get(identifier)
        with self.server.worker.condition:
            if identifier in self.server.feeds:
                raise SessionError("This viewer already has a frame feed.", 409)
            self.server.feeds.add(identifier)
        self.connection.settimeout(5)
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-camera-frames; version=1")
        self.send_header("Connection", "close")
        self.end_headers()
        seen = {}
        try:
            while not self.server.sessions.closed:
                for packet in self.server.sessions.next_frames(identifier, seen):
                    self.wfile.write(packet)
                self.wfile.flush()
        except (OSError, SessionError):
            pass
        finally:
            with self.server.worker.condition:
                self.server.feeds.discard(identifier)


def create_server(worker, sessions, *, address, web, recording, recording_info=None):
    """Wire the HTTP service without initializing an SDK or choosing a worker."""
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    port = server.server_port
    server.allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
    server.worker, server.sessions, server.feeds = worker, sessions, set()
    server.web, server.recording = Path(web), Path(recording)
    server.recording_info = recording_info or {}
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("invalid HTTP port")
    os.umask(0o077)
    config = load_config("/configuration/nvr.json")
    adapter = get_sdk_adapter(config["sdk_profile"])
    binary = adapter.compile_live_bridge()
    worker = GridWorker(binary, adapter, config, "/output")
    sessions = LiveSessions(worker, config["max_live_sources"], config["lease_seconds"])
    recording_info = {"recording_begin": os.environ.get("CAM_RECORDING_BEGIN"),
        "recording_end": os.environ.get("CAM_RECORDING_END"), "recording_seconds": os.environ.get("CAM_RECORDING_SECONDS")}
    server = create_server(worker, sessions, address=("0.0.0.0", args.port),
        web="/web", recording="/recording/historical-clip.mp4", recording_info=recording_info)
    threading.Thread(target=sessions.run_reaper, daemon=True).start()
    def shutdown(*_): threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    print(f"Live grid listening on port {args.port}; recorder connects when a viewer opens the page.", flush=True)
    try:
        server.serve_forever()
    finally:
        sessions.close(); worker.close(); server.server_close()


if __name__ == "__main__": main()
