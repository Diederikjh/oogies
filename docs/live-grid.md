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
limit defaults to eight and can be 1–16; it is an application budget, not the
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
