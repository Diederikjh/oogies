# Viewer implementation plan

Status: agreed milestone order; implementation remains incremental. Updated
after the user's request to put the automatic live grid before motion-timeline
investigation. The API and module layout in
[backend-api-plan.md](backend-api-plan.md) are proposals for review, not existing
endpoints or a finalized contract.

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
  verification code. Make that login policy explicit for other installations.
- Keep the frontend without a login for now and make the eventual viewer
  available on the home LAN. Backend access provides camera access; browsers
  need not connect directly to the NVR.
- Keep SDK, decoder and new tools in Docker. Preserve resource limits and
  private diagnostic outputs.
- Do not assume the recorder's reported channel capacity equals the number of
  configured/online cameras, or that its connection limit is known.
- Retain MJPEG for the first grid milestone. Measure before deciding whether
  a H.264 transport is needed. Audio is a later capability.

## Milestones in the revised order

| Milestone | Work | Completion criterion |
| --- | --- | --- |
| 1. Recorder configuration, camera discovery and capacity | Read the installing user's NVR IP, SDK port and clock timezone from backend configuration, with separate private credentials and an explicit login-password policy. Remove hardcoded recorder settings in viewer/SDK runners. Read configured channels, names and online state. Test concurrent previews progressively: 1, 2, 4, then all active cameras. Inspect current stream counts and measure backend resource usage. | A fresh checkout starts using documented owner-supplied settings without source edits. Establish a tested operating capacity that accommodates the grid and one historical playback, accounting for other clients such as the Android app. |
| 2. Automatic live grid | Introduce per-camera decoder contexts and shared live-source management. Start overview subscriptions on page load; add grid tiles, independent status and enlarged views. | All available cameras move simultaneously; another browser reuses the sources; one failed camera does not interrupt the rest; closing a page does not stop another viewer. |
| 3. Motion timeline feasibility | Investigate the previous error-11 recording search with minimal supported requests. Query motion events for a bounded period and compare known intervals with the Android app. Check supported SDK alternatives, then read-only ISAPI through the SDK if needed. | Motion intervals match the app with correct channel/time conversion, or document a concrete limitation and viable alternative before building the timeline. |
| 4. Historical timeline viewer | Add camera/date selection, recording and motion bands, time-based playback, pause/resume, seeking, next/previous events and short clip export. | Selecting a known event plays the correct footage and timestamp; recording gaps and unavailable motion metadata are displayed accurately. |
| 5. Reliability and transport | Test sustained use, disconnects, cleanup, resource use and playback alongside the grid. Evaluate H.264 delivery if measurements justify it. | Both use cases remain usable over longer sessions without connection leaks or frozen frames presented as live. |

## Evidence and unresolved questions

One encrypted live substream and historical time playback already work. The
browser prototype displays changing live frames, plays the extracted H.264 MP4,
and shares its single source across refreshes. It remains a one-camera diagnostic
prototype with manual Start/Stop and a finite session.

General recording search returned SDK error 11; direct playback by time worked
without search. This does not establish whether the motion-event search API
works on this recorder. The SDK documents motion-event searches, but the
bundled guide describes event-triggered recordings with recording linkage
configured. The Android app's timeline may use additional metadata; its presence
is promising evidence, not proof of API equivalence.

If event search cannot reproduce the app's timeline, compare alternative
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
C++ bridge. Evolve the bounded probe into a persistent worker that accepts
commands and returns results, reusing the recorder connection across operations.

Owner settings, including NVR IP/SDK port/timezone, belong in ignored
`.local/nvr-config.json`; credentials remain separate. Support other Hikvision
recorders through one small adapter and deterministic, versioned SDK profiles.
Make the login-password truncation policy explicit rather than universal. Keep
native dependencies isolated behind a stable worker contract and report
per-feature capabilities. Implement the current profile first; add another
implementation when a real device/SDK difference requires it. The
[compatibility review](recorder-compatibility-review.md) records current coupling,
the minimal extension points and verification criteria.

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

No feature implementation or recorder request was made while recording this
plan. See the [API proposal](backend-api-plan.md) for the intended calls and
example browser flows.
