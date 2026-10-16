# Backend API and frontend boundaries

Status: inventory, live-view leases and historical timeline queries are
implemented, including playback sessions. Export APIs below remain proposals. The exact current live
contract and verification are in [live-grid.md](live-grid.md); the milestone
sequence is in [implementation-plan.md](implementation-plan.md).
The detailed [History view plan](history-view-plan.md) records implementation
stages, SDK feasibility checks and changes to offline/browser testing.

## Design choices

The frontend uses camera IDs, viewing quality and timestamps. SDK handles,
device credentials, password rules and verification codes remain internal to
the backend. No HTTP login endpoint or frontend credential fields are planned.

Keep three types of state distinct:

1. A recorder connection owned by the backend and reused for SDK operations.
2. Live sources shared by `(camera_id, quality)` across viewers.
3. Viewer sessions referencing those sources, or owning independent historical
   playback positions.

Session IDs identify resources, not authenticated users. A live viewer session
does not necessarily create a new SDK login or source stream. Multiple historical
playbacks consume their own resources, even if they share the recorder login.

The API returns media descriptors rather than requiring frontend code to
construct SDK/RTSP URLs. This lets later transports change while retaining the
camera/session API. Live media uses one multiplexed JPEG feed per view; historical viewing could reuse
decoded-frame streaming, while clip export uses H.264 MP4. Transport changes
do not automatically provide SDK pause/seek behavior; those controls remain
explicit backend operations.

## Implemented camera inventory and backend status — milestone 1

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/api/cameras` | Configured cameras, names, online state and unknown historical capabilities |
| GET | `/api/status` | Cached recorder state, admitted source/view counts, tested capacity and saved-clip metadata |

The first inventory request opens the shared SDK connection and discovers inputs;
subsequent reads return the cache. Inventory opens no preview. Status does not
contact the recorder. Availability is refreshed through the shared connection
after 60 seconds; recovered cameras resume in existing views. Added/removed
inputs currently require service restart.

Example inventory entry:

```json
{
  "id": "camera-1",
  "channel": 1,
  "name": "Driveway",
  "online": true,
  "aspect_ratio": "16:9",
  "live_qualities": ["overview", "high"],
  "capabilities": {"time_playback":"unknown", "motion_timeline":"unknown"}
}
```

Camera IDs map to SDK channels and remain stable when display names change.
The current worker implements overview/substream and high/main-stream requests;
device compatibility is established by bounded checks, not by this list alone.
Historical capabilities remain
unknown per camera; one successful extraction is not blanket support.
Status reports `device_stream_limit: null`, configured `source_limit`, observed
`tested_concurrent_streams`, `sdk_login_calls`, `viewer_sessions` and
`active_live_sources` (admitted source slots, including a failed slot).
`active_media_feeds` counts open live and History media handlers, including
quiet paused feeds, so browser reconnection/cleanup can be checked separately
from native source occupancy. These
counts describe this backend, not other recorder clients or a hardware maximum.

## Implemented live viewer sessions — milestone 2

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/live/sessions` | Subscribe this browser view to selected camera substreams |
| GET | `/api/live/sessions/{id}` | Per-camera states, freshness, dimensions and media descriptor |
| PATCH | `/api/live/sessions/{id}` | Replace requested cameras, or `{}` to renew the lease |
| DELETE | `/api/live/sessions/{id}` | Release only this viewer's subscriptions; repeat returns 204 |
| GET | `/media/live/{id}/frames` | One multiplexed feed of JPEGs for this view |

On overview load, fetch inventory and create a view containing all discovered
inputs, including offline tiles. Previews start sequentially through the same
native worker and shared SDK login. An individual failure leaves other tiles active.

```http
POST /api/live/sessions
Content-Type: application/json
Idempotency-Key: <per-document random key>
```

```json
{"cameras":[{"id":"camera-1","quality":"overview"}]}
```

Example 201 response (illustrative ID and expiry):

