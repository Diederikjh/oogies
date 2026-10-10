# Official Hikvision SDK usage references

Update, 10 October 2026: login now works, and a PlayCtrl callback pipeline
successfully decoded the encrypted substream using the full verification code.
See [encrypted-stream investigation](encrypted-stream-investigation.md) for
the verified call arguments. The research and earlier next-step advice below
record the state before that successful test.

Research date: 9 October 2026. No recorder requests or additional authentication
attempts were made during this research. Sources below are vendor documentation
and the official Linux64 SDK archive supplied by the user.

## References to keep

| Task | Official reference | What to use it for |
| --- | --- | --- |
| Initialize library paths | [NET_DVR_SetSDKInitCfg](https://open.hikvision.com/hardware/v2/%E6%8E%A5%E5%8F%A3%E5%AE%9A%E4%B9%89/NET_DVR_SetSDKInitCfg.html) | Set component, crypto and TLS library paths before initialization |
| Log in | [NET_DVR_Login_V40](https://open.hikvision.com/hardware/definitions/NET_DVR_Login_V40.html) | Synchronous versus asynchronous login and failure handling |
| Choose login protocol | [NET_DVR_USER_LOGIN_INFO](https://open.hikvision.com/hardware/structures/NET_DVR_USER_LOGIN_INFO.html) | Private protocol on service port 8000; ISAPI on HTTP/HTTPS ports |
| Configure SDK TLS | [Newer login structure reference](https://open.hikvision.com/hardware/v2/%E7%BB%93%E6%9E%84%E4%BD%93/NET_DVR_USER_LOGIN_INFO.html) | Private-protocol TLS and certificate verification fields |
| Get live video | [NET_DVR_RealPlay_V40](https://open.hikvision.com/hardware/definitions/NET_DVR_RealPlay_V40.html) | Stream callback, system header and stream-data chunks |
| Select channel and transport | [NET_DVR_PREVIEWINFO](https://open.hikvision.com/hardware/structures/NET_DVR_PREVIEWINFO.html) | Channel, main/substream, TCP and private/RTSP transport |
| Interpret errors | [NET_DVR_GetErrorMsg](https://open.hikvision.com/hardware/definitions/NET_DVR_GetErrorMsg.html) | Distinguish credentials, permissions, missing libraries and locks |
| Interpret lock fields | [NET_DVR_DEVICEINFO_V40](https://open.hikvision.com/hardware/structures/NET_DVR_DEVICEINFO_V40.html) | Remaining attempts and lock time |
| Enable diagnostics | [NET_DVR_SetLogToFile](https://open.hikvision.com/hardware/definitions/NET_DVR_SetLogToFile.html) | Error/debug/info logging to a private writable directory |
| Understand connection bounds | [NET_DVR_SetConnectTime](https://open.hikvision.com/hardware/definitions/NET_DVR_SetConnectTime.html) | Timeout; the attempts argument is documented as reserved |

The online API reference pages are primarily Chinese. The downloaded archive
contains the English **Device Network SDK (General) Developer Guide,
V6.1.7.X, 20230606** at:

`.local/hik-sdk/sdk/doc/Device Network SDK (General)_Developer Guide_V6.1.7.X_20230606.pdf`

Useful sections and printed page numbers:

- Live view and decoder examples: chapter 5, including pages 64–69.
- Initialization: section 12.1.21, page 191.
- SDK initialization configuration: section 12.1.40, pages 206–207.
- Client stream-decryption key: section 12.1.42, pages 208–209.
- SDK logs: section 12.7.7, pages 308–309.
- Login structure, including private-protocol TLS: appendix A.263, pages 597–598.

The PDF's physical page numbering includes front matter and differs from the
printed page numbering.

Vendor C++ examples are also available locally in
`.local/hik-sdk/sdk/consoleDemo/src/consoleMain.cpp` and `GetStream.cpp`, with
their Linux build file in `consoleDemo/linux64/proj/Makefile`. These have
hardcoded demonstration credentials and interactive/long-running behavior;
read them for comparison rather than running them unchanged against the device.

## Comparison with our diagnostic

The published login pattern is: initialize, zero the vendor-defined structures,
set the device address, service port, username and device login password, select
synchronous login, then call `NET_DVR_Login_V40`. On failure, read the SDK error;
on success, use its user handle for subsequent operations.

Our C++ diagnostic follows this pattern, uses port 8000 and explicitly selects
private protocol (`byLoginMode=0`). It uses the actual supplied vendor header,
so login structure layout is not hand-recreated in Python. The examples pass
the login password as text; they do not pre-hash it using the browser's
session-login SHA-256 procedure. Password percent escaping belongs to RTSP URLs,
not the SDK's password field.

Error **1** is documented as username/password error; errors **2** and **13**
indicate operation/permission rejection. Error **153** indicates a locked user,
and errors **55** and **56** identify IP/MAC binding mismatches. These distinctions
make authentication rejection the strongest documented interpretation of our
result. They cannot exclude every firmware-specific account restriction.
The new-account test returned error 1 and zero lock time, not an explicit
permission or binding error.

The research found an incorrect future error label in our wrapper: **17** is
parameter error and **23** is unsupported function. That mapping was corrected;
our observed error 1 already had the documented meaning.

## Stream acquisition and decoding are separate stages

For headless streaming, `hPlayWnd=0` disables direct window decoding/display.
`NET_DVR_RealPlay_V40` can still deliver the system header and stream data through
a callback. Our capture path follows that approach. A positive nonblocking
preview handle alone does not establish received or decoded video; byte counts,
asynchronous errors and actual decoded frames need checking.

The English guide's decoder example uses:

```text
successful device login
    -> NET_DVR_RealPlay_V40 stream callback
    -> system header: PlayM4_GetPort / SetStreamOpenMode / OpenStream
    -> stream chunks: PlayM4_InputData
    -> decoded frames
```

The package includes `libPlayCtrl.so` and its `plaympeg4.h` header. Its guide
documents `NET_DVR_SetSDKSecretKey` for setting a **16-byte client decryption
key before live view**. The playback header also declares `PlayM4_SetSecretKey`.
These are possible decryption paths, not evidence that the saved Hik-Connect
verification code can be passed directly or padded into the required key.
The verification-code-to-key mapping and exact DVR encryption format remain
unverified. The public online SDK-secret-key page could not be retrieved;
the supplied official PDF is the source for that API's details.

## Most useful next diagnostic

First establish a successful local-device login for the new account and inspect
its remote live-view/channel permissions through the already available UI.
If valid local credentials still fail through the SDK, collect SDK debug logs
with the next separately authorized bounded attempt. Enable
`NET_DVR_SetLogToFile(3, "/output/sdk-log/", TRUE)` after initialization and check
its return value. Pre-create the private directory; the supplied English guide
requires an absolute Linux path with a trailing slash. Keep logs private and
redact any credential/session material before reporting excerpts.

There are two documented alternatives, chosen according to device evidence:

1. SDK ISAPI login (`byLoginMode=1`) through the device's actual HTTP port. This
   changes the protocol path; it is not the browser's session-login API.
2. SDK over TLS (`byLoginMode=0`, `byHttps=1`) if the recorder exposes/enables that
   service. Stream encryption does not by itself prove SDK TLS is required.

The older online login reference limits `byHttps` to ISAPI, while the newer v2
reference and supplied English guide document private-protocol TLS too. Use
the supplied SDK headers and the recorder's actual configuration rather than
copying an older reference's structure layout or guessing a TLS port.

Neither alternative was probed in this research. With three attempts remaining
at the last observation, the simplest path is obtaining new credential/service
evidence before spending another attempt. Verification remains: one accepted
device login, one channel capture, then correctly decoded frames.
