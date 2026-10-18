# Target 3: faster frontend logic tests below the browser layer

Status: **milestones 1-4 implemented, verified and reviewed; target 3 complete**.
Reviewed: 18 October 2026 (Africa/Johannesburg).
Prepared: 17 October 2026 (Africa/Johannesburg).
Baseline: `9e61f20`.
Parent: [architecture refactoring targets](refactoring-targets.md).

## Milestone 1 implementation and verification

Committed the approved plan as `8e60f84` before implementation. The first slice
adds [the runner](../tools/run_js_tests.py), explicit ES-module metadata,
[27 filename cases](../tests/js/frame-download.test.mjs), a separate JavaScript
CI job and [setup/test documentation](js-testing.md). Tests import the existing
`safeCameraName()` directly; no production function or browser assertion moved.

Native Node 22 and the pinned offline Docker runtime both pass all 27 tests.
Measured Node test durations were 74.7 ms native and 95.8 ms Docker; the warm
launcher totals were about 0.16 s and 3.97 s respectively. Deliberate failed
assertions returned exit 1 with TAP evidence in both modes, followed by clean
passing runs. Seven Python runner safeguards cover empty/missing/outside
selections, unsupported runtimes, nonzero failure propagation and report refresh.
All 134 Python tests pass (8.7 s). Three unchanged browser cases verify unsafe
camera-name downloads, PNG contents and original/preset proportions (30.0 s).

The agent's native execution sandbox exposed file-level TAP instead of named
assertions; deliberate failure still returned nonzero. Native execution outside
that sandbox and Docker produced the complete per-assertion results. This is
documented as an environment/reporting limitation, without modifying the runner
to use experimental isolation flags or changing application code.

Evidence: `.local/js-m1-{native,docker}.log` and matching `.tap` files,
`.local/js-m1-failure-{native,docker}.{log,tap}`, `.local/js-m1-backend.log` and
`.local/js-m1-browser.log`. The GitHub job is configured with the same verified
Docker commands; hosted Actions execution awaits a push. No SDK login, recorder
access or service restart was performed. The full browser baseline is still
required before milestone 2 removes/migrates browser assertions.

Milestone 1 was reviewed and committed as `ab2dd80` before milestone 2 started.
Milestone 2 was committed as `72f8d87` before milestone 3 started. The approved
design below remains the behavioral contract.

## Milestone 2 extraction and coverage

The DOM controllers delegate their calculations to three production modules:

| Module | Explicit inputs and outputs | Direct test coverage |
| --- | --- | --- |
| `clip-model.js` | Frame/mark timestamps, loaded bounds, maximum seconds, key/Shift; returns rounded marks, status, bounds and edit targets | Missing/equal/reversed/overlong marks, floor versus nearest-second rounding, four edit directions, 600/120-second limits, year-2000 floor and repair |
| `timeline-model.js` | Loaded/visible ranges, selected time, marks, center/width; returns selection/slider offset, seek intersection, domain and zoom window | End-exclusive selection, positions outside zoom, partial/empty seek ranges, finite/partial marks, 60-second zoom, padding, alignment and unchanged SDK bounds |
| `history-range.js` | Supplied clock, hours, Recent/fixed endpoint and motion intervals/direction; returns window or motion timestamp | Minute/day/month/year changes, fixed Refresh windows, current-time ceiling, equal event starts, empty results and unchanged interval order |

The modules have no DOM, network or owned timers. `ClipSelection`, `Timeline`
and `HistoryView` keep event handling, rendering and request lifetimes. The HTTP
asset allowlist explicitly serves the new relative imports. Recorder-zone/DST
resolution and playback control state remain in their existing owners.

Raw marking still permits invalid clips; only editing clamps to valid bounds.
Visible zoom and loaded/SDK playback ranges stay separate. The full browser
baseline uses an immutable `ab2dd80` source snapshot, unaffected by workspace
edits. Browser assertions are tightened after their unit coverage passes; the
baseline result and post-extraction wiring checks must pass before review.

Five browser cases now retain their wiring/presentation checks while their rule
matrices live in Node. No browser case IDs were removed (89 browser/four native
checks remain); smaller browser flows are not yet a reduction in browser startup
cost. Export feedback/response-ordering cases remain untouched for milestone 3.

