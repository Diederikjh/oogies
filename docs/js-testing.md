# JavaScript logic tests

These tests import production frontend functions directly into Node. They run
without a browser, server, recorder, SDK, npm dependencies or private configuration.
The initial 27 cases cover `safeCameraName()` in
[frame-download.js](../web/history/frame-download.js): unsafe characters, fallback
names, Unicode normalization and complete-code-point UTF-8 length limits.

This is milestone 1 of the [frontend test-layer plan](frontend-test-layer-plan.md).
Clip/range calculations and submission/confirmation state have not moved yet.
Existing browser assertions remain in place for this milestone. As logic moves,
unit tests own its rules and browser tests verify wiring and browser behavior.

## Run with existing native Node

Use native Node **22.x** and the existing Python 3.9+ launcher:

```sh
node --version
python3 tools/run_js_tests.py
python3 tools/run_js_tests.py tests/js/frame-download.test.mjs
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
The normal native run outside that sandbox and the Docker run both reported all
27 named tests. Use Docker when per-assertion reporting is needed in that context.

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
Python and browser/native jobs remain separate.

## Add logic coverage

Use `node:test` with `node:assert/strict` in `tests/js/*.test.mjs`. Import the
actual production module using a relative path with its extension. Explicit
`type: module` metadata in `web/package.json` allows Node to load those `.js`
files without a bundler or source rewriting. No npm install is needed.

Keep DOM rendering, canvas conversion, native events and layout in browser
coverage. Extract rules with plain input/output boundaries when needed; do not
create a simulated browser just to load a controller. Supply clocks and deferred
responses explicitly when the later asynchronous-state milestone begins.

The launcher's selection, runtime and failure/reporting safeguards have Python
regressions in [test_js_test_runner.py](../tests/test_js_test_runner.py). Those
tests run in the ordinary Python suite without requiring Node or Docker.
