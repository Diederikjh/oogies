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
with an accessible action label and expansion state. Expansion keeps the overview
substream and creates no extra NVR connection. Aspect selectors are under
Settings → Picture proportions, with one saved browser preference per camera
shared by its live and recorded views. Main-stream quality switching is not implemented yet. Camera 1's
16:9 setting matches the owner's Hik-Connect screenshot; other cameras can use
4:3 or Original. Browsers scale the original JPEGs without backend upscaling.

Pause view releases only that page's subscriptions. Another browser keeps its
sources. Closing a page attempts a best-effort DELETE; a 90-second lease renewed
every 30 seconds cleans up killed/disconnected tabs. The last subscriber leaving
stops that source's preview/decoder. The backend retains its one recorder login
until service shutdown, avoiding repeated authentication when views return.

The saved historical clip remains available. Switching to it releases that
page's live subscriptions. Timeline browsing and arbitrary historical playback
remain later milestones.

## Backend and SDK boundaries

- [live_grid.cpp](../docker/hikvision-sdk/live_grid.cpp) owns one synchronous SDK
  login, discovery, independent per-channel PlayCtrl contexts and bounded latest
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
larger models need verified adapter changes. Online state is a discovery snapshot,
updated when frames arrive; continuously refreshing configuration is not yet
implemented. Restart to discover added/reconnected inputs.

## Implemented API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/cameras` | Discover/cached configured inputs through the shared recorder connection; no preview starts |
| GET | `/api/status` | Cached backend state, source/view counts, tested capacity and saved-clip metadata |
| POST | `/api/live/sessions` | Create a viewer's camera/overview selection; optional `Idempotency-Key` |
| GET | `/api/live/sessions/{id}` | Per-camera state/freshness and this view's feed descriptor |
| PATCH | `/api/live/sessions/{id}` | Replace selection, or `{}` to renew the lease |
| DELETE | `/api/live/sessions/{id}` | Idempotently release only this view |
| GET | `/media/live/{id}/frames` | One bounded, multiplexed JPEG feed for all cameras in this view |
| GET | `/recording.mp4` | Previously extracted clip with HTTP byte-range support |

Only `quality: "overview"` is supported. Requests beyond the configured source
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
the UTF-8 JSON header (`camera_id`, `sequence`), then the JPEG. Native frame sizes,
packet/header lengths and outstanding buffers are bounded. Slow feed consumers
receive the newest cache state, and slow tiles skip frames rather than queuing.
Browser Blob URLs are revoked as frames are replaced.

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

The new native worker compiled, initialized and configured the decoder in Docker
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
not the grid acceptance test. Long-running recovery, main-stream enlargement,
continuous discovery refresh and historical timelines remain future work.

A real unrenewed lease expired after 90 seconds while a separate lease, renewed
every 25 seconds, kept its camera live. Only the abandoned source stopped; the
remaining view retained the same recorder login. Evidence: private
`.local/grid-check/lease-expiry.json`.

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
