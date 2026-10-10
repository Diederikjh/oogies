# Vendor SDK experiment in Docker

Status on 10 October 2026: SDK **6.1.9.48 login succeeds** using the shared
credential loader's first-16-character login password. The user-supplied archive
and Docker environment are validated. This latest attempt requested login only;
SDK video acquisition and decryption have not yet been tested.

Earlier full-password tests with the original and new non-admin accounts
returned SDK error 1. The new-account test reported three attempts remaining
and zero lock time, and its paired RTSP attempt returned 401. The subsequent
RTSP password-prefix test accepted the first 16 characters. See
`docs/authenticated-probe-results.md` for that history.

## Built environment

- `cam-hik-sdk-runtime:local`: compiler, Python, FFmpeg and runtime dependencies.
- `cam-hik-sdk-browser:local`: temporary Chromium/Selenium download environment.
- Base: pinned Debian Bookworm image in `docker/hikvision-sdk/Dockerfile`.
- Build logs: `.local/hik-sdk/runtime-build.log` and `browser-build.log`.

All additional packages are confined to Docker. No host packages were installed.
The browser runs with a 1.5 GiB memory limit and two CPUs. The SDK runner has a
2 GiB memory limit, two CPUs, no additional swap allowance, a read-only root,
dropped capabilities, and a bounded temporary filesystem.

## Archive download and validation

