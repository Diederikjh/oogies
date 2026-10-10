# Historical recording search and playback with HCNetSDK

Research date: 10 October 2026. Documentation and offline SDK inspection only;
no recorder login, recording search, playback or download was performed.
Historical playback is the next investigation before building a web viewer.

## Finding

HCNetSDK provides remote access to video recordings stored on the recorder:
search recordings, play a channel/time interval or a named recording, control
playback, receive compressed data callbacks, and download clips. A backend can
use these APIs without displaying an SDK window. The existing PlayCtrl decoder
and full verification code are a promising reuse path, but historical video
has not yet been tested on this recorder.

The supplied HCNetSDK 6.1.9.48 header declares both V40 and V50 search and
time-playback APIs. Offline inspection of `lib/libhcnetsdk.so` confirmed their
exported symbols, including the callback, playback-control, download and
cleanup APIs. This verifies local library availability, not every feature's
support in the recorder firmware or the current account's permissions.

## Available operations

| Operation | SDK interface | Useful behavior |
| --- | --- | --- |
| Find recordings | `NET_DVR_FindFile_V40` / `V50` | Channel, time interval, recording type and stream filters |
| Enumerate results | `NET_DVR_FindNextFile_V40` / `V50` | Filenames, start/end times, sizes, recording types and stream identifiers |
| Finish searching | `NET_DVR_FindClose_V30` | Release the search handle |
| Recording calendar | `NET_DVR_GetDeviceConfig`, command `NET_DVR_GET_MONTHLY_RECORD_DISTRIBUTION` (6164) | Days with recordings; firmware support needs checking |
| Play a time interval | `NET_DVR_PlayBackByTime_V40` / `V50` | Select channel and start/end time; spans recordings in that interval |
| Play a named recording | `NET_DVR_PlayBackByName` | Use the exact filename returned by a search |
| Receive recorded stream data | `NET_DVR_SetPlayDataCallBack_V40` | System header and compressed stream chunks for our decoder |
| Playback controls | `NET_DVR_PlayBackControl_V40` | Start, pause, resume, speed, frame stepping, time seeking and supported direction controls |
| Playback clock | `NET_DVR_GetPlayBackOsdTime` | Recorder playback time for a future timeline |
| Stop playback | `NET_DVR_StopPlayBack` | Release the playback session |
| Download an interval | `NET_DVR_GetFileByTime_V40` | Save a selected channel/time range to a private local file |
| Download a recording | `NET_DVR_GetFileByName` | Save a recording identified by its search result filename |
| Stop downloading | `NET_DVR_StopGetFile` | Release a download handle |

The bundled English General Developer Guide covers playback in section 5.5
(printed pages 80–83), downloading in section 8.4 (129–133), search in section
8.6.1 (139–143), and playback APIs in section 12.3 (233–243). Its examples and
prose sometimes use different API generations; implementation should use the
actual package headers for structure layout and pair each search API with its
matching result API.