| Browser case | Logic coverage now in Node | Retained browser wiring/presentation |
| --- | --- | --- |
| Unsafe camera-name frame download | `frame-download.test.mjs`: full filename-component matrix | Real camera-name snapshot reaches an actual downloaded PNG filename |
| Offline camera history ranges | `history-range.test.mjs`: minute/calendar transitions, fixed/Recent windows, navigation ceiling | Offline camera selection, range selector, Earlier/Later/Recent, SDK timezone and returned UI range |
| Mobile clip bounds | `clip-model.test.mjs`: unset/equal/reversed/overlong validity | One invalid range reaches disabled Save clip and long feedback fits the mobile layout |
| Clip dragging and zoom controls | `clip-model.test.mjs` and `timeline-model.test.mjs`: four edit directions, order/duration limits, zoom arithmetic | A native drag updates a marker; zoom-out/full-range controls work; SDK seek/generation and current time stay unchanged |
| Keyboard clip repair | `clip-model.test.mjs`: Home/End/arrow/Shift targets, reversed and overlong repair | Native key repairs the UI selection, enables Save clip and retains marker focus without an SDK seek |

Verification:

- Full pre-extraction baseline from `ab2dd80`: all 93 browser/native cases pass
  in 943.3 seconds. Sources were archived before edits and mounted independently.
- All 104 JavaScript cases pass in native Node and the pinned offline Docker
  runtime (77 added cases). Node-reported durations are 300.3 ms and 485.6 ms.
- All 134 Python tests pass in 9.1 seconds. An offline HTTP check also verified
  the new module routes, MIME types and bytes with no recorder queries/sources.
- After extraction, all 15 focused browser cases pass in 143.1 seconds, covering
  the five tightened cases plus configured limits, touch/refresh, zoomed SDK
  bounds, camera reset, motion selection, fixed Refresh, mobile selection,
  one-seek slider wiring, moving playback and recorder-zone date navigation.

The matching 15 baseline cases totalled 144.12 seconds versus 142.66 seconds
after extraction. These observations differ in run/order and host activity and
do not establish a meaningful browser speedup. The immediate gain is 104 direct
logic cases executable in under a second of Node time; browser startup costs
remain. The complete updated browser suite was not repeated for this milestone;
full post-migration measurement remains part of milestone 4.

Evidence: `.local/js-m2-baseline-browser{.log,-report.json}`,
`.local/js-m2-model-{native,docker}.log`, `.local/js-m2-model-docker.tap`,
`.local/js-m2-backend.log`, `.local/js-m2-assets.log`,
`.local/js-m2-focused-browser{.log,-report.json}`, `.local/js-m2-comparison.json`
and `.local/js-m2-migration-inventory.json`.

Milestone 2 was reviewed before proceeding to milestone 3. The viewer was
subsequently restarted at the user's request; the page and all three new module
routes returned HTTP 200, with the expected JavaScript MIME types and source
bytes. No recorder probe was needed for this check.

## Milestone 3 submission and feedback ownership

Committed the reviewed milestone 2 as `72f8d87` before implementation.
`ClipExportState` now owns the pending guard, retry identity, feedback generation
and confirmation timer. Its inputs are a flat export body and camera name;
posting, key generation, scheduling/cancellation and state notifications are
injected. Production defaults still use browser UUIDs/timers. `ClipSelection`
validates the marks, reads display preferences and renders the published state,
including the link, bounce animation and reduced-motion policy. A guard-only
update retains the feedback object's identity, avoiding a second animation.

The submitted camera/range/aspect/name are captured before awaiting the request.
Clearing feedback invalidates responses and timers without releasing a pending
submission or cancelling a backend job. Success clears retry identity even if
its feedback was invalidated; failure keeps the key for an identical retry.
Errors retain their existing non-expiring behavior.

Twenty-one direct cases in `clip-export-state.test.mjs` cover pending duplicate
suppression, immutable request data, retry keys for unchanged/changed requests,
repeat saves, synchronous/asynchronous errors, exact 59,999/60,000 ms expiry,
late success/error after clearing and stale callbacks facing pending/success/
error/cleared feedback. The small manual scheduler can remove a due callback
from its queue before invoking it, reproducing cancellation after dispatch was
already queued. Tests use no real sleeps or global timer/fetch/Date replacement.

