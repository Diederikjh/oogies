# Offline UI tests

The browser suite exercises the actual frontend, HTTP handlers, live-session
sharing/expiry and multiplexed JPEG transport against a simulated recorder worker.
It uses Docker Chromium and generated JPEG/MP4 fixtures. No SDK archive, account,
private configuration or previous camera footage is needed. The container has
networking disabled and publishes no ports; tests use only its internal loopback.
The owner's running viewer and recorder are not used.

## Run

Docker must work as the current user without sudo. Build the existing browser
image on the first run, or when its Dockerfile changes:

```sh
python3 tools/run_ui_tests.py --build
```

Subsequent runs:

```sh
python3 tools/run_ui_tests.py
```

Run one case while developing:

```sh
python3 tools/run_ui_tests.py test_viewer_ui.ViewerUITests.test_mobile_settings_and_expanded_picture_fit
```

A failing case returns a nonzero exit code and a traceback. Test outcomes and
screenshots are written to ignored `.local/ui-test-results/`, including
`ui-tests.json`. Screenshots are synthetic images. Results are overwritten on
subsequent runs. Host prerequisites are Docker and Python; browser libraries,
Selenium and FFmpeg remain in Docker. No Node.js, host pip packages or NVR setup
is needed. Existing unit tests remain separate:

```sh
python3 -m unittest discover -s tests -v
```

The UI directory intentionally has no package initializer, so host unittest
discovery does not import Docker-only Selenium dependencies.

## Coverage and boundaries

The suite checks eight simultaneous moving pictures and distinct camera identity,
offline labeling, capacity limits, individual stream failures and stale states.
It checks click/keyboard expansion, per-camera settings and persistence,
modal keyboard/focus behavior, mobile fit, synthetic recorded playback and
release of live subscriptions when changing views. Multiple tabs exercise shared
sources, Pause/Resume, refresh and closing an active tab. Lease tests suppress one
page's renewal timer and wait for its real ten-second lease while another page
renews its lease. A delayed discovery response exercises navigation during
initial loading.

Expansion tests sample intermediate tile sizes and picture proportions through
both expand and collapse, check that the focused picture fits in the viewport,
and verify manual wheel, keyboard, touch and independent scroll changes cancel
automatic following. Rapid reversals and reduced-motion preferences are covered.

The offline-recovery case uses production `GridWorker` availability cache/event
handling with a simulated SDK command transport and a controlled cache clock.
It verifies that a recovered camera remains offline at 59.999 seconds, then
starts moving in two already-open tabs at 60 seconds. It checks one shared
refresh, one recorder connection and no restarts of healthy streams. Host unit
tests additionally cover concurrent refresh callers, unsuccessful/unknown
status, preserving fresh video, confirmed offline transitions and no login
retries. No test waits a real minute for cache expiry.

[create_server](../docker/hikvision-sdk/grid_server.py) accepts an existing worker
and live-session manager. Production supplies `GridWorker`; tests supply
`FakeRecorderWorker`. No alternate recorder selector or test endpoints are
exposed by the production service. This is a small construction seam, not a
new recorder framework.

[fixture.py](../tests/ui/fixture.py) generates distinct colors and alternating
patterns, provides controllable worker states and uses the real live-session
manager. [test_viewer_ui.py](../tests/ui/test_viewer_ui.py) drives the browser;
[run.py](../tests/ui/run.py) records results. Each case uses a new browser profile,
server and worker; cleanup closes feeds, views, fixture threads and the browser.

The fake worker substitutes at the Python worker boundary. These tests do not
exercise C++ callbacks, SDK authentication, decryption, discovery compatibility,
native process events or real recorder capacity. Keep the bounded real-recorder
checks for those claims. Chrome/Chromium is the currently tested browser engine.

The proposed [History test changes](history-view-plan.md#test-changes) extend this
same worker seam with synthetic timelines and independent playback contexts.
They replace the saved-clip cases and add time selection, seeking, motion states,
selected-camera aspect and multi-viewer cleanup checks. These are planned tests,
not part of the currently verified suite.

## Verified result

After the expand/collapse refinements on 11 October, all 18 browser cases and
26 unit tests passed. The manual-input cases verify automatic scroll requests
stop during the transition while allowing native touch momentum; independent
scrollbar offsets are also preserved.

On 11 October 2026, all 14 browser cases and 26 host unit tests passed, including
the new one-minute offline-camera recovery case. The updated native bridge also
compiled against the bundled SDK and passed its offline decoder check without
network access or credentials.

On 10 October 2026, all 13 browser cases passed in Docker with networking
disabled and zero SDK logins. All 18 existing host unit tests also passed.
The delayed-discovery case found a real navigation race: returning to Live before
initial discovery completed could leave the page paused. The overview now queues
that requested start and lets Pause cancel it. The production recorder was not
contacted during this work.

## GitHub Actions

[ci.yml](../.github/workflows/ci.yml) runs on every push, pull-request creation or
update, and manual dispatch. A local commit triggers GitHub checks when it is
pushed; a push containing several commits tests the pushed revision. Every push
gets its own run; newer pushes do not cancel older runs.

Two independent Ubuntu 24.04 jobs use the same local commands:

- **Unit tests:** `python3 -m unittest discover -s tests -v`.
- **Offline UI tests:** `python3 tools/run_ui_tests.py --build`.

The workflow checks Docker access without sudo and skips Git LFS downloads.
The SDK pointer can stay unmaterialized because both suites use source/fixtures.
It requires no NVR credentials, repository secrets or private `.local/` setup.
Browser tests run with container networking disabled. The workflow has read-only
repository permissions, and action versions are pinned to release commit hashes.

The UI job attempts to upload its JSON report and PNG screenshots even when
tests fail. Look for the **ui-test-results** artifact in the workflow run; it
expires after 14 days. Only `.local/ui-test-results/ui-tests.json` and its PNGs
are selected. Hidden-file inclusion is enabled because the output lives under
`.local/`. Build failures before any results exist produce an artifact warning.
Job timeouts are five minutes for unit tests and twenty minutes for the image
build plus UI suite. The workflow runs tests; it does not deploy the service.

Commit the workflow together with the new UI test suite before pushing it to
GitHub. The CI configuration needs no additional setup files or LFS objects for
these checks. Hosted execution and artifact upload can be verified after the
repository is pushed and Actions is enabled.

References: [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push),
[checkout action](https://github.com/actions/checkout) and
[artifact action](https://github.com/actions/upload-artifact).

Local CI validation passed actionlint in Docker and both workflow commands from
a clean temporary source copy: 18 unit tests and 13 UI tests. The copy initially
contained no SDK, private configuration or prior output. The browser build reused
local Docker build layers; a hosted run will build on the runner. Actual GitHub
checkout/event dispatch and artifact upload await the first hosted execution.
