# Clip selection, frame downloads, export queue and fine seeking

Approved and committed as `06c077d`, 11 October 2026, before implementation.
Date/time navigation was committed as `bd0b069`. The design below records the
agreed scope; [clip export implementation and evidence](clip-exports.md) describes
the delivered behavior and real-recorder checks. Planning itself contacted no
recorder and changed no application code.

## User flow

1. Open a camera's History and play or pause at the desired beginning.
2. Press **Mark start** to remember the currently displayed recorded time.
3. Play, seek or use **−30s, −10s, +10s, +30s** to find the end. Press **Mark end**.
4. Review camera, both timestamps, duration and picture proportions, then press
   **Queue export**. The recording continues independently.
5. A separate **Exports** tab shows queued/running/ready/failed jobs. Once ready, press
   **Download MP4**. Pending jobs can be cancelled; finished clips can be deleted.

Both marks stay in browser memory until submission. Marking and clearing issue
no backend requests. Use the last successfully painted frame's recorded timestamp
and camera/generation, independently of the slider's drag preview or a later
status poll. Disable marking when no current recorded frame/time is available
or while a seek is pending. Marking while paused is supported.

Show start/end lines and the selected interval on the timeline, plus full dates
and the recorder timezone in the review row. Users can replace either mark or
clear both. The interval may span different visible windows on the same camera.
Changing cameras clears the draft. Navigating between Live and History preserves
the in-memory draft for that camera; reloading the page clears it. Submitted jobs
are independent of the draft and playback session. Do not automatically clear a
draft when a submission fails.

Make the marks visible as labelled **Start** and **End** flags, distinct from the
moving playback cursor, with a shaded band between them. With only a start mark,
show its flag and “Choose an end”. Flags stay fixed as video plays or seeks.
Clip the overlay to the visible window; off-screen endpoints remain visible in
the timestamp review row. This is planned UI, not a control already on the page.

Put **Exports** beside Live overview and History in the navigation. Each list row
shows camera, start/end, duration, status/progress or waiting reason, and the
appropriate Cancel, Download MP4 or Delete action. Ready rows show file size and
expiry. Enqueueing stays in History with confirmation and a “View exports” link;
it does not automatically switch away from playing video. Explicitly opening
Exports releases this page's viewing lease as other mode switches do; submitted
jobs and other viewers continue. The list covers all retained shared jobs, so
refreshing or selecting another camera does not hide an earlier download.

Use second-resolution timestamps, matching the current player. Export ranges are
`[from, to)`: a selection from 10:00:00 to 10:00:30 is thirty seconds. End must be
after start. First-version exports contain video only, at normal recorded speed,
regardless of the viewer's selected playback speed.

## Direct single-frame download

Add **Download current frame** on History beside the playback controls. This is
an immediate browser download, not an export job. The decoded JPEG is already in
the browser; no backend endpoint, SDK call, recorder slot, job record, persistent
server file or expiry policy is needed. It works while playing or paused without
altering playback, speed, clip marks or queued jobs. It does not appear in Exports.

Keep an immutable snapshot of the last successfully painted frame and its camera,
generation, recorded timestamp, sequence and native dimensions. Update it only
after image decoding succeeds; the pending image URL is not the displayed frame.
On click, freeze that snapshot and the current aspect preference before any
asynchronous conversion. A frame arriving during conversion must not change the
saved picture or filename. Clear the available snapshot on stop, camera change
or seek, and disable the button until a valid current-generation image is shown.
Require its recorded timestamp for the filename. Pausing retains the snapshot.

Proposed output is **PNG**, with the camera's selected display proportions and
its in-video timestamp/name overlays. CSS-only aspect correction is not present
in the original JPEG file, so draw the frozen image into a canvas of the selected
ratio once on click. Use dimensions derived from the source raster, preserving
detail rather than exporting the small viewport; constrain canvas size to keep
the operation bounded. `original` keeps the source proportions. PNG avoids a
second lossy JPEG encode, although resizing does not add source detail. The
[browser canvas export API](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob)
provides the image Blob for a normal download link. No resizing runs continuously.
The same source JPEG could be downloaded unchanged, but that would preserve its
native raster proportions instead of the corrected picture the owner sees.

Use a safe filename such as `oogies-Driveway_20261011T080000Z_f123.png`, combining
the sanitized camera name, recorded UTC time and frame sequence. The owner
requested names instead of IDs after initial implementation. Replace invalid
filename characters, bound length and use `Camera` when sanitization is empty.
Do not use machine paths,
recorder addresses or wall-clock arrival time. Include the full image, with no
player controls, letterboxing or timeline markup. Keep conversion errors local
and explicit; briefly disable repeated clicks while converting, then release
temporary bitmaps, canvas memory and download Blob URLs after their use.

