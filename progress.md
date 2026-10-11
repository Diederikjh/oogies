# Camera viewing investigation progress

Updated: 2026-10-11 (South Africa time).

Goal: establish whether live video from the home Hikvision DS-7108HGHI-K1
at `192.0.2.10` can be decoded and viewed in a browser, then develop the live
and historical use cases incrementally.

## GitHub LFS authentication

The HTTPS push reached the publication guard but failed during LFS upload:
the container could not access host Git/VS Code credentials. The owner prefers
native Git LFS as an exception to Docker-only investigation tools. The setup
script now configures native filters locally, while the publication hook runs
the existing privacy scan before native `git lfs pre-push`. Setup guides list
host Git LFS explicitly. The Docker credential bridge is removed.

The owner installed native Git LFS on the host; version 3.4.1 is available.
The checkout's local filters now invoke native `git-lfs`, and its hook path
remains `.githooks`. Native `git lfs fsck` passed and the SDK archive's SHA-256
still matches the original. No push was attempted for this change.

All 21 existing unit tests and the full publication privacy check passed. An
offline hook check verified that native LFS receives the original remote
arguments and ref-update input, and that a privacy failure prevents upload.
Future checkouts use `python3 tools/setup_git_lfs.py` to configure native filters
while preserving the publication hook, then `git lfs fsck` to verify the SDK.

## Storage camera recovery diagnosis

Native Git LFS migration was committed as `1db2482`. Storage is SDK channel 3.
The running viewer had cached `online: false` at discovery; its session manager
excludes offline cameras before starting any preview. Earlier private logs show
Storage successfully streamed in a previous run. Discovery was a one-time
snapshot, so a recovered camera stayed excluded until the service restarted.

A single isolated SDK probe found Storage online with normal signal/hardware
flags, decoded eight frames and published five valid JPEGs at 352 × 288 without
errors. The viewer was relaunched, and its normal HTTP session/media API then
delivered three advancing, distinct Storage JPEGs with state `live`. The temporary
test lease was deleted; the server retains one SDK login and is ready for browsers.
Evidence stays private under `.local/browser-viewer/storage-check-*/report.json`
and `.local/browser-viewer/storage-web-check.json`.

The subsequent one-minute cache change below addresses the stale offline
snapshot. Full rediscovery of added/removed channels still needs service restart.

## One-minute camera availability cache

Camera availability now expires after 60 seconds. Active viewers request a
shared SDK status refresh through the existing login; a recovered offline
camera starts automatically in already-open grids. Healthy previews are retained,
and recent decoded video takes precedence over an offline status hint. Unknown
status preserves the last known state and is retried at most once a minute.
Authentication is never retried by this path. Idle viewers make no periodic
queries; `/api/cameras` can request an expired refresh on the next access.

All 26 host unit tests passed, including exact expiry, simultaneous callers,
recovery in shared sessions, failed/unknown status, healthy-stream preservation
and no extra login. A new offline Docker browser case verifies recovery in two
tabs across the 60-second boundary using the real cache/event implementation and
a controlled clock. The updated C++ bridge compiled against the bundled SDK,
and its offline decoder check passed with networking disabled and zero logins.
All 14 Docker browser cases passed. The service was relaunched with the updated
cache and native protocol. Storage then delivered three advancing valid JPEGs
through the normal browser API with one shared SDK login; the temporary test
lease was released. Evidence is private in
`.local/browser-viewer/availability-cache-web-check.json`.

## Current milestone: automatic live grid verified

The aspect correction was committed as `95ec310`. The service now discovers inputs
and automatically shows a responsive live grid. Nine configured inputs were
found: seven online (six analog and SDK IP channel 34) and two offline. Progressive
checks of 1, 2, 4 and all 7 previews passed using one SDK login. Independent decoder
contexts share sources across viewer leases.

Real Docker Chromium checks passed for moving frames, all seven displayed at
16:9, desktop/mobile layout, expansion, two tabs sharing sources and independent
Pause, plus saved historical playback. An unrenewed lease expired after 90 seconds
while an independently renewed view kept playing. Short seven-camera samples used
approximately 154 MiB and 50% of one CPU core; the hardware stream maximum and
sustained resource use remain unverified.

Owner IP/port/profile and limits now live in private `.local/nvr-config.json`.
Frontend code is split into shared API/feed/media helpers, live overview/tiles
and recorded-clip playback. One multiplexed JPEG connection per page avoids
per-camera HTTP connection limits; browser scaling preserves native JPEG sizes.
Expand remains overview quality. The last viewer leaving stops previews; the
shared login persists until service shutdown.