| Browser coverage change | Direct replacement | Retained integration |
| --- | --- | --- |
| Remove `test_history_export_confirmation_clear_and_one_minute_expiry` | Exact expiry, cancellation, queued callback and repeat-save cases | Queue/link/download flow and animation case cover successful rendering, Clear marks and repeated saves |
| Remove `test_history_export_confirmation_navigation_ignores_delayed_response` | Late success/error invalidation and pending guard | History hide dismisses feedback through the Exports link; one held POST/Clear marks regression remains |
| Tighten `test_history_export_confirmation_clear_ignores_delayed_response` | Response order matrix belongs to Node | Real POST carries the idempotency key into the backend; new marks cannot enable Save while pending; releasing the reply enables Save without restoring feedback or duplicating the job |
| Extend `test_history_clip_marks_steps_and_camera_reset` | State invalidation belongs to Node | Selecting another camera clears successful feedback and marks while the export completes |

The held-reply browser case now waits for the enabled Save button to acknowledge
completion instead of sleeping 100 ms. Animation/reduced-motion checks, actual
MP4 downloads, export progress, cross-tab job independence and mobile layouts
remain browser coverage. The migration inventory records exactly two removed
browser IDs: 87 browser/four native cases remain, with no new skips or retries.

Verification:

- All 125 JavaScript cases pass in native Node and the pinned offline Docker
  runtime (21 added cases); Node-reported durations are 335.4/545.1 ms.
- All 134 Python tests pass in 8.5 seconds with localhost socket access. The
  initial sandbox-only attempt could not create sockets for seven HTTP cases;
  rerunning with socket access passed without changing tests.
- Seven retained export/history browser cases pass in 93.8 seconds before
  removing the duplicate timer/navigation cases. A final four-case run passes
  in 31.1 seconds, covering the updated idempotency-header/held-reply case plus
  compact workspace, mobile bounds and API-configured duration limits. This is
  11 executions of ten distinct browser cases.
- The full remaining 91-case browser/native suite was not repeated. Milestone 4
  still owns that run, feature-file organization and complete timing comparison.

Evidence: `.local/js-m3-{native,docker,backend}.log`,
`.local/js-m3-docker.tap`, `.local/js-m3-focused-browser{.log,-report.json}`,
`.local/js-m3-final-browser{.log,-report.json}` and
`.local/js-m3-migration-inventory.json`. Milestone 3 was reviewed and committed as `d2b0ab0` before milestone 4. The service restart/static readiness check is recorded in `progress.md`.

## Milestone 4 browser organization and final measurement

Committed milestone 3 as `d2b0ab0` before this mechanical split. The remaining
87 browser method bodies, all retained helper bodies, fixture options and
initial window sizes match that commit structurally. The four native cases are
unchanged. No assertions moved or disappeared in this milestone; milestones 2-3
above account for the earlier rule migration and two removed browser cases.

| Feature module/class | Cases |
| --- | --- |
| `test_live.LiveUITests` | 36 |
| `test_history.HistoryUITests` | 31 |
| `test_exports.ExportUITests` | 20 |
| `test_native_playback.NativePlaybackTests` | 4 |

`browser_support.py` contains setup, fixture options and shared helpers with no
test methods. Docker discovery yields exactly 91 unique IDs matching
`.local/js-m4-migration-inventory.json`; there are no inherited duplicate cases.
`run.py` explicitly owns one temporary `SyntheticMedia` generation for the
selected browser cases and removes it at runner exit. Each browser profile,
server and worker remains fresh per case. Native-only selection skips that
media setup. This preserves the previous single media generation without a
persistent cache or recorder/browser state shared across tests.

The JSON report now separates media setup, suite execution and total seconds,
and records browser count and media generations. Total includes media cleanup;
the terminal unittest duration excludes the media preparation now owned by the
runner. The comparison below uses total time against the pre-extraction full
baseline, not per-case sums alone. Docker limits remain two CPUs, 2 GiB, 512 PIDs
and no network. The rebuilt local image uses Chromium/ChromeDriver 154.0.8037.92,
Python 3.11.2, FFmpeg 5.1.9 and x86-64; host Docker is 29.9.0. Exact image/version
metadata is under `.local/js-m4-environment.json`.

Final local verification uses the same commands as CI:

