"""Request boundaries through the real HTTP handler, with no recorder transport."""

import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
from export_jobs import ExportJobs
from grid_server import create_server
from grid_worker import GridWorker
from live_sessions import LiveSessions


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.spawn = Mock(side_effect=AssertionError("HTTP tests must never start an SDK"))
        self.worker = GridWorker(None, SimpleNamespace(sdk_id="security-fixture"), {},
                                 self.directory.name, spawn=self.spawn)
        self.worker.state = "ready"
        self.live = LiveSessions(self.worker)
        exports = ExportJobs(self.worker, self.live.budget,
                             Path(self.directory.name) / "exports", start=False)
        self.server = create_server(self.worker, self.live, address=("127.0.0.1", 0),
            web=ROOT / "web", recording=Path(self.directory.name) / "missing", exports=exports)
        self.errors = []
        self.server.handle_error = lambda *args: self.errors.append("handler exception")
        self.host = f"localhost:{self.server.server_port}"
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown(); self.thread.join(timeout=3)
        self.live.close(); self.server.playback.close(); self.server.timeline.close()
        self.server.server_close(); self.worker.close()
        self.spawn.assert_not_called()
        self.assertEqual(self.worker.login_calls, 0)
        self.assertEqual(self.errors, [])

    def nested_create(self):
        body = b'{"cameras":[]}'
        return (f"POST /api/live/sessions HTTP/1.1\r\nHost: {self.host}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n").encode() + body

    def exchange(self, method, path, headers, body=b""):
        request = (f"{method} {path} HTTP/1.1\r\nHost: {self.host}\r\n" +
                   "".join(f"{key}: {value}\r\n" for key, value in headers) + "\r\n").encode() + body
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as connection:
            connection.sendall(request)
            response = bytearray()
            while True:
                chunk = connection.recv(65536)
                if not chunk: return bytes(response)
                response.extend(chunk)

    def assert_single_response(self, response, status):
        self.assertTrue(response.startswith(f"HTTP/1.1 {status} ".encode()), response[:100])
        self.assertEqual(response.count(b"HTTP/1.1 "), 1, "Unread bytes dispatched another request")
        self.assertIn(b"connection: close", response.split(b"\r\n\r\n", 1)[0].lower())

    def test_rejected_origin_cannot_dispatch_request_from_unread_body(self):
        nested = self.nested_create()
        for method, path in (("POST", "/api/live/sessions"), ("PATCH", "/api/live/sessions/" + "a" * 32),
                             ("POST", "/api/playback/sessions"), ("POST", "/api/exports")):
            with self.subTest(method=method, path=path):
                response = self.exchange(method, path, [("Origin", "https://untrusted.example"),
                    ("Content-Type", "application/json"), ("Content-Length", len(nested))], nested)
                self.assert_single_response(response, 403)
                self.assertEqual(self.live.sessions, {})

    def test_rejected_content_type_cannot_dispatch_request_from_unread_body(self):
        nested = self.nested_create()
        response = self.exchange("POST", "/api/live/sessions", [
            ("Content-Type", "text/plain"), ("Content-Length", len(nested))], nested)
        self.assert_single_response(response, 415)
        self.assertEqual(self.live.sessions, {})

    def test_get_and_delete_reject_unexpected_bodies_before_actions(self):
        nested = self.nested_create()
        routes = [("GET", "/"), ("GET", "/api/status"),
            *[("DELETE", path + "a" * 32) for path in
              ("/api/live/sessions/", "/api/playback/sessions/", "/api/exports/")],
            ("DELETE", "/api/exports/" + "a" * 32 + "/entry")]
        for method, path in routes:
            with self.subTest(method=method, path=path):
                response = self.exchange(method, path, [("Content-Length", len(nested))], nested)
                self.assert_single_response(response, 400)
                self.assertEqual(self.live.sessions, {})

    def test_ambiguous_and_unsupported_framing_is_rejected_before_actions(self):
        body = b'{"cameras":[]}'
        malformed = [
            [("Content-Length", len(body)), ("Content-Length", len(body))],
            [("Content-Length", len(body)), ("Content-Length", len(body) + 10)],
            [("Content-Length", f"{len(body)}, {len(body)}")],
            [("Transfer-Encoding", "chunked")],
            [("Transfer-Encoding", "identity"), ("Content-Length", len(body))],
            [("Content-Length", "-1")], [("Content-Length", "+13")],
            [("Content-Length", "not-a-number")], [("Content-Length", "9" * 100)],
        ]
        for headers in malformed:
            for method, path in (("POST", "/api/live/sessions"), ("GET", "/api/status"),
                                 ("DELETE", "/api/live/sessions/" + "a" * 32)):
                with self.subTest(headers=headers, method=method):
                    response = self.exchange(method, path, [("Content-Type", "application/json"), *headers],
                                             body + self.nested_create())
                    self.assert_single_response(response, 400)
                    self.assertEqual(self.live.sessions, {})

    def test_missing_oversized_and_invalid_json_body_cannot_dispatch_followup(self):
        cases = [([], self.nested_create()),
                 ([("Content-Length", 4097)], b" " * 4097 + self.nested_create()),
                 ([("Content-Length", 1)], b"{" + self.nested_create())]
        for headers, body in cases:
            with self.subTest(headers=headers):
                response = self.exchange("POST", "/api/live/sessions", [("Content-Type", "application/json"), *headers], body)
                self.assert_single_response(response, 400)
                self.assertEqual(self.live.sessions, {})

    def test_successful_control_does_not_dispatch_pipelined_action(self):
        body = b'{"cameras":[]}'
        response = self.exchange("POST", "/api/live/sessions", [("Content-Type", "application/json"),
            ("Content-Length", len(body)), ("Connection", "keep-alive")], body + self.nested_create())
        self.assert_single_response(response, 201)
        self.assertEqual(len(self.live.sessions), 1)

    def test_delete_with_body_does_not_remove_existing_session(self):
        view = self.live.create({"cameras": []})
        nested = self.nested_create()
        response = self.exchange("DELETE", "/api/live/sessions/" + view["id"],
                                 [("Content-Length", len(nested))], nested)
        self.assert_single_response(response, 400)
        self.assertEqual(set(self.live.sessions), {view["id"]})

    def test_valid_controls_work_across_new_connections(self):
        def api(method, path, body=None):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            try:
                encoded = json.dumps(body).encode() if body is not None else None
                connection.request(method, path, encoded,
                    {"Content-Type": "application/json"} if encoded is not None else {})
                response = connection.getresponse()
                self.assertTrue(response.will_close)
                return response.status, json.loads(response.read()) if response.status != 204 else None
            finally: connection.close()
        status, created = api("POST", "/api/live/sessions", {"cameras": []})
        self.assertEqual(status, 201)
        path = "/api/live/sessions/" + created["id"]
        self.assertEqual(api("PATCH", path, {})[0], 200)
        self.assertEqual(api("GET", path)[1]["id"], created["id"])
        self.assertEqual(api("DELETE", path)[0], 204)
        self.assertEqual(api("GET", "/api/status")[1]["viewer_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