Eighteen offline unit tests passed, including source sharing, expiry, capacity,
configuration and native failure cleanup. Setup guides and the [implemented grid API](docs/live-grid.md) describe this
behavior. The next milestone is **motion-timeline feasibility**, including
recording-search compatibility. Concurrent historical extraction with the grid,
main-stream switching and a fresh remote/LFS clone remain untested. Evidence is
private under `.local/grid-check/`; no captures or credentials enter Git.

## Display controls refined

Picture-proportion selectors now live under Settings → Picture proportions.
The camera picture itself toggles expand/collapse and supports Enter/Space.
Expansion retains the same overview source. Per-camera browser preferences are
preserved, with Camera 1's choice shared by its live and recorded views.

The focused Docker Chromium check uses a fake worker with the real HTTP handler,
viewer leases, frame feed and frontend, plus synthetic JPEG/MP4 media. Seven
interaction checks passed, including refresh persistence, independent preferences,
modal focus/Escape, mobile fit and recorded-video proportions, with networking
disabled, no credentials/SDK mounted, zero SDK logins and no browser errors.
See [check_display_controls.py](tools/check_display_controls.py).

## Offline UI test suite

The preceding settings/click-to-expand work was committed as `c25054b` before
adding this suite. `python3 tools/run_ui_tests.py` runs Docker Chromium against
the real frontend, HTTP API, live-session manager and multiplexed JPEG feed.
The small server-construction seam accepts a worker; tests supply a simulated
recorder with eight distinct animated cameras, an offline input and synthetic
recorded video. The container has no network access, SDK, credentials or private
configuration mounted, and does not use the owner's running viewer.

Cases cover camera identity/movement, independent failures/stale states, capacity,
settings/persistence/keyboard/mobile behavior, recorded playback, shared tabs,
Pause/Resume, refresh/close cleanup, real ten-second lease expiry and startup
navigation. The suite exposed and fixed returning to Live while discovery is
pending: the requested start is now queued and Pause cancels it. Backend setup
and SDK-dependent password/encryption behavior remain unchanged.

All 13 UI cases and 18 existing unit tests passed. The runner saves JSON outcomes
and synthetic screenshots in ignored `.local/ui-test-results/`. Setup guides and [UI testing](docs/ui-testing.md)
document running the suite without recorder setup. Real SDK/device compatibility
still requires its separate checks.

## GitHub CI prepared

`.github/workflows/ci.yml` runs independent unit and offline UI jobs on pushes,
pull requests and manual dispatch. It uses the same commands as local testing,
skips the SDK/LFS download and needs no recorder credentials. UI JSON results
and synthetic screenshots are retained as GitHub run artifacts for 14 days,
including ordinary test failures. GitHub checks local commits after they are
pushed; newer pushes do not cancel older runs. Deployment remains a later step.