| Layer / command | Cases | Result and time |
| --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | 134 | Pass, 8.1 s (host Python 3.12.3) |
| `python3 tools/run_js_tests.py` | 125 | Pass, 329.5 ms of Node time (native 22.14.0) |
| `python3 tools/run_js_tests.py --docker` | 125 | Pass, 547.4 ms of Node time; 4.234 s warm launcher (pinned Node 22.23.3) |
| `python3 tools/run_ui_tests.py --build` | 87 browser + 4 native | Pass, 894.911 s suite; 895.336 s total |

The media inputs are generated once in 0.400 s. A native-only selector separately
passes all four cases with zero media generations. All 91 executed IDs match
the discovery/migration inventory, are unique and report success. The only IDs
removed since the 93-case `ab2dd80` baseline are the two milestone-3 cases whose
rules now have direct JavaScript coverage.

The baseline took 943.285 s versus 895.336 s including setup now. These are single
local observations with different case order and host activity; they do not
establish a causal speedup or hosted pipeline duration. Browser startup and
integration costs remain. The concrete feedback improvement is 125 direct rule/
state cases executable in under a second of Node time (under five seconds through
the warm Docker launcher in this run). Image retrieval/build time is excluded
from that JavaScript measurement. Hosted Actions execution awaits a push.

Evidence: `.local/js-m4-{backend,native,docker,full-browser}.log`,
`.local/js-m4-docker.tap`, `.local/js-m4-full-browser-report.json`,
`.local/js-m4-native-only{.log,-report.json}`, `.local/js-m4-collected.json`,
`.local/js-m4-migration-inventory.json`, `.local/js-m4-environment.json` and
`.local/js-m4-comparison.json`. There are no new skips, retries, longer waits,
runtime tracing, host dependencies or recorder-dependent CI. Milestone 4 was
reviewed on 18 October 2026; all four milestones of target 3 are complete. Playback
ownership/rendering separation and deeper live/feed extraction remain deferred.

## Goal and boundaries

Exercise frontend rules and asynchronous state directly in JavaScript, with
controlled time and responses. Keep real browser coverage for input, layout,
rendering and representative API/media integration. Test the production code;
do not translate its rules into Python or keep a second implementation in tests.

The last complete run passed 93 browser/native cases in 887.7 seconds. That is
historical evidence, not a measurement of the final reduced suite. The recent
[Stop investigation](ui-input-tracing.md) also shows why network-state assertions
should not require correctly timed pointer coordinates.

This first implementation covers filename rules, clip/timeline/range arithmetic
and clip-export submission/confirmation state. It does not redesign playback,
live quality, JPEG parsing or backend capacity. Their browser and Python/native
regressions remain. Playback ownership/rendering separation is still target 4.

## Test layers after the change

| Layer | Owns | Execution |
| --- | --- | --- |
| JavaScript logic | Bounds, range/zoom calculations, filename rules, submission/confirmation transitions and response order | Node, no browser/server/SDK |
| Python backend | Validation, timezone resolution, sessions, capacity, export jobs, persistence and HTTP behavior | Existing unittest suite |
| Browser integration | DOM wiring, native mouse/keyboard/touch, accessibility, layout/scrolling, canvas/downloads, media and representative races | Existing offline Selenium/recorder fixture |
| Native bridge | Protocol/decoder buffer and source-limit behavior | Existing Docker native cases |

Once logic is covered by Node or other unit tests, browser tests only need to
verify the wiring: user interactions reach the tested logic, and its results
reach the UI. They do not need to repeat the full rule or its boundary cases.
One browser flow can cover several wiring paths; there is no requirement for a
browser case per extracted rule. Backend validation stays independently tested;
client validation cannot replace it.

## Runner and source loading

