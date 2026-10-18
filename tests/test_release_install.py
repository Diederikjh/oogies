"""Cutover safeguards and private, independent state preparation without Docker."""

import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import install_release as install

IMAGE = "sha256:" + "a" * 64
IDENTIFIER = "b" * 32


class ReleaseInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.source = self.root / "source"; self.source.mkdir()
        self.directory = self.root / "installed"
        (self.source / "nvr-config.json").write_text(json.dumps({"host":"192.0.2.10"}))
        (self.source / "nvr-credentials.json").write_text(json.dumps({"username":"test-user", "password":"synthetic-test-password", "verification_code":"synthetic-code"}))
        clip = self.source / "exports" / IDENTIFIER / "clip.mp4"
        clip.parent.mkdir(parents=True); clip.write_bytes(b"synthetic clip content")
        self.manifest = self.source / "exports/jobs.json"
        self.manifest.write_text(json.dumps({"version":1,"jobs":[{"id":IDENTIFIER,"state":"ready"}]}))
        self.stopped_patcher = patch.object(install, "require_stopped")
        self.stopped = self.stopped_patcher.start()
        self.addCleanup(self.stopped_patcher.stop)

    def prepare(self, **kwargs):
        return install.prepare_installation(self.source, self.directory, IMAGE, **kwargs)

    def test_preparation_preserves_private_files_and_ready_clips_independently(self):
        (self.source / "development-sdk").symlink_to(self.root / "unrelated-sdk")
        result = self.prepare(port=8090)
        self.stopped.assert_called_once_with(self.source)
        expected = hashlib.sha256(b"synthetic clip content").hexdigest()
        self.assertEqual(result["ready_exports"], {IDENTIFIER:expected})
        state = self.directory / ".local"
        self.assertFalse((state / "development-sdk").exists())
        self.assertEqual(install.validate_state(state), {IDENTIFIER:expected})
        for name in ("nvr-config.json", "nvr-credentials.json", "exports/jobs.json"):
            self.assertEqual((state / name).read_bytes(), (self.source / name).read_bytes())
            self.assertEqual((state / name).stat().st_mode & 0o777, 0o600)
        for path in (self.directory, state, state / "exports", state / "output"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        env = (self.directory / ".env").read_text()
        self.assertIn("OOGIES_IMAGE="+IMAGE, env); self.assertIn("OOGIES_PORT=8090", env)
        self.assertNotIn("synthetic-test-password", env); self.assertNotIn("192.0.2.10", env)
        self.assertEqual((self.directory / "compose.yaml").read_bytes(), (install.ROOT / "docker/release/compose.yaml").read_bytes())
        (self.source / "nvr-config.json").write_text("changed development config")
        self.assertEqual(json.loads((state / "nvr-config.json").read_text())["host"], "192.0.2.10")
        (state / "exports" / IDENTIFIER / "clip.mp4").write_bytes(b"release edit")
        self.assertEqual((self.source / "exports" / IDENTIFIER / "clip.mp4").read_bytes(), b"synthetic clip content")

    def test_pending_jobs_missing_clips_and_invalid_credentials_leave_no_installation(self):
        for status in ("queued", "running", "ready"):
            with self.subTest(status=status):
                self.manifest.write_text(json.dumps({"version":1,"jobs":[{"id":IDENTIFIER,"state":status}]}))
                if status == "ready": (self.source / "exports" / IDENTIFIER / "clip.mp4").unlink()
                with self.assertRaises(ValueError): self.prepare()
                self.assertFalse(self.directory.exists())
        self.manifest.write_text('{"version":1,"jobs":[]}')
        (self.source / "nvr-credentials.json").write_text('{"username":"test"}')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.directory.exists())

    def test_existing_installation_and_unsafe_settings_are_rejected(self):
        for kwargs in ({"port":80}, {"project":"bad\nsetting"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.prepare(**kwargs)
        with self.assertRaises(ValueError):
            install.prepare_installation(self.source, self.directory, "oogies:mutable")
        with self.assertRaises(ValueError):
            install.prepare_installation(self.source, install.ROOT / ".local/install", IMAGE)
        self.directory.mkdir(); (self.directory / "sentinel").write_text("keep")
        with self.assertRaisesRegex(ValueError, "already exists"): self.prepare()
        self.assertEqual((self.directory / "sentinel").read_text(), "keep")

    def test_symlink_state_and_source_inside_destination_are_rejected(self):
        private = self.source / "nvr-credentials.json"
        other = self.root / "other.json"; private.rename(other); private.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"): self.prepare()
        private.unlink(); other.rename(private)
        (self.source / "exports/link").symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"): self.prepare()
        with self.assertRaises(ValueError):
            install.prepare_installation(self.source, self.source / "child", IMAGE)
        self.assertFalse(self.directory.exists())

    def test_copy_failure_cleans_staging_without_modifying_source(self):
        before = self.manifest.read_bytes()
        with patch.object(install.shutil, "copytree", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError): self.prepare()
        self.assertFalse(self.directory.exists())
        self.assertEqual(list(self.root.glob(".oogies-prepare-*")), [])
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_live_mounts_refuse_parent_child_and_exact_state_paths(self):
        self.stopped_patcher.stop()
        for mounted in (self.source, self.root, self.source / "exports"):
            with self.subTest(mounted=mounted), patch.object(install.subprocess, "check_output", side_effect=["container\n", json.dumps([{"Mounts":[{"Type":"bind","Source":str(mounted)}]}])]):
                with self.assertRaisesRegex(ValueError, "Stop containers"): install.require_stopped(self.source)
        with patch.object(install.subprocess, "check_output", side_effect=["container\n", json.dumps([{"Mounts":[{"Type":"bind","Source":str(self.root / "unrelated") }]}])]):
            install.require_stopped(self.source)

    def test_main_rejects_wrong_image_platform_or_sdk_before_state_copy(self):
        for architecture, profile in (("arm64", "hcnet-6.1.9.48-linux64"), ("amd64", "other-sdk")):
            inspected = [{"Id":IMAGE,"Os":"linux","Architecture":architecture,"Config":{"Labels":{"oogies.sdk-profile":profile}}}]
            with self.subTest(architecture=architecture, profile=profile), \
                    patch.object(install.subprocess, "run"), \
                    patch.object(install.subprocess, "check_output", return_value=json.dumps(inspected)), \
                    patch.object(install, "prepare_installation") as prepare, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    install.main(["--source-state",str(self.source),"--directory",str(self.directory),"--image","oogies:test"])
                self.assertEqual(error.exception.code, 1)
                prepare.assert_not_called()