Put the small conversion/download helper in `history/frame-download.js`.
`PlaybackControls` supplies the displayed-frame snapshot; this shares the same
clock source used for clip marks and fine seeking. No SDK abstraction is added.

Verify the actual downloaded PNG in offline browser tests: image identity while
the feed advances, paused capture, camera/time/sequence filename, 16:9/4:3/original
proportions, source-derived dimensions, unchanged player/clip/job state, disabled
controls before first frame and during seeks, stale-generation rejection,
conversion failure and cleanup. Assert that clicking makes no SDK/export/API
request. The synthetic frame seam is sufficient; no new recorder probe is needed.

## Fine seeking

Place the four seek buttons beside Pause/Resume and speed controls. Anchor each
jump to the displayed recorded clock, preserving paused/playing state and rate.
Use the existing playback PATCH and generation handling; this needs no new SDK
operation or login. Disable controls during a pending seek or without a usable
clock. One click sends one seek; superseded requests must not repaint stale frames.

For the first version, clamp jumps to the active playback range's first/last
second and disable directions already at an edge. Earlier/Later and Go to time
still move the window. Automatically extending the window on a small-step seek
can be a subsequent refinement. Stepping does not change saved clip marks.
Use explicit accessible labels such as “Back 30 seconds”; retain mobile fit.

## Backend contract

