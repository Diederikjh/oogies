# Clip and frame downloads

The [approved plan](clip-export-plan.md) was committed as `06c077d` before
implementation. History now supports clip marks, 10/30-second stepping, direct
PNG downloads, and a shared durable MP4 export queue.

## Using History

Play or pause a recording, then use **Mark start** and **Mark end**. Each mark
uses the last successfully displayed frame's recorded clock, rounded to whole
seconds. Previewing the slider does not change either mark. Start/End flags and
a shaded band appear in the visible timeline. Draggable Start/End labels sit in
a fixed strip between the recording and motion bars, keeping bar heights and
preview size stable when marks are added or cleared. Text keeps both timestamps visible
when you move to another time window. The white playhead stays independent.

Choose an end after the start, from one second to ten minutes. Review the camera
and range, then press **Save clip**, the emphasized primary action. Picture
proportions are configured in **Settings** and apply to viewing and saved clips.
The request freezes the range and current picture proportions. The confirmation
appears with a brief fade and small bounce after the export is accepted, with
motion disabled for reduced-motion preferences. The **Export** word in the
success message links to the Exports tab. The confirmation disappears after 60
seconds, on **Clear marks**, or when
leaving History (including changing camera). Dismissing it does not cancel the
queued job. Continue viewing, or open **Exports** to monitor progress, cancel
work, download a ready MP4, or delete its file. Marks stay in this browser's
memory across tab changes; changing camera clears them and reloading clears them.

