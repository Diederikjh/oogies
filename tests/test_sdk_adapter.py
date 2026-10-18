"""Offline checks of policy ownership and the actual launch boundary."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from sdk_adapters import DEFAULT_SDK_ID, get_sdk_adapter


class SdkAdapterTests(unittest.TestCase):
    def test_development_bridge_selection_keeps_compilation(self):
        adapter = get_sdk_adapter()
        with patch.object(adapter, "compile_live_bridge", return_value="compiled-bridge") as compile_bridge:
            self.assertEqual(adapter.resolve_live_bridge(), "compiled-bridge")
        compile_bridge.assert_called_once_with()

    def test_packaged_bridge_never_compiles_or_falls_back(self):
        adapter = get_sdk_adapter()
        with tempfile.TemporaryDirectory() as directory, patch.object(adapter, "compile_live_bridge") as compile_bridge:
            binary = Path(directory) / "bridge"
            with self.assertRaisesRegex(ValueError, "Packaged live bridge"):
                adapter.resolve_live_bridge(binary)
            binary.write_text("synthetic executable")
            binary.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "Packaged live bridge"):
                adapter.resolve_live_bridge(binary)
            binary.chmod(0o700)
            self.assertEqual(adapter.resolve_live_bridge(binary), str(binary))
            compile_bridge.assert_not_called()

    def test_unknown_sdk_is_rejected_instead_of_silent_fallback(self):
        self.assertEqual(get_sdk_adapter().sdk_id, DEFAULT_SDK_ID)
        with self.assertRaises(ValueError):
            get_sdk_adapter("unavailable-sdk")

    def test_offline_invocation_needs_no_credentials_and_carries_no_login_input(self):
        invocation = get_sdk_adapter().invocation("synthetic-bridge", check=True,
            decrypt=True, historical=True, skip_search=True, log_dir=Path("/output/check-logs"))
        self.assertEqual(invocation.stdin, "")
        self.assertEqual(invocation.command,
                         ["synthetic-bridge", "check", "--decrypt", "--historical", "--skip-search"])
        self.assertEqual(invocation.env["CAM_SDK_LOG_DIR"], "/output/check-logs/")

    def test_live_and_historical_launch_keep_full_key_in_private_stdin(self):
        credentials = {"username": "synthetic-user", "password": "synthetic-pass",
                       "verification_code": "FullSyntheticEncryptionKeyBeyond16"}
        for extra in ({"browser_frames": True}, {"historical": True, "skip_search": True}):
            with self.subTest(mode=extra):
                invocation = get_sdk_adapter().invocation("synthetic-bridge",
                    credentials=credentials, host="192.0.2.10", port=8123,
                    seconds=5, decrypt=True, capture_dir=Path("/output/capture"), **extra)
                self.assertEqual(invocation.stdin.splitlines(),
                    ["192.0.2.10", "8123", "synthetic-user", "synthetic-pass", "5",
                     credentials["verification_code"]])
                self.assertEqual(invocation.env["CAM_SDK_CAPTURE_DIR"], "/output/capture")
                for secret in (credentials["password"], credentials["verification_code"]):
                    self.assertNotIn(secret, repr(invocation))
                    self.assertNotIn(secret, " ".join(invocation.command))

    def test_verification_code_uses_utf8_byte_limit_and_rejects_controls(self):
        credentials = {"username": "synthetic-user", "password": "synthetic-pass"}
        for key in ("", "A" * 129, "é" * 65, "synthetic\nkey", "synthetic\x00key"):
            with self.subTest(key_kind=len(key)):
                with self.assertRaises(ValueError):
                    get_sdk_adapter().invocation("synthetic-bridge", host="192.0.2.10",
                        port=8000, credentials=dict(credentials, verification_code=key), decrypt=True)


if __name__ == "__main__":
    unittest.main()
