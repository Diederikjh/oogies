# Live overview grid

Implemented and checked on 10 October 2026 after committing the image-proportion
work as `95ec310`. The current service is a live grid, replacing the one-camera
manual Start/Stop prototype.

## Behavior

Opening `http://localhost:8088/` discovers inputs and starts overview subscriptions
automatically. This recorder has nine discovered inputs: six online analog
cameras, one online IP camera (SDK channel 34), and two offline analog inputs.
Seven pictures move simultaneously; offline inputs remain labeled tiles.
Camera names are read from the recorder. Optional owner overrides can rename,
hide or change a camera's default display proportions.

Each tile has independent live/stale/offline/error/capacity state. Click its
picture to expand/collapse; the picture is a button supporting Enter and Space,
with an accessible action label and expansion state. Expansion requests a shared
high-quality main stream, retaining overview fallback; collapse releases only
that viewer's high request. A high source uses one extra recorder stream slot.
Other viewers expanding that same camera reuse it. If capacity/support/decoding
prevents upgrading, overview remains visible with explicit quality feedback and
the reason in a tooltip. Collapse and expand to retry. Expand/collapse animates the same
tile over 360 ms while preserving picture proportions; the page follows it into
view. Wheel, touch, keyboard or scrollbar input immediately cancels automatic
scrolling while the size transition finishes. Rapid toggles continue from the
current rectangle, and reduced-motion preferences use an immediate transition.
Aspect selectors are under
Settings → Picture proportions, with one saved browser preference per camera
shared by its live and recorded views. Automatic quality switching leaves the
current picture visible until the selected rendition has decoded. Camera 1's
16:9 setting matches the owner's Hik-Connect screenshot; other cameras can use
4:3 or Original. Browsers scale the original JPEGs without backend upscaling.

Pause view releases only that page's subscriptions. Another browser keeps its
sources. Closing a page attempts a best-effort DELETE; a 90-second lease renewed
every 30 seconds cleans up killed/disconnected tabs. The last subscriber leaving
stops that source's preview/decoder. The backend retains its one recorder login
until service shutdown, avoiding repeated authentication when views return.

History provides recording/motion timelines and interactive recorded playback.
Switching to it releases that page's live subscriptions, including high quality,
while other viewers continue independently.

## Backend and SDK boundaries

- [live_grid.cpp](../docker/hikvision-sdk/live_grid.cpp) owns one synchronous SDK
  login, discovery, independent per-source PlayCtrl contexts and bounded latest
  frame/JPEG buffers. Decoder callbacks identify their own context; no shared
  single-player globals are used. The existing bounded diagnostic is preserved.
- [grid_worker.py](../docker/hikvision-sdk/grid_worker.py) manages its process,
  lifecycle events and shared latest-frame caches. It never retries rejected
  authentication automatically. Startup/first-frame waits and private log sizes
  are bounded.
- [live_sessions.py](../docker/hikvision-sdk/live_sessions.py) owns per-view leases,
  idempotent creation, reference sharing, expiry and capacity admission.
- [grid_server.py](../docker/hikvision-sdk/grid_server.py) provides the HTTP API
  and media feed. SDK-specific builds/credential preparation remain in the
  [Python adapter](../tools/sdk_adapters/hcnet_61948.py).

Discovery uses device information, work state, analog enable flags, direct IP
channel configuration and picture/channel names. It does not treat the advertised
eight analog/ten digital capacity as eighteen configured cameras. The current
IP discovery handles direct-device modes 0 and 6; other acquisition modes or
larger models need verified adapter changes. Camera availability is cached for
60 seconds. While views are active, the backend refreshes expired status through
the existing native SDK login and reconciles subscriptions automatically. An
offline camera that recovers starts in all subscribed grids without reloading
the page. Concurrent viewers share one refresh; healthy streams remain shared.
The `/api/cameras` endpoint also requests a refresh when the cache has expired,
returning the current snapshot while the SDK query completes. Idle viewers make
no background recorder queries. Added/removed channels and name/configuration
changes still require service restart for full discovery.

