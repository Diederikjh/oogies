# History view plan

Status: recorded before implementation in `ccee147`, 11 October 2026.
The first [History timeline slice](history-timeline.md) is now implemented:
metadata queries and timeline selection. Interactive historical playback,
pause/resume/seek and playback coexistence remain next. This plan expands milestones 3 and 4 in
[implementation-plan.md](implementation-plan.md); endpoint contracts remain in
[backend-api-plan.md](backend-api-plan.md).

## First usable view

Replace **Recorded clip** with **History**. Show one selected camera, its picture,
and a timeline covering the last **three hours**, with 1/3/6-hour presets and
earlier/later navigation. Keep recording coverage and motion markers on separate
tracks. Clicking a time selects footage; clicking a motion marker selects its
start. Include pause/resume, a playhead, and previous/next motion actions.

Entering History loads metadata without automatically starting playback. The
user selects a time or event to start. Dragging previews a selected time locally;
only releasing the pointer sends a seek. Provide keyboard time adjustment and an
event list as alternatives to small markers. Point events and interval events
need distinct representations. Display the configured recorder timezone.

Keep a fixed selected range until the user asks for Recent again. While Recent
is active, refresh metadata at most once a minute; preserve the selection and
playback position. New events must not jump the viewer away from older footage.

Use the existing per-camera aspect preference and browser rendering, including
when the selected camera changes. History remains accessible on a fresh install
without a private MP4. A camera being offline for live viewing does not imply its
older recordings are unavailable.

Distinguish loading, confirmed recording gaps, no motion found, unavailable
motion information, incomplete search results, and playback errors. Recording
search failure must still allow an explicit time-playback attempt, since that
already succeeded independently on this recorder. Never silently switch to live.

Defer audio, speed selection, multi-camera synchronized playback, thumbnails,
calendar browsing and clip export until this flow works. Export remains a later
part of milestone 4, using its separate job API.

## Evidence and SDK feasibility

Verified: a five-second camera-1 recording was decoded through SDK time playback
and PlayCtrl, then played as an MP4. V30 recording discovery and base motion
search now return accepted results through the first History slice. The sampled
motion ranges were empty, so real nonempty marker data remains unverified.
Interactive controls and historical playback alongside another user's live
grid remain unverified. `NET_DVR_FindFile_V40` previously failed with error 11;
it did not establish missing footage or a permissions problem. See
[historical results](historical-playback-results.md) and
[timeline results](history-timeline.md).

Hikvision's [event-search documentation](https://open.hikvision.com/hardware/definitions/NET_DVR_FindFileByEvent.html)
describes finding recordings by event and using their time ranges for playback.
This is a high-confidence API candidate. The owner does not require precise
event timing or Android timeline equivalence for this milestone: present the
SDK's returned intervals with their source and granularity. Verify channel and
clock conversion; matching Android markers is optional corroboration.

Start with a minimal motion search using `NET_DVR_FindFileByEvent`, paired with
`NET_DVR_FindNextEvent` and `NET_DVR_FindClose_V30`. Match structures to the API
generation; base and V40 channel selectors differ. Bound polling, result count
and runtime, and close search handles on every exit. Investigate general
recording search separately with a minimal request; choose a legacy or V40
variant deliberately from the evidence, rather than cycling through variants.
Reuse accepted credentials; do not add authentication retries.

The [playback-control documentation](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackControl_V40.html)
provides pause, resume and absolute-time seek. Its time-playback progress query
returns coarse running/end/error values, so it cannot supply a precise playhead.
Verify the SDK OSD clock and decoder timing, pause behavior, buffer clearing on
seek, and first-frame time after seeking. Expose only verified controls.

Read the recorder clock, convert its timestamps through the configured timezone,
and compare event and playback times with the app/visible OSD. Internal times and
HTTP responses are UTC; timezone-aware inputs are mandatory. Do not derive an
absolute video time from HTTP arrival or decoder-relative milliseconds alone.
Verify timezone data inside Docker; add container `tzdata` if required. For
other installations, ambiguous daylight-saving wall times need an explicit
policy or a verified UTC-capable SDK path.

If this approach fails, reassess before editing around it: compare a supported
SDK/event-log or SDK-mediated ISAPI query, or ship time playback with motion
marked unavailable. New alarm subscriptions can collect future events but do
not backfill the Android app's historical timeline.

## Milestones and acceptance

