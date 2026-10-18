"""Run the Docker-only browser suite and save a machine-readable result."""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import time
import unittest

from browser_support import BrowserTestCase, browser_media

DEFAULT_MODULES = ("test_native_playback", "test_live", "test_history", "test_exports")


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item

class ReportResult(unittest.TextTestResult):
    def __init__(self, *args):
        super().__init__(*args)
        self.cases = []
    def startTest(self, test):
        self.started_at = time.monotonic()
        super().startTest(test)
    def record(self, test, status, error=None):
        self.cases.append(dict(test=test.id(), status=status,
            seconds=round(time.monotonic()-getattr(self,"started_at",time.monotonic()), 2), **({"error":error} if error else {})))
    def addSuccess(self, test):
        super().addSuccess(test); self.record(test, "passed")
    def addFailure(self, test, error):
        super().addFailure(test, error); self.record(test, "failed", self._exc_info_to_string(error,test))
    def addError(self, test, error):
        super().addError(test, error); self.record(test, "error", self._exc_info_to_string(error,test))

if __name__ == "__main__":
    os.umask(0o077)
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or DEFAULT_MODULES)
    browser_count = sum(isinstance(case, BrowserTestCase) for case in test_cases(suite))
    media_seconds = 0
    with ExitStack() as resources:
        if browser_count:
            media_started = time.monotonic()
            resources.enter_context(browser_media())
            media_seconds = time.monotonic() - media_started
        suite_started = time.monotonic()
        result = unittest.TextTestRunner(verbosity=2, resultclass=ReportResult).run(suite)
        suite_seconds = time.monotonic() - suite_started
    output = Path("/output"); output.mkdir(parents=True, exist_ok=True)
    (output / "ui-tests.json").write_text(json.dumps(dict(tests=result.testsRun,
        passed=result.wasSuccessful(), cases=result.cases,
        browser_tests=browser_count, media_generations=int(browser_count > 0),
        seconds=dict(media_setup=round(media_seconds, 3), suite=round(suite_seconds, 3),
                     total=round(time.monotonic()-started, 3))), indent=2)+"\n")
    sys.exit(0 if result.wasSuccessful() else 1)
