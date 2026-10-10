# Alternatives after repeated RTSP authentication rejection

Research date: 9 October 2026. No recorder requests were made during this research.

## Strategy reset

1. **Actual goal:** obtain and correctly decode one live camera stream from the
   DS-7108HGHI-K1, then establish a feasible browser-viewing path.
2. **Current approach:** standard RTSP on port 554 with the local device login;
   one later test substituted the encryption password as the login password.
3. **Evidence:** RTSP is available and advertises MD5 Digest authentication.
   Credential percent escaping round-trips correctly. However, every authenticated
   test returned 401 and a web-session attempt explicitly reported a lock. No
   media reached a decoder. The working Android app establishes a viewing path
   but does not identify its transport or whether it uses the cloud.
4. **Unverified assumptions:** current account/IP unlock status, account/channel
   permissions, firmware-specific stream-encryption behavior, acceptance of the
   saved credentials, and the Android app's actual live-view connection path.
5. **Different alternatives:** use the vendor SDK/private protocol with richer
   diagnostics; inspect the working Android app; or perform a controlled RTSP
   comparison with stream encryption temporarily disabled. ONVIF media discovery
   is a conditional additional option.
6. **Simplest viable next path:** inspect lock and live-view permissions in the
   already accessible UI, then prepare a Linux vendor SDK diagnostic in Docker.
   Do not repeat credential/port variations without new evidence.
7. **Verification:** obtain either a successful vendor login or a specific error;
   request one live-preview channel only after login succeeds; then verify correct
   decoded frames for 60 seconds. Keep authentication attempts explicitly bounded.

## 1. Check source-IP locks and channel permissions

Hikvision's hardening guide documents temporary source-IP blocking after failed
logins. Its example defaults are seven failures and 30 minutes, but that guide
uses network cameras and is not proof of this DVR's configured threshold.

A working phone session could coexist with a blocked computer. This is an
inference to investigate, not a diagnosis. Inspect the UI's login/security
settings and relevant logs. Also inspect the account's remote live-view rights
and channel access. A web login does not by itself establish live-view permission.
Menu names and available settings vary with firmware.

Sources: [Hikvision hardening guide, login management and IP filters](https://display.hikvision.com/content/dam/hikvision/eu/support/cybersecurity/Network-Security-Hardening-Guide-new-1.pdf),
[Hikvision user-management permissions](https://www.hikvision.com/content/dam/hikvision/en/cybersecurity/Network-Camera-Security-Guide.pdf).

## 2. Use the vendor SDK/private protocol

Hikvision offers a Linux 64-bit Device Network SDK. Its login and live-preview
interfaces are `NET_DVR_Login_V40` and `NET_DVR_RealPlay_V40`. Hikvision documents
8000 as the normal private-protocol device port; our scan found that port open.
That is a strong candidate, though its actual protocol has not yet been tested.

The useful difference is diagnostics: the documented SDK errors distinguish
username/password error (1), operation not authorized (2), nonexistent username
(152), locked username (153) and banned IP (1113). Not every firmware returns
every code, but this offers a more informative test than another generic RTSP 401.

Hikvision's private-protocol client configuration documents the device login
password and stream encryption key as separate fields. This supports evaluating
an interface that can handle both roles. Compatibility of the Linux SDK/playback
library with this recorder's particular encryption format still needs verification.

Prepare the SDK and a small diagnostic entirely in Docker, with credentials
mounted read-only. Configure login/reconnection behavior so rejected credentials
are not resubmitted automatically. Begin with one login and report its error;
proceed to one live-preview channel only if accepted. No host installation is needed.

Sources: [official Linux SDK download listing](https://pro-av.hikvision.com/us-en/support/download/sdk/),
[SDK login](https://open.hikvision.com/hardware/definitions/NET_DVR_Login_V40.html),
[SDK live preview](https://open.hikvision.com/hardware/definitions/NET_DVR_RealPlay_V40.html),
[SDK error reference](https://open.hikvision.com/hardware/definitions/NET_DVR_GetErrorMsg.html),
[private protocol: login and separate encryption-key configuration](https://enpinfo.hikvision.com/hkwsen/unzip/20230830144955_12918_doc/GUID-76D11646-EA40-4EDA-88DD-38821CB5826E.html).

## 3. Inspect the working Android app

The supplied APK bundles HCNetSDK, PlayCtrl and EZ streaming libraries. Use
containerized jadx to trace live-preview selection, login/native wrappers and
encryption-key handling. Establish whether this recorder uses LAN private
protocol, RTSP or cloud/P2P before investigating native implementation details.

This can begin without recorder connections. If packet observation is later
needed, capture on the phone or its traffic gateway; a normal switched-LAN
laptop will not necessarily see phone-to-recorder traffic. A cloud path is less
attractive for a home-LAN viewer but would explain why app success does not
prove acceptance of the same local RTSP credentials.

Source for the decompiler's scope: [jadx](https://github.com/skylot/jadx).
APK library findings come from our local archive inspection, not an online claim.

## 4. Controlled comparison with encryption disabled

The UI and Hikvision documentation expose a stream-encryption setting. A
temporary, explicitly authorized comparison could test whether enabling it
changes local RTSP behavior on this firmware: record the existing setting,
disable only stream encryption, make one probe using the local login, then
restore the original setting. Other devices may be affected during that window.

This is an experiment, not an established fix for our 401 responses. It should
follow the lock/permission check. It changes device configuration and has not
been performed or authorized in this research request.

Sources: [Hikvision security configuration: separate RTSP authentication and stream-encryption flags](https://open.hikvision.com/hardware/v2/%E7%BB%93%E6%9E%84%E4%BD%93/NET_DVR_SECURITY_CFG.html),
[Hikvision stream-encryption guide](https://www.hikvision.com/content/dam/hikvision/en/cybersecurity/NVR%20Security%20Guide.pdf).

## Secondary options

- **ONVIF media discovery:** if this DVR exposes an ONVIF media service, query its
  profiles and stream URI rather than guessing a URL. ONVIF support for importing
  third-party cameras does not establish that a DVR exports its own channels.
  Authentication is still needed; availability on this exact firmware is unverified.
- **Alternative ISAPI RTSP path:** Hikvision documents
  `/ISAPI/Streaming/channels/101`. We have tested `/Streaming/channels/102` with
  authentication. This is a valid later comparison, but a generic 401 does not
  identify a wrong path; the SDK documents unavailable URLs separately as 404.
- **HTTP preview/MJPEG:** documented for supported IP cameras, typically using
  the substream and MJPEG encoding. DVR support is unconfirmed and it still
  requires authenticated access, so it is not the next diagnostic.
- **go2rtc/MediaMTX:** useful once video access works. go2rtc's Hikvision `isapi`
  source is documented for backchannel audio, so it should not be treated as
  a demonstrated replacement for the DVR's video login/encryption interface.

Sources: [Hikvision ISAPI RTSP example](https://enpinfo.hikvision.com/unzip/20201110210551_77443_doc/pdf.pdf),
[HTTP MJPEG requirements](https://www.hikvision.com/content/dam/hikvision/ca/how-to-document1/network-cameras/How-to-Get-IPC-MJPEG-Stream-via-HTTP-Commands.pdf),
[go2rtc](https://github.com/AlexxIT/go2rtc).

The model's installed firmware remains unknown. General Hikvision documentation
supports these investigation routes; it does not establish their availability
or guarantee successful decoding on this exact recorder.
