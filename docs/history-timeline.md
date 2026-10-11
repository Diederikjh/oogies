# History timeline: first implementation slice

Implemented 11 October 2026, after plan checkpoint `ccee147`.

The History tab replaces Recorded clip. It displays one camera's recording
coverage and SDK motion intervals over the last three hours, with 1/3/6-hour
presets, earlier/later navigation, Recent and Refresh. Timeline bands, motion
entries, previous/next motion buttons and a keyboard-accessible time slider
select a timestamp locally. Selection pins the range; Recent enables minute
refreshes again. A currently live-offline camera can still be queried.

The timeline checkpoint selected times locally. It is now connected to
[interactive playback](history-playback.md), with video, pause/resume and seeking.
A private diagnostic MP4 is no longer required for History. Camera aspect
preferences apply to both live and recorded pictures through Settings.

## Backend and SDK

`GET /api/cameras/{id}/timeline?from={utc}&to={utc}` requires one explicit
timezone-aware start/end pair, with positive duration at most six hours. An
optional `refresh=1` requests fresh metadata. First/pending responses return
202; polling the same query returns 200 when finished. Remove `refresh=1` while
polling so completion does not immediately create another job.

`HistoryTimeline` owns normalization, a 60-second cache measured from job
completion, at most four outstanding jobs and 32 cached ranges. Identical
concurrent requests share a job. It rejects ambiguous recorder wall times and
converts through the owner's configured timezone; inputs/outputs use UTC.

`GridWorker.query_timeline(camera_id, begin_wall, end_wall)` is the Python worker
boundary also used by fixtures. The current adapter's native worker accepts:

```text
timeline <sdk_channel> <32-hex-request-id> <begin-wall-ISO> <end-wall-ISO>
```

It performs one V30 recording search and one base event search in a background
thread using the existing SDK login. API/result structures are paired correctly:

- `NET_DVR_FindFile_V30` / `NET_DVR_FindNextFile_V30`: all recording types,
  all lock states, no card filter.
- `NET_DVR_FindFileByEvent` / `NET_DVR_FindNextEvent`: motion major type 0,
  all minor types, all lock states, bitmap for the requested SDK channel.
- Both close their search handles with `NET_DVR_FindClose_V30`.

Each enumeration has a ten-second polling deadline and a 256-result cap; the
Python worker waits at most 25 seconds for a result. Native API call duration
also depends on SDK network timeouts. Reaching the enumeration limit returns
incomplete coverage, displayed as unknown rather than a confirmed gap. The
base motion selector supports channels 1–64; other channel numbers currently
report that query as unsupported. There is no API-generation fallback loop or
authentication retry. Late/unrequested results are discarded.

Each dataset independently reports `ready`, `pending`, `unsupported` or `error`.
Successful emptiness is `intervals: []`; unavailable data is `intervals: null`.
Intervals have stable IDs, clipped display start/end, original `source_start`/
`source_end`, SDK provenance and granularity (`recording` or `sdk_interval`).
Point intervals are retained. Precise Android event equivalence is not required.
Current inventory capability flags remain unknown; timeline responses describe
the observed result of each query.

Frontend modules split history lifecycle/query cancellation from timeline
rendering. Aborted/stale requests cannot overwrite a newer camera or range.
Leaving History cancels its browser polling; bounded backend work can finish
and populate the cache. Switching views releases only this page's live lease.
The existing shared SDK login remains connected.

## Real-recorder evidence

A camera-1 query covering the previous three hours returned two recording
intervals through V30. Motion search completed successfully with zero intervals.
This establishes an accepted query, not equivalence with Android's motion data.
The earlier V40 error-11 request remains an historical result; V30 now provides
a working recording-discovery path on this installation.

A second, one-hour query ran while camera 1 streamed live. Twenty live packets
were read, source sequences advanced from 1 to 34, and the check finished in
about 2.08 seconds with no feed errors. The query returned one recording interval
and zero motion intervals. The worker reported one SDK login, and only the test
viewer lease was deleted. This verifies live plus metadata, not live plus
historical video playback or a recorder connection maximum.

Detailed results remain private in `.local/browser-viewer/history-timeline-check.json`
and `.local/browser-viewer/history-live-coexistence.json`. The extended native
worker compiled against the preserved SDK and passed its offline decoder check
with no credentials, networking or logins.

See [UI testing](ui-testing.md) for offline acceptance coverage and
[the API document](backend-api-plan.md) for implemented versus proposed routes.