Use Node's built-in `node:test` and `node:assert/strict`. There is already native
Node 22 on the development machine. Start with Node 22 for both local and CI
execution, without npm dependencies, a bundler or a simulated DOM. Node documents
the stable [test runner](https://nodejs.org/download/release/latest-jod/docs/api/test.html)
and [ES module package rules](https://nodejs.org/api/packages.html).

Proposed layout:

```text
web/package.json                       # private, type: module; no dependencies
web/history/clip-model.js              # arithmetic, not DOM or HTTP
web/history/timeline-model.js          # view/seek domains and zoom arithmetic
web/history/history-range.js           # recent/fixed windows, event navigation
web/history/clip-export-state.js        # submission and feedback lifetime
tests/js/*.test.mjs                     # import the production modules directly
tests/js/support/manual-time.mjs        # small clock and deferred-promise helpers
tools/run_js_tests.py                   # native runner; explicit Docker option
```

Paths are proposed boundaries, not a requirement to create empty abstractions.
Keep related arithmetic together rather than introducing a generic state-machine
framework or a file for each one-line expression.

Add `web/package.json` with `private: true` and `type: module` so Node treats
the existing `.js` files explicitly as ES modules. Test files use `.mjs`.
Browser modules continue to be served directly. New helper imports use relative
paths with extensions; existing absolute browser imports need not be rewritten
across the application. Pure modules must be importable without DOM globals.
Do not use custom import loaders, copied source, source-text rewriting or VM eval.

Runner commands (implemented in milestone 1):

```sh
python3 tools/run_js_tests.py
python3 tools/run_js_tests.py tests/js/frame-download.test.mjs
python3 tools/run_js_tests.py --docker --pull
python3 tools/run_js_tests.py --docker
```

The default uses an existing native Node 22 and verifies its major version.
If unavailable, explain the Docker option; never install host packages
automatically. The Docker option uses a small official Node 22 image pinned by
digest during implementation, the same sources/tests, read-only mounts, current
user, resource limits and disabled networking during execution. Image retrieval
is a separate networked setup step. It needs neither the browser image nor SDK.
Both modes fail on test failure or zero selected test files and save a TAP report
under ignored `.local/js-test-results/`. Node remains optional for running Oogies;
contributors can use the existing Docker prerequisite instead.

## Production seams and required logic coverage

### Existing filename function: test before extracting anything

Import `safeCameraName()` from `frame-download.js` directly. It is already pure;
canvas/browser globals are used only when `downloadFrame()` executes.

Cover invalid filesystem characters, control/format characters, whitespace and
separator collapse, empty/dot-only fallback, Unicode NFC normalization, accented
names, emoji and the 128-byte UTF-8 bound without splitting a code point. Preserve
the current policy: `CON` and `NUL.txt` are allowed as camera-name components
because the complete filename has the `oogies-` prefix. Keep a real PNG download
test for the complete filename and actual downloaded contents.

### Clip and timeline arithmetic

Extract the bodies currently inside `ClipSelection.bounds/edit/paint` and
`Timeline.select/domain/setView/zoomToClip` into functions taking explicit
numbers/plain objects and returning values/plain objects. DOM controllers apply
their results and retain event handling. Proposed operations:

- Clip validity/duration and legal bounds for either mark, including a configured
  maximum and the current earliest-date restriction.
- Editing/rounding a mark to whole seconds; deriving keyboard edit targets.
- Loaded range versus visible zoom range, intersected slider seek range,
  second-aligned selection, clip domain and bounded zoom window.
- Recent-window minute rounding, fixed-window preservation, Earlier/Later
  calculations with an explicit `nowMs`, and previous/next motion selection.

Required cases include unset/partial marks, equal/reversed marks, 1-second clips,
exactly 600 seconds, one second over, a 120-second configured maximum, fractional
seconds, both edit directions and marks extending outside loaded history. Use
hand-worked examples and invariants; do not copy the production formula into
the expected result.

Preserve an important distinction: **Mark start/end may create an invalid range**
that the user can repair; drag/keyboard edits clamp to legal limits. Do not silently
clamp initial mark selection or remove the existing overlong-clip repair flow.
Preserve the 60-second minimum zoom, padding and whole-second rounding. Zooming
must not mutate the loaded query range or the SDK playback session's bounds.

Test minute, day, month and year boundaries using supplied timestamps, without
global `Date.now` patches. Keep clock policy in the view: Recent follows the
clock, playing a selected time pins the window, Refresh preserves a fixed window
and Earlier/Later respect the present-time ceiling. Selecting a camera still
resets its marks; hiding History clears feedback while retaining marks.

Recorder wall-time parsing and DST ambiguity/gap validation belong to Python's
existing timezone tests. Do not recreate those rules in JavaScript. Browser
date submission, recorder-zone labels and HTML input validity remain integration
coverage. Formatting an initial datetime-local value can be a later small
extraction if it materially simplifies those tests.

### Clip-export submission and confirmation state

Extract a small controller from `ClipSelection.submit/clearMessage`, with explicit
dependencies for posting an export, generating an idempotency key, scheduling/
cancelling a timeout and publishing state changes. Freeze submitted camera,
range, aspect and camera name at submission. Keep link creation, text rendering,
bounce animation and reduced-motion handling in `ClipSelection`.

The state owns the in-flight guard, retry identity and feedback generation.
Clearing feedback must not cancel a server-side export or permit a duplicate
submission while the old request is pending. Its production timer defaults use
real browser timers; the unit suite supplies a small manual scheduler and
deferred promises. Do not globally replace fetch, Date or all timers.

Required scenarios:

1. Valid submit emits one request; a second submit while pending emits none.
2. Failure retains the key for retrying the identical request; changed request
   data gets a new key; success clears the retry identity.
3. Request/feedback data retain the frozen camera/range/name, even if the source
   objects change before completion. Suppress invalidated feedback as below.
4. Success schedules expiry at 60,000 ms, stays visible at 59,999 and clears at
   60,000; errors retain the existing policy rather than gaining new expiry.
5. Clear marks, camera change and History hide invalidate old feedback. Late
   success/error cannot restore it, while the backend job still completes.
6. A previous timer firing after cancellation or after another confirmation
   cannot clear the newer feedback. Test callbacks already queued for dispatch,
   not only successful `clearTimeout` cancellation.
7. Completion after feedback invalidation still releases the submitting guard.
   No unhandled rejection or obsolete confirmation timer remains after clearing.

Keep feedback generation separate from submission identity: clearing a message
is not proof that the server did not accept the request. Use bounded explicit
timer advances and promise resolution; no sleeps or arbitrary retry loops.

## Browser coverage migration map

The names below refer to the original `test_viewer_ui.ViewerUITests` baseline.
Milestones 2-3 above record the completed logic migration. Milestone 4 preserves
remaining method names in `test_live.LiveUITests`, `test_history.HistoryUITests`
and `test_exports.ExportUITests`; its migration inventory maps full case IDs.
The retained browser checks cover wiring and browser-specific behavior, without
repeating the unit-tested rule matrix.

| Existing case/group | Move to JavaScript | Retain in browser |
| --- | --- | --- |
| `test_history_frame_download_sanitizes_camera_names` | Name matrix currently evaluated by importing JS into Chromium | Real download using a camera with unsafe characters; complete filename and PNG checks |
| `test_history_clip_drag_clamps_duration_and_order_without_seeking` | Four-way bounds matrix and repeated zoom arithmetic | Native pointer drag reaches a legal boundary; no SDK seek; selected playback time remains stable |
| `test_history_overlong_clip_zooms_and_can_be_repaired_with_keyboard` | Equal/reversed/overlong calculations and Home/End/arrow target matrix | Overlong marks disable Save clip; native keyboard repair updates markers, focus and enabled action |
| `test_history_clip_handles_respect_configured_limit` | Multiple configured-limit boundary combinations | API-provided 120-second limit actually reaches UI editing/validation |
| `test_history_camera_ranges_include_offline_inputs`, fixed-range Refresh and motion navigation | Minute/year transitions, range arithmetic, previous/next event matrix | Offline camera remains selectable; native Earlier/Later/Recent/Refresh and event selection produce correct API/DOM behavior |
| `test_history_export_confirmation_clear_and_one_minute_expiry` | Exact expiry, old timer callback and repeated-save state matrix | Clear/nav link wiring in representative queue/confirmation flow; remove this browser-only timer matrix once covered |
| `test_history_export_confirmation_clear_ignores_delayed_response` | Many response/error/clear orderings | One held POST reply, Clear marks and late completion leave DOM feedback empty while job completes |
| `test_history_export_confirmation_navigation_ignores_delayed_response` | Late response after invalidation | Consolidate redundant late-reply browser setup after unit coverage; keep navigation dismissal and Exports link integration elsewhere |

Keep mobile/touch dragging with refresh, pointer capture, marker label geometry,
compact workspace, scrolling, reduced motion, bounce animation, real canvas PNG
conversion, image decoding and cross-tab/backend resource ownership. In particular,
retain both recent Stop regressions and their native keyboard controls; target 3
does not claim to unit-test browser geometry or the complete live-quality protocol.

## Milestones and review gates

### 1. Runner and the existing pure-function seam

- Add the Node runner, explicit ES-module metadata and filename logic tests.
- Add a separate required JavaScript CI job using the Docker option, independent
  of the Python and browser jobs. Pin the image; upload the TAP report even on
  failure, with the existing artifact action and retention policy.
- Verify native/Docker parity, a deliberate failing assertion returning nonzero,
  missing/empty test selections failing, and imports requiring no browser globals.
- Keep existing browser assertions initially. Update test/setup documentation
  with commands that actually work and optional native Node verification.

**Pause for review:** a small working test layer with no production logic moved.
No runtime service restart or recorder access is needed.

### 2. Clip/timeline/range calculations

- Add the pure modules and boundary tests, then wire the real DOM controllers to
  those helpers. Move one concern at a time in separate reviewable changes.
- Preserve the behavioral distinctions above; tighten existing browser cases
  only after equivalent logic tests and their representative UI wiring pass.
- Run all JavaScript cases and affected clip/range/mobile/zoom/browser tests.

**Review gate:** the migration map identifies coverage that moved, retained
integration coverage passes and no production rule is duplicated in the tests.

### 3. Submission/feedback ordering with controlled time

- Introduce the narrow clip-export state owner and manual clock/deferred helpers.
- Cover all listed submission, expiry, cancellation and stale callback scenarios.
- Wire `ClipSelection` rendering to state changes. Preserve animation, link,
  idempotency and backend-job lifetime behavior.
- Remove the browser timer matrix and consolidate redundant delayed-response
  setup only after the retained DOM/API regressions pass.

**Review gate:** 60-second behavior and response order are verified without
waiting 60 seconds or using browser-global timer replacement.

### 4. Organize the remaining browser suite and measure

- In a separate mechanical change, split live, History and export cases into
  feature modules and put setup/assertion helpers in a support module. Shared
  base classes must contain no test methods, avoiding duplicate inherited cases.
- Update `tests/ui/run.py`, targeted selector examples and any fixture option/
  window-size lookup references. Keep four native cases discoverable and keep
  fresh browser/server/worker isolation for every browser case.
- Preserve single-suite synthetic-media setup where practical; measure repeated
  FFmpeg setup rather than introducing hidden cross-test state for speed.
- Compare collected test IDs against the migration map: moved logic assertions
  have unit coverage, while retained browser cases collectively cover UI wiring
  and browser-specific behavior.
- Run all three test jobs and record counts, durations and environment. Update
  [UI testing](ui-testing.md), both getting-started guides, this plan's results,
  the target list and `progress.md`.

**Completion gate:** Python, JavaScript and remaining browser/native suites pass
under the same commands CI uses. Documentation distinguishes runtime prerequisites
from optional development tooling. No broad skips, test retries, longer waits,
runtime tracing or recorder-dependent CI are added.

## Measurement, effort and deferred work

Before migrating browser cases, capture a full current-suite baseline with the
same Docker resource limits; keep it separate from the historical 887.7-second
result. Record new logical case counts as well as remaining browser/native
counts. Consolidating assertions is not evidence of reduced coverage by itself.

Aim for a warm JavaScript suite measured in seconds (initial target under five
seconds, excluding Docker image retrieval). Report actual browser/pipeline timing;
do not promise a percentage reduction before measuring. Browser startup remains
necessary for the UI behaviors listed above. Initially adding coverage may not
shorten the full suite until duplicated browser-only logic cases are retired.

The earlier 1-3 day estimate covered an initial test-layer slice. Allow roughly
1-2 days for milestones 1-2 and another 1-2 days for feedback extraction, browser
organization and full verification. These are planning estimates, not deadlines.

Defer `PlaybackControls` seek/rate/start/stop ownership to target 4. Defer deeper
`LiveQuality` lease/revision/decode testing, FrameFeed retry/watchdog/parser
extraction and renderer tests until their own seams are reviewed. Do not build a
fake browser, introduce a generic scheduler, move all frontend state at once or
delete a known race regression to make CI faster. If extraction needs a large
controller rewrite, stop and reassess that boundary before expanding this scope.
