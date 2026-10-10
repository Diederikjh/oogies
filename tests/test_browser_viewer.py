import concurrent.futures
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "docker/hikvision-sdk"))
spec = importlib.util.spec_from_file_location("browser_server", ROOT / "docker/hikvision-sdk/browser_server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class CapturedInput(io.BytesIO):
    def close(self):
        self.payload = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self):
        self.stdin = CapturedInput()
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
        adapter = server.get_sdk_adapter()
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, "load_credentials", return_value={
                "username":"test-user", "password":"test-password", "verification_code":"dummy-verification"}):
            camera = server.Camera("fake-sdk", directory, spawn=spawn, adapter=adapter)
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

    def test_injected_adapter_controls_credentials_and_native_launch(self):
        """Prove the HTTP/session layer can use a different adapter without SDK IO."""
        calls = []
        processes = []
        class StubAdapter:
            def load_credentials(self, path):
                calls.append(("credentials", path))
                return {"username": "synthetic-user", "password": "full-synthetic-password-over-16"}

            def invocation(self, binary, **kwargs):
                calls.append(("invocation", binary, kwargs))
                return SimpleNamespace(command=["alternate-worker", "preview"],
                    stdin=kwargs["credentials"]["password"] + "\n",
                    cwd="/alternate-sdk", env={"STUB_WORKER": "1"})

        def spawn(command, **kwargs):
            self.assertEqual(command, ["alternate-worker", "preview"])
            self.assertEqual(kwargs["cwd"], "/alternate-sdk")
            self.assertEqual(kwargs["env"], {"STUB_WORKER": "1"})
            process = FakeProcess()
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            camera = server.Camera("synthetic-bridge", directory, seconds=30,
                                   spawn=spawn, adapter=StubAdapter())
            try:
                self.assertEqual(camera.start()["state"], "connecting")
                self.assertEqual(processes[0].stdin.payload,
                                 b"full-synthetic-password-over-16\n")
                self.assertEqual(calls[0], ("credentials", "/credentials/nvr.json"))
                self.assertEqual(calls[1][2]["seconds"], 30)
                self.assertEqual(calls[1][2]["capture_dir"].parent, Path(directory))
                camera.start()
                self.assertEqual(len(calls), 2, "Duplicate Start must not reload credentials")
                self.assertEqual(len(processes), 1)
            finally:
                camera.stop()
            self.assertEqual(camera.status()["state"], "stopped")

    def test_invalid_encryption_code_never_spawns_a_worker(self):
        adapter = server.get_sdk_adapter()
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, "load_credentials", return_value={
                "username": "synthetic-user", "password": "synthetic-pass", "verification_code": ""}):
            with patch.object(server.subprocess, "Popen") as spawn:
                camera = server.Camera("synthetic-bridge", directory, adapter=adapter, spawn=spawn)
                with self.assertRaises(ValueError):
                    camera.start()
                spawn.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

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
