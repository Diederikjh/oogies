# Viewer implementation plan

Status: owner configuration, discovery and the initial live grid are implemented
and verified on the current recorder. The first History timeline slice is now
implemented; interactive historical playback is next. The
[API document](backend-api-plan.md) distinguishes implemented live/timeline endpoints from
historical proposals; [live-grid.md](live-grid.md) records observed capacity.
The [History view plan](history-view-plan.md) expands milestones 3–4 into SDK
feasibility, fixture-tested UI, real metadata and interactive playback stages.

Milestone 1's seven-camera live checks pass; a fully fresh remote/LFS installation
and simultaneous SDK historical playback remain unverified. Milestone 2's initial
grid, sharing, cleanup and expansion pass; expansion currently keeps overview
quality. Main-stream switching and sustained recovery are later work.

## Primary use cases

### Live overview

Opening the overview automatically displays configured cameras together in a
responsive grid. Use substreams for the overview and permit an enlarged view
with higher quality where supported. Show camera names and explicit states for
offline, starting, live, stale video and resource limits. Retain configured
offline cameras as labeled tiles.

Share backend camera sources among viewers: a second browser should not double
the recorder streams. A viewer closing its page releases only its subscriptions.
Replace the prototype's fixed ten-minute session with viewer-based lifetimes,
idle cleanup and bounded recovery. Authentication failures stop recovery;
there is no password guessing or automatic authentication retry loop.

### Historical camera view

Select a camera and date/time range. Display available recordings and motion
intervals as separate timeline information, with gaps represented accurately.
Click a time or motion marker to play the relevant footage. Add pause/resume,
seeking, previous/next motion event and short clip export.

Historical playback sessions are independent per viewer. Moving one viewer's
playback position must not move another's. Switching a page from overview to
history releases that page's unnecessary live subscriptions, while preserving
other viewers' streams.

Recording availability and motion markers are separate data sources. A failed
or unsupported query is not an empty successful result. The UI must distinguish
"no motion found" from "motion data unavailable." Internally normalize timestamps
to UTC and display South Africa time, with verified conversion from recorder
timestamps.

## Scope and operating preferences

- Other recorder owners must be able to clone the repository, enter their own
  NVR IP/settings and credentials, and run the service without editing source.
  Use the SDK archive already preserved through Git LFS; no separate vendor
  download is part of setup. Keep the root
  [human getting-started guide](../GETTING_STARTED.md) and detailed
  [agent setup guide](../GETTING_STARTED_AGENTS.md) current in each milestone.
- Keep credentials in the existing private backend file, including the confirmed
  16-character login rule for the original installation and the complete
  verification code. Own that policy in the selected Python SDK adapter.
- Keep the frontend without a login for now and make the eventual viewer
  available on the home LAN. Backend access provides camera access; browsers
  need not connect directly to the NVR.
- Keep SDK, decoder and new investigation tools in Docker, with the owner's
  explicit exception for native Git LFS. Preserve resource limits and private
  diagnostic outputs.
- Do not assume the recorder's reported channel capacity equals the number of
  configured/online cameras, or that its connection limit is known.
- Retain JPEG frames for the first grid milestone. Measure before deciding whether
  a H.264 transport is needed. Audio is a later capability.

## Milestones in the revised order

| Milestone | Work | Completion criterion |
| --- | --- | --- |
| 1. Recorder configuration, camera discovery and capacity | Read the installing user's NVR IP, SDK port and clock timezone from backend configuration, with separate private credentials and an explicit login-password policy. Remove hardcoded recorder settings in viewer/SDK runners. Read configured channels, names and online state. Test concurrent previews progressively: 1, 2, 4, then all active cameras. Inspect current stream counts and measure backend resource usage. | A fresh checkout starts using documented owner-supplied settings without source edits. Establish a tested operating capacity that accommodates the grid and one historical playback, accounting for other clients such as the Android app. |
| 2. Automatic live grid | Introduce per-camera decoder contexts and shared live-source management. Start overview subscriptions on page load; add grid tiles, independent status and enlarged views. | All available cameras move simultaneously; another browser reuses the sources; one failed camera does not interrupt the rest; closing a page does not stop another viewer. |
| 3. Motion timeline feasibility | Investigate the previous error-11 recording search with minimal supported requests. Query motion-related recordings for a bounded period and present SDK-returned intervals. Check supported SDK alternatives, then read-only ISAPI through the SDK if needed. | Returned SDK intervals retain their granularity and correct channel/time conversion, or document a concrete limitation without confusing unavailable data with no motion. Precise Android event equivalence is not required. |
| 4. Historical timeline viewer | Replace Recorded clip with History: camera selection, a recent-hours timeline, recording and motion tracks, time-based playback, pause/resume, seeking and next/previous events. Add clip export after that flow works. | Selecting a known event plays the correct footage and timestamp; recording gaps and unavailable motion metadata are displayed accurately; independent viewer positions and live/history coexistence pass. |
| 5. Reliability and transport | Test sustained use, disconnects, cleanup, resource use and playback alongside the grid. Evaluate H.264 delivery if measurements justify it. | Both use cases remain usable over longer sessions without connection leaks or frozen frames presented as live. |