```json
{
  "id":"live-example",
  "expires_at":"2026-10-10T13:31:30+00:00",
  "lease_seconds":90,
  "cameras":[{
    "id":"camera-1", "quality":"overview", "state":"starting",
    "frames":0, "width":0, "height":0,
    "last_frame_received_at":null, "frame_age_seconds":null, "error":null
  }],
  "media":{"transport":"jpeg-frames-v1", "url":"/media/live/live-example/frames"}
}
```

States include starting, live, stale, offline, capacity_limited and error. Source
budget overflow still creates a view and labels excess cameras; the viewer limit
returns 409. Last-frame timestamps measure backend receipt, not camera OSD time.
PATCH selection replaces the view's set. PATCH `{}` renews a configurable lease
(default 90 seconds, renewed every 30). DELETE/expiry releases only this view;
the last subscriber leaving stops that preview. The recorder login persists
until service shutdown. Media GETs never create views or authenticate.

The same idempotency key and selection reuses an active view; conflicting selection
returns 409. A refreshed or copied tab creates its own document lease and shares
existing sources. Eight viewer leases and one feed per lease are allowed.

Expansion now requests high quality; collapse requests overview. The backend
accepts `quality: "high"` in POST/PATCH selections. Sources are shared per
camera and quality; a high request retains an overview fallback and uses an
extra slot under both the high-quality and total source budgets.

Session responses add `selection_revision`, incremented for each explicit
selection PATCH (including an explicit retry), but unchanged by `{}` renewal.
Camera entries include `requested_quality`, effective `quality`, `upgrade_state`
and nullable `quality_reason: {code, message}`. Upgrade states are `overview`,
`pending`, `active`, `capacity_limited`, `unsupported`, `offline` or `error`.
Effective quality becomes high only after a fresh decoded main-stream frame.
Valid but unavailable upgrades return a successful session with overview fallback;
unknown qualities return 422 before changing selection. Selection PATCH replaces
the full selection, so retain other cameras in the request.

Denied upgrades are not queued. After failure/refusal, an explicit selection
PATCH requesting high retries admission; polling and renewal do not. Existing
admissions retain their slots and upgrades do not evict overview/history/export
work. A stalled high stream falls back rather than repeatedly opening previews.
`max_high_quality_sources` defaults to one; zero disables admission. The total
`max_live_sources` budget also includes history/export reservations and live stops
awaiting native acknowledgement.

PATCH optionally accepts `retry_high: ["camera-1"]` alongside the complete
`cameras` selection. Each entry must be distinct and selected at high quality.
When supplied, failed/refused high requests already in the selection are retried
only for those IDs; an empty list preserves all such outcomes. New high selections
still request admission. Omitting the field keeps the original retry behavior.
Renewal remains `{}`; `retry_high` without `cameras` is rejected.
The frontend uses this option so a failure between polls cannot be retried by
an unrelated camera change. It also remembers refused preferences locally and
requests overview for them in later selections until the user explicitly retries.

`/api/status` adds `high_quality_limit`, requested/starting/active counts,
`sources_by_quality` (including stopping sources), `reserved_sources`,
`occupied_source_slots`, refusal/failure totals and the last 20 upgrade events.
`live_source_metrics` reports per-source dimensions, freshness, first-frame
latency and sampled decoded/delivered FPS, JPEG bytes/sec and incoming SDK bytes/sec.
Requested counts count viewer requests, including refused ones; active counts
count distinct sources. Metrics are null until measured. Delivered FPS/bytes
describe publication into the shared Python cache, not each viewer's bandwidth.
The binary JPEG protocol is documented in [live-grid.md](live-grid.md).

## Recording and motion timeline data — milestones 3-4