| Stage | Backend work | Frontend work | Verification before moving on |
| --- | --- | --- | --- |
| A. SDK feasibility | Bounded recording/motion searches; clock conversion; pause/resume/seek and cleanup checks; one playback alongside existing live viewers. | No production UI changes; inspect the returned SDK data. | Returned intervals have correct channel/time conversion; report granularity and unsupported capabilities honestly; measure coexistence without exhausting connections. |
| B. History UI with fixtures | Extend the injected fake worker for the proposed timeline and playback contracts; add real HTTP routes/services around it. | Replace Recorded clip with History; camera/range selection, two timeline tracks, events, controls and selected-camera aspect. | Offline browser tests prove navigation, playback selection, states, accessibility and viewer isolation without a saved private clip. |
| C. Real timeline queries | Add bounded SDK search operations through the current adapter/worker; normalize results and cache recent metadata. | Connect the fixture-tested timeline to real metadata; handle partial/unknown data and refresh. | The timeline faithfully displays returned SDK intervals; metadata queries do not interrupt another tab's live frames. |
| D. Interactive historical playback | Add independent SDK playback contexts and decoder feeds, verified controls, leases and capacity admission. | Render moving historical frames; update the playhead; connect seek, pause and event navigation. | Correct footage/time after seeks; no old frames reappear; one viewer's controls/expiry do not affect another; bounded live/history coexistence passes. |

The order allows the UI to be developed against fixtures after feasibility,
without pretending fixture results verify recorder support. Each stage should
be a separately reviewable change, with guides and progress updated alongside it.

## Backend design and API

Continue using Python for HTTP, normalized metadata, caching and viewer leases;
C++ owns SDK handles, callbacks and decoding. Extend the existing concrete
Python adapter and worker protocol only for operations required here. A second
SDK can later implement the same normalized operations; no new plugin framework
or general recorder abstraction is needed.

