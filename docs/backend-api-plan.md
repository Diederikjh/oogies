# Backend API and frontend boundaries

Status: inventory and live-view leases are implemented. Historical timeline,
playback-session and export APIs below remain proposals. The exact current live
contract and verification are in [live-grid.md](live-grid.md); the milestone
sequence is in [implementation-plan.md](implementation-plan.md).

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
contact the recorder. Added/reconnected inputs currently require service restart.

Example inventory entry:

```json
{
  "id": "camera-1",
  "channel": 1,
  "name": "Driveway",
  "online": true,
  "aspect_ratio": "16:9",
  "live_qualities": ["overview"],
  "capabilities": {"time_playback":"unknown", "motion_timeline":"unknown"}
}
```

Camera IDs map to SDK channels and remain stable when display names change.
Only overview/substream quality is supported. Historical capabilities remain
unknown per camera; one successful extraction is not blanket support.
Status reports `device_stream_limit: null`, configured `source_limit`, observed
`tested_concurrent_streams`, `sdk_login_calls`, `viewer_sessions` and
`active_live_sources` (admitted source slots, including a failed slot). These
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

Expand currently changes layout only and keeps overview quality. Main-stream
quality switching remains future work and would require separate capacity admission.
The binary JPEG protocol is documented in [live-grid.md](live-grid.md).

## Recording and motion timeline data — milestones 3–4

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/api/cameras/{id}/timeline?from={utc}&to={utc}` | Recording availability and motion intervals over a bounded time range |

Both timestamps must carry an explicit timezone; responses normalize them to
UTC. Store source provenance and interval granularity in the backend. Display
times in `Africa/Johannesburg` in the frontend.

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
    "error": null
  },
  "motion": {
    "state": "unsupported",
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

Motion intervals include `id`, `start`, `end`, `type: "motion"`, and a granularity
such as `event` or `recording`. Do not label entire motion-triggered recordings
as precise event durations unless the data supports that interpretation.
Cache bounded camera/range queries and avoid querying the recorder while the
user is dragging the timeline. Pending responses can be polled until ready;
queries that need long processing return 202 with the same response shape.

## Independent historical playback — milestone 4

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
  "to": "2026-10-10T11:52:50Z"
}
```

Return 201 with a playback ID, starting state, range, media descriptor, lease
expiry and verified `supported_controls`. Select an available recorded stream;
do not assume the live substream was also recorded.

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

Unspecified fields remain unchanged; PATCH `{}` only renews the lease. Validate
seek targets against the session range, clear old decoder buffers during seek,
and report `seeking` until new frames arrive. Return supported controls only
after their behavior has been verified. Use accurate decoded/playback timestamps
for `position`; return null while unavailable rather than inventing precise
positions from HTTP arrival times.

Playback state may be starting, playing, paused, seeking, ended or error. An
ended session cannot silently switch to live video. Playback sessions do not
share mutable position/controls between viewers. Admission counts playback
resources alongside the shared live sources and retains room for other clients.

## Clip export — milestone 4

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/exports` | Request a short clip using `camera_id`, `from`, `to` |
| GET | `/api/exports/{id}` | queued/processing/ready/error status and download URL when ready |
| GET | `/media/exports/{id}.mp4` | Download the completed private clip; support byte ranges |

Creation returns 202 because SDK extraction/encoding takes time. Validate a
configurable duration limit, serialize or limit export jobs within the resource
budget, and expire artifacts according to a documented retention policy. A
ready result points only to its clip, never a workspace path or directory.

## Shared response conventions

- JSON for state/control; binary media through `/media/...`. Return media URLs
  from the backend. The frontend does not recreate URLs from NVR addresses.
- Explicit timezone on input timestamps, UTC ISO8601 on output, South Africa
  display time in the UI. Verify source clock conversion before interpreting
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

## Frontend files along functional boundaries

The current live modules follow these boundaries; history/timeline/control/export
modules in this layout remain planned:

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
    recorded-clip.js              implemented saved MP4 playback
    history-view.js              camera/date/range selection and query lifecycle
    timeline.js                  recording/motion bands and timeline interaction
    playback-controls.js         playback session, seek, pause and speed
    exports.js                   clip-export requests and job state
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

Inventory, live leases and their feed above are implemented. `/recording.mp4`
serves an existing private clip with byte-range support. The prior `/api/start`,
`/api/stop` and `/stream.mjpeg` routes are no longer exposed by the default service.
Timeline queries, independent SDK historical sessions and export jobs remain
proposals pending motion/recording feasibility work. Shared response conventions
above describe the eventual API; current live errors use a generic structured
`error.code` plus safe message and do not expose raw SDK logs.
