# Target 3: faster frontend logic tests below the browser layer

Status: **milestone 1 reviewed and approved; milestone 2 authorized**.
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

Milestone 1 has been reviewed and approved for commit before milestone 2 starts.
Milestones 3-4 have not started. The approved design below remains the behavioral
contract.

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
tests/js/helpers/manual-clock.mjs       # only the timer operations needed here
tests/js/helpers/deferred.mjs           # explicitly resolve/reject a Promise
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

All names below currently live in `tests/ui/test_viewer_ui.py`. Record each moved
logic assertion and its new unit test before removing it from the browser suite.
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