Implemented in the [first History slice](history-timeline.md), now connected to
[playback](history-playback.md). Queries return bounded results from V30 recording and base motion
searches through the shared login; no API fallback or authentication retry occurs.

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/api/cameras/{id}/timeline?from={utc}&to={utc}` | Recording availability and motion intervals over a bounded time range |
| GET | `/api/cameras/{id}/timeline?local_time={recorder-wall-time}&hours={hours}` | Resolve a local date/time and return its surrounding 1, 3 or 6-hour timeline plus `selected_time` |

Both timestamps must carry an explicit timezone; responses normalize them to
UTC. Store source provenance and interval granularity in the backend. Display
times in the configured recorder timezone (`Africa/Johannesburg` for the current
installation), returned with timeline metadata.
The local navigation variant accepts `YYYY-MM-DDTHH:mm[:ss]` without an offset,
interpreted using the backend recorder timezone. It rejects invalid, future,
repeated or nonexistent local times before recorder work. Older windows are
centred on that timestamp; near-now windows end at server time. Responses
include UTC `selected_time`, `from`/`to` and the recorder timezone, with the same
202/200 metadata states and cache as ordinary queries. The browser polls the
resolved UTC range after its first response. Do not combine both query variants
or repeat parameters. Both forms optionally support `refresh=1`.

Example partial response: recording information is available, but motion is not:

```json
{
  "camera_id": "camera-1",
  "from": "2026-10-10T11:00:00Z",
  "to": "2026-10-10T12:00:00Z",
  "recordings": {
    "state": "ready",
    "intervals": [
      {"start": "2026-10-10T11:00:00Z", "end": "2026-10-10T12:00:00Z"}
    ],
    "complete": true,
    "error": null
  },
  "motion": {
    "state": "unsupported",
    "complete": false,
    "intervals": null,
    "error": {"code": "motion_unavailable", "message": "Motion intervals are not available through the supported query."}
  }
}
```

The example describes the response contract, not an observed limitation of this
recorder. Each dataset has its own ready/pending/unsupported/error state. A
successful empty query returns `ready` and `intervals: []`. Failure or unknown
data returns `intervals: null`. This preserves the distinction between no motion
and no usable motion query. Recording-search failure need not prevent direct
time playback, which already works on this recorder.

Motion intervals include `id`, `start`, `end`, original `source_start`/`source_end`,
SDK provenance, `type: "motion"`, and `granularity: "sdk_interval"`. Recording
coverage uses `granularity: "recording"`. Do not label entire motion-triggered recordings
as precise event durations unless the data supports that interpretation.
Cache bounded camera/range queries and avoid querying the recorder while the
user is dragging the timeline. Pending responses can be polled until ready;
queries that need long processing return 202 with the same response shape.
Initially bound requests to six hours and cache recent results for 60 seconds,
sharing concurrent identical work. Include query time, completeness and queried
coverage; truncated or unsearched ranges are unknown rather than confirmed gaps.
Point events may have equal start/end. The detailed History plan describes the
three-hour default UI. Native enumerations are bounded to ten seconds and 256
results each; the worker has a 25-second response deadline. There are at most
four queued/running metadata jobs and 32 cached ranges. `refresh=1` invalidates a
completed cache entry; omit that flag on subsequent polls. Responses include
`timezone`, `generated_at` and nullable `recorder_now`; ambiguous wall-clock
ranges are rejected for the current SDK's timezone-free search API.

## Independent historical playback — milestone 4

Implemented for one admitted historical viewer session. The native worker
reuses its login, with an independent playback handle/decoder and position.

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/playback/sessions` | Start a camera/time playback for this viewer |
| GET | `/api/playback/sessions/{id}` | State, actual playback position, supported controls and media descriptor |
| PATCH | `/api/playback/sessions/{id}` | Pause/resume, seek, change supported speed, or renew the lease |
| DELETE | `/api/playback/sessions/{id}` | Stop and release this playback |
| GET | `/media/playback/{session_id}` | Read browser-ready playback media |

Example creation:

```json
{
  "camera_id": "camera-1",
  "from": "2026-10-10T11:51:50Z",
  "to": "2026-10-10T11:52:50Z",
  "position": "2026-10-10T11:52:00Z"
}
```

