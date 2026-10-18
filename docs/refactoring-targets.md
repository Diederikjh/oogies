# Architecture refactoring targets

Reviewed: 17 October 2026 (Africa/Johannesburg).
Baseline: `480c85c`. The owner reviewed the detailed target-1 plan and approved
implementation after committing it on 17 October 2026 as `19d12bf`. Target 1 is
**implemented, verified and committed as `0f3bf9f`**. Target 2's reviewed plan was
committed as `900483a`; its implementation, all 127 backend checks and all
[93 browser/native checks pass](stream-budget-refactor-plan.md). Implementation
was reviewed and committed as `3021d42`. Target 3's
[approved detailed plan](frontend-test-layer-plan.md) was committed as `8e60f84`;
milestone 1 was committed as `ab2dd80` and milestone 2 as `72f8d87`.
Milestone 3 was reviewed and committed as `d2b0ab0`. Milestone 4 organizes the
remaining browser cases by feature; all 134 Python, 125 JavaScript and
91 browser/native checks pass. Target 3 is implemented and verified, with
milestone 4 reviewed on 18 October 2026.
Targets 4-9 remain backlog proposals.
Target 1 passed its seven
new accounting tests, all 25 export tests and the then-complete 107-test backend
suite; these regressions remain in the expanded suite. See the
[target-1 results](export-accounting-refactor-plan.md#implementation-and-verification-result).

Keep the existing Python/C++ split, one SDK login, shared quality-specific
sources, bounded latest-frame caches, synthetic recorder seam and frontend
functional modules. The main pressure points are resource ownership, shared
mutable state, asynchronous UI state and the cost of testing these through a
browser. This review does not establish a need to change frameworks or introduce
a universal SDK abstraction before a second implementation exists.

Effort below means focused developer days including relevant tests. These are
rough estimates, with overlapping work; they should not be added as independent
commitments. Return describes reliability, testability and maintenance benefits,
not a promised runtime speedup.

| Target | Effort | Expected return | Pressure / evidence |
| --- | --- | --- | --- |
| 1. Race-safe export file accounting (implemented) | Estimated 0.5-1 day | High; resolve a demonstrated failure with a small change | Replaced separate existence/size checks with one metadata observation and per-file missing-path handling; deterministic regression and caller/queue tests pass. |
| 2. Shared stream-budget manager and independent export/playback ownership (implemented and verified) | Estimated 2-4 days | Very high; explicit ownership and isolated contention tests | Identified shared reservations replace live-counter mutations; helper/maintenance ownership and fixtures migrated. Backend contention, failure and cleanup checks pass. |
| 3. Faster logic tests below the browser layer (implemented and verified) | 1-3 days initially | Very high; more combinations, faster feedback | Native/Docker Node tests cover 125 filename, clip, timeline, range and export-state cases. Submission/feedback ordering uses controlled time; browser wiring/presentation stays covered. 134 Python cases pass; 87 browser/four native cases are organized by feature with one media setup. The full 91-case suite passes in 895.3 s including setup versus the 943.3 s baseline; a single local comparison does not establish a speedup. Direct logic checks take under one second of Node time. |
| 4. Separate playback state from rendering | 2-4 days | High; simpler reasoning about overlapping controls | `PlaybackControls` combines leases, requests, seeks, rates, JPEG rendering, downloads and DOM state. Epoch/generation/control guards solve real races but are spread through the controller. |
| 5. Shorter shared-lock critical sections | 2-4 days | High; reduce opportunities for unrelated work to stall | Export manifest writes, `fsync`, directory cleanup and frame packet construction use the worker's shared condition lock. Actual contention needs measurement before claiming a speedup. |
| 6. Native transport boundary and protocol tests | 2-4 days | High; cover bridge failures and prepare for another SDK | `GridWorker` combines process transport, event handling, discovery and frame/state caches. The fake recorder and native helper tests cover useful behavior but do not exercise the complete SDK bridge protocol. |
| 7. Incremental JPEG-path improvements | 1-2 days initially; 3-5 more for a new handoff | Medium now; higher with larger images or more viewers | Python polls every 50 ms and reads JPEGs before checking the cached sequence; native publication runs roughly every 100 ms. The browser parser repeatedly copies accumulated chunks. |
| 8. Explicit HTTP/application lifecycle | 1-2 days | Medium; easier startup, shutdown and failure testing | The grid handler inherits utilities from the prototype server, and `create_server()` replaces `server_close` dynamically. Service ownership and cleanup are spread between setup, entrypoint and tests. |
| 9. Build or cache the native bridge before startup | 1-2 days | Low-medium; predictable startup and a possible smaller runtime image | Each service start recompiles the bridge. This does not materially improve steady-state streaming and needs a clear rebuild/invalidation path. |

## Proposed extractions and verification

1. **Export accounting:** use a single metadata observation for each candidate
   file, skip normal disappearance, retain visibility of other I/O failures.
   Add deterministic rename/removal tests and verify queue/list/admission paths.
   See the [detailed target-1 plan](export-accounting-refactor-plan.md).
2. **Capacity ownership:** introduce a small component that owns reservations,
   releases and capacity snapshots. Preserve source sharing, existing admission
   priority, delayed-live-stop accounting and explicit retry behavior. Test
   simultaneous live/History/export requests, repeated release and stale events.
   See the [detailed target-2 plan](stream-budget-refactor-plan.md), including
   independent feature state/lifetimes and concrete required tests.
3. **Test structure:** extract logic with explicit clock/timer inputs. Partition
   the large UI suite by feature for navigation, while retaining representative
   browser interaction, layout and integration cases. Moving files alone does
   not create a faster or more complete test suite. See the
   [detailed target-3 plan](frontend-test-layer-plan.md) for the JavaScript runner,
   production seams, assertion migration map and staged review/verification gates.
4. **Playback controller:** separate explicit state transitions/request ownership
   from image and button rendering. Test seek/rate response reordering, stop
   during startup, camera changes, reconnection and late frames using a small
   controlled scheduler before preserving the corresponding browser cases.
5. **Lock scope:** document lock ownership, snapshot immutable data under the
   lock, and perform suitable file/packet work outside it. Keep export writes
   ordered with appropriate storage synchronization. Verify slow storage,
   concurrent playback, cleanup and finalization; avoid replacing one race with
   another by merely moving I/O out of the lock.
6. **Native protocol:** separate transport from domain state without finalizing
   an interface for an unknown second SDK. Test process exit, malformed and
   fragmented events, stale generations, command failures and cleanup using a
   fake native process. Keep compiler/toolchain work in Docker. Real SDK behavior
   still needs explicit bounded device checks.
7. **Media hot path:** first profile per-stage costs and avoid unchanged-image
   reads; test generation/sequence safety and arbitrary network fragmentation.
   Consider framed IPC only if measured file handoff costs justify it. Preserve
   bounded buffering, latest-frame behavior and honest freshness reporting.
8. **Lifecycle:** extract shared HTTP helpers and one owner of service resources;
   test partial construction, repeated close and shutdown with active sessions.
   Preserve the current API and authentication policy.
9. **Build:** place compilation in image creation or a content/version-keyed
   cache. Verify changes invalidate the binary, a fresh install builds correctly,
   and normal startup uses the correct SDK without an authentication probe.

## Performance context and prioritization

The bounded experiment with four online overview sources and two 960x1088 mains
averaged about 49% of one backend CPU core, peaking around 148 MiB backend memory
and 506 MiB browser memory. These are short Docker samples, not a sustained
measurement of today's seven-camera workload or the recorder's internal CPU.
See [the workload comparison](live-grid.md#two-main-stream-capacity-experiment).

JPEG encoding, file handoff, network delivery, packet copies and browser decoding
are scaling costs. Shared sources prevent duplicate SDK decoding for another
viewer, but each viewer still receives and renders media. Browser aspect sizing
already avoids server-side image resizing. A compressed-video transport should
be a separately measured investigation if JPEG costs become limiting.

Targets 1 and 2 provide initial ownership/test seams. Review target 3 next, then
use the resulting logic tests to support targets 4-6. Schedule larger media
changes after profiling.

## Relevant code and existing evidence

- [Export jobs](../docker/hikvision-sdk/export_jobs.py),
  [encoder](../docker/hikvision-sdk/export_encoder.py),
  [export tests](../tests/test_export_jobs.py).
- [Live sessions](../docker/hikvision-sdk/live_sessions.py),
  [playback sessions](../docker/hikvision-sdk/playback_sessions.py).
- [Worker](../docker/hikvision-sdk/grid_worker.py),
  [native bridge](../docker/hikvision-sdk/live_grid.cpp),
  [current SDK seam](sdk-adapter-seam.md).
- [Playback UI](../web/history/playback-controls.js),
  [frame parser](../web/shared/frame-feed.js),
  [browser test fixture](../tests/ui/fixture.py), [test guide](ui-testing.md).
- [HTTP composition](../docker/hikvision-sdk/grid_server.py),
  [adapter compilation](../tools/sdk_adapters/hcnet_61948.py).
