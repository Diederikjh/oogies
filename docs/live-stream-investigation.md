# Goal 1: live-video feasibility investigation

Research date: 9 October 2026. Recorder: Hikvision DS-7108HGHI-K1 at
`192.0.2.10`. Reference APK: `/home/your-user/Downloads/Hik-Connect.apk`.

## Preliminary conclusion

Live-video decoding looks highly feasible using standard interfaces. This is a
research conclusion, not a verified result from the home recorder: no device
connections or authenticated stream tests have been performed.

Hikvision classifies this model as a Turbo HD DVR. Its model-specific datasheet
lists H.264/H.264+ and H.265/H.265 Pro/H.265 Pro+ encoding. The installed FFmpeg
has standard H.264 and HEVC decoders. The actual firmware, selected codec,
encryption and enabled interfaces still need to be checked. Decoding a stream
with FFmpeg and playing it in a browser are separate milestones.

Sources: [model datasheet, firmware V4.70.160](https://www.hikvision.com/content/dam/hikvision/products/S000000001/S000000132/S000000133/S000000138/OFR009576/M000018279/Data_Sheet/Datasheet-of_DS-7108HGHI-K1_V4.70.160_20230822.pdf),
[newer model datasheet](https://assets.hikvision.com/prd/public/all/doc/m000018279/Datasheet-of_DS-7108HGHI-K1_20241212.pdf).
Published specifications do not establish the capabilities of the installed firmware.

## Options, in investigation order

| Option | Purpose | Decision |
| --- | --- | --- |
| RTSP | Obtain an individual camera's encoded live video | First choice; test with existing ffprobe and FFmpeg |
| ISAPI over HTTP | Inspect model, firmware, channel and codec configuration | Companion to RTSP; try read-only GET requests |
| ONVIF | Discover media profiles and stream URIs | Optional if the recorder exposes a media service; model support is unconfirmed |
| Hikvision device SDK | Obtain live data through the vendor interface | Fallback if standard RTSP cannot supply usable video |
| APK and phone-traffic inspection | Establish the app's actual LAN/cloud connection and playback path | Targeted fallback, guided by the failed standard-interface tests |

Hikvision documents RTSP channel IDs as `channel * 100 + stream`, where stream
1 is main and stream 2 is substream. First candidates, assuming the usual port
554, are:

```text
rtsp://192.0.2.10:554/Streaming/channels/101
rtsp://192.0.2.10:554/Streaming/channels/102
```

These URLs intentionally omit credentials; authenticated access will normally
be necessary. Channel 2 would use 201/202. An alternative path to test is
`/ISAPI/Streaming/channels/101` or `/ISAPI/Streaming/channels/102`.
The configured port and device response take precedence over examples.

Sources: [Hikvision RTSP integration guide](https://supportusa.hikvision.com/support/solutions/articles/17000131124-how-do-i-setup-rtsp-stream-),
[Hikvision integration overview](https://www.hikvision.com/content/dam/hikvision/vn/webinar/Thang3_Hikvision_Tich_Hop_He_Thong_Overview-of-3rd-Party-Integration.pdf),
[ISAPI RTSP example](https://enpinfo.hikvision.com/unzip/20201110210551_77443_doc/pdf.pdf).

## Existing tools and APK findings

- Available: Docker, adb 34.0.4, FFmpeg/ffprobe 6.1.1, curl, unzip, Java,
  Python 3, strings and readelf.
- FFmpeg's H.264, HEVC, G.711 A-law and G.711 mu-law decoders are present.
- Docker daemon access works outside the execution sandbox. An existing
  `spacewar-ghidra:12.1.2` image has Ghidra's headless analyzer configured.
- jadx, apktool, aapt/aapt2 and apkanalyzer were not found in the checked paths.
  Any additional tools will run inside Docker; nothing new will be installed
  on the host.
- The roughly 251 MB APK has 25 DEX files and native libraries for arm64-v8a
  and armeabi-v7a. Relevant entries include `libhcnetsdk.so`,
  `libPlayCtrl.so`, `libHCPlayBack.so`, `libezstreamclient.so` and
  `libezLongLink.so`.
- Library presence suggests vendor networking/playback components are bundled;
  it does not prove which path is used for this recorder. The bundled Android
  ARM libraries cannot simply be loaded in this Linux amd64 process.

## Bounded investigation plan

### 1. Establish the device's actual interface

Use a known local device account. The Hik-Connect cloud account and verification
code should not be assumed to be the recorder's local username/password.
First check HTTP 80, RTSP 554 and the commonly used vendor service port 8000,
plus any ports reported in the recorder configuration. Keep checks limited to
this recorder. Inspect HTTP/RTSP authentication challenges without guessing
passwords.

Try authenticated read-only ISAPI endpoints:

```text
GET /ISAPI/System/deviceInfo
GET /ISAPI/System/capabilities
GET /ISAPI/Streaming/channels
GET /ISAPI/Streaming/channels/101
GET /ISAPI/Streaming/channels/102
```

Endpoint availability depends on firmware. Record model suffix, firmware,
active channels, configured codec, dimensions, frame rate and stream settings.
If ISAPI is unavailable, obtain the same information from the web configuration
and RTSP session description where possible.

### 2. Prove decoding for one channel

Start with the substream, then repeat with the main stream. Use RTSP over TCP
initially to reduce UDP routing variables. Obtain codec metadata with ffprobe,
then decode 30–60 seconds with FFmpeg to a null output and extract one local
frame for visual verification. Inspect frame counts and decode errors.
A successful metadata probe or `-c copy` recording alone does not prove decoding.

Record time to first frame, observed frame rate, decoder errors and approximate
CPU usage. Keep attempts bounded by connection/read and overall timeouts.
Run a short reconnect test after the first successful decode.

Source: [FFmpeg RTSP transport and timeout options](https://ffmpeg.org/ffmpeg-protocols.html#rtsp).

### 3. Prove browser playback with an existing gateway

Run one gateway in Docker, using its supplied viewer rather than building an
application. Start with go2rtc; MediaMTX is an alternative. Pin a released image
version/digest when preparing the experiment. Keep credentials in local private
configuration and keep the test viewer restricted to the intended local access.

Prefer forwarding compatible H.264 without video re-encoding. Try WebRTC for
low latency; use HLS or MSE if the source/browser combination makes that easier.
H.265 browser support is conditional, and H.264 B-frames can prevent WebRTC
playback. If necessary, test gateway-side H.264 transcoding before considering
changes to the recorder. Defer audio; it has separate codec constraints.

Sources: [go2rtc protocols, Docker and FFmpeg integration](https://github.com/AlexxIT/go2rtc),
[MediaMTX browser playback](https://mediamtx.org/docs/read/web-browsers),
[MediaMTX WebRTC codec limitations](https://mediamtx.org/docs/features/webrtc-specific-features).

### 4. Investigate the APK only when needed

Use jadx in a container with the APK mounted read-only. Inspect manifest and
version first, then target device login, native SDK wrappers, live-preview
requests, stream selection and encryption-key handling. Avoid starting with
full native decompilation of every library. Use strings/readelf first and the
existing Ghidra container for selected native functions if required.

Hikvision documents live-preview callbacks through `NET_DVR_RealPlay_V40`;
this gives us a vendor SDK fallback to evaluate before recreating a protocol.
Check SDK platform support and compatibility with this firmware if we need it.

If static evidence is insufficient, observe a short phone live-view session.
Capture traffic on the phone or on a gateway through which its traffic passes;
an ordinary laptop on the same switched LAN will not normally see phone-to-DVR
unicast traffic. Use adb/logcat where available, with sensitive output redacted.
First establish whether the app connects directly to the recorder or through
Hik-Connect infrastructure. Encrypted traffic can still reveal destinations and
transport; it may not expose protocol contents.

Sources: [jadx](https://github.com/skylot/jadx),
[Hikvision live-preview SDK function](https://open.hikvision.com/hardware/definitions/NET_DVR_RealPlay_V40.html).

## Unknowns and completion criteria

Unknowns: firmware/hardware revision, usable local credentials, RTSP port and
enablement, active camera channels, actual codecs/profiles and stream encryption.
The working Android app proves a working viewing path, but does not establish
that it uses RTSP or stays on the LAN.

Hikvision documents a stream-encryption verification code. Its effect on the
tested interface must be checked on this firmware; neither assume all local
RTSP is encrypted nor assume cloud encryption never affects it.
Source: [Hikvision stream-encryption explanation](https://supportusa.hikvision.com/support/solutions/articles/17000128922-what-is-a-verification-code-encryption-key).

Goal 1 is demonstrated when one real camera stream yields correct decoded
frames for at least 60 seconds, its codec/transport/authentication requirements
are documented, and we can state what is required for browser viewing. A short
browser demonstration is useful supporting evidence. A full dashboard,
eight-camera capacity test, recording, playback and remote access are later work.

If tests repeatedly fail or contradict the assumed interface, stop and compare
standard RTSP, vendor SDK and app-path evidence before extending the approach,
following the supplied Strategy Reset Protocol.
