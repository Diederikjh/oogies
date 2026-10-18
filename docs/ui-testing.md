# Offline UI tests

The browser suite exercises the actual frontend, HTTP handlers, live-session
sharing/expiry and multiplexed JPEG transport against a simulated recorder worker.
It uses Docker Chromium and generated JPEG/MP4 fixtures. No SDK archive, account,
private configuration or previous camera footage is needed. The container has
networking disabled and publishes no ports; tests use only its internal loopback.
The owner's running viewer and recorder are not used.

The [frontend test-layer plan](frontend-test-layer-plan.md) describes moving
logic matrices into JavaScript unit tests while preserving browser wiring,
input, layout and API/media integration coverage. Milestones 1-3 now provide
[125 JavaScript logic tests](js-testing.md) for filenames, clip/timeline/range
calculations and export submission/feedback state. Browser tests verify how the
UI reaches those rules and displays their results.

Milestone 3 removes two redundant browser cases after direct expiry/response-order
coverage and retained wiring checks pass. There are now **87 browser/four native
cases**. The real animation/reduced-motion, queue/link/download, camera reset,
pending POST/Clear marks, progress and independent-job checks remain. The held
POST case acknowledges completion through the enabled Save button instead of a
fixed 100 ms delay. Browser-global confirmation timer replacement is removed;
exact 60-second expiry and already-queued callbacks use an injected manual clock
in Node.

