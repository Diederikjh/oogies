#!/usr/bin/env python3
"""Local live grid with shared native sources and independent viewer leases."""

import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import threading
import tempfile
from urllib.parse import parse_qs, urlsplit

from browser_server import Handler as BaseHandler, byte_range
from export_jobs import ExportJobs
from grid_worker import GridWorker
from live_sessions import LiveSessions
from service_errors import SessionError
from history_timeline import HistoryTimeline
from playback_sessions import PlaybackSessions
from nvr_config import load_config
from sdk_adapters import get_sdk_adapter
from stream_budget import StreamBudget
from maintenance import run_maintenance

ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"),
    "/shared/media-player.js": ("shared/media-player.js", "text/javascript"),
    "/shared/api.js": ("shared/api.js", "text/javascript"),
    "/shared/frame-feed.js": ("shared/frame-feed.js", "text/javascript"),
    "/shared/display-preferences.js": ("shared/display-preferences.js", "text/javascript"),
    "/settings/display-settings.js": ("settings/display-settings.js", "text/javascript"),
    "/live/overview.js": ("live/overview.js", "text/javascript"),
    "/live/camera-tile.js": ("live/camera-tile.js", "text/javascript"),
    "/live/live-quality.js": ("live/live-quality.js", "text/javascript"),
    "/live/tile-expansion.js": ("live/tile-expansion.js", "text/javascript"),
    "/history/history-view.js": ("history/history-view.js", "text/javascript"),
    "/history/date-time-navigation.js": ("history/date-time-navigation.js", "text/javascript"),
    "/history/frame-download.js": ("history/frame-download.js", "text/javascript"),
    "/history/clip-selection.js": ("history/clip-selection.js", "text/javascript"),
    "/history/clip-model.js": ("history/clip-model.js", "text/javascript"),
    "/history/clip-export-state.js": ("history/clip-export-state.js", "text/javascript"),
    "/history/timeline-model.js": ("history/timeline-model.js", "text/javascript"),
    "/history/history-range.js": ("history/history-range.js", "text/javascript"),
    "/history/exports.js": ("history/exports.js", "text/javascript"),
    "/history/timeline.js": ("history/timeline.js", "text/javascript"),
    "/history/playback-controls.js": ("history/playback-controls.js", "text/javascript"),
    "/history/history.css": ("history/history.css", "text/css")}


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
        playback = re.fullmatch(r"/api/playback/sessions/([a-f0-9]{32})", path)
        try:
            export = re.fullmatch(r"/api/exports/([a-f0-9]{32})", path)
            if operation == "POST" and path == "/api/exports":
                self.json_response(self.server.exports.create(self.body(), self.headers.get("Idempotency-Key")), 202)
            elif operation == "DELETE" and export:
                if self.headers.get("Origin") not in (None, "http://" + self.headers["Host"]):
                    raise SessionError("Invalid origin.", 403)
                self.server.exports.delete(export[1])
                self.send_response(204); self.send_header("Content-Length", "0"); self.end_headers()
            elif operation == "POST" and path == "/api/playback/sessions":
                self.json_response(self.server.playback.create(self.body()), 201)
            elif operation == "PATCH" and playback:
                self.json_response(self.server.playback.patch(playback[1], self.body()))
            elif operation == "DELETE" and playback:
                if self.headers.get("Origin") not in (None, "http://" + self.headers["Host"]):
                    raise SessionError("Invalid origin.", 403)
                self.server.playback.delete(playback[1])
                self.send_response(204); self.send_header("Content-Length", "0"); self.end_headers()
            elif operation == "POST" and path == "/api/live/sessions":
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
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
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
            if path == "/api/exports":
                self.json_response(self.server.exports.list())
            elif (match := re.fullmatch(r"/api/exports/([a-f0-9]{32})", path)):
                self.json_response(self.server.exports.get(match[1]))
            elif (match := re.fullmatch(r"/media/exports/([a-f0-9]{32})\.mp4", path)):
                self.export_file(match[1])
            elif path == "/api/cameras":
                worker.ensure_ready()
                worker.refresh_availability()
                with worker.condition:
                    self.json_response({"cameras": list(worker.cameras.values())})
            elif path == "/api/status":
                with worker.condition:
                    quality_status = sessions.quality_status()
                    self.json_response(dict(state=worker.state, error=worker.error,
                        active_live_sources=len(sessions.wanted), viewer_sessions=len(sessions.sessions),
                        active_media_feeds=len(self.server.feeds),
                        playback_sessions=len(self.server.playback.sessions),
                        active_exports=int(self.server.exports.active is not None),
                        device_stream_limit=None, source_limit=sessions.limit,
                        tested_concurrent_streams=worker.tested_capacity, sdk_login_calls=worker.login_calls,
                        sdk_adapter=worker.adapter.sdk_id, recording_available=self.server.recording.is_file(),
                        **quality_status,
                        **self.server.recording_info))
            elif (match := re.fullmatch(r"/api/cameras/(camera-[0-9]+)/timeline", path)):
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if any(len(values) != 1 for values in query.values()):
                    raise SessionError("A single timeline range or local date/time is required.")
                if query.get("refresh", ["0"])[0] not in ("0", "1"):
                    raise SessionError("Invalid refresh option.")
                keys = set(query) - {"refresh"}
                if keys == {"local_time", "hours"}:
                    result, status = self.server.timeline.query_local(match[1], query["local_time"][0], query["hours"][0], query.get("refresh") == ["1"])
                elif keys == {"from", "to"}:
                    result, status = self.server.timeline.query(match[1], query["from"][0], query["to"][0], query.get("refresh") == ["1"])
                else:
                    raise SessionError("Use either a from/to range or a local_time/hours selection.")
                self.json_response(result, status)
            elif re.fullmatch(r"/api/live/sessions/[a-f0-9]{32}", path):
                self.json_response(sessions.get(path.rsplit("/", 1)[1]))
            elif re.fullmatch(r"/api/playback/sessions/[a-f0-9]{32}", path):
                self.json_response(self.server.playback.get(path.rsplit("/", 1)[1]))
            elif (match := re.fullmatch(r"/media/live/([a-f0-9]{32})/frames", path)):
                self.frames(match[1])
            elif (match := re.fullmatch(r"/media/playback/([a-f0-9]{32})", path)):
                self.frames(match[1], playback=True)
            elif path == "/recording.mp4":
                self.file(self.server.recording, "video/mp4", ranged=True)
            elif path in ASSETS:
                name, mime = ASSETS[path]; self.file(self.server.web / name, mime)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except SessionError as error:
            self.json_response({"error": {"code": "session_error", "message": str(error), "retryable": False}}, error.status)
        except (OSError, ValueError):
            self.json_response({"error": {"code": "recorder_unavailable", "message": "Recorder discovery failed; no automatic login retry.", "retryable": False}}, 503)

    def frames(self, identifier, playback=False):
        sessions = self.server.playback if playback else self.server.sessions
        sessions.get(identifier)
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
            while not sessions.closed:
                # Paused History/offline inputs can be quiet indefinitely. A
                # disconnected peer must free its feed slot without a write.
                if select.select([self.connection], [], [], 0)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                    break
                for packet in sessions.next_frames(identifier, seen):
                    self.wfile.write(packet)
                self.wfile.flush()
        except (OSError, SessionError):
            pass
        finally:
            with self.server.worker.condition:
                self.server.feeds.discard(identifier)

    def export_file(self, identifier):
        with self.server.exports.download(identifier) as (file, filename):
            size = os.fstat(file.fileno()).st_size
            try: first, last = byte_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0"); self.end_headers(); return
            ranged = self.headers.get("Range") is not None
            self.send_response(206 if ranged else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Accept-Ranges", "bytes")
            if ranged: self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            self.send_header("Content-Length", str(last - first + 1)); self.end_headers()
            self.connection.settimeout(5); file.seek(first); remaining = last - first + 1
            while remaining:
                chunk = file.read(min(65536, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)


def create_server(worker, sessions, *, address, web, recording, recording_info=None, timeline=None, playback=None, exports=None):
    """Wire the HTTP service without initializing an SDK or choosing a worker."""
    if any(service is not None and service.budget is not sessions.budget for service in (playback, exports)):
        raise ValueError("Viewing and export services must share one stream budget")
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    port = server.server_port
    server.allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
    server.worker, server.sessions, server.feeds = worker, sessions, set()
    server.web, server.recording = Path(web), Path(recording)
    server.recording_info = recording_info or {}
    server.timeline = timeline or HistoryTimeline(worker, worker.config.get("timezone", "Africa/Johannesburg"))
    server.playback = playback or PlaybackSessions(worker, sessions.budget, lease_seconds=sessions.lease_seconds)
    server.maintenance_stop = threading.Event()
    temporary = None
    if exports is None:
        temporary = tempfile.TemporaryDirectory(prefix="oogies-exports-fixture-")
        exports = ExportJobs(worker, sessions.budget, temporary.name)
    server.exports = exports
    close = server.server_close
    def close_exports():
        server.maintenance_stop.set()
        server.exports.close()
        close()
        if temporary: temporary.cleanup()
    server.server_close = close_exports
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
    budget = StreamBudget(worker.condition, config["max_live_sources"], config["max_high_quality_sources"])
    sessions = LiveSessions(worker, lease_seconds=config["lease_seconds"], budget=budget)
    recording_info = {"recording_begin": os.environ.get("CAM_RECORDING_BEGIN"),
        "recording_end": os.environ.get("CAM_RECORDING_END"), "recording_seconds": os.environ.get("CAM_RECORDING_SECONDS")}
    server = create_server(worker, sessions, address=("0.0.0.0", args.port),
        web="/web", recording="/recording/historical-clip.mp4", recording_info=recording_info,
        exports=ExportJobs(worker, sessions.budget, "/exports"))
    maintenance = threading.Thread(target=run_maintenance,
        args=(sessions, server.playback, server.maintenance_stop), daemon=True)
    maintenance.start()
    def shutdown(*_): threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    print(f"Live grid listening on port {args.port}; recorder connects when a viewer opens the page.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.maintenance_stop.set(); maintenance.join(timeout=2)
        server.exports.close(); sessions.close(); server.playback.close(); worker.close(); server.timeline.close(); server.server_close()


if __name__ == "__main__": main()