## Evidence and unresolved questions

Seven encrypted previews now play simultaneously in the automatic grid, shared
across two browser views using one login. Independent Pause and 90-second orphan
lease expiry were verified. Historical time extraction and saved MP4 playback
also work. Hardware maximum and historical playback alongside the grid remain
unknown; short seven-camera samples used about 154 MiB and half one CPU core.

The earlier V40 recording search returned SDK error 11; direct playback by time
worked without search. V30 recording search now returns coverage. Base motion
event search completed successfully with no intervals in two bounded camera-1
queries. The [implemented timeline](history-timeline.md) presents returned SDK
data without requiring Android equivalence. Live video continued during metadata
search through the same login; interactive historical playback coexistence and
controls remain unverified.

If richer motion data is needed later, compare alternative
SDK/event-log and supported ISAPI paths. Recording intervals labeled as motion
must retain their actual granularity rather than being presented as exact
motion-trigger timestamps. Future alarm subscription/storage can collect new
events, but cannot reconstruct older events by itself.

Connection limits, outgoing recorder bandwidth, backend decoding load and
browser-delivery bandwidth are separate constraints. A shared SDK login can
own multiple preview handles, but it does not make their video connections free.
The milestone establishes a usable capacity; deliberately exhausting the
recorder is unnecessary.

## Functional boundaries

Use Python for the HTTP API, configuration, viewer-session management and job
coordination. Keep native SDK calls, decoder callbacks and video buffers in a
C++ bridge. The live grid now uses a persistent worker accepting per-source commands and
lifecycle events, reusing one recorder connection. Historical operations currently
remain separate bounded probes.

Owner settings, including NVR IP/SDK port/timezone, belong in ignored
`.local/nvr-config.json`; credentials remain separate. Support other Hikvision
recorders through one small adapter and deterministic, versioned SDK profiles.
Keep the login-password truncation policy in the SDK adapter rather than owner
configuration. Keep native dependencies isolated behind a stable worker contract and report
per-feature capabilities. Implement the current profile first; add another
implementation when a real device/SDK difference requires it. The
[compatibility review](recorder-compatibility-review.md) records current coupling,
the minimal extension points and verification criteria.

The first [Python adapter seam](sdk-adapter-seam.md) is now implemented with one
concrete SDK class and explicit dependency injection. It owns credential policy,
bridge build/launch details and runtime selection. The broader recorder/worker
interface remains provisional until a second SDK supplies evidence. Grid discovery and per-source native contexts now use this seam through the
configured SDK profile. A second SDK still needs real compatibility evidence.

Separate frontend navigation, API access, live overview, camera tiles, historical
view, timeline, playback controls and shared media rendering. Use ordinary
JavaScript modules initially; no frontend framework or bundler is required for
these boundaries. Keep HTTP route handling separate from recorder/SDK operations
and source/session management in the backend.

Fresh-checkout setup is part of milestone verification. Changes to configuration,
dependencies or startup behavior must update [GETTING_STARTED.md](../GETTING_STARTED.md)
and [GETTING_STARTED_AGENTS.md](../GETTING_STARTED_AGENTS.md) alongside implementation.
Current Linux amd64 support and device-specific
limitations remain explicit until broader compatibility is verified.

See the [API document](backend-api-plan.md) for current live/timeline calls and
proposed playback flows. Both setup guides describe the first History slice.