Workflow syntax passed actionlint in Docker. All 18 unit tests and 13 UI tests
passed using the workflow commands from a clean temporary source copy, initially
without SDK, `.local/` or Git metadata. Evidence is private under
`.local/ci-validation/`. Hosted Actions execution awaits a GitHub push; no repository remote
or publishing action was configured here. See [CI notes](docs/ui-testing.md#github-actions).

## Real service revalidated after the UI-testing seam

The viewer was relaunched with `create_server` wired to the real SDK worker.
HTTP/assets loaded; one SDK login discovered nine configured inputs. The current
snapshot reports four online (channels 1, 6, 8 and 34) and five offline (2, 3, 4,
5 and 7), compared with seven online in the initial grid experiment. The cause
of that availability change was not investigated or attributed to the seam.

A brief check retrieved valid JPEG packets for every available stream, confirmed
two viewer leases share the same sources/login, and verified that deleting one
lease preserves advancing frames for the other. The saved recording still serves
HTTP byte ranges. Temporary leases were released; the service remains ready for
the owner's browser. Private results: `.local/relaunch-check.json`. No credential
retry or recorder settings change was performed.

## Publication preparation

The approved UI suite, CI workflow and production seam changes are committed
with publication cleanup. General Gitleaks history scanning found no token or
password leaks. Known-value checks found no saved login password, effective
password prefix or full stream-encryption code in publishable files, Git objects
or the SDK archive. Account-name substring matches were technical vocabulary;
no literal credential assignment was found.

Local recorder addresses and personal home paths were removed from source/notes.
The remaining legacy diagnostics now read private configuration. Unpublished
history is sanitized before the first push, with the original Git metadata and
LFS objects preserved under ignored `.local/publication-backup/`. Commit IDs
change; older IDs in investigation notes describe the original local history.
The original SDK archive and private running-service configuration are preserved.

A repeatable publication check is added to the pre-push/LFS hook and CI. It checks
publishable files and branch/tag history, with private values kept out of reports.
No GitHub remote or push is performed until the owner provides the repository.
See [publication checks](docs/publication-checks.md). The offline suite now has
21 unit cases, including three publication-check tests; UI coverage remains 13.

## Authentication finding

The recorder's web password input accepts at most 16 characters. The password
in the credentials file was longer; using its first 16 characters resolved
both RTSP and SDK authentication. This is verified for this recorder, rather
than assumed to be a universal Hikvision rule.

The current Python SDK adapter now owns that limit for all authenticated probes.
`tools/credentials.py::load_credentials()` only reads and validates the original
values. The adapter preserves the username, the complete verification/encryption
code, and the original credential file. Credentials
remain private in `.local/nvr-credentials.json`; tests cover the boundary and
preservation of those values. The new non-admin account also logs into the
local web UI.

## RTSP login: successful; video decoding unresolved

- Port 554 is open; the tested path is `/Streaming/Channels/102` (camera 1,
  substream) over RTSP/TCP.
- At 12:46:11 on 2026-10-10, one FFmpeg session using the first 16 password
  characters passed authentication and reached HEVC/H.265 processing.
- FFmpeg reported invalid VPS/SPS/PPS/NAL data and could not determine frame
  dimensions. No valid frames or usable capture were produced.
- Stream encryption is enabled in the recorder UI. The decode errors are
  consistent with encryption, but do not alone prove it is the cause. No
  verification/encryption code was applied during that RTSP test.

Details: [RTSP result](docs/rtsp-first16-results.md) and
[authentication history](docs/authenticated-probe-results.md).

## SDK login: successful in Docker

- The original Linux64 HCNetSDK 6.1.9.48 package was downloaded manually after
  the vendor site blocked automated downloads. The runtime and download tools
  run in Docker; no new tools were installed on the host.
- Offline loading and initialization passed. The SDK needs more than the
  initial 128-thread/process container limit; the working runner allows 512
  with CPU and memory limits still in place.
- At 12:54:51 on 2026-10-10, one synchronous `NET_DVR_Login_V40` call on port
  8000 succeeded with SDK error 0, using the shared credential loader.
- That initial test was login only, followed by logout and cleanup. A later
  preview verified capture and decryption, as recorded below.

Details: [SDK investigation](docs/sdk-docker-investigation.md),
[SDK usage notes](docs/official-sdk-usage-notes.md) and
[credential loader](docs/credential-loading.md).

## Encrypted live stream: successfully decoded

At 13:29:45 on 2026-10-10, a single SDK login and 20-second preview successfully
decoded **300 YV12 frames at 352 × 288** from the first camera's substream.
PlayCtrl reported encrypted video (type 2, AES-10-round) with a key present,
and zero decoder/input errors. The saved frame was converted offline to PNG
and visually confirmed as recognizable camera imagery with a valid timestamp.

The working call is `PlayM4_SetSecretKey(port, 1, full_verification_code_utf8,
128)` before opening the stream. Offline inspection of the supplied Hik-Connect
APK established this call pattern; the live test confirmed it with the supplied
Linux decoder. The complete verification code is preserved. The fixed `128`
argument does not mean truncating that string to 16 characters.

No recorder settings were changed to disable encryption. Authentication
remains bounded to one login per probe. Details and reproduction commands:
[encrypted-stream investigation](docs/encrypted-stream-investigation.md).

## Historical playback: successfully extracted

The installed SDK provides recording search, time/filename playback, recorded
data callbacks, playback controls and downloads. Both V40 and V50 APIs are
present in its headers and exported by the Linux library. Recorded callbacks
can feed PlayCtrl, and the APK's playback branch uses the same full encryption
string.

At 14:51:50 on 2026-10-10, direct SDK time playback retrieved camera 1's main
recording for **13:51:50–13:51:55**, exactly an hour earlier by the DVR clock.
PlayCtrl decoded 75 frames at 960 × 1088 and 15 fps; offline FFmpeg produced
a verified 5-second H.264 MP4. Its first frame visibly confirms the requested
historical timestamp. The full verification code was configured, but this
recording did not report an encryption flag, so its key requirement is unknown.

Two bounded sessions were used: the initial recording search returned SDK
error 11; the subsequent direct playback succeeded without a search. Login
succeeded once in each session; there were no credential retries or recorder
settings changes. Recording discovery remains unresolved.

Details: [historical-playback investigation](docs/historical-playback-investigation.md).
Verified result and commands: [historical-playback results](docs/historical-playback-results.md).

## Earlier single-camera browser prototype

A local Docker-backed prototype now serves camera 1 at `http://localhost:8088/`.
Start/Stop controls manage one shared SDK/PlayCtrl session, with the full
verification code kept in the backend. Latest decoded frames are converted
to JPEG and shown as MJPEG; the previously extracted MP4 also plays in the
browser with native controls.

Chromium verification observed changing displayed pixels, advancing recorded
playback, and 49 live frames. Repeated Start and a refresh reused the same
session. The native result confirms one login, 81 decoded frames, 50 JPEGs,
encryption type 2 and zero decoder errors. Stop cleaned up that session; the
web server remains running, with the camera stopped and ready for user Start.

Details and commands: [browser-viewer prototype](docs/browser-viewer-prototype.md).

## Agreed milestone plan

Before grid work, [image proportions](docs/image-display-aspect.md) were inspected
using existing media. Live frames are 352 × 288; historical frames are 960 × 1088.
The browser now has a shared media-display module and a 16:9/4:3/Original control
for both live and recorded views, with a remembered browser preference. It fits
the whole picture without cropping. The owner confirmed 16:9 matches this
camera's Hik-Connect view; it is a confirmed display preference, not measured
stream metadata or a global rule for other cameras.
Eight Docker Chromium fixture cases and the ten offline unit tests passed.
Initial correction used saved media only. After the owner supplied a matching
Android screenshot, the service was relaunched and one brief live session
confirmed moving frames at 16:9, unchanged 352 × 288 JPEGs and zero size-style
updates during steady playback. The native report recorded one login, 84 decoded
frames, 50 JPEGs and zero errors; Stop cleaned up. Recorded playback also showed
16:9. The server remains available with the camera stopped. A versioned preference
key clears old comparison choices once; new choices remain remembered.

The first [Python SDK adapter seam](docs/sdk-adapter-seam.md) is implemented.
One concrete HCNetSDK 6.1.9.48 adapter owns credential normalization, deterministic
native build locations, launch arguments/stdin/library environment and runtime
image. The browser accepts an injected adapter; diagnostics and host launchers
use the shared selector. No plugin framework or second SDK was introduced.

Ten offline unit tests passed, including a stub adapter with different launch
settings and an untruncated password. The actual Docker SDK/decoder check also
passed with private SDK logging enabled, networking disabled, no credentials
mounted, zero login calls and zero decoder errors. The later aspect-ratio check
above also verified the adapter with one real live session;
recorder configuration, camera discovery and persistent per-stream workers were
the next milestones and are now implemented above. The 16-character policy is now assumed to belong to the SDK
implementation rather than a user-configurable installation override.

The agreed plan follows this order, with the automatic live grid ahead of motion
timeline investigation as requested:

1. Recorder configuration, camera discovery and capacity.
2. Automatic live grid.
3. Motion timeline feasibility.
4. Historical timeline viewer.
5. Reliability and transport.

Credentials remain in the backend file and frontend login is deferred for home
LAN use. Frontend files may be split by logical function: shared API/media
helpers, live overview/tiles, history/timeline/playback controls and exports.

The recorded plan is in [implementation-plan.md](docs/implementation-plan.md).
A reviewable API proposal is in [backend-api-plan.md](docs/backend-api-plan.md).
Inventory and live-session endpoints are now implemented; historical
timeline/playback/export endpoints remain proposals. Discovery and the initial
grid are verified above; the next investigation is motion metadata.

## Reproducibility and preservation

The setup guides, agreed milestone order and API proposal were committed as
`b9c7cca`. A subsequent [recorder compatibility review](docs/recorder-compatibility-review.md)
assesses readiness for other Hikvision NVRs/SDKs. It confirms `.local/` owner
configuration and recommends one small adapter with versioned SDK bundles,
explicit authentication policies and independently reported capabilities.
Current code remains a single-recorder prototype; no new NVR probes or feature
implementation were performed for the review.

The service is intended for other owners to clone and run on their own machines.
The installing user supplies the NVR IP and SDK port in backend configuration,
with credentials kept separate. The viewer and authenticated SDK runner now
read owner configuration; legacy RTSP/web investigation scripts retain the
original address. Python application logic and a persistent C++ SDK bridge
implement the current backend split.

The root [GETTING_STARTED.md](GETTING_STARTED.md) gives a short human-facing setup
overview; [GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md) contains detailed
installation and verification instructions. Both must be maintained with
architecture changes. Setup uses the SDK archive
already in Git LFS, without a separate vendor download. Only documentation was
changed to record these requirements; no recorder calls or feature code were added.

The agent guide includes a prerequisite/install/verification checklist,
with Docker explicitly required to work without sudo as the installing
user. Offline SDK checks, private-file validation, Docker TCP reachability,
HTTP readiness and live video acceptance are separate stages. Host installation
recipes are documented for missing essentials; none were executed here.

Source, investigation notes and credential tests are versioned. The complete
original SDK ZIP, including its binaries, headers, examples and vendor
documentation, is tracked with Git LFS under `vendor/hikvision/`.
Credentials, native debug logs, APK analysis and camera captures stay in the
ignored `.local/` directory. See [README](README.md) for Docker/LFS setup and
restoring the SDK.