Official online references:
[recording search](https://open.hikvision.com/hardware/definitions/NET_DVR_FindFile_V40.html),
[search conditions](https://open.hikvision.com/hardware/structures/NET_DVR_FILECOND_V40.html),
[search results](https://open.hikvision.com/hardware/structures/NET_DVR_FINDDATA_V40.html),
[time playback](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackByTime_V40.html),
[recorded-data callback](https://open.hikvision.com/hardware/definitions/NET_DVR_SetPlayDataCallBack_V40.html),
[controls](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackControl_V40.html),
[file download](https://open.hikvision.com/hardware/definitions/NET_DVR_GetFileByName.html).

## Search before assuming that footage exists

A V40 search supplies `NET_DVR_FILECOND_V40`. For the first diagnostic, use
channel 1, all recording types (`dwFileType=0xff`), both locked/unlocked files
(`dwIsLocked=0xff`), normal search (`byQuickSearch=0`), and all recorded streams
(`byStreamType=0xff`). Use a bounded time interval rather than scanning the
whole disk. Normal search returns filenames; quick calendar search omits some
details needed for filename-based playback.

`NET_DVR_FindNextFile_V40` has distinct result statuses:

| Status | Meaning | Diagnostic action |
| --- | --- | --- |
| 1000 (`NET_DVR_FILE_SUCCESS`) | One recording returned | Save metadata and continue within bounds |
| 1001 (`NET_DVR_FILE_NOFIND`) | Nothing found | Stop; do not interpret this as bad credentials |
| 1002 (`NET_DVR_ISFINDING`) | Search still running | Wait briefly before polling again |
| 1003 (`NET_DVR_NOMOREFILE`) | Enumeration ended | Close the handle |
| 1004 (`NET_DVR_FILE_EXCEPTION`) or -1 | Failure | Report status/error and close the handle |

The vendor reference limits a V40 query to 4,000 results. A future timeline
should query manageable intervals; the first probe should impose a much lower
result cap and a deadline, with no busy-wait loop. Metadata must remain private
alongside the captures.

The live substream we decoded is not evidence that a substream is recorded.
Read each search result's stream type and use an available recorded stream.
Recordings may therefore have a larger frame size and decoding cost than the
352 × 288 live substream.

## Playback data can feed the existing decoder

`NET_DVR_PlayBackByTime_V40` selects an interval using `NET_DVR_VOD_PARA`.
Set structure sizes, the channel, start/end times and a null window handle.
The SDK then receives stream data without its own display/decoding window.
Register `NET_DVR_SetPlayDataCallBack_V40` before issuing `NET_DVR_PLAYSTART`.
Creating a playback handle alone does not start playback.

The callback returns a system header first (documented as 40 bytes), followed
by compressed data. Its `SYSHEAD` and `STREAMDATA` types match the live-view
callback, so the PlayCtrl pipeline can be shared while acquisition remains a
separate playback operation.

The supplied Hik-Connect APK's recorded-playback branch uses
`setStreamOpenMode(port, 1)` (file mode) and the same full UTF-8 string with
`setSecretKey(port, 1, bytes, 128)` before opening the header. This supports
using `STREAME_FILE` and the existing native `PlayM4_SetSecretKey` call for
recorded footage. It is strong implementation evidence, not yet a historical
decode result on our DVR. See [encrypted-stream investigation](encrypted-stream-investigation.md).

Keep callbacks short: copy into a bounded queue and feed the decoder from a
worker when implementing historical playback. File-mode streams can arrive
in bursts, so the live probe's simple input handling is not sufficient evidence
for sustained playback, speed changes or seeks. A seek must also clear or
reinitialize decoder buffers so old frames do not appear at the new position.
Do not issue blocking HCNetSDK requests inside the data callback.

## Timeline and control details

The SDK has pause/resume, faster/slower playback, normal speed, frame stepping
and absolute-time seek commands. The online reference documents speed changes
as doubling/halving, subject to device, network and decoder limits. These are
SDK capabilities to verify on the DVR, not guaranteed UI features.

For playback by time, do not implement a seek bar using percentage progress:
the documented progress values are only 0 (running), 100 (finished) and 200
(error). Use absolute-time positioning (`NET_DVR_PLAYSETTIME`, or the
timezone-aware V50 variant) and recorder playback timestamps instead.
Percentage positioning is documented for playback by filename.

Reverse-playback APIs exist, but the vendor's
[Linux reverse-playback notes](https://open.hikvision.com/hardware/definitions/NET_DVR_PlayBackReverseByTime_V40.html)
say SDK decoding/display is unsupported for that path. Any reverse playback
with our separate decoder needs its own verification; defer it initially.

Search V40 and playback V40 time structures have no timezone field. Treat their
times in the recorder's clock convention and verify the clock/offset first.
The previous decoded frame's overlay showed about 11:29 while the client was
at 13:29 South Africa time. That observation suggests a two-hour difference;
it does not establish the DVR timezone configuration.

The package's V50 search supports `byLocalOrUTC`, and V50 playback has ISO8601
and UTC-offset fields. These provide an explicit time representation if the
recorder supports that route. Do not silently mix PC local time, UTC and
recorder wall-clock timestamps.

## Downloads, containers and later web delivery

Downloading by time or filename requires `NET_DVR_PLAYSTART`, then cleanup
with `NET_DVR_StopGetFile`. This is a useful alternative to an interactive
player: get a bounded clip and examine it offline.

`NET_DVR_SET_TRANS_TYPE` can request PS, TS or RTP containers; the documentation
restricts MP4/3GPP to filename-based playback/download. Container conversion
does not establish codec conversion, decryption or browser compatibility.
Verify exported bytes rather than relying on a filename extension.

The V50 playback structure also documents a `byHls` option. Its presence in the
SDK is not proof of an exposed, usable HLS stream on this DVR. It is a later
capability lead, not the initial playback path.

Keep the working private-protocol login on port 8000. The guide documents
limitations for ISAPI login, including filename playback and some search and
control features, so changing login protocols adds no benefit to the first
historical probe.

## Recommended next experiment

Two viable approaches are (a) callback playback into the already working
PlayCtrl decoder and (b) download a small interval for offline decoding. Choose
(a) first because it reuses the verified decryption path and directly tests the
functions needed by a historical viewer.

1. Add an explicit historical-search diagnostic using the actual vendor headers
   in the existing bounded Docker runner. Validate compilation offline.
2. Make one SDK login. Read the DVR clock and search channel 1 over one recent
   day in recorder time, with all recording types/streams and capped results.
   Report filenames, intervals and stream types; close the search handle.
3. Select a returned interval. On a subsequent bounded playback test, use one
   login, the available recorded stream, and a 30–60-second historic range.
   Register the callback before starting and run for at most 20 seconds.
4. Apply the full verification code in file mode. Count decoded frames, confirm
   dimensions, save one frame privately, and verify that its timestamp and
   imagery belong to the requested earlier interval. Stop, close and log out.

No fallback password, repeated login, recording-setting change, full-disk
download or web player is needed for that first validation. Remote playback
permissions for the non-admin account, footage availability, recording stream
type and firmware support remain unverified. A successful login/live preview
does not by itself prove permission to search or play recordings.