Setting both marks automatically zooms around them, including an overlong or
reversed draft. Drag either Start/End handle horizontally to adjust it, using
mouse or touch. A drag keeps a fixed time-to-pixel scale and holds metadata redraws
until release. Handle edits stay in the browser, preserve playback and clamp to
an ordered range of 1–600 seconds (or the owner's lower configured limit).
An invalid initial draft becomes valid on the first handle movement. Keyboard
arrows move one second, Shift+arrows ten seconds, and Home/End reach each handle's
allowed bounds. **Zoom to clip**, **Zoom out** and **Full range** control the
visible window without changing playback or fetching SDK metadata. Coverage
outside the loaded window is shown as unknown if marks span different windows.
The seek slider follows the visible, loaded portion; committing a seek keeps
the existing SDK session range. A displayed frame outside the zoom is labelled
accordingly instead of automatically moving the viewport while you edit.

The four step buttons move from the displayed recorded clock by ±10/30 seconds,
retain pause and speed, and clamp to the current playback window. They do not
move clip marks or extend that window.

**Download current frame** saves a PNG directly in the browser. It requires no
job or recorder request. A successfully painted JPEG Blob, camera ID/name, timestamp
and sequence are frozen at click time. One canvas conversion applies the chosen
16:9/4:3/Original proportions; native detail is retained, bounded to 16 megapixels.
Playback performs no canvas resizing. Filenames include the sanitized camera
name, recorded UTC second and frame sequence, for example
`oogies-Driveway_20261011T080000Z_f123.png`. Names retain Unicode letters and spaces;
path separators, reserved punctuation and control/format characters become
hyphens. Leading/trailing dots, spaces and hyphens are trimmed, names are bounded
to 128 UTF-8 bytes, and an empty result falls back to `Camera`. The `oogies-`
prefix prevents a reserved device name from being the entire filename. These
choices account for [Windows filename rules](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
as well as path separators on Unix. No controls or letterboxing are included.

## Queue and artifacts

| API | Behavior |
| --- | --- |
| `POST /api/exports` | `{camera_id, from, to, aspect_ratio}`, UTC whole seconds; 202; optional `Idempotency-Key` |
| `GET /api/exports` | Shared recent jobs, limits and current artifact storage use |
| `GET /api/exports/{id}` | State, progress/wait reason, requested range and verified media details |
| `DELETE /api/exports/{id}` | Cancel queued/running work or delete a ready clip; repeat safely |
| `GET /media/exports/{id}.mp4` | Ready attachment, single byte ranges; 409 pending/failed, 410 expired/deleted |

States are `queued`, `running`, `ready`, `failed`, `cancelled`, `expired`.
The list stays newest first when returning from History, refreshing, or receiving
updates from another browser. Existing rows and their controls are reused.
Running jobs show a circular progress indicator with the backend's percentage
in the centre and an accessible progressbar value. Queued jobs show their wait
reason; completed or cancelled jobs show their status instead of the ring.
Progress follows recorded-time capture and stays below 100% until the MP4 is
finalized and verified. Reduced-motion preferences disable the ring transition.
One worker runs, with three waiting jobs by default. A queued job holds no
recorder slot. An active job reserves one slot in the same budget as live and
historical viewers. Full capacity waits without probing or evicting another view.
Entering Exports releases only the current page's viewing leases. Export jobs
continue after browser closure; they do not use viewing leases.

Jobs and files live in ignored `.local/exports/`, mounted writable at `/exports`.
A versioned manifest is atomically replaced. Ready and queued jobs survive a
service restart; interrupted captures fail and partial files are removed. Ready
files expire after 24 hours. Delete/expiry closes new downloads immediately and
defers unlinking an already-open download until it finishes. Recent terminal
history is bounded; idempotency keys remain valid while their jobs are retained.

Defaults are a 256 MiB per-file cap and 1 GiB storage quota. Admission and
scheduling leave one extra file cap of finalization headroom. Completed files
are never silently evicted to admit another job. Optional strict configuration
is documented in [the setup agent guide](../GETTING_STARTED_AGENTS.md).

## Capture path and precision

Python owns validation, admission, persistence, HTTP and FFmpeg. The existing
C++ bridge opens a separate main-stream playback handle and file-mode decoder
through its existing SDK login, using the full stream encryption password.
The export context owns a thread so capture does not block live publication or
browser playback controls. Decoder callbacks retain every YV12 frame in order
through a bounded 16 MiB queue and nonblocking FIFO. The existing compressed-data
queue is also bounded to 16 MiB. Cancellation wakes both before SDK/decoder stop.
The whole raw clip is never retained in memory or saved to disk.

The first decoded frame may have no recorded clock. It is skipped until a valid
OSD clock can anchor the decoder's millisecond stamps. Subsequent stamps must
advance, tolerate unsigned wrap, and remain consistent with recorded time.
Timestamp discontinuities, format changes, stalls and incomplete range coverage
fail. Short edge uncertainty is limited by whole-second device time; final MP4
duration must also match the request within one second, consistent with the
reported clock precision, and encoded frame count must match captured frames.
Requested ranges are `[from,to)`; frame-exact wall-clock
trimming is **not** promised. Actual coverage is reported at second precision.

FFmpeg receives raw YV12 as `yuv420p` with `swapuv`, encodes H.264/yuv420p at the
reported frame rate, and adds `faststart`. Output is video only at normal speed,
independent of viewer speed. 16:9/4:3 are stored as display-aspect metadata without
resizing every frame; Original uses native pixel proportions. Codec, dimensions,
duration and display aspect are checked with FFprobe before publishing the MP4.
Capture has stall/overall deadlines and checks the file cap while writing.

The ten-minute cap is an application constraint, not a demonstrated Hikvision
hardware maximum. The alternative vendor direct-download format remains
unverified and is not used as an automatic fallback.

## Real-recorder evidence, 2026-10-11

| Requested | Verified MP4 duration | Frames | Dimensions | Display aspect |
| --- | --- | --- | --- | --- |
| 1 second | 0.934 seconds | 14 | 960 × 1088 | 16:9 |
| 10 seconds | 9.867 seconds | 148 | 960 × 1088 | 16:9 |
| 60 seconds | 59.934 seconds | 899 | 960 × 1088 | 16:9 |
| 300 seconds | 299.867 seconds | 4,498 | 960 × 1088 | 16:9 |
| 600 seconds | 599.134 seconds | 8,987 | 960 × 1088 | 16:9 |

The 1/60/300-second ladder and later 600-second check ran with one live preview and one historical viewer.
Historical viewing continued throughout; SDK login count stayed at one.
Sampled runtime memory was about 280–300 MiB, within the existing two-CPU/2-GiB
container limits. This establishes three concurrent contexts for that check,
not a general hardware maximum or full-grid-plus-history-plus-export guarantee.
The later ten-minute repeat sampled about 356 MiB, still within those limits.
Ready clips also survived service restart and supported ranged downloads without
reconnecting to the recorder. The regression suites pass 78 backend unit cases
and a full 56-case Docker browser/native run, with follow-up coverage for the new
57th case (zoomed slider seeking) and updated clip flows.
Cancelling a real in-progress capture released its slot, removed partial output
and preserved advancing frames in a separate live preview, with one SDK login.
The first ten-minute check failed the former quarter-second duration guard.
Rechecking the same recording measured a 0.866-second difference between nominal
constant-rate MP4 duration and the requested recorded range. Validation now
allows at most one second, consistent with the reported position precision,
and additionally checks encoded frame count. No padding, frame duplication or
gap stitching was added; independent recorded-coverage and stamp checks remain.

Explicit reproduction (contacts the configured recorder):

```sh
python3 tools/check_clip_exports.py --seconds 1 60 300 --with-views
python3 tools/check_clip_exports.py --seconds 600 --with-views
```

Private downloaded clips and reports stay under `.local/export-checks/`.
Automated unit/browser tests use the fake recorder boundary and actual FFmpeg,
including timestamp validation, queue limits, persistence, cancellation, active
downloads, HTTP ranges, PNG colors/aspects/conversion races, and independent
viewers. They require no SDK credentials or recorder access.
