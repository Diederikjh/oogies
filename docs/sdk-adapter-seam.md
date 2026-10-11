# The current Python SDK adapter seam

Implemented on 10 October 2026. This is a small extraction of existing behavior,
not a complete plugin framework or a finalized recorder interface.

## Where the code lives

- [sdk_adapters/__init__.py](../tools/sdk_adapters/__init__.py) selects the known
  implementation through `get_sdk_adapter()`.
- [hcnet_61948.py](../tools/sdk_adapters/hcnet_61948.py) implements the current
  HCNetSDK 6.1.9.48 Linux64 integration.
- [credentials.py](../tools/credentials.py) reads and validates the private file,
  preserving its full password and verification code.
- The browser session takes an `adapter` argument; the SDK runner builds and
  launches through the selected adapter. Host launchers mount the adapter
  package read-only and use its runtime image.

The current adapter owns the first-16-character login policy, known compiler
header/library locations, encryption-code validation, native arguments/stdin,
library environment and runtime image. The existing RTSP/web diagnostics reuse
its credential preparation to preserve the proven behavior on this installation;
they retain their own protocol encoding and authentication code.

The design now treats password normalization as SDK-dependent. The original
16-character result was observed with this device/SDK combination; the cause
has not been independently established across different versions. Keep the
working rule in this adapter until another implementation provides evidence.
Do not offer a global truncation override or mutate the stored credentials.

## The small boundary used today

`get_sdk_adapter()` currently returns only `HcNetSdk61948`; an unknown SDK ID
raises an error. Selecting or constructing an adapter performs no file reads,
compilation, SDK initialization or network requests.

The concrete implementation supplies:

| Member | Responsibility |
| --- | --- |
| `sdk_id`, `runtime_image` | Identify the implementation and its Docker runtime |
| `load_credentials(path=None)` | Read validated credentials and prepare its login password |
| `compile_bridge()` | Compile the bounded diagnostic bridge inside Docker |
| `compile_live_bridge()` | Compile the persistent grid worker inside Docker |
| `invocation(binary, ...)` | Return native command, private stdin, cwd and environment without launching |

Credentials are sent only through stdin; the invocation's representation hides
that field. The browser/runner retain process lifetime, timeout, output handling
and cleanup. The C++ bridge retains actual SDK calls and decoding. Native output
uses `CAM_SDK_REPORT` for bounded probes. The grid uses `GRID_EVENT` JSON
lifecycle events, text start/stop commands, a `refresh` command returning an
`availability` event through the same login, and per-camera latest-frame files; see
[the grid contract](live-grid.md).

Historical metadata extends that same worker with `query_timeline(camera_id,
begin_wall, end_wall)` on the Python side and a bounded native `timeline` command.
The current SDK's V30 recording and base motion searches live in
`history_queries.h`; `HistoryTimeline` normalizes returned intervals/timezones
for the HTTP API. The fixture worker substitutes at this operation boundary.
See [History timeline](history-timeline.md). This is a concrete extension, not a
new abstract recorder hierarchy.

The same worker now exposes `start_playback`, `control_playback` and
`stop_playback` with independent session IDs/generations. The current native
implementation owns file-mode decoder contexts; the Python manager owns leases,
UTC ranges and capacity. Seeking/resuming use a fresh generation and time-based
context rather than another login. The current pause strategy stops the native
context and retains its last frame/time. [History playback](history-playback.md)
records the verified behavior and limits a later SDK implementation must address.

There is no abstract base class, dynamic loader, speculative camera/history
interface or extra SDK implementation. The invocation arguments describe the
operations already present in the prototype. They can change when a second
implementation reveals a better boundary.

## Adding another SDK later

1. Add one concrete module under `tools/sdk_adapters/`. Use the existing
   implementation as a reference; do not inherit its password policy or assume
   identical native dependencies merely because both SDKs are from Hikvision.
2. Implement the small boundary required by existing callers. Return an
   invocation object with `command`, `stdin`, `cwd` and `env`; it need not inherit
   the current adapter or use its dataclass. Preserve the current bridge result
   and latest-frame contract, or revise the boundary deliberately with tests.
3. Add explicit selection in `get_sdk_adapter()`. Keep SDK selection consistent
   between host launcher and container worker before exposing it through user
   configuration. Do not choose a fallback SDK after authentication rejection.
4. Preserve the SDK archive in Git LFS, document its build/runtime requirements
   and run offline compile/load/decoder checks. A genuinely different ABI may
   need another C++ bridge variant or Docker image.
5. Verify the real recorder's live/history features independently and update
   both getting-started guides. Mocks establish the Python boundary, not device
   compatibility.

Owner `.local/nvr-config.json` now selects a known SDK profile and supplies the
recorder address/port. Both host launcher and container use that selection;
unknown profiles fail rather than falling back. One current profile is supplied.
Camera discovery, per-stream contexts and the persistent worker are implemented
in the live grid. A contributor needs its native event/frame contract or an
explicit corresponding Python controller change when adding a different SDK.
The boundary remains intentionally small, without a speculative plugin framework.

## Verification

Ten offline unit tests passed, including preserved raw credentials/current SDK
normalization, full encryption-code handling, unknown-SDK rejection, concurrent
Start sharing, cleanup and a stub adapter that uses different launch settings
and a password longer than 16 characters without changing the HTTP/session code.

The refactored runner also passed this real vendor-library check in Docker:

```sh
python3 tools/run_hik_sdk.py check --decrypt --historical --skip-search --sdk-log
```

Networking was disabled and credentials were not mounted. The loaded SDK was
6.1.9.48; initialization, decoder key setup and private SDK logging succeeded,
with `login_calls: 0` and `decoder_error: 0`. Live behavior was not retested during
the extraction itself. A subsequent [display-aspect check](image-display-aspect.md)
verified the real viewer/adapter with one successful live session and cleanup.

The subsequent [grid verification](live-grid.md) passed seven concurrent previews,
two views sharing one SDK login and independent lease expiry.

## Browser testing boundary

The HTTP service now has a small `create_server(worker, sessions, ...)` factory.
Offline [UI tests](ui-testing.md) inject a simulated worker while retaining the
real HTTP, leases, frame transport and frontend. The SDK-specific adapter remains
unchanged. A later fake native process could extend coverage through `GridWorker`
and the adapter invocation boundary; that is not required for the current UI suite.
