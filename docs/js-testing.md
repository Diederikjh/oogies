# JavaScript logic tests

These tests import production frontend functions directly into Node. They run
without a browser, server, recorder, SDK, npm dependencies or private configuration.
The 125 cases cover these production modules:

| Module | Logic covered |
| --- | --- |
| [frame-download.js](../web/history/frame-download.js) | Filename sanitization, fallback names, Unicode normalization and UTF-8 length limits |
| [clip-model.js](../web/history/clip-model.js) | Mark rounding, validity, configured duration limits, edit bounds and keyboard targets |
| [timeline-model.js](../web/history/timeline-model.js) | Selection, loaded/visible/seek domains, slider offsets and zoom bounds |
| [history-range.js](../web/history/history-range.js) | Recent/fixed windows, calendar/minute boundaries, Earlier/Later and motion navigation |
| [clip-export-state.js](../web/history/clip-export-state.js) | Pending guard, immutable requests, retry keys, exact confirmation expiry, invalidated replies and already-queued timer callbacks |

This follows milestones 1-3 of the [frontend test-layer plan](frontend-test-layer-plan.md). Unit tests own the logic
rules; browser tests verify wiring and browser-specific behavior.

## Run with existing native Node

Use native Node **22.x** and the existing Python 3.9+ launcher:

```sh
node --version
python3 tools/run_js_tests.py
python3 tools/run_js_tests.py tests/js/frame-download.test.mjs
python3 tools/run_js_tests.py tests/js/clip-model.test.mjs
python3 tools/run_js_tests.py tests/js/clip-export-state.test.mjs
```

The launcher checks the Node major version. It does not install or change Node.
If Node 22 is unavailable, use Docker below. Node is optional development tooling;
running the viewer does not require Node or npm.

## Run in Docker

Docker must work as the current user without sudo. Retrieve the pinned official
Node 22 image once, then run tests separately:

```sh
python3 tools/run_js_tests.py --docker --pull
python3 tools/run_js_tests.py --docker
python3 tools/run_js_tests.py --docker tests/js/frame-download.test.mjs
```

`--pull` only retrieves the image and exits. Test execution never pulls implicitly
and runs with networking disabled, read-only filesystem/source mounts, the current
UID/GID, one CPU, 256 MiB memory and a PID limit. Only `web/` and `tests/js/` are
mounted. Reports are written by the host launcher, so the container needs no
write access to the checkout or `.local/`. It needs neither the SDK nor browser
image. The immutable image reference is maintained in
[run_js_tests.py](../tools/run_js_tests.py).

Docker is also useful in agent execution environments that restrict native Node
child-process reporting. During development, the host agent sandbox reported
only file-level results; a deliberate failed assertion still returned nonzero.
Normal native execution outside that sandbox and Docker provide complete named
results. Use Docker when per-assertion reporting is needed in that context.

## Results and CI

Both modes stream TAP to the terminal and write
`.local/js-test-results/tests.tap`. Actual test runs overwrite that report, and
assertion/import/runtime failures return a nonzero exit code. Missing test files,
empty discovery and paths outside `tests/js/` fail before execution; setup errors
do not refresh a previous test report. Use the command exit status and output.

Tests are selected by `.test.mjs` file paths, not by arbitrary commands or helper
files. With no selection the launcher finds all such files under `tests/js/`.
It serializes test files and applies a ten-second Node test timeout to bound hangs.

The independent **JavaScript logic tests** GitHub Actions job uses the same
Docker commands, skips Git LFS retrieval and has a five-minute job timeout. It
attempts to upload the TAP report as **js-test-results**, even after a failure,
with 14-day retention. A setup failure before execution may have no report.
Python and browser/native jobs remain separate. The browser suite is organized
into live, History and export features; see [UI testing](ui-testing.md) for
feature selectors and the final multi-layer measurements.

## Add logic coverage

Use `node:test` with `node:assert/strict` in `tests/js/*.test.mjs`. Import the
actual production module using a relative path with its extension. Explicit
`type: module` metadata in `web/package.json` allows Node to load those `.js`
files without a bundler or source rewriting. No npm install is needed.

Keep DOM rendering, canvas conversion, native events and layout in browser
coverage. Extract rules with plain input/output boundaries when needed; do not
create a simulated browser just to load a controller. Supply clocks and deferred
responses explicitly. The small helpers in `tests/js/support/manual-time.mjs`
advance only the injected export clock; `takeDue()` lets tests dispatch callbacks
that were already queued when cancellation happened. No global timer, fetch or
Date replacement is needed.

The launcher's selection, runtime and failure/reporting safeguards have Python
regressions in [test_js_test_runner.py](../tests/test_js_test_runner.py). Those
tests run in the ordinary Python suite without requiring Node or Docker.