Keep Python responsible for validation, job state, scheduling and files. Extend
the existing worker seam with concrete export operations and normalized progress;
C++ owns SDK capture/decoder handles. There is no second recorder framework.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/exports` | Queue an immutable camera/range export; return 202. |
| GET | `/api/exports` | Bounded shared queue/recent-job list and configured limits. |
| GET | `/api/exports/{id}` | Current job state, requested/actual bounds and download descriptor. |
| DELETE | `/api/exports/{id}` | Cancel queued/running work or remove its finished artifact; repeat safely. |
| GET | `/media/exports/{id}.mp4` | Download a ready clip with byte-range support. |

Example creation body:

```json
{
  "camera_id": "camera-3",
  "from": "2026-10-11T08:00:00Z",
  "to": "2026-10-11T08:00:30Z",
  "aspect_ratio": "16:9"
}
```

The browser supplies its camera display preference (`16:9`, `4:3`, or `original`)
and freezes it with the job. Use a client idempotency key so a lost response or
double click does not enqueue the same submission twice; conflicting reuse is
409. A deliberate later submission with a new key is a new job.

Validate camera, explicit timezone-aware timestamps, supported recorder times,
positive duration, future dates, aspect enum and queue/storage limits before SDK
work. Offline live status does not exclude historical exports. Use existing UTC
normalization and DST restrictions. Reject unknown fields and arbitrary output
paths. Queue-full responses are 409; invalid ranges are 422. Return safe messages
with raw logs kept private.

States: `queued`, `running`, `ready`, `failed`, `cancelled`, `expired`. A queued
job can explain “Waiting for stream capacity” or “Waiting for storage”. Running
jobs may report capture/finalization progress based on recorded duration; use an
indeterminate indicator when progress is unknown. Report requested and measured
actual coverage and second precision, rather than promising frame-accurate cuts.
Only ready jobs expose media URLs. Missing/incomplete footage fails explicitly;
do not silently create a shorter clip, fill gaps, or join discontinuous recordings
in the first version. Metadata alone is insufficient proof of complete capture.

The queue is shared across this currently trusted local application. It requires
no frontend sign-in, and closing a tab does not cancel submitted jobs. The panel
can rediscover retained jobs after refresh using GET rather than storing camera
timestamps in browser persistence.

## Capture and encoding approach

The existing [five-second extraction](historical-playback-results.md) produced a
valid H.264 MP4 through SDK time playback, PlayCtrl decryption and YV12 decoding.
It writes raw frames to disk and has diagnostic-only limits and a relative
“one hour ago” start; it is evidence, not the production export implementation.
The browser feed also deliberately skips frames and cannot supply an export.

Recommended first implementation:

- Give the job its own playback handle/file-mode decoder through the shared SDK
  login, using its immutable camera/start/end and the full backend verification
  code. Viewing seeks/speed changes cannot modify it.
- Capture all decoded frames in order through bounded compressed and raw-frame
  queues. Use upstream flow control and heartbeat handling already established
  for playback. Cancellation must wake blocked producers before SDK stop.
- Feed frames directly to a Docker FFmpeg process while capturing, using the
  verified YV12 colour conversion. Do not write a multi-minute raw-video file or
  hold the clip in memory. The encoder writer runs away from live publication;
  an encoder exit or full pipe must release its buffers/handles promptly.
- Initially decode at 1× and encode normal-speed H.264/yuv420p MP4. Bounded
  deadlines scale with clip duration. Faster extraction is a later optimization
  after proving that it retains every frame and correct timing.
- Preserve encoded pixel dimensions and write the chosen display aspect into
  MP4/H.264 metadata, so the current 960 × 1088 footage plays at the selected
  proportions. [FFmpeg setdar/setsar](https://ffmpeg.org/ffmpeg-filters.html#setdar_002c-setsar)
  support this without changing frame dimensions. Verify the saved clip in a
  browser and with FFprobe; a browser CSS preference alone will not fix downloads.
- Finalize with [MP4 faststart](https://ffmpeg.org/ffmpeg-formats.html#mov_002c-mp4_002c-ismv),
  verify the output, then atomically publish it. Failed/partial files are never
  downloadable. Serve attachments with a safe camera-ID/time filename and existing
  range-response handling, never a filesystem path in the API.

There is also an official
[SDK time-download API](https://open.hikvision.com/hardware/definitions/NET_DVR_GetFileByTime_V40.html).
Its encrypted output and suitability for direct MP4/remux have not been verified
here. Reconsider it if the proven decode/encode path cannot meet the timing or
resource requirements; do not silently switch protocols or credentials.

**Feasibility gate before committing to production capture:** inspect frame
timestamps versus the recorded clock and prove start/end trimming for a short
arbitrary interval. A time-playback handle or fixed frame count alone is not
enough. Verify initial keyframe lead-in, end boundary, gaps and complete output.
If only coarser timing can be established, report the measured limitation for
review before widening clip limits or claiming precise exports.

## Scheduling, limits and lifetime

Proposed first-version defaults, configurable in private owner configuration:

| Setting | Proposed value |
| --- | --- |
| Maximum clip duration | 10 minutes; minimum 1 second (owner increased after initial implementation) |
| Active export workers | 1 |
| Waiting queue | 3 jobs in addition to the active job |
| Completed clip retention | 24 hours after completion |
| Export storage quota | 1 GiB across ready and partial artifacts |
| Per-clip output limit | 256 MiB |

### What constrains maximum clip length

The ten-minute limit is an application default, not an established SDK
or recorder maximum. The official
[time-playback API](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackByTime_V40.html)
and [download API](https://open.hikvision.com/hardware/definitions/NET_DVR_GetFileByTime_V40.html)
pages reviewed do not state a general maximum duration for arbitrary clips.
The playback page mentions five seconds to ten minutes in guidance about
extending event-playback intervals for pre/post-recording. That context does not
establish a universal ten-minute clip limit. The SDK already accepts multi-hour
viewer ranges here, but a completed multi-hour export has not been verified.

The SDK download API documents automatic file splitting at a default 1024 MB
threshold, configurable through local SDK settings. That is a file-size policy
for the alternative vendor-download path, not a duration limit or the planned
FFmpeg exporter's per-clip cap. Do not infer direct MP4 compatibility or decrypted
output from the filename suffix.

Relevant constraints for the selected implementation:

| Constraint | Consequence |
| --- | --- |
| Recording retention and gaps | The entire selected interval must still exist on the recorder. Missing/overwritten footage fails explicitly. |
| Existing diagnostic | Its ten-second input cap, twenty-second native deadline and 512 MiB raw-file cap were investigation bounds, not hardware limits. Only a five-second saved clip was verified. |
| Raw-video volume | At the tested 960 × 1088, 15 fps, five minutes of YV12 is about 6.6 GiB. Stream frames to the encoder instead of storing them. |
| Export execution time | At the initial 1× capture rate, a five-minute clip takes roughly five minutes plus preparation/finalization. Longer clips occupy the worker for longer. |
| CPU/memory and connections | The existing viewer container has two CPU cores and 2 GiB RAM. An export adds decoding/encoding and a recorder source; coexistence needs measurement. Bounded queues keep memory from growing with duration. |
| Encoded size and disk quota | File size depends on content and encoded bitrate. Both the 256 MiB clip cap and 1 GiB storage quota apply even when a duration is allowed. |
| Trim/clock correctness | Keyframe lead-in, timestamp mapping and gap detection must be proven for the arbitrary selected range. The proposed one-second minimum also needs this verification. |

For scale, a five-minute encoded clip at 2/4/8 Mbps is approximately
72/143/286 MiB. The last exceeds the proposed per-file cap; these are sizing
examples, not measured output bitrate guarantees. As a first validation ladder,
prove 10-30 seconds, then one minute, then five minutes with bounded storage and
viewing coexistence. Raising the configurable duration later must also review
file quota, execution deadlines and queue latency. It does not require a longer
browser playback session or retaining the whole raw clip in RAM.

Use one shared Python admission calculation for live sources, historical viewer
reservations and active exports. An active export reserves one extra source slot;
a queued job reserves no recorder slot. If the budget is full, the export waits
without evicting a view, stopping the user's playback, or repeatedly probing the
recorder. Release its reservation exactly once on success, failure, cancellation
or shutdown. Serialize jobs in submission order. Native capacity errors and auth
errors fail the job without an automatic login/retry loop.

Do not assume spare connection or CPU capacity simply because a slot fits the
configured application budget. Verify an interactive playback plus a short
export and a live preview through one login. Measure live-frame advancement,
playback responsiveness, CPU/memory and slow-encoder flow control before testing
a larger grid. Keep current Docker resource limits and capped encoder threads;
refine execution policy if measured contention harms viewing.

Keep job metadata and clips under ignored `.local/exports/`, with private
permissions and a dedicated writable runtime mount. An atomically written,
versioned job manifest is sufficient for the bounded queue; no database service
is needed. Persist accepted jobs and ready artifacts. On server restart retain
queued jobs and valid ready files, mark interrupted running jobs failed, and
remove incomplete files; do not automatically retry interrupted capture.

Enforce disk quota during writing and leave headroom for finalization. Retention
cleanup must not delete an active download; defer unlinking until it finishes and
keep those bytes counted. Ready files persist until expiry or explicit deletion;
do not silently evict them to admit more exports. Expired/missing download URLs
return an explicit unavailable state (410 for expiry).

## Frontend boundaries

Keep `playback-controls.js` responsible for step seeking and the displayed clock.
Add `history/clip-selection.js` for the in-memory camera-bound draft and marks;
add `history/exports.js` for submission, shared job polling, cancellation and
the separate Exports list. Application navigation mounts that list, and
`HistoryView` coordinates camera/window changes. Timeline rendering
can accept clip boundaries and paint their visible portion without owning jobs.
Freeze the job's range/aspect at submission even if settings or marks change later.

Queue polling runs only while its tab is visible, at roughly one-second
intervals while work is pending and slower when idle. Navigating away stops
polling, not the backend job. Use a normal download link for ready files. Keep
loading/error labels, keyboard focus and mobile layout consistent with the player.

## Milestones and verification

1. **Selection, frame download and small-step seeking:** add the direct PNG
   download, four step buttons, frame-clock marks, draft validation and timeline
   highlight. Test frame download/cleanup and client-only marking,
   camera resets, preserved draft across windows, paused/playing seeks, rate,
   clamping, stale generations, keyboard and mobile use. No export worker yet.
2. **Bounded SDK capture proof:** after approval, extract a short arbitrary
   interval with all-frame capture and streaming encoding. Prove clock mapping,
   trimming, color, normal-speed duration and saved aspect. Test encoder failure,
   producer cancellation and viewing coexistence. Reassess the pipeline before
   further edits if these assumptions fail.
3. **Queued jobs and downloads:** integrate the Python worker seam, one-worker
   scheduler, shared admission, persistent manifest, MP4 serving, cancellation,
   quota/retention cleanup and the separate Exports tab. Commit reviewable increments
   and maintain both getting-started guides, API notes and progress as they land.

Backend unit/API cases cover validation before SDK work, idempotency, queue order
and saturation, independent immutable jobs, slot waiting/release, cancellation
races, failed encoders, restart recovery, bounded storage, expiry during downloads,
content disposition, byte ranges and unavailable artifacts. Add native offline
tests for ordered all-frame delivery and cancelling blocked capture/encoder paths.

Offline Chromium cases use a deterministic fake export worker with the real job
manager/routes. Test marking while frames move, ±10/30s at different rates,
disabled controls, range validation, duplicate clicks, queued-to-ready download,
cancel/error/retry with a new job, refresh/navigation recovery, settings changes
after submission, labelled/fixed/off-screen clip marks, camera changes and
another viewer remaining live. Check Exports navigation releases only this page's
viewing lease and retains submitted jobs. Inspect the
downloaded synthetic MP4 with Docker FFprobe and a browser to verify content,
duration, colours, dimensions and aspect. Existing 60 unit/41 Docker regressions
remain required, and the unchanged GitHub Actions commands include new cases.

Real recorder checks are deliberate and bounded, separate from offline CI. Do
not run them while this document is awaiting owner review. Deferred features:
audio, long/unbounded clips, bulk/multi-camera exports, gap stitching, cloud
uploads, faster capture and direct encrypted-stream remux.
