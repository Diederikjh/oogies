"""Release context boundaries and identity checks, without Docker or the SDK."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_release as release


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        files = ["docker/release/Dockerfile", release.SDK_ARCHIVE, "vendor/hikvision/README.md"]
        files += ["docker/hikvision-sdk/"+name for name in release.APP_MODULES + release.NATIVE_SOURCES]
        files += ["tools/"+name for name in release.SUPPORT_MODULES]
        files += ["web/index.html", "web/app.js", "web/private-backup.json", ".local/nvr-credentials.json", ".env"]
        for name in files:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("public input")
        self.server = self.root / "docker/hikvision-sdk/grid_server.py"
        self.server.write_text('ASSETS = {"/":("index.html","text/html"), "/app.js":("app.js","text/javascript")}\n')
        for name in ("web/private-backup.json", ".local/nvr-credentials.json", ".env"):
            (self.root / name).write_text("PRIVATE_TEST_SENTINEL")

    def test_context_contains_only_listed_inputs_and_hashes_snapshot_bytes(self):
        context = self.root / "context.tar"
        with patch.object(release, "validate_archive"):
            metadata = release.create_context(self.root, context, {"version":"test"})
        with tarfile.open(context) as archive:
            names = set(archive.getnames())
            self.assertIn("sdk.zip", names); self.assertIn("native/live_grid.cpp", names)
            self.assertIn("app/grid_server.py", names); self.assertIn("support/credentials.py", names)
            self.assertIn("web/index.html", names); self.assertIn("web/app.js", names)
            self.assertFalse(any(name.startswith((".local", ".git")) for name in names))
            self.assertNotIn("web/private-backup.json", names); self.assertNotIn(".env", names)
            self.assertEqual(json.load(archive.extractfile("release.json")), metadata)
            for name, digest in metadata["files"].items():
                self.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(), digest)
        self.assertNotIn(b"PRIVATE_TEST_SENTINEL", context.read_bytes())
        (self.root / "web/app.js").write_text("changed after packaging")
        with tarfile.open(context) as archive:
            self.assertEqual(archive.extractfile("web/app.js").read(), b"public input")

    def test_archive_pointer_or_corruption_fails_before_docker(self):
        archive = self.root / release.SDK_ARCHIVE
        archive.write_text("version https://git-lfs.github.com/spec/v1\n")
        with self.assertRaisesRegex(ValueError, "git lfs pull"):
            release.validate_archive(archive)
        metadata = {"version":"test", "revision":"a"*40, "dirty":False}
        with patch.object(release, "ROOT", self.root), patch.object(release, "build_metadata", return_value=metadata), \
                patch.object(release.subprocess, "run") as execute, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error: release.main([])
        self.assertEqual(error.exception.code, 1)
        self.assertFalse(any(call.args[0][0] == "docker" for call in execute.call_args_list))

    def test_archive_checksum_is_verified(self):
        archive = self.root / release.SDK_ARCHIVE
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        release.validate_archive(archive, digest)
        archive.write_bytes(b"modified")
        with self.assertRaises(ValueError): release.validate_archive(archive, digest)

    def test_symlink_input_and_traversing_asset_are_rejected(self):
        script = self.root / "web/app.js"; script.unlink()
        script.symlink_to(self.root / ".local/nvr-credentials.json")
        with self.assertRaisesRegex(ValueError, "Symlink"): release.context_inputs(self.root)
        self.server.write_text('ASSETS = {"/":("../.local/nvr-credentials.json","text/plain")}\n')
        with self.assertRaisesRegex(ValueError, "relative file"): release.context_inputs(self.root)

    def test_missing_required_source_fails(self):
        (self.root / "web/app.js").unlink()
        with self.assertRaisesRegex(ValueError, "Release input missing"): release.context_inputs(self.root)

    def test_metadata_distinguishes_dirty_sources_and_validates_versions(self):
        for status, expected in ((b"", "dev-"+"a"*12), (b"?? public-new-file.py\n", "dev-"+"a"*12+"-dirty")):
            with self.subTest(status=bool(status)), patch.object(release.subprocess, "check_output", side_effect=["a"*40, status]):
                metadata = release.build_metadata(self.root)
                self.assertEqual(metadata["version"], expected)
                self.assertEqual(metadata["dirty"], bool(status))
        with patch.object(release.subprocess, "check_output", side_effect=["a"*40, b""]):
            self.assertEqual(release.build_metadata(self.root, "0.1.0-rc.1")["version"], "0.1.0-rc.1")
        with patch.object(release.subprocess, "check_output", side_effect=["a"*40, b""]):
            metadata = release.build_metadata(self.root, source_url="https://github.com/example/oogies")
            self.assertEqual(metadata["source_url"], "https://github.com/example/oogies")
        for source_url in ("http://github.com/example/oogies", "https://github.com/example/oogies\nINJECT=value"):
            with self.subTest(source_url=source_url), patch.object(release.subprocess, "check_output", side_effect=["a"*40, b""]):
                with self.assertRaises(ValueError): release.build_metadata(self.root, source_url=source_url)
        for version in ("../private", "bad version", "--push", "a"*121):
            with self.subTest(version=version), patch.object(release.subprocess, "check_output", side_effect=["a"*40, b""]):
                with self.assertRaises(ValueError): release.build_metadata(self.root, version)
