# Interactive History playback

Implemented after timeline checkpoint `bb40e0f`, 11 October 2026.

Click a recording track, motion marker/event, or commit a time-slider selection
to show moving footage in the History player. A recording-band pointer click
uses its actual position on the time axis; a motion click starts at the returned
interval's beginning. Keyboard time changes also seek. Dragging previews time
locally and sends one seek when committed. The recorded clock moves the playhead
as frames arrive, without overriding an in-progress drag.

Pause retains the picture; Resume continues near its confirmed recorded time.
Selecting a new time while paused displays that time's first frame and remains
paused. Previous/next motion selects and plays the corresponding footage.
Stop playback and leaving History release only this viewer's playback. Another
page's live or historical view keeps its own sources and position.

The player uses the selected camera's remembered Settings aspect ratio. Camera
settings remain available even when History is opened before live discovery
finishes. Original dimensions and display proportions are independent: verified
recorded frames are 960 × 1088 and are displayed at the owner's chosen 16:9.
The browser scales the JPEG; there is no resize/transcode per aspect preference.

## API and lifetime

The implemented routes are:

| Method | Path | Meaning |
| --- | --- | --- |
| POST | `/api/playback/sessions` | Create an independent camera/range playback. |
| GET | `/api/playback/sessions/{id}` | State, confirmed position, generation, dimensions, lease and media. |
| PATCH | `/api/playback/sessions/{id}` | Seek, pause/resume, or renew with `{}`. |
| DELETE | `/api/playback/sessions/{id}` | Release this viewer; repeated delete is safe. |
| GET | `/media/playback/{id}` | JPEG frame feed at the returned URL. |

Creation accepts `camera_id`, timezone-aware `from`/`to` (maximum six hours), and
an optional `position` inside that range. Position defaults to `from`. The UI
sends the whole visible range and the chosen timestamp. Responses normalize to
UTC and report nullable `position`, `position_precision: "second"`, `generation`
and verified controls. Positions come from PlayCtrl's recorded system time,
converted using the owner's recorder timezone, rather than HTTP arrival time.

PATCH accepts `{position: utc}`, `{state: "paused"}`, `{state: "playing"}` or
`{}`. Invalid ranges/controls are rejected. Generation changes on seeking and
resume; old metadata, packets and pending image loads are discarded. The player
serializes requests and drops superseded selections. A slow creation finishing
after navigation is released, with lease expiry covering abandoned pages.

Leases use the existing configured duration (default 90 seconds) and renewal
every third of that duration. GET/media reads do not renew them. Source capacity
is shared with live previews. Current production admits **one historical viewer
session**, including a paused session, and reserves one configured source slot
for it. This is a conservative application limit, not a measured recorder
maximum. A full budget returns 409 and does not evict another view. Stop releases
the reservation so live recovery can use it again.

## SDK implementation

`PlaybackSessions` coordinates normalized state and leases in Python.
`GridWorker` owns the small `start_playback`, `control_playback`, `stop_playback`
boundary used by fixtures. The selected adapter still builds/launches the
persistent C++ worker and applies its credential policy. Native time playback
and independent file-mode PlayCtrl decoder contexts live in `history_playback.h`.
They reuse the existing recorder login and the full backend verification code.

The current SDK profile opens main-stream time playback with
`NET_DVR_PlayBackByTime_V40`, registers its data callback before PLAYSTART, and
feeds bounded compressed queues to file-mode decoding. When the queue fills,
the SDK callback waits for capacity before copying the next chunk. The main
thread retries decoder input without waiting, so live publication and controls
continue. Refused chunks remain counted and ordered; closing wakes a waiting
callback before stopping the SDK handle. A playback heartbeat runs every two
seconds, as recommended by the
[SDK control documentation](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackControl_V40.html).
The latest frame
is converted to JPEG at up to ten publications per second; there is no
pre-encoding or downloading the full timeline. Compressed queues cap at 16 MiB,
decoder input at 4 MiB and accepted decoded frames at 4 MiB. Existing Docker CPU,
memory and PID limits remain in force.

The initial combined SDK/decoder pause path failed with code 8; the aggregated
error did not establish which layer rejected it. The simpler verified approach
closes that playback handle/decoder on pause, retaining the last JPEG/time in
Python and the browser. Resume reopens time playback at that confirmed time.
Seek likewise replaces only that playback context and decoder, clearing old
buffers. A paused seek pauses again after publishing its first new frame.
Second-resolution resume can repeat a small amount of footage; it is not frame
accurate. No login retries, alternate credentials or automatic API fallback
were introduced.

EOF is reported as ended; it does not switch to live. Missing footage or decoder
failure is shown explicitly. A fifteen-second frame deadline bounds starts and
stalls. Audio, speed controls, clip export, synchronized multi-camera history
and H.264 browser transport remain future work.

## Verification

The real API check read moving, distinct JPEGs. The first frame's recorded clock
exactly matched the chosen timestamp. Pause held the frame/time stable, resume
worked, and playing/paused seeks reached their target timestamps. All operations
used one SDK login; the test viewer was deleted. A separate Docker Chromium
check clicked the actual History UI and verified moving footage, paused picture,
960 × 1088 source dimensions, approximately 16:9 display and zero playback
sessions after Stop.

The same playback/control check ran while a camera-1 live preview was active:
live frames advanced from 2 to 31, the preview remained live, and SDK login count
remained one. This verifies one preview plus playback; it does not establish
full-grid coexistence or a recorder connection maximum.

Private evidence is in `.local/browser-viewer/playback-check-*/report.json` and
`.local/browser-viewer/history-ui-check/`. Captures and screenshots remain ignored.
The live coexistence report is `.local/browser-viewer/playback-live-coexistence.json`.
The first check can be repeated deliberately with
`python3 tools/check_history_playback.py`; it opens one bounded playback session,
uses the existing credentials indirectly through the API, and cleans up its own
lease. It is not part of CI.

The initial checks ran only a few seconds between controls. A subsequent owner
test exposed error 43: our callback queue accepted compressed data faster than
real-time decoding and treated its 16 MiB limit as a fatal error. Retrying decoder
input alone did not slow the producer. `playback_buffer.h` now applies bounded
flow control instead of enlarging the buffer or dropping video data. The check
defaults to sixty uninterrupted seconds in a three-hour range, renews its lease,
and verifies normal recorded-clock advancement before pause/resume/seek checks.
Use `--continuous-seconds 75 --with-live` to include a concurrent live preview.
That check passed: 606 received frames over 75 uninterrupted seconds, with the
recorded clock advancing exactly 75 seconds and no frame-feed errors. The native
queue reached its 16 MiB cap and repeatedly waited instead of failing. The live
preview advanced from 7 to 608 frames and stayed live; all controls still passed
through one SDK login. Sampled service memory was about 107 MiB. This verifies
one preview alongside one historical playback, rather than full-grid capacity.
The separate real Chromium check then passed thirty uninterrupted seconds,
Pause and Stop using the final running bridge. Aggregated private queue evidence
is in `.local/browser-viewer/playback-flow-control.json`.

Offline tests cover independent positions, generation cleanup, confirmed-time
resume, repeated pause/delete, lease expiry, shared capacity/live recovery, frame
metadata, moving browser pixels, pause/resume, paused seeking, one seek per drag,
selected-camera aspect, live coexistence and navigation/discovery races.
GitHub Actions continues to use synthetic footage without SDK/credentials.
The Docker suite also compiles the production buffer directly and tests decoder
refusal, fast-producer/slow-consumer ordering and capacity, and cancellation of a
blocked callback, without linking or loading the SDK.