The [official Linux64 SDK page](https://www.hikvision.com/en/support/tools/hitools/clf4633a00e385d6ea/)
loads in the browser container and lists V6.1.9.48, 64.12 MB. Its download link is
`EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip` on `assets.hikvision.com`.
Direct HTTP retrieval returns 403 and browser navigation to the asset shows
“Access Restricted.” The automated page-button flow did not produce an archive.
The exact cause has not been established. The user downloaded the archive in a
desktop browser and supplied `/home/your-user/Downloads/EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip`.

The supplied ZIP is 67,235,848 bytes. All entries passed CRC verification; the
412 entries contain 102,942,051 uncompressed bytes. Paths were checked before
extraction, with no absolute paths, parent traversal or symlinks accepted.
It was extracted into `.local/hik-sdk/sdk`.

Recorded SHA-256 (a local fingerprint, not a comparison with a vendor checksum):
`8de553fb2e8dbb0ac441ee1bd73c5ecb73d720c1359396750479a6e169abf93f`.

Strategy reset: the goal remains testing one live stream via the vendor SDK.
The container build is complete, but repeated automated download attempts have
not advanced that goal. The unverified assumption is that the vendor's current
download flow permits this automated browser. Alternatives were a normal desktop
browser download or locating another official vendor distribution. The desktop
download was chosen and completed; the supplied ZIP contents and local SHA-256
were checked before extraction under `.local/hik-sdk/sdk`.

The old local iVMS-4200 library is 32-bit and lacks the intended login API. It is
not being substituted for the current Linux64 SDK.

## Offline validation, then one recorder attempt

The SDK root must expose `lib/libhcnetsdk.so` and `HCNetSDK.h` (normally `incEn`).
After inspecting and extracting the official archive:

```sh
python3 tools/run_hik_sdk.py check
```

This compiles inside Docker, loads and initializes the SDK, reports the SDK
version, and cleans up. It runs with `--network none` and without credentials.
Only proceed when this check succeeds.

Optional `--sdk-log` enables vendor debug logging in a separate private directory
for that run. It can also be validated with `check --sdk-log` while networking
is disabled. Logging failure aborts before login. Raw logs are never included
in the printed report.

```sh
python3 tools/run_hik_sdk.py probe --capture-seconds 60
```

The live mode reads the existing credential file through a read-only mount.
It calls `NET_DVR_Login_V40` once against `192.0.2.10:8000`, using the local
username and login password. It does not substitute the encryption password or
retry another credential. One SDK API call does not establish the vendor
library's exact packet-level authentication behavior.

If login fails, stop and report its SDK error and any returned lock information.
If it succeeds, request the first channel's substream over the private TCP
protocol, collect up to 60 seconds, stop preview, log out, and clean up. No
device settings are changed. The launcher removes the container on its overall
timeout rather than leaving it running.

Reports and captured video stay under `.local/hik-sdk/results`, whose directory
permissions are private. Credentials and encoded credentials are excluded from
reports. The SDK archive, extracted libraries, browser data and captures are
gitignored through `.local/`.

A successful login or byte capture alone does not prove decoding. The next
verification is decoding the capture offline into correctly rendered frames.
The stream encryption key in `verification_code` has not yet been applied by
this diagnostic. The downloaded package includes `libPlayCtrl.so` and a
`PlayM4_SetSecretKey` declaration. Its General Developer Guide also documents
`NET_DVR_SetSDKSecretKey` as a client stream-decryption API requiring a 16-byte
key before live view. This establishes available decryption interfaces, but
does not establish how this recorder's verification code maps to their keys.

## Completed offline check

The first compilation exposed an incorrect SDK-path structure name in the
diagnostic; it was corrected to the header's `NET_DVR_LOCAL_SDK_PATH`.
The next run returned SDK initialization error 41 (resource allocation failed).
A credential-free diagnostic showed that the container's `pids.events` limit
counter had incremented while memory counters showed no exhaustion or OOM.
SDK initialization creates more threads than the original limit of 128 allowed.

Initialization alternatives were to trace SDK resource failures or adjust the
specific resource limit identified by the counters. The simpler viable choice
was raising the process/thread limit to 512 while retaining the 2 GiB memory
and two-CPU limits. Explicit paths to the bundled OpenSSL 1.1 libraries were
also configured per the supplied developer guide. A network-disabled repeat
then initialized and cleaned up successfully, reporting SDK **6.1.9.48** and
zero login calls at **20:03:05 UTC / 22:03:05 South Africa time**.

## Single recorder login result

At **20:03:30 UTC / 22:03:30 South Africa time**, the diagnostic made one
`NET_DVR_Login_V40` call to `192.0.2.10:8000`, using the saved local username
and login password without URL encoding or shell interpolation.

- Login rejected after 125 ms: SDK error **1**, username/password error.
- Lock reporting supported: **six attempts remaining**, **zero lock seconds**.
- No preview call, capture, alternative password or authentication retry.
- No device settings changed; the encryption password was not used.

Private result: `.local/hik-sdk/results/sdk-probe-20261009T200330Z.json`.
The exact recorder protocol response is SDK evidence; it does not prove which
credential is wrong. This result is separate from the earlier account lock and
from stream encryption, because authentication failed before media access.

## Strategy reset after authentication rejection

1. Goal: obtain and decode one live camera stream.
2. Approach: validated vendor SDK, private port 8000, one saved-credential login.
3. Evidence for: the current Linux SDK initializes; the recorder returns an
   authentication result and lock information. Evidence against: saved credentials
   have now been rejected through RTSP, web-session login and the private SDK.
4. Unverified assumptions: the saved credentials exactly match the currently
   accepted local-device account, and the working Android app uses that same
   account rather than a Hik-Connect cloud session.
5. Alternatives: reconcile the saved credential file with a known successful
   local web-admin login; or inspect the APK's working LAN/cloud connection path
   offline to establish which credentials and protocol it actually uses.
6. Simplest next path: establish accepted local-device credentials using the
   existing successful browser login before any further recorder probes.
7. Verification: only after new credential evidence, one accepted SDK login,
   then one stream capture and offline frame decoding. Do not spend remaining
   attempts on repeated protocol or password variations.

## Shared credential loader and successful SDK login

On 10 October, the user requested centralizing the password rule and then
trying the SDK login. `tools/credentials.py::load_credentials` now reads the
file, limits only the login password to 16 characters, and supplies credentials
to all authenticated probes and the SDK wrapper. The username and encryption
code remain intact, and a before/after integrity check confirmed the file was
unchanged. See `docs/credential-loading.md` for the helper and its consumers.

The credential regression checks passed, covering boundary lengths, unchanged
encryption key/source file and rejection of invalid login input. A Docker SDK
check also passed without networking or credentials after importing the shared
module through its read-only mount.

At **12:54:51 South Africa time / 10:54:51 UTC**, exactly one
`NET_DVR_Login_V40` call to port 8000 succeeded after **129 ms**, reporting SDK
error **0**. The SDK reported eight analog channels starting at 1, and ten
digital channels starting at 33. These are SDK-reported channel fields, not a
count of configured online cameras. Main/substream protocol fields were both 2.

Debug logging was enabled and wrote one private 1,594-byte log. No preview,
video capture or encryption-key call was made. The program logged out and
cleaned up; there was no second authentication attempt.

Private result: `.local/hik-sdk/results/sdk-probe-20261010T105451Z.json`.
The password-length discrepancy explains the tested SDK authentication failure
as well as the RTSP failure. Correctly decoded encrypted video remains the next
verification milestone.
