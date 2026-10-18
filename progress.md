# Camera viewing investigation progress

Updated: 2026-10-18 (South Africa time).

Goal: establish whether live video from the home Hikvision DS-7108HGHI-K1
at `192.0.2.10` can be decoded and viewed in a browser, then develop the live
and historical use cases incrementally.

## Users can remove failed and cancelled export entries

Added **Remove entry** to failed/cancelled export rows. The separate
`DELETE /api/exports/{id}/entry` endpoint dismisses diagnostics and rejects
queued/running/ready jobs; existing Cancel export retries retain their behavior.
Removal is durable and repeatable. When a cancelled capture is still finishing,
its row is hidden immediately while cleanup keeps the stream reservation until
the worker finishes. Late cancellation/error completion cannot restore the row.

All 141 Python tests pass (8.8 s). Three focused browser cases pass (34.8 s),
covering keyboard removal of a failed row while retaining a ready MP4, cancelled
entry removal and ordinary ready clip deletion. Browser case count stays 88 plus
four native; the complete 92-case suite was not repeated. Documentation explains
the new action. Evidence is under
`.local/export-dismiss-{backend.log,browser.log,browser-report.json}`.
Restarted the service with no queued/running exports and removed the six old
failed/cancelled entries through the new API. Both ready MP4s remain. The live
list and persisted manifest contain only those two ready entries; the served UI
module matches the checkout. Evidence: `.local/export-dismiss-service.json`.
Refresh an existing browser page once to load the new button code.

## Export files and entries expire together

Removed retained expired entries when their MP4/directory is removed, covering
retention expiry, Delete clip and missing files. Older expired manifest entries
are pruned during restore. The existing frontend polling removes absent rows
without a page refresh. Active downloads finish normally; expired entries are
hidden immediately and final file/manifest cleanup waits for the last reader.
Failed/cancelled diagnostic history keeps its existing bounded policy.

All 138 Python tests pass (8.3 s). Added exact-expiry, concurrent-reader,
legacy-manifest and cleanup-error regressions; existing missing-file, delete,
idempotency, HTTP, accounting and capacity checks pass. Four focused browser
cases pass (62.2 s), including a new polling expiry case, manual deletion,
newest-first listing and cancellation. There are now 88 browser/four native
cases; the complete updated 92-case suite was not repeated. Evidence is in
`.local/export-entry-cleanup-{backend.log,browser.log,browser-report.json}`.
Restarted the viewer after confirming no queued/running exports. The restart
pruned 14 old expired entries; both remaining ready clips still exist. HTTP
checks confirm the live API and persisted manifest contain no expired rows.
No recorder probe was needed; service evidence is
`.local/export-entry-cleanup-service.json`.

## Target 3 milestone 4: browser feature modules and full verification

Committed milestone 3 as `d2b0ab0`. Split the remaining 87 browser cases into
36 live, 31 History and 20 clip/export cases, with setup/assertions in
`browser_support.py`. The base class has no tests. An AST comparison preserves
all test/helper bodies, options and window sizes; Docker collection confirms
91 unique IDs including the four unchanged native cases. The local migration
inventory maps every old full browser ID to its new module/class.

The runner explicitly generates synthetic input media once per browser run,
keeps each browser/server/worker isolated, and removes media at exit. Reports now
include media generation count and separate setup/suite/total seconds.
Native-only selection skips media generation. Updated both setup guides, module
selectors and test/tracing documentation; production code is unchanged here.

All CI-command suites pass: 134 Python cases in 8.1 s, 125 JavaScript cases in
native Node 22.14.0 and pinned Docker Node 22.23.3 (329.5/547.4 ms Node time;
4.234 s warm Docker launcher), and all 91 browser/native cases. The full rebuilt
browser run takes 894.911 s in the suite, 895.336 s including the single 0.400 s
media setup and cleanup. Native-only selection separately passes four cases with
zero media generations. No new skips, retries, longer waits or tracing were added.