The full pre-extraction `ab2dd80` baseline passed 93 cases in 943.3 seconds from
an immutable source snapshot. Milestone 2's 15 focused browser cases passed in
143.1 seconds. Milestone 3's seven retained export/history checks passed in
93.8 seconds, followed by four final checks in 31.1 seconds (ten distinct cases
across both runs). All 125 JavaScript and 134 Python cases pass. The complete
updated 91-case browser/native suite now passes under the same `--build`
command as CI: 894.911 seconds of suite time and 895.336 seconds including the
single 0.400-second media setup and cleanup. The run has 87 browser/four native
cases and no retries/skips. Native-only selection separately passes with zero
media generations. The earlier baseline took 943.285 seconds; this single local
comparison differs in order/host activity and is not a causal speedup claim.
The 125 JavaScript cases take 329.5/547.4 ms of Node time in native/Docker modes;
the warm Docker launcher takes 4.234 seconds. Python's 134 cases pass in 8.1 s.
Hosted Actions execution awaits a push. See the
[milestone-3 migration](frontend-test-layer-plan.md#milestone-3-submission-and-feedback-ownership)
and [milestone-4 results](frontend-test-layer-plan.md#milestone-4-browser-organization-and-final-measurement)
for coverage, environment and local evidence.

## Pending-reply Stop timeout and input timing

The later failure in
`test_live_quality_pending_reply_cannot_modify_replacement_lease` has the same
interaction pattern as the two-main failure below: change a tile's expansion,
wait for network/media state, then click Stop with a pointer. Neither wait
guarantees that animation/focus scrolling has finished. The earlier adjustment
covered the two-main tests but left this Stop click unchanged. Frontend source
is unchanged between the passing `900483a` and this investigation; a single
passing CI run does not rule out a timing race.

Three unmodified reruns passed in 19.0 seconds. Their event traces show Stop
activation during animation, with scrolling between the action request and
pointer press. A controlled probe with early polling and a 400 ms pause between
pointer movement and press reproduced the timeout: Stop moved up 148 pixels,
the click landed on a camera button, no DELETE was issued, and the fixture
retained one viewer/nine sources with no native stops. This demonstrates a
concrete input-timing mechanism with the reported backend signature. The exact
CI event sequence remains unconfirmed because that run did not record inputs.
The `animating:0` in its timeout diagnostic describes the page twelve seconds
after the action, not its state when the click was attempted.

The pending-reply test now uses the existing native Enter/pause-acknowledgement
helper. Collapse and Resume also use native Enter, retaining the held response
until after the replacement lease is established. The media-reconnect pause
case uses the same pause helper. Assertions for cleanup, new lease identity and
rejection of the old reply remain; dedicated mouse/animation tests retain their
pointer coverage. No application code, retries, sleeps or timeouts changed.

A private probe passed three times in 26.5 seconds with 20-times-lengthened
animation and early polling. It asserts that Stop's native keyboard click and
the successful DELETE occur during active animation, and that viewer/source
counts reach zero before resuming with the old reply still held. Logs/traces:
`.local/stop-pending-baseline.log`, `.local/stop-pending-delayed.log`,
`.local/stop-pending-keyboard-motion.log` and
`.local/stop-click-investigation/pending-*.json`.

The final focused run passed all 12 executions in 102.0 seconds: three reruns of
the reported replacement-lease test, both two-main capacity/ownership cases,
delayed reply/decode cases, media pause/reconnect, and four pointer/animation
cases. Log: `.local/stop-pending-focused-ui.log`; report:
`.local/stop-pending-focused-ui-report.json`. Input artifacts were also checked
for bounded records, native Enter activation, a successful DELETE and creation
of the replacement session. The full suite was not repeated for this test-only
change; the preceding full result remains recorded below.

Temporary input/request tracing helped establish the mechanism above. It has
now been removed from test setup, teardown and CI artifacts; keyboard interaction
fixes and compact backend/page timeout diagnostics remain. The design and steps
for using it again are preserved in [UI input tracing](ui-input-tracing.md).
After removal, the replacement-lease, two-main sharing and media-pause cases
passed again (three tests in 31.6 seconds). Log:
`.local/stop-trace-removal-ui.log`.

## Two-main Stop timeout in CI

CI at `0f3bf9f` timed out waiting for zero viewers/sources after the final Stop
pointer click in `test_two_distinct_high_streams_share_and_release_independently`.
This occurred after an animated collapse; the backend/paint assertions preceding
Stop had passed. The test's Stop interaction was unchanged through the later
capacity refactor, committed as `3021d42`.

Three unmodified local reruns and two private motion/pointer-delay probes passed.
Both probes delivered Stop clicks and cleaned up correctly. The exact CI cause
was therefore not reproduced; animation-related input timing remains a
hypothesis, and the supplied traceback alone cannot distinguish a missed
activation from delayed cleanup. No application or backend change is based on
that hypothesis.

The two-main ownership/capacity tests now activate the real Stop button with
Enter, then require the page's "View paused" state and disabled Stop control
before checking unchanged backend resource counts. Keyboard activation makes
these ownership assertions independent of pointer coordinates during focus
scrolling. Dedicated pointer, animation and manual-scroll cases remain intact.
There are no new retries, sleeps or increased timeouts. Resource waits read one
atomic fixture snapshot per poll and include expected/last counts plus page
summary, Stop state, active-animation count and scroll position on timeout.

Seven focused cases passed in 73.8 seconds: the reported test three times, the
adjacent seven-overview/two-main budget case, and three animation/manual-scroll
cases. Logs are `.local/stop-click-baseline.log`, `.local/stop-click-motion.log`,
`.local/stop-click-motion20.log` and `.local/stop-click-focused-ui.log`.
Private diagnostic scripts/traces are in `.local/stop-click-investigation/`.
A final keyboard-input probe with 20-times-lengthened animation passed in 16.2
seconds, recording Stop activation while animation was still active and final
counts of zero viewers/sources. A deliberately impossible resource wait verified
the enriched timeout message against the real browser and fixture. Its log is
`.local/stop-keyboard-motion.log`; the expected error is recorded privately as
`.local/stop-click-investigation/expected-timeout.txt`.
The complete suite was not rerun for these test-only changes; task 2's preceding
full 93-case pass is preserved separately below.

## Shared-capacity refactor verification

Task 2 migrates the fixture to an identified shared stream budget and neutral
application maintenance. A new case holds capture active while the user seeks,
changes History camera and closes that tab, then verifies that the immutable
export completes in another tab with reservations released. It passed alongside
two-main capacity and live/export coexistence checks. The expanded suite contains
93 browser/native cases; the complete run passed all 93 in 887.7 seconds
(89 browser/four native). Its full report is retained privately as
`.local/task2-full-ui-report.json` and its log as `.local/task2-full-ui.log`. The separate backend
suite passes 127 cases, including contention, stale handles, delayed live stops,
playback expiry without live viewers, independent cancellation and export faults.

Compact History cases check that video, seeking, speed and mark/export controls
stay inside the laptop/desktop viewport, including an active clip and queue
confirmation. A long motion list scrolls without moving the video or page, and
its last event still seeks correctly. Keyboard opening/Escape, outside clicks,
navigation dismissal and date draft retention are checked. Fresh mobile loads
start with collapsed events; timeline selection, event expansion/selection,
paused stepping and marking remain usable without horizontal overflow. Existing
date cases also verify successful submission closes the picker and invalid
dates keep the error visible without disturbing playback.
Visibility inside native closed `<details>` uses Chromium's `checkVisibility()`;
the installed Selenium version reports those unpainted descendants as visible.
Milestone 2's complete local run passed 84 cases: 80 browser cases, three native
buffer regressions and one live-quality/frame-bounds native case, using the same
command as GitHub Actions. Milestone 3 expands this to 90 cases (86 browser/four
native). The previous complete run passed all 90 in 849.6 seconds after the owner's
repository-wide en-dash-to-hyphen replacement. Its initial run passed 89; a capacity test clicked while another tile was
still animating and timed out awaiting a collapse that never occurred. That test
now waits for settled geometry and verifies its click; three consecutive reruns
passed. All six final reliability cases passed targeted runs, including paused
reconnection, a response-header timeout and terminal History cleanup; all also
passed the subsequent full rerun. The separate backend suite passed all 97 cases.
The subsequent two-main experiment adds a browser case covering distinct high
sources, sharing across tabs and independent release; its focused run passed.
The expanded suite has 91 browser/native cases and has not been rerun in full.
The complete backend/monitor suite now passes 100 cases, including two-source
admission and Docker monitor startup/exit races.
An additional case reproduces the seven-overview/eight-total-source constraint
with a high-quality cap of two, checks the distinct total-budget refusal label,
and confirms that an explicit retry admits both mains after capacity increases.
It passed alongside the shared-two-main and high-quality-cap refusal cases.
The expanded browser/native suite now contains 92 cases; it has not been rerun
in full since adding these capacity cases.
Confirmation feedback coverage samples the real browser animation for its fade,
vertical bounce and settled state, then checks repeated saves, cancellation on
Clear marks, reduced motion and keyboard navigation to export jobs.
Clip-label coverage checks that Start/End sit between the bars and adding or
clearing them preserves both bar geometry and preview size. Mouse, touch and
keyboard editing use the same dedicated strip, retaining duration/order limits
and metadata-refresh behavior without seeking playback.
Collapsed Motion events coverage checks that the heading fits inside its panel
without a scrollbar at desktop, narrow desktop and phone widths. Keyboard
expansion/collapse preserves playback and reveals/hides the event list.
Speed/seek concurrency coverage holds a rate-change response after the backend
applies it, seeks through the still-interactive slider, and checks that the
requested rate survives both seeking and the delayed acknowledgement. A failed
speed request restores the confirmed rate for subsequent seeking. Boundary-step
checks wait for browser readiness and a new playback generation, keeping the
rate assertions and avoiding backend-only synchronization.
The offline-camera range case controls only the browser's `Date.now()` and
checks Recent both within a minute and across recorder midnight/New Year.
It verifies the exact recorder query bounds; HTTP, cache, lease and animation
timers remain real, so CI does not depend on when the case happens to run.

Live-quality API coverage opens two high-quality viewer leases for one camera
while the ordinary grid remains at overview quality. The browser decodes the
actual multiplexed JPEG feed and checks its larger raster and inverted fixture
colors, one shared high source, capacity fallback for a different camera and
independent release. Expansion cases now verify actual upgraded images and labels,
moving overview while high frames are gated, collapse, refused/disabled/unsupported/
offline inputs, decoder failures and stalls. Controlled delayed GET/PATCH replies
and JPEG decode completion check revision/generation/lifecycle guards. A lost
reply releases unconfirmed upgrades but preserves an acknowledged high source;
shared-tab expiry keeps the remaining viewer moving. Mobile/keyboard/reduced-motion
cases and existing animation/rapid-toggle checks exercise successful upgrades.
Known refused cameras are not retried by another camera change. Host tests use
the real worker/session logic with a substituted native command transport to
cover admission races, delayed native stops, failed/stalled upgrades, generations,
lease expiry, bounded diagnostics, and contention with history/export reservations.
Scoped retry validation and a failure between browser polls exercise the optional
`retry_high` API contract without changing the legacy full-selection behavior.
The native bounds case checks SDK main/substream selection and supported YV12
sizes, including accepting a common 4K raster and rejecting oversized/malformed
frames. Real SDK/device compatibility is verified separately.

Reliability cases inject a wrapper at the browser fetch boundary while retaining
the actual HTTP server, session manager and synthetic worker. Clean EOF and a
read error recover the same high-quality source without another lease or native
start. A feed that silently discards received bytes makes the tile/summary stale
before the watchdog reconnects it. Repeated EOF exhausts the three retries,
releases sources and allows manual Resume; a forbidden media response stops
without authentication retries. Pause and navigation cancel backoff. History
recovers independently while another tab stays at high quality, retains its
playback generation, and can remain paused beyond the media watchdog timeout.
Paused-media recovery also survives a ten-second response-header timeout; terminal
failure releases its reservation while the other high-quality view keeps moving.
The helper lives in [browser_feed_fault.js](../tools/browser_feed_fault.js) and is
installed explicitly by the Docker browser; it is not a production test endpoint.
An HTTP unit regression closes a quiet feed, verifies the handler counter returns
to zero while the lease remains active, and reconnects that lease without another
native source start. This models paused/offline delivery without adding protocol
heartbeats or relying on a recorder.
Real SDK/resource measurements remain in the separate explicit
[reliability check](live-grid.md#reliability-and-resource-checks), never CI.

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
python3 tools/run_ui_tests.py test_live.LiveUITests.test_mobile_settings_and_expanded_picture_fit
python3 tools/run_ui_tests.py test_history.HistoryUITests.test_history_camera_ranges_include_offline_inputs
python3 tools/run_ui_tests.py test_exports.ExportUITests.test_history_export_queue_download_and_delete
```

To run a whole feature, select `test_live`, `test_history` or `test_exports`.
The old `test_viewer_ui.ViewerUITests` selectors have moved; method names remain
unchanged. Default selection runs all three features and `test_native_playback`.
Use the launcher above so runner-scoped media setup is performed.

A failing case returns a nonzero exit code and a traceback. Test outcomes and
screenshots are written to ignored `.local/ui-test-results/`, including
`ui-tests.json`. Screenshots are synthetic images. Results are overwritten on
subsequent runs. The JSON includes per-case seconds, browser count, number of
media generations and `seconds.media_setup`, `seconds.suite` and `seconds.total`.
Total includes media setup and cleanup; the unittest terminal summary measures
only the suite itself. Native-only selections skip media generation.
Host prerequisites are Docker and Python; browser libraries,
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
manager. The browser cases live in three feature modules:

| Module | Cases | Owns |
| --- | --- | --- |
| [test_live.py](../tests/ui/test_live.py) | 36 | Live grid, quality, reconnects, sharing, expansion and settings |
| [test_history.py](../tests/ui/test_history.py) | 31 | Timeline, dates, playback, seeking/speed and History layout |
| [test_exports.py](../tests/ui/test_exports.py) | 20 | Clip marks/editing, frame downloads, submission feedback and export jobs |

[browser_support.py](../tests/ui/browser_support.py) contains the shared base,
fixture options and assertions; it has no test methods. Method names, fixture
options and initial window sizes are preserved. [run.py](../tests/ui/run.py)
loads each module once and explicitly generates media once for the selected
browser cases. Only generated input media is shared across classes within that
run; each case still uses a new browser profile, server and worker. Cleanup closes
feeds, views, fixture threads and the browser; runner exit removes the media.
Native-only selection needs no generated media.

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
A fourth native case compiles the production live-quality/frame-size helper and
checks main/substream mapping, valid larger rasters and invalid/oversized frames.

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

Three independent Ubuntu 24.04 jobs use the same local commands:

- **Unit tests:** `python3 -m unittest discover -s tests -v`.
- **JavaScript logic tests:** `python3 tools/run_js_tests.py --docker --pull`,
  then `python3 tools/run_js_tests.py --docker`.
- **Offline UI tests:** `python3 tools/run_ui_tests.py --build`.

The workflow checks Docker access without sudo and skips Git LFS downloads.
The SDK pointer can stay unmaterialized because all suites use source/fixtures.
It requires no NVR credentials, repository secrets or private `.local/` setup.
Browser tests run with container networking disabled. The workflow has read-only
repository permissions, and action versions are pinned to release commit hashes.

The UI job attempts to upload its JSON report and PNG screenshots even when
tests fail. Look for the **ui-test-results** artifact in the workflow run; it
expires after 14 days. Only `.local/ui-test-results/ui-tests.json` and its PNGs
are selected. Hidden-file inclusion is enabled because the output lives under
`.local/`. Build failures before any results exist produce an artifact warning.
The separate JavaScript job uploads `.local/js-test-results/tests.tap` as
**js-test-results**, also with 14-day retention; see [JavaScript testing](js-testing.md).
Job timeouts are five minutes for Python/JavaScript tests and twenty minutes for the image
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