Introduce a timeline service and a playback-session manager alongside the live
manager, with focused routes in the existing server. Search operations must not
block live frame delivery: use bounded background work with private search
handles and serialize incompatible SDK operations as evidence requires. Reuse
the worker's recorder login. Do not run the diagnostic extraction subprocess
for each HTTP request.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/cameras/{id}/timeline?from={utc}&to={utc}` | Recording coverage and motion data for the chosen range. |
| POST | `/api/playback/sessions` | Start independent playback with `{camera_id, from, to}`. |
| GET | `/api/playback/sessions/{id}` | State, actual position, range, verified controls, lease and media descriptor. |
| PATCH | `/api/playback/sessions/{id}` | `{position: utc}`, `{state: paused\|playing}`, or `{}` for lease renewal. |
| DELETE | `/api/playback/sessions/{id}` | Release this viewer's playback; repeat is safe. |
| GET | `/media/playback/{id}` | Read the feed at the backend-returned URL. |

The proposed timeline response retains independent `recordings` and `motion`
datasets, each with `ready`, `pending`, `unsupported` or `error` state. Successful
empty results have `intervals: []`; unavailable results have `intervals: null`.
Include completeness/queried coverage, source provenance, granularity and stable
event IDs. A point event may have equal start/end. Never show an unsearched or
truncated portion as a confirmed gap. A partial response can contain useful
recordings with a motion error; use 202 while work is pending and poll the same
query. Include the configured timezone and query-generation timestamp.

Initially limit timeline requests to six hours, split native searches into
bounded smaller ranges, and cap outstanding jobs, cached entries and results.
Use half-open recording ranges `[from, to)` and an explicit point-event boundary
rule. Deduplicate concurrent identical queries. Cache recent results for 60
seconds; an explicit Refresh invalidates that entry while still sharing work.
Keep failures distinct from successful emptiness. Exact native deadlines/result
limits should follow stage A measurements. No video is fetched for a metadata
query, and a timeline range never requires pre-encoding hours of footage.

Generalize the existing time-playback pipeline to arbitrary discovered cameras
and requested times. Its current diagnostic is limited to the first configured
camera, one hour ago, and a 1–10-second extraction; it is not the history backend.
Use per-playback decoder contexts, the full configured verification code and
bounded queues. Start with the existing browser JPEG frame approach; measure
main-stream decode/encode costs before changing transport. Pace displayed frames
to the recorded clock and bound queued work, preserving normal playback speed.

After a seek, clear old buffers, increment a generation, and discard stale frames
and timestamps on both sides of the bridge. If reliable in-place seeking fails,
restart only that playback context at the selected time. Return `position: null`
until an absolute timestamp is established; approximate clock precision should
be explicit. Reuse frame/media helpers without inventing browser `video.currentTime`
for a JPEG stream.

Use the existing 90-second lease/30-second renewal pattern. Page navigation
releases this page's live lease before history playback; other pages retain
their sources. Leaving History stops its playback and feed. Page-close cleanup
is best effort, with expiry as the guarantee. Renew from the session controller,
not from status polling or media reads.

Initially admit one historical playback across the backend until coexistence
is verified; other attempts receive an explicit capacity response. The manager
must still treat positions as independent, and fixture tests should exercise
multiple sessions with a higher injected limit. Playback consumes the shared
resource budget in addition to live sources; a slot is not permission to evict
another viewer. Recorder clients outside Oogies remain outside our measured
counts. End-of-range and recording gaps need explicit states/actions.

## Frontend boundaries

- `app.js`: navigation and mount/unmount; replace the saved-clip availability
  check with history capabilities/loading states.
- `history/history-view.js`: camera and range selection, request cancellation,
  latest-response validation, refresh and view lifecycle.
- `history/timeline.js`: time axis, recording/event tracks, selection and keyboard
  interaction; emit selected timestamps without making SDK requests.
- `history/playback-controls.js`: session creation, controls, renewal and cleanup;
  coordinate returned media and actual playback position.
- `history/history.css`: timeline/view styling, including mobile layouts.
- Shared API, frame feed and media display: reuse request handling, rendering,
  transport cleanup and per-camera aspect. Extend frame metadata only as needed
  for playback generation and time.

Remove the production `recorded-clip.js` view after its replacement works; the
private diagnostic MP4 can remain a debugging artifact. Update display settings:
they currently apply the recorded view's aspect to hardcoded `camera-1`. History
must follow its actual selected camera. Register new modules in the server's
static-asset allowlist.

## Test changes

### Offline unit and API tests

- Time parsing/conversion, positive offsets in query strings, midnight boundaries,
  recorder clock offset, and daylight-saving ambiguity for future owners.
- Interval clipping, overlaps, point events, stable IDs, completeness, gaps and
  granularity. Merging recording coverage must not merge distinct motion events.
- Camera/range validation, pending and partial responses, empty versus unavailable
  data, bounded searches, handle cleanup, concurrent query deduplication and the
  exact 60-second cache boundary. History must work for a currently offline input.
- Pause/seek state transitions, stale generations, independent positions,
  capacity admission, repeated cleanup, expiry and navigation races. No extra SDK
  login or authentication retries. Search failures must not kill healthy feeds.

### Browser tests through the existing seam

Extend `tests/ui/fixture.py` at the injected worker boundary, using the production
HTTP routes and session services. Generate moving synthetic historical frames
with a controlled clock, several events, a recording gap, and at least two
cameras. Include a camera that is live-offline but has historical footage,
successful empty motion results, unsupported/error results, and delayed responses.

Replace the saved-MP4 test with History selection, moving frames, playhead,
pause/resume, selected-camera aspect and release of only this page's live lease.
Change the fresh-install test to expect History without a private recording.
Update the delayed-discovery/navigation test and settings selectors for the new
panel. Retain existing live grid, sharing, animation, scrolling and recovery cases.

Add tests for click/touch/keyboard selection, one seek on drag completion,
previous/next event, gaps versus unknown coverage, partial motion results,
midnight labels, stale camera/range responses, old frames after a seek, fixed
ranges during refresh, mobile controls, and changing camera aspect preferences.
Two-tab cases cover live plus history and independent historical positions,
closing/expiring one session while another remains active.

### Real SDK checks and CI

Offline native compilation checks structures and call pairings. Bounded manual
recorder checks verify returned SDK intervals, OSD time, decryption,
pause/resume/seek, cleanup and resource use with another live viewer. Start with
one known camera; expand to other channel types only after it succeeds. Fixture
tests cannot establish SDK compatibility or physical connection capacity.

Keep the existing GitHub Actions commands:

```sh
python3 -m unittest discover -s tests -v
python3 tools/run_ui_tests.py --build
```

CI uses synthetic data with networking disabled and requires no SDK download,
credentials or home footage. The plan checkpoint baseline was 26 unit and 18
browser cases; the first timeline slice passes 40 unit and 24 browser cases.
New counts/results are recorded after each implementation stage. Maintain the
human and agent setup guides when dependencies, configuration, capabilities or
startup behavior change. No additional host tools are planned.
