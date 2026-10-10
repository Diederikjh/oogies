# Historical SDK extraction result

Date: 10 October 2026. The user requested a few seconds of footage from about
one hour ago. Two bounded SDK sessions were used, with one login call in each,
the same accepted login password, and no recorder configuration changes.

## Outcome

Direct time-based playback successfully extracted camera 1's recorded main
stream for **13:51:50–13:51:55 South Africa/recorder time**. The SDK clock read
was 14:51:50, so the selected start was exactly one hour earlier. The first
decoded frame visibly shows `10-10-2026 Sat 13:51:50` and recognizable driveway
imagery.

The resulting `historical-clip.mp4` is a **5-second H.264 video**, 960 × 1088,
15 fps, 75 frames, 691,937 bytes. FFprobe confirmed these properties, and
FFmpeg decoded a preview frame successfully. Audio was not extracted.

Private output:

```text
.local/hik-sdk/results/sdk-capture-20261010T125150Z-ba9aca68/historical-clip.mp4
.local/hik-sdk/results/sdk-capture-20261010T125150Z-ba9aca68/first-frame.png
.local/hik-sdk/results/sdk-probe-20261010T125156Z.json
```

The encoded video, preview, intermediate YV12 frames, compressed SDK stream,
system header and logs remain ignored by Git.

## Initial search failed; direct playback succeeded

The first session logged in successfully and read the DVR clock. It requested
a recording search for 13:49:29–13:49:34 with all recording types/streams.
`NET_DVR_FindFile_V40` returned SDK error **11**, before a playback session was
started. Hikvision defines this as unsupported/invalid request data or invalid
received data. The private log confirms failure sending the search command,
without identifying a rejected field. It is not proof of a permission issue,
missing footage or incorrect credentials.

Result: `.local/hik-sdk/results/sdk-probe-20261010T124930Z.json`.

The goal remained a short historical clip. Two alternatives were considered:
direct playback by time without search, or downloading the interval for offline
decoding. The simplest path was the SDK's documented direct time playback,
using our verified PlayCtrl pipeline. A second bounded session was explicitly
reported to the user before running. No alternate credentials or automatic
authentication retries were used.

The direct session succeeded using:

```text
NET_DVR_Login_V40
NET_DVR_GetDVRConfig(NET_DVR_GET_TIMECFG): read recorder clock
subtract one hour in recorder wall-clock time; select five seconds
NET_DVR_PlayBackByTime_V40: channel 1, main stream, null SDK window
NET_DVR_SetPlayDataCallBack_V40
NET_DVR_PlayBackControl_V40(NET_DVR_PLAYSTART)
    bounded callback queue -> PlayCtrl in STREAME_FILE mode
    full verification code -> PlayM4_SetSecretKey(port, 1, code, 128)
    decoded YV12 frames -> private raw clip
NET_DVR_StopPlayBack; decoder cleanup; logout; SDK cleanup
offline FFmpeg -> swap YV12 chroma planes -> H.264 MP4 with faststart
```

There were zero decoder errors, zero decoder-buffer waits, no queue overflow,
and no clip-write errors. Source frame timestamps ran from 0 to 4,920 ms.
Unlike the live-stream test, this historical session produced no encryption
callback indication. The full verification code was configured, but whether
it was necessary for this particular recording remains unverified.

## Reproduction and bounds

Offline compile/file-mode initialization (zero login calls):

```sh
python3 tools/run_hik_sdk.py check --historical --decrypt --skip-search
```

Exact successful command (each execution starts a new bounded SDK session):

```sh
python3 tools/run_hik_sdk.py probe --historical --decrypt --skip-search --capture-seconds 5 --sdk-log
```

`--historical` chooses one hour before the DVR's current clock, rather than a
fixed saved timestamp. `--skip-search` selects the main recorded stream directly;
it is an explicit option, not an automatic fallback. Each run uses a new private
capture directory. Extractions are limited to 1–10 seconds; playback runs for
at most 20 seconds, the callback queue to 16 MiB, and raw clip data to 512 MiB.
Docker continues to enforce 2 CPUs, 2 GiB memory and a 512-process limit.

The remaining historical issue is recording discovery: the V40 search call's
compatibility needs investigation before implementing a calendar/file list.
Direct time playback and the non-admin account's ability to retrieve this
camera's recorded footage are now verified.
