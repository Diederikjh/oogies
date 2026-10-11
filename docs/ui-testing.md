# Offline UI tests

The browser suite exercises the actual frontend, HTTP handlers, live-session
sharing/expiry and multiplexed JPEG transport against a simulated recorder worker.
It uses Docker Chromium and generated JPEG/MP4 fixtures. No SDK archive, account,
private configuration or previous camera footage is needed. The container has
networking disabled and publishes no ports; tests use only its internal loopback.
The owner's running viewer and recorder are not used.

The export cases use the production job manager, HTTP routes, persistence and
FFmpeg encoder. The fake SDK boundary supplies ordered, timestamped YV12 frames
through the same bounded pipe protocol. Cases cover local marks/shading, paused
10/30-second steps and window limits, PNG colors and all aspect modes, a frozen
download across camera/settings changes, mobile controls, queue/cancel/download/
delete, newest-first ordering on returning from History and refreshing after
another viewer queues work, per-file failure/retry, and preserving another live tab while an export
waits for a slot. Host tests cover ranges, idempotency, FIFO/admission, restart,
retention, storage limits, active-download deletion, and HTTP byte ranges/410.
Circular export progress is checked against the fixture's actual capture progress,
including accessible values, completion/cancellation, mobile fit and reduced motion.
Real-recorder timing/coexistence evidence is separate in [clip exports](clip-exports.md).

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
modal keyboard/focus behavior, mobile fit, synthetic history timelines and
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

The fake worker substitutes at the Python worker boundary. The browser cases do not
exercise C++ callbacks, SDK authentication, decryption, discovery compatibility,
native process events or real recorder capacity. Keep the bounded real-recorder
checks for those claims. Chrome/Chromium is the currently tested browser engine.

Three additional Docker tests compile the production C++ playback buffer without
the SDK. They exercise decoder refusals, bounded lossless delivery from a fast
producer, and waking a blocked producer on stop. These run before the browser
cases in the same local/CI command, using the compiler already in the image.
Run just these regressions with `python3 tools/run_ui_tests.py test_native_playback`.
The Python fixture cannot reproduce native compressed-stream overflows.

The [first History slice](history-timeline.md) extends the same worker seam with
synthetic recording and motion intervals. It replaces the saved-clip case and
checks camera/range selection, offline inputs with recordings, point events,
previous/next motion selection, keyboard time selection, empty/unsupported/error
motion states, a pinned range/selection during Refresh, mobile fit and delayed
old responses. Navigation releases only this page's live lease while another
tab keeps moving. A fresh checkout needs no private MP4. Unit tests cover UTC,
midnight and ambiguous clock conversion, clipped intervals/stable IDs, bounded
queue/cache behavior, native response cleanup and HTTP parameter encoding.

The [interactive playback suite](history-playback.md) now checks moving frames
after time selection, pause/resume, paused seeking, one SDK seek per slider
commit, independent historical tabs, live plus history, offline cameras with
recordings, selected-camera aspect, and Settings opened before discovery finishes.
The fixture supplies decoded frames/clocks through the production worker/session
boundary; SDK compatibility and native resource behavior still use manual checks.

The camera-shortcut and speed cases verify selection of a non-default camera,
keyboard activation/focus, navigation to an offline camera's recordings,
0.5×/1×/2×/4× recorded-clock advancement, in-place controls, rate preservation
through seek/pause/resume, and a rejected rate retaining moving video. Unit
tests cover rate validation before SDK calls, native acknowledgement handling,
old request/generation rejection and independent viewer rates. The real check
`python3 tools/check_playback_rates.py` measures SDK clock advancement; the fake
decoder cannot establish actual native Fast/Slow behavior.

Date-navigation cases check recorder timezone despite a different browser zone,
cross-midnight date conversion, direct playback on the selected camera,
preserving a reserved slot and speed beside a full live grid, future/blank
validation preserving paused footage, delayed date responses after camera
changes, and mobile/keyboard use. Backend cases cover centred/clipped ranges,
minute/second input, DST ambiguity/gaps, strict HTTP query variants, shared UTC
cache entries and invalid range updates leaving sessions unchanged.

## Verified result

Direct date/time navigation passed all 60 unit tests and 41 Docker cases
(38 browser and three native buffer tests). The real browser date form started
footage at its exact requested recorded second and retained the session/4× speed
through a second date jump. Thirty uninterrupted seconds, all speeds, Pause and
Stop passed with one SDK login and zero historical sessions after cleanup.

The camera-shortcut/speed increment passed all 54 unit tests and 36 Docker cases
(33 browser and three native buffer regressions). The final shortcut keyboard
focus adjustment passed a targeted repeat. Real SDK clock measurements matched
all four rates, and a Docker browser exercised the new controls against moving
camera footage through the same SDK login, followed by Pause/Stop cleanup.

After the sustained-playback correction, all 50 unit tests and 33 Docker cases
passed (30 browser and three native buffer regressions). The real API check
ran 75 uninterrupted seconds with a concurrent live preview, normal recorded
clock advancement and working controls. The actual browser then played for
thirty seconds and confirmed Pause/Stop cleanup. See
[History playback](history-playback.md) for evidence and manual check commands.

Interactive playback passes 50 unit tests and the full 30-case browser suite,
including moving playback and delayed History settings. Real recorder checks
verified requested first-frame time, paused/resumed footage and playing/paused
seeks through one login. Docker Chromium also displayed actual SDK video with
the correct aspect and verified pause/Stop cleanup. A real live preview advanced
from 2 to 31 received frames while the full playback/control check ran; it
remained live with one SDK login. Wider capacity is still unverified.

The first History timeline slice passed all 40 unit and 24 Docker browser cases. Its native
SDK worker compiled and passed an offline decoder check. Real metadata queries
returned recording coverage, while a live/history-metadata coexistence check
kept camera frames advancing through one login. These checks do not establish
interactive playback controls or live plus historical video capacity.

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
