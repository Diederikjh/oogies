"""Runner safeguards use Python only; backend CI needs neither Node nor Docker."""

import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_js_tests as runner


class JavaScriptRunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.tests = self.root / "tests/js"
        self.tests.mkdir(parents=True)

    def test_empty_discovery_and_missing_selection_fail(self):
        with self.assertRaisesRegex(ValueError, "No JavaScript test files"):
            runner.select_tests(self.root, [])
        with self.assertRaisesRegex(ValueError, "not found"):
            runner.select_tests(self.root, ["tests/js/missing.test.mjs"])

    def test_discovery_ignores_helpers_and_explicit_selection_is_deduplicated(self):
        for name in ("a.test.mjs", "b.test.mjs", "helper.mjs"):
            (self.tests / name).touch()
        self.assertEqual(runner.select_tests(self.root, []),
                         [Path("tests/js/a.test.mjs"), Path("tests/js/b.test.mjs")])
        self.assertEqual(runner.select_tests(self.root, ["tests/js/b.test.mjs"] * 2),
                         [Path("tests/js/b.test.mjs")])

    def test_selection_rejects_outside_paths_and_symlinks(self):
        private = self.root / "private.test.mjs"
        private.touch()
        (self.tests / "link.test.mjs").symlink_to(private)
        for path in ("private.test.mjs", "tests/js/link.test.mjs"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "inside tests/js"):
                runner.select_tests(self.root, [path])

    def test_native_runtime_requires_node_22_and_explains_docker_alternative(self):
        with patch.object(runner.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "--docker"):
                runner.native_node()
        for version, supported in (("v22.14.0", True), ("v24.0.0", False), ("v20.0.0", False)):
            with self.subTest(version=version), patch.object(runner.shutil, "which", return_value="node"), \
                    patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, version)):
                if supported:
                    self.assertEqual(runner.native_node(), "node")
                else:
                    with self.assertRaisesRegex(ValueError, "Native Node 22"):
                        runner.native_node()

    def test_process_failure_preserves_output_and_nonzero_exit(self):
        report = self.root / "output/tests.tap"
        command = [sys.executable, "-c", "print('TAP version 13'); print('not ok 1 - deliberate failure'); raise SystemExit(7)"]
        with contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertEqual(runner.stream_tests(command, report, self.root), 7)
        self.assertEqual(report.read_text(), console.getvalue())
        self.assertIn("not ok 1", report.read_text())

    def test_success_replaces_previous_failure_report(self):
        report = self.root / "tests.tap"
        report.write_text("old failure")
        with contextlib.redirect_stdout(io.StringIO()):
            code = runner.stream_tests([sys.executable, "-c", "print('ok 1 - passed')"], report, self.root)
        self.assertEqual(code, 0)
        self.assertEqual(report.read_text(), "ok 1 - passed\n")

    def test_invalid_selection_fails_before_starting_a_runtime(self):
        with patch.object(runner, "ROOT", self.root), patch.object(runner, "native_node") as native, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                runner.main(["tests/js/missing.test.mjs"])
        self.assertEqual(error.exception.code, 2)
        native.assert_not_called()
