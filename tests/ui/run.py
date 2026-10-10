"""Run the Docker-only browser suite and save a machine-readable result."""
import json
import os
from pathlib import Path
import sys
import time
import unittest

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
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or ["test_viewer_ui"])
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReportResult).run(suite)
    output = Path("/output"); output.mkdir(parents=True, exist_ok=True)
    (output / "ui-tests.json").write_text(json.dumps(dict(tests=result.testsRun,
        passed=result.wasSuccessful(), cases=result.cases), indent=2)+"\n")
    sys.exit(0 if result.wasSuccessful() else 1)
