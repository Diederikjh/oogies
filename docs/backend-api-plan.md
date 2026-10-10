# Proposed backend API and frontend boundaries

Status: design proposal for discussion. None of the endpoints below have been
implemented unless explicitly listed in the current-prototype section. The
milestone sequence is in [implementation-plan.md](implementation-plan.md).

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
camera/session API. Initially live media uses MJPEG; historical viewing can reuse
decoded-frame streaming, while clip export uses H.264 MP4. Transport changes
do not automatically provide SDK pause/seek behavior; those controls remain
explicit backend operations.

## Camera inventory and backend status — milestone 1

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/api/cameras` | Configured cameras, names, online state and verified/unknown capabilities |
| GET | `/api/status` | Recorder/backend readiness, source counts, tested capacity and resource status |

Inventory and status reads use cached/current backend state, with bounded
device refreshes through the shared recorder connection. They do not open
preview streams. Distinguish an unknown capability from unsupported, and a
configured offline camera from an unused channel.

Example inventory shape (illustrative values):

```json
{
  "cameras": [
    {
      "id": "camera-1",
      "name": "Driveway",
      "online": true,
      "live_qualities": ["overview", "detail"],
      "capabilities": {
        "time_playback": "supported",
        "motion_timeline": "unknown"
      }
    }
  ]
}
```

`overview` normally maps to the substream; `detail` to the main stream. The
backend validates what is actually available. The illustrative detail quality
is not yet verified as a live stream on this recorder. Camera IDs remain stable
if display names change; the backend maps IDs to recorder channels.

Status should distinguish advertised limits, tested capacity and current usage:
for example, `device_stream_limit: null`, `tested_concurrent_streams: 1`,
`active_live_sources: 0`, `active_playbacks: 0`. Do not publish a guessed limit
as a hardware fact. Counts describe backend usage separately from known total
recorder connections, including other applications.

## Live viewer sessions — milestone 2

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/live/sessions` | Subscribe this browser view to selected cameras/qualities |
| GET | `/api/live/sessions/{id}` | Per-camera states, freshness, dimensions and media descriptors |
| PATCH | `/api/live/sessions/{id}` | Change requested cameras/qualities, or renew the viewer lease |
| DELETE | `/api/live/sessions/{id}` | Release this viewer's subscriptions |
| GET | `/media/live/{session_id}/{camera_id}` | Read an existing session's browser-ready stream |

On overview load, fetch inventory and create a viewer session for the configured
online cameras. Offline configured cameras remain labeled tiles. Stream starts
are staggered within the tested capacity; they do not produce a burst of new
SDK logins.

Example request:

```http
POST /api/live/sessions
Content-Type: application/json
Idempotency-Key: <one stable key for this browser view>
```

```json
{
  "cameras": [
    {"id": "camera-1", "quality": "overview"},
    {"id": "camera-2", "quality": "overview"}
  ]
}
```

Example `201 Created` response, with states allowed to advance asynchronously:

```json
{
  "id": "live-example",
  "state": "starting",
  "expires_at": "2026-10-10T13:31:30Z",
  "cameras": [
    {
      "id": "camera-1",
      "quality": "overview",
      "state": "starting",
      "last_frame_received_at": null,
      "media": {
        "transport": "mjpeg",
        "url": "/media/live/live-example/camera-1"
      },
      "error": null
    }
  ]
}
```

The abbreviated response demonstrates one camera; actual responses contain an
entry for every requested camera. Possible camera states include starting,
live, stale, offline, capacity_limited and error. A partially working grid keeps
working cameras active and reports failures on their own tiles. A request
rejected entirely for capacity returns 409.
`last_frame_received_at` measures backend receipt/freshness; it is not a claim
about the camera overlay's timestamp or historical playback position.

PATCH with a `cameras` array replaces this viewer's requested set. PATCH `{}`
only renews the lease. Proposed initial lease duration: 90 seconds, renewed by
an active page every 30 seconds. DELETE releases only this view. The last
subscriber leaving permits an idle source to stop; other viewers retain it.
Expiry provides cleanup when a tab disappears without a reliable close request.
Expired/suspended pages can acquire a new lease on return.

Refresh reuses or replaces the browser's lease without duplicating an existing
upstream source. A repeated creation with the same idempotency key and body
returns the same active session; a conflicting body returns 409. Media GETs
never create sessions or trigger fresh logins independently.

An enlarged view updates that camera's requested quality. If another browser
still needs its overview stream, the backend retains it. A second quality may
therefore consume an additional source; admission uses the capacity budget.

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

Proposed layout; no file moves have been made:

```text
web/
  index.html
  app.js                         navigation and view mounting
  style.css                      shared page styling
  shared/
    api.js                       request helpers, errors, timestamp serialization
    media-player.js              media descriptor to MJPEG/video rendering
    status.js                    shared status presentation
  live/
    overview.js                  live viewer lease and subscriptions
    camera-tile.js               one tile and enlarged-view interaction
    overview.css                 grid/tile styling
  history/
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
adapter and decoder/source management. The existing global camera state in the
prototype must become explicit per-camera/per-session contexts before a grid.

## Example browser flows

**Overview:** GET cameras -> POST live session -> attach returned media URLs ->
GET session status periodically + PATCH lease renewal -> PATCH selection when
enlarging a tile -> DELETE this session on leaving the view when possible.

**History:** release this page's live subscriptions -> GET timeline for camera/
range -> POST playback for a selected interval -> attach returned media ->
PATCH seek/pause/resume -> DELETE playback on leaving. A separate POST export
creates a downloadable clip without replacing another viewer's playback.

## Current prototype versus proposal

Existing endpoints are `/api/status`, `/api/start`, `/api/stop`, `/stream.mjpeg`
and `/recording.mp4`, for one shared camera and one saved clip. They do not yet
provide the inventory, leases, multiple cameras, timeline or playback-session
API above. Replace/transition the live controls in milestone 2, then introduce
timeline/playback/export operations in later milestones after SDK feasibility
checks. No implementation or recorder probes were performed for this proposal.
