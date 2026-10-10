import concurrent.futures
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
spec = importlib.util.spec_from_file_location("browser_server", ROOT / "docker/hikvision-sdk/browser_server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class FakeProcess:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.finished = threading.Event()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.finished.set()

    kill = terminate

    def wait(self, timeout=None):
        if not self.finished.wait(timeout):
            raise server.subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


class BrowserContractTests(unittest.TestCase):
    def test_concurrent_start_and_refresh_share_one_process_and_stop_it(self):
        created = []
        def spawn(*args, **kwargs):
            process = FakeProcess()
            created.append(process)
            return process
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "load_credentials", return_value={
                "username":"test-user", "password":"test-password", "verification_code":"dummy-verification"}):
            camera = server.Camera("fake-sdk", directory, spawn=spawn)
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                statuses = list(pool.map(lambda _: camera.start(), range(4)))
            self.assertEqual(len(created), 1)
            self.assertEqual(len({s["session"] for s in statuses}), 1)
            for _ in range(10):
                self.assertEqual(camera.status()["state"], "connecting")
            self.assertEqual(len(created), 1)
            self.assertEqual(camera.stop()["state"], "stopped")
            self.assertIsNone(camera.process)
            self.assertTrue(created[0].finished.is_set())

    def test_recording_ranges_support_seek_and_reject_invalid_requests(self):
        for header, expected in [(None,(0,99)), ("bytes=0-9",(0,9)), ("bytes=90-",(90,99)),
                                 ("bytes=-10",(90,99)), ("bytes=0-999",(0,99))]:
            with self.subTest(header=header):
                self.assertEqual(server.byte_range(header,100), expected)
        for header in ("bytes=100-", "bytes=10-5", "bytes=-0", "bytes=0-1,3-4", "bytes=-", "garbage"):
            with self.subTest(header=header):
                with self.assertRaises(ValueError):
                    server.byte_range(header,100)


if __name__ == "__main__":
    unittest.main()