Return 201 with a playback ID, starting state, range, media descriptor, lease
expiry and verified `supported_controls`. Select an available recorded stream;
do not assume the live substream was also recorded.
`position` is optional and defaults to `from`. The UI supplies its entire visible
range and the clicked timestamp, so later seeks can go earlier or later within it.
Creation optionally accepts `rate` (default 1). Responses include `rate`,
`requested_rate`, `supported_rates: [0.5, 1, 2, 4]` and nullable `rate_error`.

Example PATCH bodies:

```json
{"state": "paused"}
```

```json
{"state": "playing"}
```

```json
{"position": "2026-10-10T11:52:10Z"}
```

```json
{"rate": 2}
```

To change the time window without losing this viewer's reserved slot, PATCH the
same session with `from`, `to` and `position` together:

```json
{"from":"2026-10-09T10:00:00Z", "to":"2026-10-09T13:00:00Z", "position":"2026-10-09T11:15:30Z", "state":"playing"}
```

All range/date checks happen before mutation. The range remains at most six
hours, and position must fall inside it. Accepted jumps increment generation,
clear old decoder data, keep the lease ID/source reservation and preserve rate
unless explicitly supplied. Other viewers are unchanged. Go to time uses
`state: "playing"` to start footage even if the previous picture was paused.

Unspecified fields remain unchanged; PATCH `{}` only renews the lease. Validate
seek targets against the session range, clear old decoder buffers during seek,
and report `seeking` until new frames arrive. Rate requests are limited to
0.5, 1, 2 and 4, with booleans/strings and other numbers rejected before SDK work.
Playing speed changes affect only that decoder, retain its generation/position,
and are confirmed asynchronously; pending `requested_rate` may differ from
`rate`. A rejected rate preserves video and reports its actual speed plus
`rate_error`. While paused the chosen rate applies on resume/seek. Seek and
resume preserve it. Use accurate decoded/playback timestamps
for `position`; return null while unavailable rather than inventing precise
positions from HTTP arrival times.
Include playback generation and timestamp precision where needed to discard
old frames after seeks and avoid implying greater accuracy than the SDK provides.
The current profile stops that viewer's handle/decoder on pause, retaining its
last picture/time. Resume reopens at the confirmed time and increments generation;
seek likewise replaces only that context. A paused seek shows its first new frame
then holds it. Position uses PlayCtrl's recorded system time at second precision.

Playback state may be starting, playing, pausing, paused, seeking, ended or error. An
ended session cannot silently switch to live video. Playback sessions do not
share mutable position/controls between viewers. Admission counts playback
resources alongside the shared live sources and retains room for other clients.
Admit one historical viewer, including a paused lease, pending wider capacity
measurement. Reuse
the live lease pattern (90 seconds, renewed every 30) and preserve other viewers'
sources when switching this page between Live and History.

## Clip export — milestone 4