Refreshes query work state and IP-channel status without rereading camera names
or logging in again. Unknown/failed status results preserve the previous known
state and may be queried again after a minute; they never trigger authentication
retries. Recent decoded frames take precedence over an offline status hint.

On 11 October, Storage (SDK channel 3) demonstrated this limitation: a running
viewer cached it as offline and never attempted its preview, while a fresh SDK
query reported normal signal/hardware and its encrypted substream decoded
successfully. Restarting the viewer restored Storage through the normal web
session/media API; three advancing, distinct JPEG frames were verified.
The subsequent one-minute cache expiry and automatic status refresh address
that recovery problem. Hikvision documents the signal/hardware flags in
[NET_DVR_CHANNELSTATE_V30](https://open.hikvision.com/hardware/structures/NET_DVR_CHANNELSTATE_V30.html).

## Implemented API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/cameras` | Cached configured inputs; requests availability refresh after 60 seconds through the shared recorder connection; no preview starts |
| GET | `/api/status` | Cached backend state, source/view counts, tested capacity and saved-clip metadata |
| POST | `/api/live/sessions` | Create a viewer's camera/overview selection; optional `Idempotency-Key` |
| GET | `/api/live/sessions/{id}` | Per-camera state/freshness and this view's feed descriptor |
| PATCH | `/api/live/sessions/{id}` | Replace selection, or `{}` to renew the lease |
| DELETE | `/api/live/sessions/{id}` | Idempotently release only this view |
| GET | `/media/live/{id}/frames` | One bounded, multiplexed JPEG feed for all cameras in this view |
| GET | `/recording.mp4` | Previously extracted clip with HTTP byte-range support |

`quality: "overview"` and `quality: "high"` are supported by the backend. High
requests retain an overview fallback, share a separate source with other high
viewers of that camera, and promote only after a fresh main-stream frame.
The configurable high-quality limit defaults to one; zero disables it. Limits,
unsupported streams, failed decoding or stale high frames preserve overview
with an explicit quality reason. Refused/failed requests require an explicit
selection PATCH to retry; they do not wait in an upgrade queue.
Requests beyond the configured source
budget retain working tiles and label excess cameras capacity-limited. There
are at most eight viewer leases and one feed per lease. The configured source
limit defaults to eight and can be 1-16; it is an application budget, not the
recorder's hardware limit. Hardware limits remain unknown. Individual source
errors do not stop other cameras. Refresh acquires a new document lease while
reusing existing sources; copied browser tabs do not share mutable lease IDs.

## One JPEG feed per view

Separate long-lived MJPEG requests would compete with browser per-origin HTTP
connection limits once the grid exceeds a few cameras. Instead, the existing
JPEGs are multiplexed without re-encoding into one fetch connection. API media
descriptors identify the transport as `jpeg-frames-v1`.

Each packet has a 4-byte big-endian body length, then a 2-byte JSON-header length,
the UTF-8 JSON header (`camera_id`, `quality`, `generation`, `sequence`,
`selection_revision`), then the JPEG. Each viewer receives one effective rendition
per camera. The frame version includes quality and generation, so sequence reuse
cannot hide the first upgraded frame. Native frame sizes,
packet/header lengths and outstanding buffers are bounded. Slow feed consumers
receive the newest cache state, and slow tiles skip frames rather than queuing.
Browser Blob URLs are revoked as frames are replaced.

Logical source identity is `(camera_id, quality)`. Overview cache/directory keys
remain `camera-N` for existing diagnostics, with `camera-N-high` for main streams.
Worker protocol 2 requires quality and Python-issued generation on live start/stop
commands and lifecycle events. Old generations cannot stop or promote a restarted
source. Each rendition has independent preview, decoder and bounded frame buffers.
Decoded YV12 frames accept even dimensions up to 4096 per axis and 16 MiB total;
JPEGs and feed packets retain their existing 4 MiB JPEG limit. Compressed decoder
buffers remain 4 MiB and publication stays at most ten JPEGs/second per source.
These bounds permit common 4K rasters without unbounded allocation, but are not
a claim that every configured main stream is supported or affordable.

Frontend code is separated into shared API/feed/media helpers, live overview,
camera tiles and saved-clip viewing. No host/frontend packages or build system
were added. The service remains localhost-only and credentials/configuration
are never served as assets.

## Owner configuration

The service and authenticated SDK diagnostic now use ignored
`.local/nvr-config.json`; [nvr_config.py](../tools/nvr_config.py) validates it.
Credentials remain in a separate read-only `.local/nvr-credentials.json` mount.
Example schema:

```json
{
  "host": "192.0.2.10",
  "sdk_port": 8000,
  "timezone": "Africa/Johannesburg",
  "sdk_profile": "hcnet-6.1.9.48-linux64",
  "max_live_sources": 8,
  "max_high_quality_sources": 1,
  "lease_seconds": 90,
  "camera_overrides": {
    "1": {"name": "Driveway", "aspect_ratio": "16:9"},
    "4": {"enabled": false}
  }
}
```

SDK-dependent password normalization remains in the adapter and cannot be
overridden globally here. Only the current SDK is supported. Timezone records
the device's clock context for later historical queries; live OSD is untouched.
Settings are loaded at startup, so restart after editing the file. Legacy raw
RTSP/web diagnostics now also read the private recorder configuration.

## Verification and limits

The original native worker compiled, initialized and configured the decoder in Docker
with networking disabled and zero login calls. Eighteen unit tests passed,
including independent viewer deletion, expiry while another view survives,
idempotency, capacity/failure states, feed selection, configuration validation,
delayed native stop events and broken-pipe invalidation of cached frames.

One real SDK connection discovered nine inputs. Progressive previews at 1, 2,
4 and 7 online cameras all produced decoded frames through that connection.
Chromium displayed all seven at 16:9, observed changing pixels, checked responsive
layout/expansion, and opened a second tab with seven shared sources and one SDK
login. Pausing one view preserved the other. Saved playback still worked after
releasing the last live view; no browser errors occurred.

Two brief backend resource samples with all seven sources running were about
50% of one CPU core and 154 MiB RAM, with 156 processes/threads, inside the
2-CPU/2-GiB/512-PID container limits. These are short samples, not a sustained-use
benchmark or the device's maximum capacity. Six analog substreams are 352 × 288;
the configured IP substream is 1280 × 720, and its larger raster is retained.

Private evidence is under `.local/grid-check/`: `capacity.json`,
`resources.json`, browser screenshots and `browser/grid-check.json`. The
browser reproduction tool is [check_live_grid.py](../tools/check_live_grid.py).
Older one-camera browser/aspect tools document the previous frontend and are
not the grid acceptance test. Long-running failure recovery and rediscovery of
changed configuration remain future work.

A real unrenewed lease expired after 90 seconds while a separate lease, renewed
every 25 seconds, kept its camera live. Only the abandoned source stopped; the
remaining view retained the same recorder login. Evidence: private
`.local/grid-check/lease-expiry.json`.

## High-quality backend verification — 16 October 2026

The approved plan is committed as `efc4007`; milestone 1 was reviewed and committed
as `482aa8d` before frontend work. The following figures record its backend-only
check, when expansion still requested overview. All 94 backend
tests and 73 offline browser/native tests passed; C++ compilation and SDK/decoder
initialization passed without network access or credentials. The current SDK's
bundled `incEn/HCNetSDK.h` documents `NET_DVR_PREVIEWINFO.dwStreamType` as zero
for main stream and one for substream; the native helper uses that mapping.

One bounded real check used one SDK login and at most one high-quality live source,
with the existing viewer stopped to avoid duplicating its connections. Four
inputs were reported online, and all four decoded in the measured grid. Camera 1
changed from 352×288 overview to 960×1088 main-stream JPEGs. These are native
rasters; browser picture proportions still apply. Two high viewers shared one
source; downgrading one preserved the other, and releasing the last high viewer
left overview moving. All source slots were released at final cleanup.

| Measured workload | Mean CPU (% of one core) | Peak container memory |
| --- | ---: | ---: |
| One overview | 9.3% | 50.9 MiB |
| One overview + one high | 34.3% | 78.9 MiB |
| Four overviews | 37.8% | 94.8 MiB |
| Four overviews + one high | 43.5% | 121.1 MiB |
| Four overviews + one high + historical playback | 60.8% | 149.4 MiB |

Each sample lasted eight seconds in the existing 2-CPU/2-GiB/512-PID runtime
limits. The four-overview/high sample received about 139 KiB/s of container
network traffic; high-quality JPEG cache publication was about 519 KiB/s at
8.9 FPS, with the SDK decoding around 15 FPS. First high frame arrived in about
0.25 seconds. Rates vary with scene, stream settings and workload. These samples
exercise the worker/source path, with no browser feed consumers; per-viewer
JPEG delivery adds bandwidth and browser work. Other recorder clients remain
outside these counters. The earlier seven-camera workload was not recreated
because only four inputs were reported online during this check.

Keep the high-quality cap at one. Additional concurrent main streams and sustained
load remain unverified. The existing source budget of eight accommodated the
measured six-source live/history workload. A separate export/high-quality
contention check uses the actual export job manager offline; this device check
used historical playback for coexistence rather than exporting another clip.

[check_live_quality.py](../tools/check_live_quality.py) reproduces the bounded
worker check inside the SDK Docker runtime. It expects read-only `/sdk`, `/probe`
and `/support` mounts, private configuration at `/configuration/nvr.json`, private
credentials at `/credentials/nvr.json`, and a writable private `/output` mount.
Use the viewer's standard resource limits and `PYTHONPATH=/support:/probe`.
Run `python3 /support/check_live_quality.py` explicitly; it is never part of CI.
No settings or credentials are modified. Outputs include private camera frames
and logs, so bind `/output` beneath ignored `.local/` and keep it private.
Evidence for this run is under
`.local/live-quality-check/quality-check/quality-check.json`.

## Frontend quality switching

[live-quality.js](../web/live/live-quality.js) coordinates desired qualities for
one document's lease. It serializes full selections and coalesces rapid changes
to the latest intent. Failed/refused preferences remain local until a deliberate
collapse/expand retry. Optional PATCH `retry_high` IDs prevent unrelated changes
from retrying failures the browser has not observed yet. Renewal keeps selection
unchanged. A lost reply triggers one bounded cleanup selection, releasing only
unconfirmed upgrades while preserving previously acknowledged high requests.

Frames carry quality, generation and selection revision. The coordinator rejects
obsolete revisions/leases; the tile rejects obsolete generations. Tiles decode
JPEGs offscreen before replacing the visible image and recheck intent after
decoding. Superseded loads revoke their Blob URLs and cannot replace a newer
picture. Slow tiles still skip frames instead of queuing. Existing browser picture
fitting remains responsible for aspect correction; no backend resizing or extra
encoding was added.

The quality label describes the painted image and reports Upgrading, returning
to overview or a short unavailability reason. Tooltip text retains the full
reason. Labels use polite status announcements and update only when their text
changes. The footer counts painted high-quality views. Animation, keyboard
activation, manual-scroll cancellation and reduced-motion behavior are retained.

Pause, navigation, close and lease expiry release this viewer's requests. Another
viewer of the same high source continues independently. Returning to Live or
resuming preserves expanded tiles and requests their preferred quality in the
new lease. The existing device reproduction tool now verifies expansion quality,
collapse, two high viewers sharing one source and independent release, retaining
private screenshots and source counts.

On 16 October, the real Chromium check passed with four reported online inputs.
Expansion displayed Camera 1's 960×1088 main stream at a measured 1.778 display
ratio; the expanded screenshot was visually reviewed. Two high tabs shared five
live sources (four overview plus one high) through one SDK login. Pausing/closing
one kept the other moving, and collapse returned to overview. Final live/view/
occupied-slot counts were zero with no browser errors. Evidence is private under
`.local/grid-quality-ui-check/`. The complete offline suite passed 84 cases
(80 browser and four native), and the backend suite passed 96.

## Reliability and resource checks

Milestone 3 follows the approved reliability/resource scope in
[the live-quality plan](live-quality-plan.md#milestone-3-reliability-and-resource-checks).
The shared browser feed now treats clean EOF as a disconnect. It reconnects the
existing media URL after 1, 2 and 4 seconds; 30 seconds of stable delivery resets
that consecutive-failure budget. Missing complete packets for ten seconds while
video is expected triggers recovery, including silent media stalls. Paused/ended
History and a grid with no live sources are excluded from that watchdog.
Each connection attempt still has a ten-second response-header deadline,
including while paused or offline.
HTTP 4xx ends recovery except 409, which can briefly occur while the old server
feed releases its slot. Readers, timers and backoff cancel on navigation/Pause.
Neither SDK login nor viewer/playback creation is retried automatically.
The HTTP server checks for a closed peer even when paused/offline sources send
no frames, releasing its feed slot without waiting for a write or lease expiry.
`/api/status` reports `active_media_feeds` separately from viewer leases and
native source occupancy; a live grid and History tab should have two media feeds.

Live tiles distinguish backend health from browser delivery: after five seconds
without a painted JPEG they display Video delayed and dim the retained picture;
a known disconnection shows Reconnecting. Status polling cannot turn that stale
picture back into Live. The summary counts locally fresh tiles. A new decoded
frame restores the badge. Quality preference, generation and revision guards
continue to apply through reconnection. Exhausting retries releases that viewer
and offers Resume view. History retains its independent position/rate through
media recovery; a terminal failure releases playback and asks for a time selection.

The explicit host runner
[run_live_reliability_check.py](../tools/run_live_reliability_check.py) invokes
[check_live_grid.py](../tools/check_live_grid.py) with a 180-900 second sustained
stage, using [live_reliability.py](../tools/live_reliability.py). It requires an
idle, already verified running service, one high-quality slot and sufficient
total capacity. It does not stop/restart the service or change owner settings.
It shares the service's network namespace and existing login. The restricted
browser container gets only tools and private output, without SDK/credentials.

The workload keeps the full reported online grid plus one main stream moving
while a second tab plays History. It spans multiple lease renewals, disconnects
each browser media feed independently, checks paused History, repeats three
upgrade/release cycles and checks final zero occupancy. Browser-injected
[feed faults](../tools/browser_feed_fault.js) preserve the real HTTP/SDK backend;
they do not disconnect the recorder itself or test SDK reauthentication.
This helper is not served as a frontend asset. Only check-owned session IDs are
deleted in cleanup, with lease expiry as the fallback if the browser is lost.

The host samples Docker service CPU, memory, PIDs and cumulative network counters.
It stops on >75% of the 2 GiB memory cap, >450 PIDs, >180% of one CPU core for
30 seconds, an unexpected SDK login/main source, or excess source occupancy.
Both runtime and browser retain their existing 2-CPU/2-GiB/512-PID container caps.
CPU figures are sampled snapshots; Docker network counters exclude loopback
browser traffic. The browser separately counts delivered media bytes and verifies
changing pixel hashes from the images actually painted at native dimensions. Private reports, logs and
screenshots go under `.local/live-reliability-check/`. This is a bounded workload
check, not a hardware maximum, overnight soak, or reason to increase the high cap.

### Device evidence — 16 October 2026

The final check passed 302.6 seconds of concurrent moving video: four reported
online overview sources, one shared main stream and one independent historical
playback. It recorded 58 samples across multiple 90-second lease periods. Live
and History feed interruptions recovered without another source generation,
playback generation or SDK login. Paused History remained quiet for 12 seconds,
then recovered a deliberately closed media feed. Three upgrade/release cycles
passed. Final viewer, playback, occupied-source and media-feed counts were zero;
the SDK login count stayed one, and no unexpected browser errors were reported.

The whole diagnostic took 346.5 seconds. Mean sampled service CPU was 55.0% of
one core, peak memory was 247.1 MiB and peak PIDs were 168. Idle PIDs returned
from 142 to 142; idle memory was 109.5 MiB before and 155.1 MiB after the check.
This verifies bounded source/feed cleanup; it does not assert that every SDK
allocation returns immediately or establish long-term memory behavior. Actual
browser media averaged about 1.12 MiB/s for Live and 0.44 MiB/s for History;
these are delivery rates for this footage/workload, separate from recorder traffic.
Keep the high-quality cap at one.

An initial diagnostic stopped around 115 seconds on a one-shot History-image
readiness assertion while native frames continued to be decoded/published with
no SDK error. The diagnostic now waits briefly for a decoded image, checks
pixel hashes and SDK playback frame counts independently, and captures UI state
on failure. The repeat passed without changing SDK playback or raising capacity.
Private final evidence is under
`.local/live-reliability-check/20261016-212301/`: `resource-check.json`,
`reliability-check.json`, `grid-check.json`, `browser.log` and screenshots.

## Two-main-stream capacity experiment

[run_live_capacity_check.py](../tools/run_live_capacity_check.py) explicitly
compares the same online grid with zero, one and two distinct main streams.
It temporarily reloads the private high-quality cap as two, preserving the total
source limit and all recorder settings. The original config bytes/permissions
are backed up privately and restored afterwards; the normal viewer is restarted.
Live browser tabs need Resume/refresh after this reload. Active History or
exports prevent the initial reload. Keep other viewer tabs paused during the
measurements so their delivery load does not change the workload.

The restricted Docker browser runs
[check_live_capacity.py](../tools/check_live_capacity.py) against the actual UI,
checking painted pixel hashes, native generations, effective qualities, source
counts, frame ages, upgrade failures and one SDK login throughout all phases.
The default pair is the first two online SDK channels, with an explicit
`--cameras` override. Stages include 20-second overview baselines, 45-second
single-main samples before/after, a configurable 60-600-second dual-main sample
(default 180), and 30 seconds of History alongside both mains when capacity
allows. Each measurement follows a five-second settling period.

Host monitoring tags Docker CPU/memory/PID/network samples with each stable phase,
separating service and browser costs. Container stop thresholds remain >75% of
the 2 GiB memory cap, >450 PIDs or >180% of one CPU core for 30 seconds. Host
available memory below 1 GiB or sustained memory-pressure full avg10 above 1%
also stops the check. Host CPU includes other applications. Chrome is headless
with GPU acceleration disabled, so its measured software rendering cost can
differ from a desktop browser. Docker network counters exclude loopback media;
the browser separately counts delivered JPEG/feed bytes.

Private reports, config backups and screenshots stay under
`.local/live-capacity-check/`; the browser mounts only its output subdirectory,
without SDK, credentials or the config backup. The initial diagnostic-container
creation race is covered by host monitor regressions: service statistics remain
available while Docker has not yet created, or has just removed, the browser.
The offline worker/browser seam separately verifies two admitted main streams,
two viewers sharing them, independent release and refusal of a third main until
an explicit new request. Production defaults remain one main/eight total sources.

The 16 October 2026 experiment passed with camera-1 and camera-6, each at native
960x1088. All four online overview streams remained running. Mean CPU below is
the average of Docker snapshots, as a percentage of one CPU core; memory is peak
Docker-reported container usage in MiB. Each container was capped at two cores
and 2 GiB. Short phases have only three to six host samples; the dual-main phase
has 26. This is a practical workload comparison, not an integrated CPU benchmark.

| Workload | Seconds | Backend CPU | Backend memory | Browser CPU | Browser memory |
| --- | ---: | ---: | ---: | ---: | ---: |
| Overview before | 20.3 | 35.7% | 90.6 | 70.5% | 388.6 |
| One main before | 45.8 | 38.1% | 118.7 | 67.0% | 404.8 |
| Two mains | 183.9 | 49.2% | 148.4 | 56.5% | 505.7 |
| Two mains + History | 30.9 | 58.3% | 205.1 | 58.2% | 585.7 |
| One main after | 45.9 | 43.9% | 153.5 | 64.0% | 508.2 |
| Overview after | 20.5 | 35.1% | 130.4 | 75.8% | 484.0 |

For the initial one-main versus two-main comparison, the extra main added about
11 percentage points of one CPU core, 30 MiB backend peak memory and 101 MiB
browser peak memory. Live media delivery rose from 1.195 to 1.736 MiB/s. This
delivery counter excludes History media. Both Docker containers share a network
namespace, so their Docker network counters must not be added together. Browser
CPU varies with layout, visible tiles, content and warmup: the lower dual-main
sample does not establish lower rendering cost. Memory stayed higher after
release within the same process; this short check cannot establish long-term
memory behavior.

Host CPU averaged 21-27% overall across phases, including other applications.
Available memory stayed above 4.36 GiB; peak memory-pressure full avg10 was
0.49%. Peak service/browser PID counts were 170/138. No stop threshold fired.
Live frames kept changing, generations stayed stable within each measurement,
and one SDK login served the whole workload. History's SDK frame count advanced
alongside both mains; History pixel hashes were not sampled. No upgrade failure
or unexpected restart occurred. All experiment viewers, sources, playback and
media feeds were released at completion.

The private config was restored byte-for-byte with its original permissions,
and the normal service was restarted at the original high cap of one. Two mains
look comfortable for this tested pair and duration. The recorder's internal CPU
was not measured, and this does not establish capacity for higher-resolution
cameras or overnight operation. Private evidence is in
`.local/live-capacity-check/20261016-220831/`: host `resource-check.json`,
`summary.json`, browser `browser/capacity-check.json`, screenshots and
`browser.log`. Offline test logs are `.local/two-high-backend-tests.log` and
`.local/two-high-ui-tests.log`.

## Offline display-control check

[check_display_controls.py](../tools/check_display_controls.py) injects a fake
worker into the real HTTP/session layers and exercises the actual frontend.
Synthetic JPEG/MP4 fixtures require no private footage or SDK binaries. It checks
picture-click and keyboard expansion, the settings dialog, per-camera persistence,
mobile fitting and the shared live/recorded preference. Seven checks passed with
zero SDK logins and no browser errors. This covers UI behavior; device/decoder
compatibility remains covered by the real-recorder checks above.

Run with the existing browser image:

```sh
mkdir -p .local/display-controls-check
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" --cap-drop=ALL --security-opt=no-new-privileges \
  --cpus=2 --memory=2g --pids-limit=512 --tmpfs /tmp:rw,exec,nosuid,size=256m \
  --env XDG_CONFIG_HOME=/tmp/config --env XDG_CACHE_HOME=/tmp/cache \
  --env PYTHONPATH=/support:/probe \
  --mount "type=bind,source=$PWD/tools,target=/support,readonly" \
  --mount "type=bind,source=$PWD/docker/hikvision-sdk,target=/probe,readonly" \
  --mount "type=bind,source=$PWD/web,target=/web,readonly" \
  --mount "type=bind,source=$PWD/.local/display-controls-check,target=/output" \
  cam-hik-sdk-browser:local python3 /support/check_display_controls.py
```