The pre-extraction `ab2dd80` baseline took 943.285 s for 93 cases. The only two
removed cases are the milestone-3 expiry/navigation matrices now covered in
Node. Different order and host activity limit this single timing comparison;
there is no hosted-CI or causal speedup claim. The direct rule/state feedback now
runs in seconds without a browser. See [milestone-4 results](docs/frontend-test-layer-plan.md#milestone-4-browser-organization-and-final-measurement)
and `.local/js-m4-{full-browser.log,full-browser-report.json,comparison.json}`
for complete results, environment and the ID migration. All target-3 milestones
are complete; milestone 4 was reviewed on 18 October 2026. Hosted Actions
execution awaits a push. The next proposed refactor is target 4, separating
playback state from rendering; it has not started.

## Target 3 milestone 3: export submission and feedback state

Committed the reviewed milestone 2 as `72f8d87`. Extracted `ClipExportState` from
`ClipSelection`: the pending guard, frozen request, idempotency retry key,
feedback generation and 60-second timer now have explicit dependencies. The DOM
controller still renders the confirmation link, bounce and reduced-motion state.
Clear marks, camera changes and History hide invalidate feedback without
cancelling jobs or releasing a pending request. Late completion releases the
guard but cannot restore dismissed feedback.

Added 21 direct cases using deferred promises and a small manual scheduler,
including exactly 59,999/60,000 ms, immutable request data, retries, repeated saves,
late errors/successes and timer callbacks already queued before cancellation.
All 125 JavaScript cases pass in native Node and pinned offline Docker
(335.4/545.1 ms Node time); all 134 Python cases pass in 8.5 s. Seven retained
browser cases pass in 93.8 s, then four final checks in 31.1 s: ten distinct cases
cover API/header wiring, held replies, animation, navigation/downloads, camera
reset, independent jobs, progress and compact/mobile/configured-limit controls.

Removed the browser timer matrix and redundant delayed-navigation case only
after their direct replacements and retained browser checks passed. The held
POST regression now waits for Save to re-enable rather than sleeping 100 ms.
The migration inventory preserves 87 browser/four native cases; the full updated
suite was not repeated. The [milestone-3 results](docs/frontend-test-layer-plan.md#milestone-3-submission-and-feedback-ownership)
record coverage and `.local/js-m3-*` evidence. Restarted the viewer and verified
HTTP 200 plus current source/MIME types for the page and export modules; no
recorder probe was needed. Evidence: `.local/js-m3-service.log`. Milestone 3
was reviewed and committed as `d2b0ab0` before milestone 4 organized browser
tests by feature and completed full verification.

## Target 3 milestone 2: directly tested clip, timeline and range calculations

Committed milestone 1 as `ab2dd80` before implementation. Extracted pure
`clip-model.js`, `timeline-model.js` and `history-range.js` and wired the actual
History controllers to them. Marks still permit invalid selections for repair;
editing clamps duration/order. Zoom remains independent of loaded/SDK bounds.
Clock inputs are explicit in logic tests; recorder-zone/DST resolution, rendering,
requests and control state remain in their existing owners. Added the three
module routes to the backend's static asset allowlist.

The same native/Docker runner now passes 104 cases (77 new), in 300.3/485.6 ms
of Node test time. All 134 Python tests pass. The full immutable `ab2dd80`
browser/native baseline passed 93 cases in 943.3 s. After extraction, 15 focused
browser cases passed in 143.1 s, including all five tightened wiring cases and
nearby input, touch, range, zoom, playback and date-navigation paths.

The filename matrix, mark/edit/key boundaries and calendar/range matrices now
live in Node. Browser checks keep real downloads, native gesture/key wiring,
focus, configuration propagation and layout. All 89 browser/four native IDs
remain; submission-feedback cases are untouched for milestone 3. Matched browser
case timings were 144.12 s before and 142.66 s after, insufficient for a meaningful
speedup claim. The gain here is direct, fast logic feedback and more combinations.
The complete post-extraction browser suite was not repeated.

Evidence and the assertion migration map are in the
[milestone-2 results](docs/frontend-test-layer-plan.md#milestone-2-extraction-and-coverage)
and `.local/js-m2-*` reports/logs. After implementation, the viewer was restarted
at the user's request and its page/new module routes verified over HTTP, without
a recorder probe. Milestone 2 was reviewed before starting milestone 3.

## Target 3 milestone 1: JavaScript runner and direct filename tests

Committed the reviewed plan as `8e60f84`, then implemented the initial runner
slice. Native Node 22 and a digest-pinned official Docker image run the same
27 tests against the existing filename sanitizer. No production function moved,
browser assertion was removed, npm dependency added or host package installed.
The Docker execution mounts only web/test sources, is read-only and offline,
and uses the current user with CPU/memory/PID limits. Image retrieval is separate.

Added seven Python safeguards for selection, runtime checks, failure propagation
and report refresh, bringing the full passing Python suite to 134 cases. Both
Node modes pass all 27 cases and return exit 1 for a deliberate failed assertion.
Warm launcher samples were about 0.16 s native and 3.97 s Docker. Three unchanged
browser download/name/proportion cases pass in 30.0 s. The host agent sandbox
reports native results at file level; normal native and Docker runs verified all
named assertions, and even the sandbox's deliberate failure remained nonzero.

A separate GitHub JavaScript job runs the verified Docker commands and retains
TAP reports. Both setup guides, test docs and the
[target-3 plan](docs/frontend-test-layer-plan.md) describe the new layer. Evidence
is retained in `.local/js-m1-*.log` and `.tap` files. Hosted execution awaits a
push. No recorder request or service restart was performed. Milestone 1 was
reviewed and committed as `ab2dd80` before starting milestone 2.

## Target 3 planned: frontend logic tests below the browser

Reviewed and approved the [detailed target-3 plan](docs/frontend-test-layer-plan.md),
based on `9e61f20`. Start with Node's built-in runner and the existing pure
filename sanitizer, then extract clip/timeline/range arithmetic and the smaller
clip-export submission/confirmation state. Explicit clocks and deferred promises
cover boundaries, expiry and late responses without browser timing.

The plan maps current Selenium assertions to replacement JavaScript coverage and
retained browser wiring, layout, native input, downloads, media and ownership
regressions. It includes native Node plus a Docker option, a separate CI job,
feature-based browser organization, setup-document updates and measurement gates.
Pause after the first working runner slice for review. The larger playback/live
controller refactors remain separate. The plan was committed as `8e60f84` before
milestone 1. No implementation, test execution, package installation, recorder
access or service restart was performed for the planning stage.

## Pending-reply CI timeout: shared input-timing mechanism

Compared the new pending-quality-reply timeout with the previous two-main Stop
failure. Both use pointer activation after a tile expansion/collapse while their
preceding network/media waits do not synchronize animation or focus scrolling.
The frontend is unchanged since the passing `900483a`; that pass alone cannot
exclude intermittent input timing. The new CI snapshot retained a live page,
one viewer/nine sources and no native stops.

Three ordinary reruns passed. A controlled early-polling/pointer-delay probe
reproduced that backend signature: the page scrolled 148 pixels between pointer
movement and press, the click hit a camera button, and no DELETE was sent. This
proves a timing mechanism, but the exact CI click sequence was not recorded.
Use native Enter/pause acknowledgement in the pending-reply and media-pause
ownership tests, and keyboard collapse/Resume in the replacement-lease case.
The held response, cleanup and stale-lease assertions remain in place. A slowed
animation/early-polling probe passed three times, confirming Stop activation and
successful deletion during animation, with zero resources before replacement.

Used temporary bounded offline input/live-request traces and per-test JSON
diagnostics to distinguish input failures from backend cleanup. At the owner's
request, removed the tracing script, setup/teardown hooks and extra CI artifacts
after investigation. Retained keyboard interactions and compact backend/page
timeout diagnostics. The reusable approach is documented in
[UI input tracing](docs/ui-input-tracing.md).
No application, recorder, running-service or timeout/retry policy change.
Evidence is in `.local/stop-pending-*.log` and
`.local/stop-click-investigation/pending-*.json`.
See [UI testing](docs/ui-testing.md) for reproduction and verification details.
Final verification passed 12 focused executions in 102.0 seconds, including
three reruns of the reported test, the prior failure and unchanged pointer/
animation checks. Report: `.local/stop-pending-focused-ui-report.json`.
The separate three-run slowed-animation probe passed in 26.5 seconds.
After trace removal, the replacement-lease, two-main sharing and media-pause
tests passed again (three tests in 31.6 seconds). Log:
`.local/stop-trace-removal-ui.log`. Publication/history and whitespace checks
passed. The full suite was not repeated.

## Two-main Stop timeout investigated

Committed the reviewed task-2 refactor as `3021d42` before investigating the
owner's CI timeout at `0f3bf9f`. The reported test reached its final Stop pointer
click after collapsing a tile, then timed out waiting for zero viewers/sources.
Three unmodified local reruns and two lengthened-animation/pointer-delay probes
passed. Stop clicks were delivered and cleanup completed in those probes; the
exact CI failure has not been reproduced. A pointer/focus timing issue is a
hypothesis, not an established backend defect.

The two-main ownership cases now use native Enter activation on Stop, require
the page to acknowledge pause, then retain the backend cleanup assertions.
Resource waits sample counts atomically and add backend/page diagnostics on
timeout. No application code, cleanup timeout or retry policy changed. Seven
focused cases passed, including three reruns of the reported case and unchanged
pointer/animation/manual-scroll coverage. Evidence: `.local/stop-click-*.log`
and `.local/stop-click-investigation/`. See [UI testing](docs/ui-testing.md).
A final slowed-animation keyboard probe passed with Stop activated during active
animation and zero final resource counts; it also verified timeout diagnostics
by deliberately waiting for impossible counts. Log:
`.local/stop-keyboard-motion.log`.
The preceding task-2 full suite passed 93 cases; it was not repeated for this
test-only adjustment. Those changes were subsequently committed as `67618d1`.

## Target 2 implementation: independent capacity ownership

Committed the approved task-2 plan as `900483a` before implementation. The new
`StreamBudget` owns total/HQ admission and identified playback/export handles,
with immutable usage snapshots and identity-checked release. `LiveSessions`
provides read-only occupancy including current native stops; playback and export
services receive the budget directly and no longer mutate live counters or call
private live reconciliation. A bound public refresh callback preserves immediate
overview recovery without automatically retrying refused HQ requests.

Shared errors and time conversion live in neutral modules. Application-level
maintenance expires playback even with no live viewers. Production, diagnostic
and offline-fixture construction match these boundaries. The HTTP factory
rejects mismatched budgets; exports require completed occupancy wiring before
restored queued work may run. Configuration, routes, media and public status
field meanings remain in place.

All 107 migrated backend tests initially passed. New budget/ownership/failure
tests bring the complete suite to 127 passing cases. These cover last-slot
contention, delayed/stale stops, repeated/foreign releases, callback failure and
notification, controls retaining a handle, cancellation isolation, storage waits,
persistence/encoder/cleanup failures and HTTP counts. All seven target-1 cases
remain. Three focused browser cases passed, including immutable export state
across History seek/camera change/tab close. The expanded full browser/native
run passed all 93 cases (89 browser/four native) in 887.7 seconds. The final
export-independence case passed again in 14.6 seconds after its cleanup wait was
tightened. Full report: `.local/task2-full-ui-report.json`; logs:
`.local/task2-*.log`. See the
[task-2 results](docs/stream-budget-refactor-plan.md).

The refactor was reviewed and committed as `3021d42`. No real recorder request, service restart or
owner configuration change was performed.

## Target 2 planned: independent export/playback ownership and shared capacity

Committed target 1 as `0f3bf9f` after review. The
[detailed target-2 plan](docs/stream-budget-refactor-plan.md) addresses History
playback and exports mutating live-session counters/private reconciliation,
playback expiry owned by live maintenance, and shared error/time utilities
located inside feature modules. It keeps export jobs and interactive playback
as independent state owners and proposes a neutral stream budget with identified
reservations, read-only live occupancy, explicit release and compatible status.

The plan spells out ownership/lifetimes, initialization order for restored
exports, immediate overview recovery, delayed live-stop acknowledgement,
independent cancellation, concurrency/failure tests, helper migration and neutral
maintenance wiring. Estimated effort is refined to 2-4 days including testing.
Documentation only; implementation awaits owner review. No service restart,
configuration change or recorder probe was performed for this planning work.

## Target 1 implemented: race-safe export accounting

Committed the reviewed architecture targets and seven-test implementation plan
as `19d12bf` before changing code. A deterministic metadata hook renamed a real
partial MP4 between the old check and size read, reproducing the recorded
`FileNotFoundError`. Accounting now obtains one metadata result per candidate
for regular-file type and size, skips only missing candidates and continues
counting survivors. Other I/O errors are preserved; concurrent scans remain
best-effort rather than transactional quota snapshots.

Added seven tests for atomic rename, disappearing file/parent, exact stable
totals and filtering, permission/other I/O errors, the actual HTTP export-list
request during finalization, storage-admission refusal with a survivor, and
background queue progress with exact acquire/release transitions. Race injection
uses real temporary files and targeted metadata hooks/events, not random timing.
The reproduction failed before the fix; all 25 export tests and all 107 backend
tests passed afterwards. Logs are `.local/export-accounting-red.log`,
`.local/export-accounting-focused.log` and
`.local/export-accounting-backend-tests.log`.

The [target-1 plan](docs/export-accounting-refactor-plan.md) and
[architecture backlog](docs/refactoring-targets.md) reflect completion. Production
changes are confined to export file accounting. The browser/native suite was
not rerun; no live service restart or recorder requests were needed. Target-1
implementation was subsequently reviewed and committed as `0f3bf9f`.

## Architecture refactoring review and target-1 plan

The two-HQ rollout, total-budget fix, refusal labels and regressions were
committed as `480c85c`. The [refactoring targets](docs/refactoring-targets.md)
record nine proposed improvements, rough effort/return, code evidence and test
opportunities. Existing SDK/source-sharing and synthetic-test seams remain the
foundation; proposals focus on ownership, asynchronous state and test speed.

The [target-1 plan](docs/export-accounting-refactor-plan.md) details the observed
export-accounting check/read race, the proposed single-metadata-read behavior,
normal-disappearance versus other-I/O-error handling, deterministic reproduction,
caller/queue verification and completion criteria. Concurrent directory scans
remain best-effort; stronger transactional quota accounting and shared-lock
restructuring are separate work. Documentation only: implementation is awaiting
owner review, and the existing race has not been fixed by this planning work.
Following review feedback, the plan now leads with seven explicit required
backend test cases, including how each fault is triggered and what it asserts.
They cover rename/removal, surviving-file accounting, file selection, unexpected
I/O errors, real HTTP listing, storage admission and background queue progress.
They are planned additions, not implemented tests; implementation still awaits
review.

## Second high-quality stream refused by total budget

The running service correctly reported a high-quality cap of two, but its
recorded upgrade refusals were `source_limit`, not `high_quality_limit`.
Seven cameras were now online, compared with four in the capacity experiment:
seven overview fallbacks plus two main streams need nine slots, exceeding
the unchanged total budget of eight. Updated only the owner's private total
budget to ten, preserving the cap of two and allowing one History or export
alongside the seven-camera/two-main workload. Restarted the service; portable
configuration still defaults to eight total sources.

The UI now distinguishes total-stream and high-quality limits, and backend
tooltips explain the applicable configured cap. A new offline browser case
reproduces this exact refusal with seven overviews and then verifies two mains
after increasing capacity and explicitly retrying. All 100 backend tests and
three focused browser cases passed. The full expanded 92-case browser/native
suite was not rerun. Private logs are `.local/two-high-budget-backend-tests.log`
and `.local/two-high-budget-ui-tests.log`.

A restricted real-browser check then painted two 960x1088 main streams while
retaining all seven online overview sources (nine occupied slots). Every live
tile's pixels changed across samples; all source frames remained fresh, with
zero upgrade refusals/failures and one SDK login. The diagnostic released its
viewer and all nine sources. Private evidence and a screenshot are under
`.local/two-high-budget-check/`; the command log is
`.local/two-high-budget-live-check.log`. The normal service remains running with
ten total slots and two high-quality slots.

## Two-high-stream rollout

Committed the capacity experiment as `5566de8` before changing the operating
limit. Following owner approval, the project configuration default and private
owner setting now allow two distinct high-quality live sources. The total
source budget remains eight, shared with overview, History and exports. Explicit
owner overrides, including zero or one high-quality source, still apply.
Configuration examples and the experiment runner's missing-value fallback match
the new default. The local service was restarted to load the updated setting.

All 100 backend/monitor tests passed on rerun, and the focused two-high-stream
browser test passed. The initial backend run encountered an intermittent export
storage-accounting race: a partial clip disappeared between `is_file()` and
`stat()` in `_used_bytes`. This unrelated issue remains unresolved; the rerun
passed without changing export code. Private logs are
`.local/two-high-rollout-backend-tests.log`,
`.local/two-high-rollout-backend-rerun.log` and
`.local/two-high-rollout-ui-tests.log`. The full browser/native suite was not
rerun for this configuration change.

## Two-high-stream load experiment

The reviewed reliability work and character replacement were committed as
`a05a2dc` before this experiment. No production stream code is being changed:
the existing private high-quality capacity setting already accepts two.
A new backend regression checks two distinct admitted sources, independent
sharing/release and explicit retry after refusing a third. A synthetic-browser
case paints both larger renditions in two sharing tabs and independently releases
one. The complete backend/monitor suite passes 100 cases, and the focused browser
case passed; the expanded 91-case browser/native suite has not been run in full.

The explicit capacity runner temporarily reloads the high cap as two, measures
the full online grid with one/two mains, optionally adds a historical viewer,
then measures recovery and restores the original config/service. It records
service/browser/host resource use with stop thresholds and private evidence.
An initial attempt aborted on Docker's diagnostic-container creation race before
collecting samples; original cap one and the normal service were restored. The
monitor now retains service statistics while the browser container is absent;
two host regressions and a real Docker check cover this.

The repeated experiment passed: camera-1 and camera-6 each supplied a 960x1088
main stream alongside all four online overview streams for 183.9 seconds,
followed by 30.9 seconds with History playback too. Mean backend CPU rose from
38.1% of one core with one main to 49.2% with two; peak container memory rose
from 118.7 to 148.4 MiB. With History, these were 58.3% and 205.1 MiB. Browser
peak memory rose from 404.8 to 505.7 MiB for the second main. Available host memory
stayed above 4.36 GiB. No stream failure, unexpected restart or additional SDK
login was detected, and final viewer/source/feed counts were zero.

Original private configuration bytes and permissions were restored exactly;
the normal service is running again with the high-quality cap of one. These
measurements support two mains for this pair, rather than establishing the NVR's
maximum capacity or long-term resource behavior. The protocol, full comparison
and private evidence locations are in [live grid](docs/live-grid.md#two-main-stream-capacity-experiment).

## Character replacement validation

After the owner's repository-wide replacement of en dashes with ASCII hyphens,
all 97 backend tests passed and the complete offline browser/native suite passed
all 90 cases (86 browser and four native) in 849.6 seconds. This includes the
previously timing-sensitive capacity case and all six reliability cases. Python
syntax checks passed for all 50 source files; publication/history and whitespace
checks passed. Results are in `.local/replacement-backend-tests.log`,
`.local/replacement-ui-tests.log` and `.local/ui-test-results/`. No application
or test changes were needed for this rerun.

## Reliability and resource checks: milestone 3

Milestone 2 was reviewed and committed as `6312fca` before this work. The owner
approved longer sessions, browser reconnection/cleanup and historical playback
alongside high-quality live video, retaining the high-quality cap at one. The
scope is recorded in [the quality plan](docs/live-quality-plan.md).

A browser regression reproduced clean media EOF leaving a frozen picture labeled
Live. The shared feed now recovers the same media URL with bounded 1/2/4-second
backoff, without recreating sessions or retrying SDK authentication. Live tiles
measure successfully painted frames independently of backend health; delayed
pictures are dimmed/labeled and excluded from the live summary. A ten-second
watchdog applies only when video is expected; paused/ended History is excluded.
Terminal media failure releases that viewer/playback and asks for manual resume
or time selection. Six final reliability cases passed targeted runs for EOF/read
errors, silent stalls, exhaustion/manual resume, forbidden responses, Pause and
navigation, and independent live/History recovery. Extended History coverage
includes paused reconnection, a ten-second response-header timeout and terminal
playback cleanup while the other high-quality view remains live.

The full 90-case browser/native run passed 89. One capacity case clicked while a
previous tile's focus animation was still moving its target, then timed out
waiting for a collapse that had not happened. Its interaction now waits for
settled geometry and asserts the expanded state changed; three consecutive
reruns passed. Existing dedicated animation/rapid-toggle cases passed unchanged.
The subsequent full rerun after the character replacement passed all 90 cases,
including this synchronized test and the six reliability cases. Initial private logs are
`.local/m3-ui-tests.log`, `.local/m3-final-focused.log` and
`.local/m3-history-final.log`.

A separate quiet-feed HTTP regression reproduced a closed peer retaining its
media slot when no frames were being sent. The handler now detects peer closure
without a write or protocol heartbeat; the same viewer can reconnect without
another native start/login. All 97 backend tests passed after that fix.

The explicit [reliability runner](tools/run_live_reliability_check.py) requires
an idle, verified service and uses a restricted browser container without SDK or
credentials. It retains the existing SDK login, enforces resource/source limits,
samples service load and browser media bytes, and keeps footage/reports private.

The real-browser check passed 302.6 seconds with all four reported online
overview streams, one shared high source and a historical viewer. Both browser
feeds recovered controlled interruptions while keeping their source/playback
generations and the existing SDK login. Paused History stayed paused without
false recovery, then recovered an explicit disconnect. Three upgrade/release
cycles passed. Final viewer/playback/source-slot/media-feed counts were zero,
SDK login calls stayed one and no unexpected browser errors were reported.
Mean sampled service CPU across the complete diagnostic was 55.0% of one core,
peak memory 247.1 MiB and peak PIDs 168. Idle PIDs returned to 142; idle memory
was 109.5 MiB before and 155.1 MiB after. Browser delivery averaged 1.12 MiB/s
for Live and 0.44 MiB/s for History. Keep the high-quality cap at one; this is a
five-minute workload check, not an overnight soak or a hardware-capacity maximum.

The first diagnostic hit a one-shot History image-readiness assertion around
115 seconds although native frames kept advancing without an SDK error. The
probe now waits for decoding and checks actual pixel changes plus SDK frame
progress, with failure-state capture; its repeat passed. Final private evidence
is `.local/live-reliability-check/20261016-212301/`; full details are in
[live grid](docs/live-grid.md#device-evidence--16-october-2026).
The updated service is running at `http://localhost:8088/`. Milestone 3 was
reviewed and committed as `a05a2dc` before the two-high-stream capacity experiment.

## Expansion-driven quality: milestone 2

Milestone 1 was committed as `482aa8d` before frontend work. Expanding now requests
high quality through the existing lease and collapsing requests overview. The
grid keeps its current picture until a selected rendition is decoded. Quality
labels and the footer describe painted frames, with upgrading/fallback feedback,
short reasons and tooltip details. Existing aspect correction, animation,
keyboard access, reduced motion and manual-scroll cancellation remain in place.

A separate frontend quality coordinator serializes full selections, coalesces
rapid changes and guards lease/revision/intent lifetimes. Per-tile offscreen
JPEG decoding rejects superseded generations and revokes obsolete Blob URLs.
Slow tiles skip frames instead of buffering. Refused/failed preferences remain
local until an explicit retry. Lost responses trigger one cleanup selection for
unconfirmed upgrades while retaining acknowledged high requests.

An optional validated `retry_high` list scopes retries to explicitly selected
cameras, preserving legacy API behavior when omitted. This prevents a failed
stream between polls from being retried by another camera's selection change.
Two backend regressions cover that race and invalid-request atomicity. All 96
backend tests passed. Focused browser cases passed for actual larger images,
sharing/expiry, failure/stall/limit/unsupported/offline feedback, delayed replies,
late JPEG decoding, replacement leases, ambiguous responses and preserving an
acknowledged high source. The complete offline browser/native suite passed all
84 cases (80 browser and four native). The existing CI command discovers all
new cases. Publication and documentation-link checks passed.

A Docker Chromium check against the real running service passed with four
reported online cameras. Expansion painted the 960×1088 main stream, kept 16:9
display proportions and showed the high-quality footer/label. Collapse returned
to overview. Two browser tabs shared four overview sources plus one high source
through one SDK login; pausing/closing one preserved moving high video in the
other. Final live/view/occupied-slot counts were zero, with no browser errors.
The expanded screenshot was visually reviewed. Private evidence is under
`.local/grid-quality-ui-check/`, including `grid-check.json` and screenshots.
The service remains running at `http://localhost:8088/`; refresh an existing tab
to load the new frontend. Milestone 2 was reviewed and committed as `6312fca`.

## High-quality live backend: milestone 1

The approved plan was committed as `efc4007` before implementation. Backend live
selections now accept overview and high quality, sharing separate native sources
per camera/quality through one login. High requests retain overview fallback and
promote only when a fresh main-stream frame arrives. Configured high-quality
capacity defaults to one shared source; zero disables it. Total capacity includes
overview, high quality, history/export reservations and native live stops awaiting
acknowledgement. Failed/refused upgrades require explicit retry and do not queue.

Worker protocol 2 identifies quality and generation throughout commands, events,
cache paths and media headers. Selection revisions separate explicit updates from
lease renewal. Limits, fallback reasons and per-source FPS/bytes/freshness/latency
are available through the existing API and `/api/status`. Decoded YV12 buffers
are bounded at 16 MiB with dimension validation; JPEG limits remain 4 MiB.

All 94 backend tests and the complete 73-case offline browser/native suite passed.
Coverage includes concurrent admission, sharing, fallback, stale events/files,
closing-source reservations, history/export contention, actual high-quality media
decoding in Chromium and preservation of the ordinary grid. The native bridge
compiled and initialized SDK/decoder offline with zero login calls. Publication
checks passed. Both setup guides and API/test/grid documentation were updated.

One bounded Docker device check used one SDK login and at most one high-quality
live source. The recorder reported four online inputs at this check; all four
decoded alongside high quality and one historical playback. Camera 1 overview
was 352×288; main stream was 960×1088, with existing browser aspect correction
still applicable. Four overview streams plus high quality sampled about 43.5%
of one CPU core and 121.1 MiB; adding history sampled 60.8% and 149.4 MiB.
Each resource sample lasted eight seconds and excluded browser media delivery;
these are short operating samples, not a maximum-capacity or sustained-use claim.
Independent high-view release and final zero-source cleanup passed. Private
evidence is in `.local/live-quality-check/quality-check/quality-check.json`.

The service was relaunched with the updated backend. At that milestone,
frontend expansion still used overview. The owner approved the review and
committed milestone 1 as `482aa8d` before milestone 2. Keep the high-quality cap
at one.

## Recent history range boundary in CI

The offline-camera range test assumed Recent always restored the initial window.
Crossing a minute correctly advances that window, causing the reported CI failure.
Controlling the page wall clock reproduced the failure across recorder midnight
and New Year. The test now checks both returning within the same minute and
advancing into the next one, including exact recorder query bounds and the
disabled Later button. Other timers and production behavior are unchanged.
Four focused browser cases passed for ranges/offline inputs, fixed-range refresh,
recorder timezone/date navigation and delayed camera responses. Publication
checks passed; the complete suite was not rerun for this test-only change.

## Playback speed race in CI

Committed as `bf46318`.

GitHub Actions exposed a speed/seek race: the backend had applied 4× before the
browser received its response, so a seek could still submit the cached 1× speed.
A browser regression held the response and reproduced the same `1 != 4` failure.
The player now retains requested speed immediately, carries it through seeks,
discards superseded acknowledgements, and restores the confirmed rate on request
failure. The boundary-step test waits for browser confirmation/readiness and each
new playback generation. Six focused speed/date/error cases passed. Local host
Python needed inherited library overrides cleared for the test command; no host
configuration or dependencies were changed.
The complete offline suite then passed all 71 cases (68 browser and three native
buffer regressions), including the reported CI failure. Publication checks passed.

## Compact History workspace

The label-strip change was committed as `e88dab8`. A browser regression
reproduced a clipped Motion events heading at desktop, narrow desktop and phone
sizes: the collapsed flex item had a zero content-size basis. It now uses its
natural heading/padding height without shrinking; the expanded list still fills
the available space and scrolls independently.
Three focused browser cases passed for collapsed geometry/keyboard reopening,
expanded-list scrolling/seeking, and fresh mobile playback/marking.

The confirmation animation was committed as `bd84642`. Start/End handles now
occupy a fixed strip between the recording and motion bars. Both bars retain
their normal height and selection shading; marking or clearing no longer changes
the preview's size. The label strip owns pointer capture and keyboard editing,
preserving time-to-pixel scaling, focus, zoom and playback independence.
Nine focused browser cases passed for fixed geometry, labels between bars,
mouse/touch/keyboard editing, limits, metadata refresh, camera reset, mobile
selection and zoomed seeking. The marked laptop screenshot was visually reviewed.

Save clip/Settings refinements were committed as `645640c`. Successful save
confirmations now appear with a brief fade and small vertical bounce, highlighted
inside the clip box. The animation uses opacity/transforms, leaves layout and
scroll position alone, restarts for each accepted save, and is cancelled on
message dismissal. Reduced-motion preferences show the feedback immediately.
Six focused browser cases passed: real animation samples, repeat saves, reduced
motion, compact layout, timed/clear/navigation dismissal, delayed responses and
the existing queue/download/delete flow.

The compact layout and its browser coverage were committed as `95b85c1`.
The main clip action reads Save clip with a filled highlight. Its text uses the
same normal weight as the other buttons.
Picture proportions are shown/configured in Settings; the clip box shows its
range and duration. Saving still uses the current camera's picture preference.
Two focused browser cases passed for compact layout/Save clip and the complete
queue, download and deletion flow.

The owner approved the initial layout-only prototype and requested UI coverage. Desktop
History now fits the available viewport: video, timeline, seeking and playback
controls share the main pane; clip marks/export controls sit beside them, above
an independently scrolling motion list. A single pair of draggable clip labels
sits between the bars, with selection shading on both tracks.
Camera/range navigation is above the workspace. Date/time opens in a dismissible
popover and closes after successful navigation. Smaller screens stack the panels
and initially collapse the motion list. Existing playback/export APIs are unchanged.
Synthetic browser previews were used to review desktop/mobile layout and exercise
playback, paused seeking, marking and date navigation. Four browser regressions
now cover simultaneous visibility on laptop/desktop screens, independent motion
list scrolling with playback/selection, date-picker keyboard/outside/navigation
dismissal and draft retention, and mobile collapsed-event playback/seeking/marks.
Existing date and mouse/touch/keyboard mark tests use the new visible controls.
The complete offline suite passed all 66 cases (63 browser and three native
buffer regressions). The existing GitHub Actions UI command discovers these
cases automatically. No recorder access or SDK credentials were used.

## Clip exports, frame downloads and fine seeking

The export ordering fix was committed as `5f3c9fd`. Running exports now use a
circular SVG progressbar with the existing backend progress and a central
percentage. The ring is reused on polling, hidden outside running state, and
provides an accessible label/range/value. Reduced-motion preferences disable
the short arc transition; no new requests or dependencies were added.
Four focused browser cases passed for actual capture percentage updates,
completion, cancellation, download/delete and ordering. The new case also checks
mobile fit and reduced motion; its intermediate screenshot was visually reviewed.

Exports previously appended new jobs below cached rows. Returning from History
or refreshing kept the wrong order; a full reload rebuilt it newest first.
A browser regression reproduced this, then passed after positioning reused rows
in the API's newest-first order. It also covers refreshing for another viewer's
new job while retaining existing row elements.
Four focused browser cases passed for ordering, download/delete, cancellation,
and preserving a separate live viewer. The running service serves the updated
frontend; no restart or new recorder probe was needed.

The approved export implementation was committed as `d97e032`. Queue confirmations
now clear on Clear marks, after 60 seconds, or when leaving History/changing
camera. A delayed queue response cannot restore a dismissed message, and an old
timer cannot erase a newer confirmation. Dismissal leaves the export job running.
Four focused browser tests passed: Clear marks and the 60-second timer, delayed
responses after clear/navigation, and the existing queue/download/delete flow.
The timer check invokes the scheduled callback without waiting a real minute.

The owner increased the default maximum to ten minutes (600 seconds). Setting
both marks zooms the visible timeline around them, including an invalid draft.
Mouse/touch dragging and keyboard arrows edit either handle, clamping to an
ordered 1-600-second range (or a configured lower limit). The viewport stays
fixed during a drag and metadata redraws wait until release. Zoom changes only
the visible window; editing marks does not seek, pause or create SDK requests.
Zoom to clip, Zoom out and Full range provide explicit viewport controls.
All 78 backend tests and the full 56-case browser/native run passed. Follow-up
checks passed after making the seek slider follow the zoom, including a new
57th browser/native case. Overlong/reversed drafts, mouse/touch/keyboard limits,
metadata refresh during a drag, mobile layout and unchanged playback were checked.
The real ten-minute export produced a 599.134-second MP4 with 8,987 frames and
16:9 display metadata. One live preview and historical viewer kept playing
through one SDK login. Longer clips exposed a mismatch with the old quarter-
second validation; duration validation now matches the reported one-second
position precision and also verifies every captured frame reached the encoder.
Recorded-time coverage and timestamp-gap checks still reject missing footage.

Date/time navigation was committed as `bd0b069`; the owner-approved
[plan](docs/clip-export-plan.md) was committed as `06c077d` before implementation.
History now has browser-only Start/End marks and shaded timeline selection,
±10/30-second seeking, and direct current-frame PNG downloads. Marks use the
successfully displayed recorded clock. PNG conversion freezes that frame and
picture proportions once, with no SDK/backend job or per-frame resizing.
Image filenames now use the camera name, frozen with the displayed frame.
Names are sanitized for path separators, reserved punctuation and control
characters, trimmed and bounded, with a generic fallback for empty names.
Three focused browser checks passed for named PNG downloads, freezing the name
across camera/settings changes, and invalid/empty/Unicode/long-name sanitization.
The Export word in a successful queue confirmation now links to the Exports
tab. Its keyboard navigation and subsequent MP4 download/delete browser test passed.

The shared Exports tab lists immutable queued/running/ready/failed jobs, wait
reasons, cancellation, MP4 downloads, deletion, size and expiry. Python owns the
durable private manifest, admission, retention and HTTP byte ranges. A separate
native playback/decoder context shares the existing SDK login; bounded raw and
compressed queues feed FFmpeg without storing the whole raw clip. Cancellation
wakes callbacks before SDK stop. Export jobs outlive browsers; ready/queued jobs
survive service restart. Defaults are ten-minute clips, one active plus three
waiting, 24-hour retention, 1 GiB storage and a 256 MiB file cap. Active exports
reserve one stream slot without evicting views.

Real SDK exports of 1/10/60/300 seconds produced 0.934/9.867/59.934/299.867-second
H.264 MP4s, at 960 × 1088 with correct 16:9 display metadata. The 1/60/300 ladder
kept one live preview and one historical viewer running, with one SDK login.
Sampled memory stayed about 280-300 MiB. The initial frame can lack OSD time;
capture waits for a usable clock and validates subsequent stamps and coverage.
Clip bounds have second precision, not frame-exact guarantees. Full-grid plus
history plus export capacity remains unverified. Details, reproduction commands
and test scope are in [clip exports](docs/clip-exports.md).
Real cancellation also released the export slot and kept an independent live
preview advancing through the same login. Ready clips survived service restart
and remained downloadable with HTTP byte ranges, without a new recorder login.

Backend unit checks passed (78 cases); the complete Docker browser/native suite
passed (56 cases), plus the new zoomed-slider case and affected follow-up checks.
Both getting-started guides now cover the
export configuration, storage mount, source budget and verification steps.

## Direct date/time navigation

Camera History shortcuts and speeds were committed as `122b655` before this
increment. History now offers Date & time and Go to time for the selected
camera. The field labels the recorder's configured timezone and accepts seconds;
browser timezone does not alter interpretation. Go loads a surrounding
one/three/six-hour timeline and starts footage at that time, including from a
paused view. Older windows are centred; near-now windows stop at current time.
Ranges and selected times now show the year. Refresh keeps the pinned window,
and Recent returns to the latest hours. Incoming frames do not overwrite input.

The existing timeline endpoint accepts a local_time/hours query variant. Python
resolves it with the configured ZoneInfo and returns UTC selected_time and range
bounds, sharing the normal metadata cache. Invalid/future, repeated or nonexistent
local times are rejected before SDK work. The prior picture/window remains
working on invalid input, and superseded camera/date responses are ignored.

Playback PATCH can replace from/to with position in the same session. It validates
before mutation, preserves rate and the reserved viewer slot, and starts a fresh
native generation. This avoids losing the slot to another live grid between
date ranges. No native SDK change, new dependency or extra authentication flow
was required. The frontend date form has its own small functional module.

The actual Docker browser jumped to footage from an hour earlier, whose first
recorded clock matched the requested UTC second exactly. It displayed moving
footage for thirty seconds and exercised all speeds, Pause, and a second date
jump. That jump retained its session and 4× speed. Stop left zero historical
sessions and SDK login count stayed one. Private evidence remains in
`.local/browser-viewer/history-ui-check/`.

The five targeted browser cases passed: timezone independence/selected camera,
slot/speed preservation beside a full live grid, rejected input preserving
paused footage, delayed response cancellation, and mobile/keyboard submission.
Both setup guides and the timeline/playback/API notes describe the new behavior.
All 60 unit tests and 41 Docker cases (38 browser, three native queue tests)
passed. The final supported-year guard also passed the unit suite. Whitespace
and publication privacy checks passed.
These date-navigation changes were committed as `bd0b069`; the service remains
available. The newer export plan is documentation only and awaits review.

## Camera History shortcuts and playback speeds

Working interactive playback and its sustained-buffer fix were committed as
`563a6d7` before this increment. Each live tile now has a keyboard-accessible
History button which opens that camera's recent timeline and focuses the
selector. Offline cameras can still open historical recordings. Selecting a
time starts video; the shortcut itself only navigates and selects the camera.

The player now has 0.5×, 1×, 2× and 4× buttons. The Python worker seam accepts
normalized rates; the native bridge adjusts that file-mode decoder with
PlayCtrl Fast/Slow increments and confirms its actual rate. Playing changes
retain the same handle, generation and position. Seek/resume preserve the
selection; changing it while paused holds the picture/time. A rejected rate
reports a separate control error and keeps footage moving at its actual speed.
Other viewers' rates and live sources are independent. JPEG publication and
compressed queue bounds remain unchanged.

A real SDK check measured 5/10/20/40 recorded seconds in approximately ten wall
seconds at 0.5×/1×/2×/4×, followed by normal speed again at 1×. All speed changes
kept generation 1 and one login. Paused changes held their frame/clock, and
resume/seek preserved 4×. The actual Docker browser also opened the camera's
History shortcut, played continuously for thirty seconds, clicked every speed,
verified Pause and left zero historical sessions after Stop.

All 54 unit and 36 Docker cases passed (33 browser, three native queue tests),
including the new shortcut/rate cases. The final keyboard-focus case also passed
after its last adjustment. Offline native compilation and decoder initialization
passed without credentials or network. The updated service is running for review.
Both setup guides, API/seam notes and
[History playback](docs/history-playback.md) document the new controls. Private
speed evidence is under `.local/browser-viewer/rates-check-*/report.json`.
The bounded check can be repeated with `python3 tools/check_playback_rates.py`.

## Sustained History playback correction

The owner reported playback stopping after a few seconds with code 43. The
earlier checks had exercised only short runs between seeks. The recorder sends
compressed footage faster than real-time decoding: the bridge's 16 MiB callback
queue filled and generated that error locally. Retrying decoder input did not
apply flow control to incoming data.

The queue now waits for capacity before copying more data and retains refused
decoder chunks in order, including their memory accounting. The main publisher
does not wait for the decoder. Closing wakes the callback before SDK stop, and
two-second playback heartbeats keep the connection active while it waits. The
queue limit remains 16 MiB. Private buffer statistics confirmed the cap was
reached and 141 capacity waits occurred, without losing playback.

A 75-second uninterrupted real-recorder check received 606 frames with exactly
75 seconds of recorded-clock advancement and no feed errors. A concurrent live
preview advanced from 7 to 608 frames and stayed live through the same SDK
login. Pause/resume, playing seek and paused seek passed afterward. Sampled
service memory was about 107 MiB. A separate Docker Chromium check displayed
moving footage for thirty uninterrupted seconds, verified Pause, and left zero
historical sessions after Stop. The updated service is running on localhost.

Three new Docker tests compile the production C++ buffer without the SDK and
cover decoder refusals, fast-producer/slow-consumer ordering and bounds, and
stopping a blocked callback. They run with the existing UI/CI command. The
manual API and browser checks now include sustained playback by default.
All 50 host unit tests and 33 Docker cases (30 browser, three native buffer)
passed. The publication privacy scan and whitespace check also passed.
Evidence and usage are in [History playback](docs/history-playback.md).

## Interactive History playback

The functioning timeline was committed as `bb40e0f` before this work. Clicking
the recording timeline, motion intervals or a committed time selection now shows
moving SDK footage. The player supports pause/resume, playing and paused seeks,
Stop, recorded-time playhead updates and per-camera aspect preferences. Dragging
previews locally and sends one seek on release. Entering History before live
discovery finishes still supplies camera settings, including an already-open
Settings dialog.

Independent Python playback leases share the existing native SDK login, while
each playback owns its handle/decoder, position and generation. The current
application admits one historical viewer and reserves one source-budget slot;
it does not evict another live viewer. New generations discard old frames and
timestamps. Leaving History, Stop, page-close cleanup and expiry release only
that viewer. SDK credentials and the full verification code remain backend-only.

The initial combined SDK/decoder pause failed with aggregated code 8; its layer
was not established. The verified implementation stops the native context on
pause, retains the last picture/time, and reopens at that recorded time on resume.
Seek also replaces just that context; a paused seek publishes one new picture
before holding. Positions come from the decoded stream's recorded system clock.

A bounded real API check verified exact first-frame time, distinct moving JPEGs,
pause holding frame/time, resume and playing/paused seeks, with one SDK login and
test-session cleanup. The real Docker browser displayed moving SDK footage at
the chosen time, 960 × 1088 source dimensions and approximately 16:9 display;
Pause held its image and Stop left zero playback sessions. A live preview also
advanced from 2 to 31 frames during the complete playback/control check, remained
live and reused the same login. Full-grid playback capacity is still unverified.

All 50 unit and 30 browser tests passed, covering playback,
settings and viewer isolation alongside existing grid/animation/recovery checks.
Details and private evidence paths are in
[History playback](docs/history-playback.md). Guides and API proposals now
describe implemented playback; audio, speed and export remain future work.
The updated service is running with the player and its new assets served. The
functional timeline checkpoint remains `bb40e0f`; playback and its flow-control
correction were subsequently committed as `563a6d7`.

## First History timeline slice

The pre-implementation plan was committed as `ccee147`. History now replaces
Recorded clip and displays SDK recording coverage and motion intervals for a
selected camera and 1/3/6-hour range (default three hours). Earlier/later,
Recent/Refresh, interval selection, previous/next motion and a keyboard time
slider are implemented. Playback video, pause/resume and seeking remain the
next slice; selecting time currently stays local.

The Python timeline service normalizes recorder wall time through private owner
timezone configuration, caches results for 60 seconds from completion, shares
identical work and bounds the query queue/cache. The existing native worker
performs metadata searches in a background thread through its shared SDK login.
It closes search handles, caps enumeration duration/results and keeps incomplete
coverage distinct from confirmed gaps. Credentials and captured data stay private.

V30 recording search returned two camera-1 intervals in a bounded three-hour
query, resolving the need for a usable recording-discovery path after the earlier
V40 error 11. Base motion search succeeded with zero intervals in that range.
A one-hour query while camera 1 streamed returned one recording interval and
zero motion intervals; 20 live packets were read, source sequences advanced
1-34, no feed errors occurred, and one SDK login was retained. Only the temporary
test viewer was released. Live plus historical video capacity remains unverified.

The native worker compiled and passed its offline decoder check without
credentials/networking/logins. All 40 unit and 24 browser cases passed with synthetic data,
including six new History cases and updated navigation/fresh-install checks.
See [History timeline](docs/history-timeline.md) for the API, limits and evidence.
Both getting-started guides and the API/milestone plan reflect this first slice.
The service was relaunched with the new History assets; HTTP readiness and all
new module/style routes passed without opening another recorder session.

## History view planning

Animated camera expansion and manual-scroll cancellation were committed as
`3ce2a65`; the local `origin/main` tracking ref now points to that commit after
the owner's VS Code push. Terminal HTTPS and SSH pushes lacked accepted GitHub
authentication; repository remotes were not changed.

The [History view plan](docs/history-view-plan.md) proposes replacing Recorded
clip with a single-camera, last-three-hours timeline, separate recording and
motion tracks, and independent interactive playback. Its stages are SDK
feasibility, a fixture-tested History UI, real timeline metadata, then moving
historical playback with verified pause/resume/seek. Clip export follows that
flow. The API proposal and milestone plan are aligned with these stages.

SDK time playback is verified; motion markers, general recording discovery,
interactive controls and live/history coexistence still need bounded checks.
The plan includes unit/API cases, changes to existing saved-MP4 browser tests,
new synthetic timeline/playback fixtures and unchanged offline CI commands.
No history code or recorder probe was added during planning. Existing verified
test counts remain 26 unit and 18 browser cases.

Before implementation, the owner clarified that precise event equivalence is
not required: present the SDK's returned motion-related intervals as provided,
with correct channel/time conversion and honest granularity. This plan is the
checkpoint before starting implementation.

## GitHub LFS authentication

The HTTPS push reached the publication guard but failed during LFS upload:
the container could not access host Git/VS Code credentials. The owner prefers
native Git LFS as an exception to Docker-only investigation tools. The setup
script now configures native filters locally, while the publication hook runs
the existing privacy scan before native `git lfs pre-push`. Setup guides list
host Git LFS explicitly. The Docker credential bridge is removed.

The owner installed native Git LFS on the host; version 3.4.1 is available.
The checkout's local filters now invoke native `git-lfs`, and its hook path
remains `.githooks`. Native `git lfs fsck` passed and the SDK archive's SHA-256
still matches the original. No push was attempted for this change.

All 21 existing unit tests and the full publication privacy check passed. An
offline hook check verified that native LFS receives the original remote
arguments and ref-update input, and that a privacy failure prevents upload.
Future checkouts use `python3 tools/setup_git_lfs.py` to configure native filters
while preserving the publication hook, then `git lfs fsck` to verify the SDK.

## Storage camera recovery diagnosis

Native Git LFS migration was committed as `1db2482`. Storage is SDK channel 3.
The running viewer had cached `online: false` at discovery; its session manager
excludes offline cameras before starting any preview. Earlier private logs show
Storage successfully streamed in a previous run. Discovery was a one-time
snapshot, so a recovered camera stayed excluded until the service restarted.

A single isolated SDK probe found Storage online with normal signal/hardware
flags, decoded eight frames and published five valid JPEGs at 352 × 288 without
errors. The viewer was relaunched, and its normal HTTP session/media API then
delivered three advancing, distinct Storage JPEGs with state `live`. The temporary
test lease was deleted; the server retains one SDK login and is ready for browsers.
Evidence stays private under `.local/browser-viewer/storage-check-*/report.json`
and `.local/browser-viewer/storage-web-check.json`.

The subsequent one-minute cache change below addresses the stale offline
snapshot. Full rediscovery of added/removed channels still needs service restart.

## One-minute camera availability cache

Camera availability now expires after 60 seconds. Active viewers request a
shared SDK status refresh through the existing login; a recovered offline
camera starts automatically in already-open grids. Healthy previews are retained,
and recent decoded video takes precedence over an offline status hint. Unknown
status preserves the last known state and is retried at most once a minute.
Authentication is never retried by this path. Idle viewers make no periodic
queries; `/api/cameras` can request an expired refresh on the next access.

All 26 host unit tests passed, including exact expiry, simultaneous callers,
recovery in shared sessions, failed/unknown status, healthy-stream preservation
and no extra login. A new offline Docker browser case verifies recovery in two
tabs across the 60-second boundary using the real cache/event implementation and
a controlled clock. The updated C++ bridge compiled against the bundled SDK,
and its offline decoder check passed with networking disabled and zero logins.
All 14 Docker browser cases passed. The service was relaunched with the updated
cache and native protocol. Storage then delivered three advancing valid JPEGs
through the normal browser API with one shared SDK login; the temporary test
lease was released. Evidence is private in
`.local/browser-viewer/availability-cache-web-check.json`.

## Current milestone: automatic live grid verified

The one-minute availability cache and recovery tests were committed as
`50c2272`. Picture expand/collapse now animates the existing tile over 360 ms,
keeping its aspect ratio and existing video source. Automatic scrolling brings
the tile into view and yields immediately to wheel, touch, keyboard, pointer or
scrollbar changes. Rapid reversals start from the current rectangle, resize and
disposal clean up the transition, and reduced-motion preferences skip animation.
Browser tests sample intermediate sizes/ratios and cover manual interruption,
rapid reversal and reduced motion. No backend video resizing or new stream is
introduced by expansion.
All 26 unit tests and 18 offline browser cases passed. The local service was
reloaded and verified to serve the new animation module. Browser checks also
verified that touch momentum can continue after manual input without further
automatic scroll requests; scrollbar offsets remain where the user places them.

The aspect correction was committed as `95ec310`. The service now discovers inputs
and automatically shows a responsive live grid. Nine configured inputs were
found: seven online (six analog and SDK IP channel 34) and two offline. Progressive
checks of 1, 2, 4 and all 7 previews passed using one SDK login. Independent decoder
contexts share sources across viewer leases.

Real Docker Chromium checks passed for moving frames, all seven displayed at
16:9, desktop/mobile layout, expansion, two tabs sharing sources and independent
Pause, plus saved historical playback. An unrenewed lease expired after 90 seconds
while an independently renewed view kept playing. Short seven-camera samples used
approximately 154 MiB and 50% of one CPU core; the hardware stream maximum and
sustained resource use remain unverified.

Owner IP/port/profile and limits now live in private `.local/nvr-config.json`.
Frontend code is split into shared API/feed/media helpers, live overview/tiles
and recorded-clip playback. One multiplexed JPEG connection per page avoids
per-camera HTTP connection limits; browser scaling preserves native JPEG sizes.
Expand remains overview quality. The last viewer leaving stops previews; the
shared login persists until service shutdown.

Eighteen offline unit tests passed, including source sharing, expiry, capacity,
configuration and native failure cleanup. Setup guides and the [implemented grid API](docs/live-grid.md) describe this
behavior. The next milestone is **motion-timeline feasibility**, including
recording-search compatibility. Concurrent historical extraction with the grid,
main-stream switching and a fresh remote/LFS clone remain untested. Evidence is
private under `.local/grid-check/`; no captures or credentials enter Git.

## Display controls refined

Picture-proportion selectors now live under Settings → Picture proportions.
The camera picture itself toggles expand/collapse and supports Enter/Space.
Expansion retains the same overview source. Per-camera browser preferences are
preserved, with Camera 1's choice shared by its live and recorded views.

The focused Docker Chromium check uses a fake worker with the real HTTP handler,
viewer leases, frame feed and frontend, plus synthetic JPEG/MP4 media. Seven
interaction checks passed, including refresh persistence, independent preferences,
modal focus/Escape, mobile fit and recorded-video proportions, with networking
disabled, no credentials/SDK mounted, zero SDK logins and no browser errors.
See [check_display_controls.py](tools/check_display_controls.py).

## Offline UI test suite

The preceding settings/click-to-expand work was committed as `c25054b` before
adding this suite. `python3 tools/run_ui_tests.py` runs Docker Chromium against
the real frontend, HTTP API, live-session manager and multiplexed JPEG feed.
The small server-construction seam accepts a worker; tests supply a simulated
recorder with eight distinct animated cameras, an offline input and synthetic
recorded video. The container has no network access, SDK, credentials or private
configuration mounted, and does not use the owner's running viewer.

Cases cover camera identity/movement, independent failures/stale states, capacity,
settings/persistence/keyboard/mobile behavior, recorded playback, shared tabs,
Pause/Resume, refresh/close cleanup, real ten-second lease expiry and startup
navigation. The suite exposed and fixed returning to Live while discovery is
pending: the requested start is now queued and Pause cancels it. Backend setup
and SDK-dependent password/encryption behavior remain unchanged.

All 13 UI cases and 18 existing unit tests passed. The runner saves JSON outcomes
and synthetic screenshots in ignored `.local/ui-test-results/`. Setup guides and [UI testing](docs/ui-testing.md)
document running the suite without recorder setup. Real SDK/device compatibility
still requires its separate checks.

## GitHub CI prepared

`.github/workflows/ci.yml` runs independent unit and offline UI jobs on pushes,
pull requests and manual dispatch. It uses the same commands as local testing,
skips the SDK/LFS download and needs no recorder credentials. UI JSON results
and synthetic screenshots are retained as GitHub run artifacts for 14 days,
including ordinary test failures. GitHub checks local commits after they are
pushed; newer pushes do not cancel older runs. Deployment remains a later step.

Workflow syntax passed actionlint in Docker. All 18 unit tests and 13 UI tests
passed using the workflow commands from a clean temporary source copy, initially
without SDK, `.local/` or Git metadata. Evidence is private under
`.local/ci-validation/`. Hosted Actions execution awaits a GitHub push; no repository remote
or publishing action was configured here. See [CI notes](docs/ui-testing.md#github-actions).

## Real service revalidated after the UI-testing seam

The viewer was relaunched with `create_server` wired to the real SDK worker.
HTTP/assets loaded; one SDK login discovered nine configured inputs. The current
snapshot reports four online (channels 1, 6, 8 and 34) and five offline (2, 3, 4,
5 and 7), compared with seven online in the initial grid experiment. The cause
of that availability change was not investigated or attributed to the seam.

A brief check retrieved valid JPEG packets for every available stream, confirmed
two viewer leases share the same sources/login, and verified that deleting one
lease preserves advancing frames for the other. The saved recording still serves
HTTP byte ranges. Temporary leases were released; the service remains ready for
the owner's browser. Private results: `.local/relaunch-check.json`. No credential
retry or recorder settings change was performed.

## Publication preparation

The approved UI suite, CI workflow and production seam changes are committed
with publication cleanup. General Gitleaks history scanning found no token or
password leaks. Known-value checks found no saved login password, effective
password prefix or full stream-encryption code in publishable files, Git objects
or the SDK archive. Account-name substring matches were technical vocabulary;
no literal credential assignment was found.

Local recorder addresses and personal home paths were removed from source/notes.
The remaining legacy diagnostics now read private configuration. Unpublished
history is sanitized before the first push, with the original Git metadata and
LFS objects preserved under ignored `.local/publication-backup/`. Commit IDs
change; older IDs in investigation notes describe the original local history.
The original SDK archive and private running-service configuration are preserved.

A repeatable publication check is added to the pre-push/LFS hook and CI. It checks
publishable files and branch/tag history, with private values kept out of reports.
No GitHub remote or push is performed until the owner provides the repository.
See [publication checks](docs/publication-checks.md). The offline suite now has
21 unit cases, including three publication-check tests; UI coverage remains 13.

## Authentication finding

The recorder's web password input accepts at most 16 characters. The password
in the credentials file was longer; using its first 16 characters resolved
both RTSP and SDK authentication. This is verified for this recorder, rather
than assumed to be a universal Hikvision rule.

The current Python SDK adapter now owns that limit for all authenticated probes.
`tools/credentials.py::load_credentials()` only reads and validates the original
values. The adapter preserves the username, the complete verification/encryption
code, and the original credential file. Credentials
remain private in `.local/nvr-credentials.json`; tests cover the boundary and
preservation of those values. The new non-admin account also logs into the
local web UI.

## RTSP login: successful; video decoding unresolved

- Port 554 is open; the tested path is `/Streaming/Channels/102` (camera 1,
  substream) over RTSP/TCP.
- At 12:46:11 on 2026-10-10, one FFmpeg session using the first 16 password
  characters passed authentication and reached HEVC/H.265 processing.
- FFmpeg reported invalid VPS/SPS/PPS/NAL data and could not determine frame
  dimensions. No valid frames or usable capture were produced.
- Stream encryption is enabled in the recorder UI. The decode errors are
  consistent with encryption, but do not alone prove it is the cause. No
  verification/encryption code was applied during that RTSP test.

Details: [RTSP result](docs/rtsp-first16-results.md) and
[authentication history](docs/authenticated-probe-results.md).

## SDK login: successful in Docker

- The original Linux64 HCNetSDK 6.1.9.48 package was downloaded manually after
  the vendor site blocked automated downloads. The runtime and download tools
  run in Docker; no new tools were installed on the host.
- Offline loading and initialization passed. The SDK needs more than the
  initial 128-thread/process container limit; the working runner allows 512
  with CPU and memory limits still in place.
- At 12:54:51 on 2026-10-10, one synchronous `NET_DVR_Login_V40` call on port
  8000 succeeded with SDK error 0, using the shared credential loader.
- That initial test was login only, followed by logout and cleanup. A later
  preview verified capture and decryption, as recorded below.

Details: [SDK investigation](docs/sdk-docker-investigation.md),
[SDK usage notes](docs/official-sdk-usage-notes.md) and
[credential loader](docs/credential-loading.md).

## Encrypted live stream: successfully decoded

At 13:29:45 on 2026-10-10, a single SDK login and 20-second preview successfully
decoded **300 YV12 frames at 352 × 288** from the first camera's substream.
PlayCtrl reported encrypted video (type 2, AES-10-round) with a key present,
and zero decoder/input errors. The saved frame was converted offline to PNG
and visually confirmed as recognizable camera imagery with a valid timestamp.

The working call is `PlayM4_SetSecretKey(port, 1, full_verification_code_utf8,
128)` before opening the stream. Offline inspection of the supplied Hik-Connect
APK established this call pattern; the live test confirmed it with the supplied
Linux decoder. The complete verification code is preserved. The fixed `128`
argument does not mean truncating that string to 16 characters.

No recorder settings were changed to disable encryption. Authentication
remains bounded to one login per probe. Details and reproduction commands:
[encrypted-stream investigation](docs/encrypted-stream-investigation.md).

## Historical playback: successfully extracted

The installed SDK provides recording search, time/filename playback, recorded
data callbacks, playback controls and downloads. Both V40 and V50 APIs are
present in its headers and exported by the Linux library. Recorded callbacks
can feed PlayCtrl, and the APK's playback branch uses the same full encryption
string.

At 14:51:50 on 2026-10-10, direct SDK time playback retrieved camera 1's main
recording for **13:51:50-13:51:55**, exactly an hour earlier by the DVR clock.
PlayCtrl decoded 75 frames at 960 × 1088 and 15 fps; offline FFmpeg produced
a verified 5-second H.264 MP4. Its first frame visibly confirms the requested
historical timestamp. The full verification code was configured, but this
recording did not report an encryption flag, so its key requirement is unknown.

Two bounded sessions were used: the initial recording search returned SDK
error 11; the subsequent direct playback succeeded without a search. Login
succeeded once in each session; there were no credential retries or recorder
settings changes. Recording discovery remains unresolved.

Details: [historical-playback investigation](docs/historical-playback-investigation.md).
Verified result and commands: [historical-playback results](docs/historical-playback-results.md).

## Earlier single-camera browser prototype

A local Docker-backed prototype now serves camera 1 at `http://localhost:8088/`.
Start/Stop controls manage one shared SDK/PlayCtrl session, with the full
verification code kept in the backend. Latest decoded frames are converted
to JPEG and shown as MJPEG; the previously extracted MP4 also plays in the
browser with native controls.

Chromium verification observed changing displayed pixels, advancing recorded
playback, and 49 live frames. Repeated Start and a refresh reused the same
session. The native result confirms one login, 81 decoded frames, 50 JPEGs,
encryption type 2 and zero decoder errors. Stop cleaned up that session; the
web server remains running, with the camera stopped and ready for user Start.

Details and commands: [browser-viewer prototype](docs/browser-viewer-prototype.md).

## Agreed milestone plan

Before grid work, [image proportions](docs/image-display-aspect.md) were inspected
using existing media. Live frames are 352 × 288; historical frames are 960 × 1088.
The browser now has a shared media-display module and a 16:9/4:3/Original control
for both live and recorded views, with a remembered browser preference. It fits
the whole picture without cropping. The owner confirmed 16:9 matches this
camera's Hik-Connect view; it is a confirmed display preference, not measured
stream metadata or a global rule for other cameras.
Eight Docker Chromium fixture cases and the ten offline unit tests passed.
Initial correction used saved media only. After the owner supplied a matching
Android screenshot, the service was relaunched and one brief live session
confirmed moving frames at 16:9, unchanged 352 × 288 JPEGs and zero size-style
updates during steady playback. The native report recorded one login, 84 decoded
frames, 50 JPEGs and zero errors; Stop cleaned up. Recorded playback also showed
16:9. The server remains available with the camera stopped. A versioned preference
key clears old comparison choices once; new choices remain remembered.

The first [Python SDK adapter seam](docs/sdk-adapter-seam.md) is implemented.
One concrete HCNetSDK 6.1.9.48 adapter owns credential normalization, deterministic
native build locations, launch arguments/stdin/library environment and runtime
image. The browser accepts an injected adapter; diagnostics and host launchers
use the shared selector. No plugin framework or second SDK was introduced.

Ten offline unit tests passed, including a stub adapter with different launch
settings and an untruncated password. The actual Docker SDK/decoder check also
passed with private SDK logging enabled, networking disabled, no credentials
mounted, zero login calls and zero decoder errors. The later aspect-ratio check
above also verified the adapter with one real live session;
recorder configuration, camera discovery and persistent per-stream workers were
the next milestones and are now implemented above. The 16-character policy is now assumed to belong to the SDK
implementation rather than a user-configurable installation override.

The agreed plan follows this order, with the automatic live grid ahead of motion
timeline investigation as requested:

1. Recorder configuration, camera discovery and capacity.
2. Automatic live grid.
3. Motion timeline feasibility.
4. Historical timeline viewer.
5. Reliability and transport.

Credentials remain in the backend file and frontend login is deferred for home
LAN use. Frontend files may be split by logical function: shared API/media
helpers, live overview/tiles, history/timeline/playback controls and exports.

The recorded plan is in [implementation-plan.md](docs/implementation-plan.md).
A reviewable API proposal is in [backend-api-plan.md](docs/backend-api-plan.md).
Inventory and live-session endpoints are now implemented; historical
timeline/playback/export endpoints remain proposals. Discovery and the initial
grid are verified above; the next investigation is motion metadata.

## Reproducibility and preservation

The setup guides, agreed milestone order and API proposal were committed as
`b9c7cca`. A subsequent [recorder compatibility review](docs/recorder-compatibility-review.md)
assesses readiness for other Hikvision NVRs/SDKs. It confirms `.local/` owner
configuration and recommends one small adapter with versioned SDK bundles,
explicit authentication policies and independently reported capabilities.
Current code remains a single-recorder prototype; no new NVR probes or feature
implementation were performed for the review.

The service is intended for other owners to clone and run on their own machines.
The installing user supplies the NVR IP and SDK port in backend configuration,
with credentials kept separate. The viewer and authenticated SDK runner now
read owner configuration; legacy RTSP/web investigation scripts retain the
original address. Python application logic and a persistent C++ SDK bridge
implement the current backend split.

The root [GETTING_STARTED.md](GETTING_STARTED.md) gives a short human-facing setup
overview; [GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md) contains detailed
installation and verification instructions. Both must be maintained with
architecture changes. Setup uses the SDK archive
already in Git LFS, without a separate vendor download. Only documentation was
changed to record these requirements; no recorder calls or feature code were added.

The agent guide includes a prerequisite/install/verification checklist,
with Docker explicitly required to work without sudo as the installing
user. Offline SDK checks, private-file validation, Docker TCP reachability,
HTTP readiness and live video acceptance are separate stages. Host installation
recipes are documented for missing essentials; none were executed here.

Source, investigation notes and credential tests are versioned. The complete
original SDK ZIP, including its binaries, headers, examples and vendor
documentation, is tracked with Git LFS under `vendor/hikvision/`.
Credentials, native debug logs, APK analysis and camera captures stay in the
ignored `.local/` directory. See [README](README.md) for Docker/LFS setup and
restoring the SDK.