Now implemented; see [the implementation and evidence](clip-exports.md). The approved
[clip export and fine-seeking plan](clip-export-plan.md) specifies selection,
job states, SDK capture verification, initial limits and test coverage.
That plan also adds Download current frame to History as a direct browser PNG
download from the displayed frame, preserving the selected aspect. It needs no
backend endpoint or export job. Only multi-frame video exports use these routes.

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/exports` | Request a short clip using `camera_id`, `from`, `to`, `aspect_ratio`; optional Idempotency-Key |
| GET | `/api/exports` | Bounded shared queue/recent jobs and configured limits |
| GET | `/api/exports/{id}` | queued/running/ready/failed/cancelled/expired status and download URL when ready |
| DELETE | `/api/exports/{id}` | Cancel pending work or remove the finished artifact |
| GET | `/media/exports/{id}.mp4` | Download the completed private clip; support byte ranges |

Export follows the first interactive History flow. Creation returns 202 because
SDK extraction/encoding takes time. Validate a
configurable duration limit, serialize or limit export jobs within the resource
budget, and expire artifacts according to a documented retention policy. A
ready result points only to its clip, never a workspace path or directory.

## Shared response conventions

- JSON for state/control; binary media through `/media/...`. Return media URLs
  from the backend. The frontend does not recreate URLs from NVR addresses.
- Explicit timezone on input timestamps, UTC ISO8601 on output, South Africa
  display time in the UI for the current installation; other owners use their
  configured recorder timezone. Verify source clock conversion before interpreting
  timeline intervals.
- 400 for malformed input, 404 for unknown resources, 409 for conflicting state
  or capacity, 422 for invalid ranges/unsupported requested controls, 502 for a
  failed recorder response and 503 for recorder/backend unavailability.
- Structured errors: `{"error":{"code":"stream_capacity_exceeded",
  "message":"No stream slot is currently available.","retryable":false}}`.
  Keep raw SDK logs private. Timeline dataset failures can coexist with a 200
  response containing useful partial data.
- DELETE returns 204 and safely tolerates a repeat after cleanup. Leases govern
  abandoned sessions; expose no global Stop action that disconnects other views.
- Start/seek/export actions are explicit requests. Status polling and media
  delivery do not produce repeated SDK logins or authentication retries.
- Browser media recovery reuses the existing lease/media URL, with at most three
  consecutive retries (1/2/4-second backoff). A fresh packet does not reset this
  budget; a connection must remain stable for 30 seconds. Pause/navigation aborts
  pending recovery. Ordinary 4xx responses stop recovery; a temporary 409 can be
  retried while the previous feed closes. Exhaustion releases only that view's
  session and requires an explicit user action to start again. Live status/renewal
  failures still stop the view. Backend source availability and browser delivery
  freshness are separate; neither changes the requested quality automatically.

## Frontend files along functional boundaries

Live, history/timeline, playback controls and export modules follow these boundaries:

```text
web/
  index.html
  app.js                         navigation and view mounting
  style.css                      shared page styling
  shared/
    api.js                       request helpers, errors, timestamp serialization
    media-player.js              browser aspect/fit scaling
    frame-feed.js                multiplexed JPEG transport
    status.js                    shared status presentation
  live/
    overview.js                  live viewer lease and subscriptions
    camera-tile.js               one tile and enlarged-view interaction
                                 grid/tile styling currently in style.css
  history/
    history-view.js              camera/date/range selection and query lifecycle
    timeline.js                  recording/motion bands and timeline interaction
    playback-controls.js         playback session, seek, pause and speed
    clip-selection.js            browser marks, immutable export requests
    frame-download.js            frozen displayed-frame PNG conversion
    exports.js                   shared job polling and download/cancel/delete
    history.css                  historical-view styling
```

Use browser-native ES modules initially. The API helper owns fetch/error
handling; view modules own their state and cleanup. Timeline code emits a chosen
timestamp; playback controls perform the session update. Media rendering handles
transport selection but does not contain SDK or timeline-search logic.

Backend boundaries should likewise separate camera inventory/status, live-session
routes, history/timeline routes, playback routes and export jobs from the recorder
adapter and decoder/source management. The live grid now has independent
per-camera decoder contexts and shared sources referenced by per-view leases.

## Example browser flows

**Overview:** GET cameras -> POST live session -> attach returned media URLs ->
GET session status periodically + PATCH lease renewal -> DELETE this session on
leaving the view when possible. Expansion currently changes layout only.

**History:** release this page's live subscriptions -> GET timeline for camera/
range -> POST playback for a selected interval -> attach returned media ->
PATCH seek/pause/resume -> DELETE playback on leaving. A separate POST export
creates a downloadable clip without replacing another viewer's playback.

## Current implementation versus proposal

Inventory, live leases, their feed, timeline queries and playback sessions above are implemented.
`/recording.mp4` retains access to an existing private diagnostic clip with
byte-range support but is no longer the History UI. The prior `/api/start`,
`/api/stop` and `/stream.mjpeg` routes are no longer exposed by the default service.
Export jobs remain proposals. Selecting a History timestamp now starts/seeks
an independent SDK historical session. Shared response conventions
above describe the eventual API; current live errors use a generic structured
`error.code` plus safe message and do not expose raw SDK logs.
