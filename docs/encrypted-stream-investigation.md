# Encrypted stream: verified decoding with the full verification code

Date: 10 October 2026. One live SDK login and one 20-second preview session.
The recorder's settings and credential file were not changed.

## What the documentation establishes

Hikvision's [NVR Security Guide](https://www.hikvision.com/content/dam/hikvision/en/cybersecurity/NVR%20Security%20Guide.pdf)
describes the verification code as necessary for viewing encrypted video.
The [NVR AI Series manual, section 22.2](https://assets.hikvision.com/prd/public/all/doc/m000134202/UD39054B_Network-Video-Recorder-AI-Series_User-Manual_V5.01.000_20240812.PDF)
states that the stream encryption key and Hik-Connect verification code are
synchronized. These cross-product references support the meaning of the field;
the user also confirmed that the recorder UI's Encryption Password matches
our private credentials file's `verification_code` value.

The official [EZVIZ Android EZPlayer reference](https://open.ys7.com/doc/en/android/com/videogo/openapi/EZPlayer.html#setPlayVerifyCode-java.lang.String-)
documents `setPlayVerifyCode(String verifyCode)` as supplying the password for
decoding encrypted video, including handling verification-code-needed and
verification-code-error events. This is a player/decryption credential, distinct
from the username/password used for device login.

The bundled HCNetSDK General Developer Guide provides two relevant pieces:

- Chapter 5 (printed pages 63–69): acquire data using a live-view callback,
  open the system header in PlayCtrl, and feed stream data for decoding.
- Section 12.1.42 (printed pages 208–209): `NET_DVR_SetSDKSecretKey` takes a
  16-byte client decryption key before live view. This API description alone
  does not establish how a variable-length verification code should be passed.

## Reassessing the initial 16-byte-key assumption

The goal is decoded local live video while keeping recorder encryption enabled.
Treating the verification code as an already prepared 16-byte SDK key was an
unverified assumption: our saved code is not 16 bytes, and the official player
API accepts an encryption password as a string. No guessed padding, hashing
or truncation was applied.

Two different routes were considered:

1. The SDK's documented AES-key getter and client-secret-key API, which would
   avoid guessing a raw key but depends on device support and permissions.
2. Supply the original verification string to the vendor PlayCtrl decoder,
   following the existing Hik-Connect Android player implementation.

The second route became the simplest supported choice after inspecting the
user-supplied APK offline in Docker. Actual decoded video was the verification
criterion, rather than a successful setter or preview handle alone.

## Evidence from the supplied Hik-Connect APK

Selected classes were decompiled with the existing JADX tool in a Docker
container with networking disabled. The APK was not executed.

- `classes23.dex`, `qed.e(...)`: the live-header path supplies the stream's
  encryption string as UTF-8 bytes to `Player.setSecretKey(port, 1, bytes, 128)`
  before `openStream(...)`. The playback branch uses the same arguments.
- `classes25.dex`, `org.MediaPlayer.PlayM4.Player.setSecretKey(...)`: copies all
  supplied bytes, adds a null terminator, and forwards them to its native
  `SetSecretKey` method. It does not hash or truncate the string.
- The supplied Linux SDK includes the corresponding native
  `PlayM4_SetSecretKey` export and the actual Linux ABI header at
  `QtDemo/includeCn/LinuxPlayM4.h`. The Windows-oriented `incEn/plaympeg4.h`
  should not be used to recreate Linux callback structure layouts.

Private decompiled output is under `.local/apk-auth/encryption/`. Decompiled
branch reconstruction includes warnings; the concrete calls and wrapper data
handling above are independently visible. The Android-to-Linux equivalence
was initially an inference and is now supported by the successful live test.

## Working call sequence

```text
load_credentials(): login password = first 16 characters;
                    verification_code = complete original string
NET_DVR_Init
PlayM4_GetPort
PlayM4_SetStreamOpenMode(port, STREAME_REALTIME)
PlayM4_SetSecretKey(port, 1, full_verification_code_utf8, 128)
NET_DVR_Login_V40: one synchronous login on port 8000
NET_DVR_RealPlay_V40: first analog channel, substream, private protocol, TCP
    SYSHEAD -> PlayM4_OpenStream
               register encryption and decoded-frame callbacks
               PlayM4_Play(port, 0): headless decoding
    STREAMDATA -> PlayM4_InputData
    decoded callback -> count YV12 video frames; save the first frame privately
NET_DVR_StopRealPlay
PlayM4_Stop / CloseStream / FreePort
NET_DVR_Logout / Cleanup
```

The fixed `128` key-length argument follows the APK's AES-128 call convention;
it is not the verification string's character or UTF-8 byte count. Pass the
complete null-terminated string and let PlayCtrl handle it. Our diagnostic
limits supplied strings to 128 UTF-8 bytes and rejects controls before login.
There is no blank-key fallback or second authentication attempt.

## Verified result

Offline initialization with a dummy string passed with zero login calls and
networking disabled. The existing credential boundary tests also passed.

The live session finished at **13:29:45 South Africa time / 11:29:45 UTC**:

| Observation | Result |
| --- | --- |
| `NET_DVR_Login_V40` calls | 1; succeeded, SDK error 0 |
| Live preview | Started; error 0; 20 seconds |
| Received data | 529,972 bytes in 933 callback chunks |
| System header | 40 bytes |
| Full verification string set | Yes |
| Decoder started | Yes, headless |
| Decoder API / input errors | 0 / 0 |
| Decoded video frames | 300 YV12 frames |
| Dimensions | 352 × 288 |
| Encryption callback | Video type 2 (`ENCRYPT_AES_10R_VIDEO`); audio type 0 |
| Decoder key present | 1 |
| First decoded frame saved | Yes |

The `live-stream.bin`, `system-header.bin`, and first-frame artifacts are in
`.local/hik-sdk/results/sdk-capture-20261010T112924Z-aac7ff15/`. The result report
is `.local/hik-sdk/results/sdk-probe-20261010T112945Z.json`. Camera imagery and
native debug logs stay private and untracked.

The decoded YV12 frame was converted offline to `first-frame.png`, swapping
the chroma planes to match FFmpeg's YUV420P input convention. Visual inspection
confirmed recognizable camera imagery with a readable recorder timestamp and
channel overlay, rather than merely a plausible byte count or dimensions.

To prepare without contacting the recorder:

```sh
python3 tools/run_hik_sdk.py check --decrypt
```

The exact live command used (each execution makes a new login/preview session):

```sh
python3 tools/run_hik_sdk.py probe --capture-seconds 20 --decrypt --sdk-log
```

## Implication for a web viewer

Local encrypted live video is demonstrably decodable using the vendor Linux
PlayCtrl library and the existing verification code. The current diagnostic
produces raw decoded frames; it does not yet serve browser video. The next
web milestone is a small bridge from decrypted frames to a browser-compatible
stream, with the credentials and verification code kept in the backend.
Before that, the user has prioritized
[historical recording search and playback](historical-playback-investigation.md).

This result covers one camera substream and this SDK/firmware combination.
Main streams, other cameras, audio, continuous reconnect behavior and the
eventual web transport remain untested. It does not establish that ordinary
FFmpeg RTSP input can directly decrypt the vendor stream.
