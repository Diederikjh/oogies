# Hikvision recorder and SDK compatibility review

Update: the [Python SDK adapter seam](sdk-adapter-seam.md) and
[configured live grid](live-grid.md) are now implemented. `.local/nvr-config.json`
supplies owner settings and the SDK profile; discovery handles analog and direct
IP inputs with per-source decoders. Other SDKs, non-direct IP modes and timestamp
conversion still need evidence. The review below is the earlier design snapshot,
not the current implementation status.

Reviewed: 10 October 2026. Source/documentation review only; no new recorder
requests or compatibility implementation. The preceding setup guides, milestone
plan and API proposal were committed as `b9c7cca`.

## Assessment

Python application logic with a C++ SDK worker is a suitable direction for other
Hikvision recorders. The proposed HTTP API already hides SDK handles and vendor
structures. The current one-camera prototype still requires changes before
another owner can configure it or select a different native SDK bundle.

A different NVR does not automatically mean a different SDK is needed. Verify
the selected SDK against that device's firmware and required features first.
No compatibility with a second recorder or SDK has been established here.

## Current coupling

| Area | Evidence | Required change |
| --- | --- | --- |
| Recorder address | `browser_server.py` and `run_probe.py` use `192.0.2.10:8000` directly. | Shared owner configuration, validated before login. |
| Authentication | `tools/credentials.py` always truncates the login password to 16 characters. | Explicit installation policy; never assume this behavior for every recorder. |
| Cameras | `probe.cpp` chooses the first reported analog channel, otherwise the first digital channel. | Discover configured/online cameras and normalize channel IDs. |
| Sessions | Native decoder ports, buffers, callbacks and history queues are global; Python owns one `Camera`. | Per-stream contexts for the grid and independent historical playback. |
| Protocol/encryption | Private SDK login/preview, TCP, live substream and required nonempty verification code. | Handle only documented/verified alternative modes; unencrypted viewing is not currently an implemented mode. |
| SDK selection | One extracted directory/image; native compilation uses recursive first-match header discovery. | Deterministic selection of a matched SDK/header/decoder bundle. |
| Dependencies | SDK initialization fixes component paths and loads bundled `libcrypto.so.1.1` and `libssl.so.1.1`. | Runtime dependencies and initialization paths belong to the selected bundle. |
| Historical features | V40 search returned error 11; direct time playback succeeded. | Separate recording-search, time-playback and motion-query capabilities. |
| Time | Current extraction operates in recorder wall-clock time; the proposed API uses UTC. | Explicit conversion using the configured recorder timezone. |

Evidence is in [probe.cpp](../docker/hikvision-sdk/probe.cpp),
[run_probe.py](../docker/hikvision-sdk/run_probe.py),
[browser_server.py](../docker/hikvision-sdk/browser_server.py),
[credentials.py](../tools/credentials.py),
[run_browser_viewer.py](../tools/run_browser_viewer.py) and
[run_hik_sdk.py](../tools/run_hik_sdk.py).

## Minimal extension points

### Owner settings under `.local/`

The NVR IP belongs in ignored `.local/nvr-config.json`. Credentials stay in
`.local/nvr-credentials.json`. Commit a schema/example, not the owner's settings.
The viewer and authenticated SDK runner should share loading/validation rules
and receive read-only configuration mounts.

Proposed configuration, not implemented:

```json
{
  "host": "192.0.2.10",
  "sdk_port": 8000,
  "timezone": "Africa/Johannesburg",
  "sdk_profile": "hcnet-6.1.9.48-linux64"
}
```

Retain the tested 16-character policy in the current Python SDK adapter. A
different SDK adapter owns its own normalization behavior. Validate native field
byte lengths and encoding separately; never truncate the encryption password.
Do not try alternate password policies or SDK profiles automatically after a
login failure.

### One small Hikvision adapter

Keep application-facing operations limited to what the milestones need:
connect/disconnect, camera discovery, live start/stop, recording/motion queries,
and playback start/control/stop. Channel mapping, SDK errors, key handling and
device differences stay behind this boundary. The HTTP API and frontend use
stable camera IDs, normalized timestamps and returned media URLs.

Use one HCNetSDK implementation initially. Small explicit branches for verified
differences are enough; add another adapter implementation only when a real SDK
family or device difference requires it. Dynamic plugin loading and a generic
all-vendor framework are unnecessary.

### Versioned native SDK profiles

A profile identifies the archive/checksum, exact header and component paths,
PlayCtrl bundle, initialization dependencies, bridge variant and Docker image.
Select from known repository-defined profiles rather than arbitrary commands or
first-match searches across installed SDKs. Extract each profile into its own
`.local/` directory; preserve vendor archives with Git LFS.

Compile C++ against that profile's actual headers and run one native bundle per
worker process/container. This permits different dependency requirements and
avoids loading conflicting SDK releases into one process. Replacing an SDK ZIP
alone is not a verified upgrade; its decoder, ABI, symbols and dependencies
must be checked together. Keep the previous profile available for rollback.

Start with only the currently working profile. SDK and PlayCtrl release numbers
need not match; preserve and validate their complete known bundle.

### Stable worker contract and capabilities

Version the Python-to-worker command/result protocol. Use JSON for controls and
results, with a separate bounded media path for frames. Keep native structures
and handles inside C++. At startup identify the worker protocol, selected
profile, loaded SDK build and decoder identity; reject incompatible combinations
before login. Distinguish worker API availability from recorder support.

Discover camera mappings and documented capabilities where available, then
verify behavior with bounded tests. Expose supported, unsupported and unknown
separately for live qualities, time playback, searches, motion and controls.
One unavailable historical query must not hide functioning time playback.

The bundled **Device Network SDK (General) Developer Guide**, section 12.1.4,
printed page 178, documents `NET_DVR_GetDeviceAbility`; capability types and
buffers vary by device/function. It is not a universal discovery response. The
installed headers expose `NET_DVR_GetSDKBuildVersion`, which the probe already
reports. These are evidence for the design, not additional device tests.

## Incremental delivery and verification

Milestone 1 should add owner configuration, SDK-owned credential policy,
deterministic current-profile loading and camera discovery. Verify alternate
addresses/channel mappings/password policies offline without contacting an
unintended recorder. Then confirm the original installation retains its proven
behavior with one bounded session.

Milestone 2 should replace global native state with per-stream contexts and
introduce the persistent worker contract. Check shared live sources, independent
stream cleanup and separate historical positions. Fake worker responses can
test unsupported/unknown handling without claiming physical-device support.

When another recorder/SDK is available, run offline compile/load/decoder checks
for its profile, then verify one login and visible moving frames. Test history,
searches, motion and cleanup independently. Record model, firmware, SDK/decoder
bundle and per-feature results in a compatibility matrix. Successful compilation
or a mocked adapter alone does not establish compatibility.

This provides two practical extension points: owner settings for ordinary
differences, and a replaceable native profile/adapter when the SDK differs.
