# Camera viewing investigation progress

Updated: 2026-10-10 (South Africa time).

Goal: establish whether live video from the home Hikvision DS-7108HGHI-K1
at `192.0.2.10` can be decoded for a future web viewer. The web application
is a later phase.

## Authentication finding

The recorder's web password input accepts at most 16 characters. The password
in the credentials file was longer; using its first 16 characters resolved
both RTSP and SDK authentication. This is verified for this recorder, rather
than assumed to be a universal Hikvision rule.

`tools/credentials.py::load_credentials()` now applies that limit to the login
password for all authenticated probes. It preserves the username, the complete
verification/encryption code, and the original credential file. Credentials
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

## Historical playback: documentation investigated

The installed SDK provides recording search, time/filename playback, recorded
data callbacks, playback controls and downloads. Both V40 and V50 APIs are
present in its headers and exported by the Linux library. Recorded callbacks
can feed PlayCtrl, and the APK's playback branch uses the same full encryption
string. This remains a documented approach; no historical recorder requests
or playback tests have been made yet.

Details: [historical-playback investigation](docs/historical-playback-investigation.md).

## Next: verify historical search and decoding

Investigate historical footage before the live web viewer: confirm recorder
time, search a bounded interval for camera 1, then decode a short returned
historic range using PlayCtrl in file mode. Check which streams are actually
recorded and whether the non-admin account has playback permissions.

A browser streaming bridge follows this validation. Main streams, other
cameras, audio and long-running behavior are not yet tested.

## Reproducibility and preservation

Source, investigation notes and credential tests are versioned. The complete
original SDK ZIP, including its binaries, headers, examples and vendor
documentation, is tracked with Git LFS under `vendor/hikvision/`.
Credentials, native debug logs, APK analysis and camera captures stay in the
ignored `.local/` directory. See [README](README.md) for Docker/LFS setup and
restoring the SDK.
