# High-quality live viewing plan

Proposed: 16 October 2026; approved plan committed as `efc4007`.
Milestone 1's backend was reviewed and committed as `482aa8d` after passing
94 backend and 73 browser/native cases. Milestone 2's frontend switching is now
implemented; verification and device evidence are recorded in
[live grid](live-grid.md) and [progress](../progress.md).
Milestone 2 was committed as `6312fca`. The subsequently approved milestone 3
is implemented with offline recovery checks and a successful 302.6-second
real-browser workload check, committed as `a05a2dc`. A subsequent bounded
experiment passed with two concurrent high-quality sources and History;
[measurements and scope](live-grid.md#two-main-stream-capacity-experiment) are
recorded separately. The experiment restored the original operating limit of one; the subsequent
approved rollout raises the configured limit and project default to two.

## Intended behavior

Opening Live overview continues to use overview streams. Expanding a camera
requests its main stream; the enlarged picture stays usable at overview quality
until a fresh high-quality frame arrives. Collapsing releases that viewer's
high-quality request. Other viewers and cameras continue independently.

The initial limit was one distinct high-quality source across the backend.
After the two-source experiment, the default and owner configuration allow two;
the limit remains configurable. Several viewers expanding the same camera share that source
and count as one. Expanding different cameras competes for the available slots;
existing admissions retain their slots. Keep the existing ability to expand
multiple tiles; an expanded tile can remain at overview quality.

## Current constraints and design choice

Before milestone 1, sources were keyed only by camera, native preview selected
the substream, and the session API accepted only `quality: "overview"`. The configured
`max_live_sources` budget also accounts for historical playback and exports.
Its default of eight is an application limit; the recorder's maximum is unknown.

Use source identity `(camera_id, quality)` in Python and corresponding explicit
source identity in native commands, events, frame directories and generations.
Preserve one SDK login. Keep SDK stream selection behind the current adapter /
worker boundary; the public API uses `overview` and `high`, not SDK constants.
Validate the selected SDK's main-stream setting before the bounded device check.

Keep the overview source while high quality is requested. This costs an extra
preview/decoder but gives immediate fallback and preserves other viewers' grid
quality. Replacing the shared overview would change every subscriber's stream;
deriving overview JPEGs from the main stream adds resizing and decoder coupling.
Consider those alternatives only if measurements justify their complexity.

## Milestone 1: backend support, limits and evidence

1. Extend native preview and Python source management to distinguish the two
   qualities, including errors, availability evidence, cleanup and frame caches.
   Audit users of camera-keyed sources, including diagnostics, the fake worker,
   history/export admission and native channel validation. Keep reference counts
   explicit: each high-quality subscription retains an overview fallback.
2. Add validated private configuration `max_high_quality_sources`, initially one,
   with zero disabling the feature. Keep `max_live_sources` as the total budget:
   overview + high-quality sources + historical/export reservations. Admission is
   atomic and counts starting/closing resources until actually released. Healthy
   admitted streams and existing historical/export work are not evicted for an
   upgrade. At a full budget, high quality falls back to overview.
3. Reject malformed/unknown qualities, but treat valid high-quality requests
   that cannot be served as per-camera fallback, rather than failing the whole
   session. Do not leave denied requests queued for an unexpected later upgrade.
   A failed/denied attempt can be retried by collapsing and expanding again.
   Bound first-frame waits, release failed native resources and avoid automatic
   SDK login or stream retry loops. A stalled high-quality source falls back to
   fresh overview frames and reports the reason.
4. Extend the existing live session PATCH selection. For example:

   ```json
   {"cameras":[{"id":"camera-1","quality":"high"},{"id":"camera-2","quality":"overview"}]}
   ```

   Retain every selected camera when updating the selection. Responses distinguish
   `requested_quality`, effective `quality`, upgrade status and a structured
   reason such as capacity, unsupported or decoder failure. Effective quality
   changes only after a fresh frame is available. Renewal with `{}` continues to
   renew the lease without changing selection. Overview-only clients keep working.
5. Reuse one media feed per viewer and send only that viewer's effective rendition
   for each camera. Include quality, source generation and a session selection
   revision in frame/status metadata. Discard superseded frames, late native
   events and stale HTTP replies, including JPEG decodes finishing after a switch.
   Internal counters include source identity so equal frame sequence numbers
   across renditions cannot suppress the first upgraded frame.
6. Extend `/api/status` with requested/starting/active high-quality counts, distinct
   sources by quality, total capacity/reservations, configured limits and recent
   upgrade refusals/failures. Record per-source dimensions, decoded/delivered FPS,
   frame age, JPEG bytes and first-frame latency. Sample container CPU/RAM and
   network throughput during bounded checks. Keep measured capacity separate from
   configured limits; other clients such as Hik-Connect are outside our counters.

Before milestone 1, the native decoded-frame limit was 4 MiB, separate from JPEG/feed and
compressed decoder buffers; milestone 1 raised the validated YV12 limit to 16 MiB.
Review resolution-dependent allocation, dimensions,
frame-size validation and all transport caps before assuming larger main streams
fit. Keep buffers bounded, publish only the latest live frame and retain the
current publication cadence initially. High quality means the recorder's main
stream at its configured resolution, not a promise of original frame rate or a
lossless copy. Browser scaling continues to apply picture proportions efficiently.

Verify offline first, then one bounded real main-stream session with the existing
encryption key. Compare dimensions, moving frames and load against overview.
Next check full overview + one high source, two viewers sharing it, and coexistence
with one historical session or export when the configured budget allows. Start
with one high source; test two only if the first measurements show headroom and
there is a reason to raise the default. Stop on errors, sustained stale frames or
resource pressure; do not search for the recorder's absolute failure threshold.

Completion: the API can request high quality, preserve overview on failure, share
and release resources correctly, and report enough evidence to choose a safe cap.

## Milestone 2: frontend switching

- Notify Overview when a tile expands/collapses. Preserve the existing animation,
  automatic scrolling, manual-scroll cancellation and keyboard activation.
- PATCH that camera's desired quality through the existing viewer lease. Serialize
  selection changes and coalesce rapid toggles to the latest intent. Guard poll,
  PATCH and frame handling with selection revisions; delayed responses cannot
  restore high quality after collapse or apply changes to a replacement session.
- Keep the current overview picture while upgrading, then swap on the first
  accepted high-quality frame. On collapse, switch to overview and release only
  this viewer's high-quality reference. Navigation, Pause view, close and lease
  expiry release all of this viewer's references through the existing lifecycle.
- Show “Upgrading…”, “High quality” or “Overview · High quality unavailable” with
  a useful reason. A capacity refusal leaves video moving and does not become
  an offline/error tile. Make quality feedback accessible. The badge describes
  frames actually displayed, not merely the preference sent to the backend.
- Derive per-tile and overall quality labels from effective status; the current
  hardcoded Overview metrics/footer must no longer mislabel a high-quality view.

Completion: expansion visibly upgrades where admitted, collapse returns to
overview, and refused upgrades preserve a working enlarged view.

## Milestone 3: reliability and resource checks

Approved after milestone 2 was committed as `6312fca`. Keep the shared
high-quality cap at one throughout this stage.

- Reproduce browser media disconnections, including a clean end of the feed.
  Reconnect only the existing media URL, with bounded retries and cancellation
  on Pause/navigation. Preserve lease, selections and native source sharing;
  do not retry SDK authentication or create a new viewer automatically.
- Show interrupted/delayed delivery accurately even if backend frames continue.
  Verify terminal failures release resources, and paused History is not mistaken
  for a stalled live feed. Exercise recovery alongside high-quality live video.
- Add deterministic offline browser regressions for disconnects, retry exhaustion,
  cancellation, freshness, and independent live/history lifetimes.
- Run a bounded longer real-browser check across multiple lease renewals with
  the full reported online grid, one shared main stream and historical playback.
  Sample service CPU, memory, processes and traffic; verify moving pixels,
  source sharing, repeated switch/release and final cleanup. Stop on stale frames,
  unexpected sources/login calls or resource pressure. Keep evidence private.

Completion: the tested workload remains usable over the recorded duration,
interrupted pictures are labeled honestly, browser recovery does not duplicate
native sources, and all resources owned by the check are released. Report the
duration and resource observations explicitly; this does not establish a hardware
maximum or justify raising the high-quality cap. H.264 transport remains separate.

## Tests and documentation

Backend tests cover two qualities for one camera, shared high sources, atomic
concurrent admission, both budgets, active history/export reservations, fallback,
timeouts/stalls, first-frame promotion, source-generation isolation, idempotency,
renewal, delete/expiry and resource release. Test a freed high-quality slot being
reused by an explicit new request, without resurrecting a rejected request.
Native offline checks cover stream selection, identity routing, frame bounds and
cleanup; mocks cannot establish main-stream compatibility on the actual NVR.

Extend the synthetic worker with visibly distinct overview/high frames and
controllable first-frame delays, failures and stale events. Browser tests check
actual rendition pixels/dimensions as well as badges: expansion/collapse,
keyboard/mobile/reduced motion, rapid reversal, delayed replies/decodes, two tabs
sharing one high source, another camera denied by the cap, fallback while the
other grid moves, and navigation/close/expiry cleanup. Existing expansion and
sharing tests must account for intentional additional high-quality starts while
continuing to assert no duplicate sources per camera and quality.

Run the full backend and offline UI/native suites through the current CI entry
points after implementation. Document real-device measurements separately.
Update both getting-started guides for the new private setting, plus API, live
grid, UI testing and progress documentation. Review the measured operating cap
before enabling frontend upgrades by default. Transport changes such as H.264
remain a separate decision if JPEG costs prove too high.
