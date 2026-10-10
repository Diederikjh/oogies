# Authenticated probe results

Date: 9 October 2026. Recorder: `192.0.2.10`.

## Observed results

- Credential file fields were populated. Checks found no surrounding whitespace,
  control characters, quote wrappers or masked-password placeholders. Actual
  credential values were neither printed nor included in this report.
- HTTP Digest access to `/ISAPI/System/deviceInfo` returned 401.
- FFprobe access to camera 1's substream (`102`) over RTSP/TCP returned 401
  during OPTIONS. No verification code was supplied. No stream metadata or
  video was obtained.
- The public web login page uses `/ISAPI/Security/sessionLogin/capabilities`
  and `/ISAPI/Security/sessionLogin`. Its capabilities reported 100 iterations,
  irreversible password encoding, session ID version 2 and session-tag support.
- The public `lib/utils.js` defines the password encoding used by the web UI:
  SHA-256 of username + salt + password, then SHA-256 of that result + challenge,
  followed by further SHA-256 iterations. The local session probe mirrors this
  function and the fields submitted by `isapi/webAuth.js`.
- One web-protocol login request returned HTTP 401 with `lockStatus=lock`,
  `retryLoginTime=0` and `unlockTime=1551` (approximately 26 minutes).
  This locked response cannot establish whether the submitted password was
  correct. No further authentication attempts were made after it.

## Authentication retry handling

The initial HTTP probe used Python's standard Digest handler. Inspection of
the library revealed that it can automatically retry rejected authentication.
The probe now limits this to one Digest response; the exact number of earlier
submissions and the cause/time of the account lock were not recorded. Our
attempts may have contributed to the lock. The web session probe submits one
login request and does not retry it.

## Verification code and channel password

The supplied `verification_code` has not been used: the tested protocols failed
at login before media delivery, and standard RTSP does not define a Hik-Connect
verification-code field. The user-requested test without a verification code
has been performed. Stream encryption remains untested; no encryption or other
recorder settings were changed.

Hikvision documents Channel Default Password as the password used when adding
IP cameras to a recorder. Its role differs from the Hik-Connect stream-encryption
verification code. This is vendor documentation, not inspection of this
recorder's current configuration.

Sources: [camera-management manual](https://assets.hikvision.com/prd/public/all/doc/m000000676/UD12787B_Baseline_User-Manual-of-DS-96000NI-I-Series-Network-Video-Recorder_20230303.pdf),
[verification-code explanation](https://supportusa.hikvision.com/support/solutions/articles/17000128922-what-is-a-verification-code-encryption-key).

## Next step

Allow the lock to expire, then confirm that the credentials in
`.local/nvr-credentials.json` match a successful current web login. Retry one
bounded login with those confirmed credentials; stop if it is rejected. Obtain
codec metadata and attempt a 60-second decode only after authentication works.

Tools: `tools/probe_authenticated.py` supports read-only Digest inspection,
RTSP metadata probing and bounded decoding. `tools/probe_web_session.py` uses
the web UI's session login followed by read-only inspection. Private diagnostic
results are in the git-ignored `.local/` directory. Do not commit credentials,
session material or private camera frames.

## Single RTSP probe after the waiting period

On 9 October 2026 at 20:34:33 South Africa time, the user authorized one further
probe. `tools/probe_rtsp_once.py` sent an unauthenticated DESCRIBE for channel
102 on port 554 to obtain the normal Digest challenge, then submitted exactly
one MD5 Digest authentication response using the saved local credentials.

The final response was `RTSP/1.0 401 Unauthorized`. The tool did not retry,
probe another channel or attempt to decode video. No verification code was used.
The Digest calculation uses the raw credential values directly, so credential
URL percent escaping does not affect this attempt. Its calculation was checked
offline with dummy special-character credentials before the single live probe.

This result confirms continued authentication rejection; it does not establish
whether the cause is credentials, account lock or device/account restrictions.
Video decoding and stream encryption remain untested. Before another approach
is attempted, compare a confirmed current UI login and account permissions with
the standard RTSP login requirements, or investigate the vendor session/SDK
interface. No further recorder requests were made in this turn.

## Encryption password substituted for the RTSP login password

The user subsequently confirmed that the UI's Encryption Password matches the
saved `verification_code`, then authorized exactly one probe using that value
instead of the local login password.

At 20:38:18 South Africa time on 9 October 2026, channel 102 on port 554 was
probed with the saved username and `verification_code` as the MD5 Digest
authentication password. There was one authentication submission following
the normal unauthenticated challenge. The final result was again
`RTSP/1.0 401 Unauthorized`. There were no retries or other device probes.

The credential file was unchanged; substitution occurred only in memory.
No media arrived. This tests the encryption password as a login password,
not its ability to decrypt video, and does not establish that the encryption
password is invalid. Account-lock status remains unknown.

## New non-admin account: one RTSP session and one SDK attempt

The user created a new recorder account, updated the credential file, and
authorized one RTSP view attempt followed by one SDK attempt. The file's active
username is not the default `admin` account; no alternate credential fields were
present. Credential values were not printed, modified or included in reports.

Before contacting the recorder, the container's FFmpeg 5.1.9 client was checked
against a mock RTSP server with networking disabled and dummy credentials. It
sent one unauthenticated OPTIONS request and one authenticated response, then
stopped on the second 401. This verified rejection handling without consuming
a recorder attempt. The [upstream RTSP client implementation](https://github.com/FFmpeg/FFmpeg/blob/n5.1.9/libavformat/rtsp.c)
also bounds the initial challenge exchange to two requests. Successful streaming
would include authenticated DESCRIBE, SETUP and PLAY requests within that session.

At **20:13:20 UTC / 22:13:20 South Africa time** on 9 October 2026, one
RTSP/TCP session attempted channel 102 on port 554. It was configured to decode
and save up to 60 seconds of video using that same connection. Authentication
failed at OPTIONS with **401 Unauthorized**, after 0.09 seconds. No encoded
video file or decoded frames were produced. The verification code was not used.

At **20:13:35 UTC / 22:13:35 South Africa time**, one `NET_DVR_Login_V40` call
used the new account on port 8000. It returned error **1** (username/password
rejected) after 127 ms. The SDK reported lock support, **three attempts remaining**
and **zero lock seconds**. No live-preview call or capture followed the rejected
login. The SDK API was called once; its internal packet-level login exchange was
not instrumented. No passwords were substituted and no device settings changed.

The updated username/password have no surrounding whitespace, control
characters or quote wrappers. Percent encoding round-trips correctly for both.
RTSP uses encoded URL credentials; the SDK receives the raw values through stdin.

Private reports:

- `.local/new-user-rtsp-20261009T201238Z/decode-102-554-20261009T201320Z.json`
- `.local/hik-sdk/results/sdk-probe-20261009T201335Z.json`

### Strategy reset

1. Goal: authenticate once, obtain live video and establish decoding feasibility.
2. Approach: compare one RTSP session and one SDK login using a newly created
   non-admin account to test an admin-specific restriction hypothesis.
3. Evidence for the experiment: the new account removes the default admin name
   from this test; SDK initialization and bounded RTSP rejection handling work.
   Evidence against the hypothesis: both protocols still reject authentication,
   and SDK lock information reports no active lock. No explicit permission error
   was returned.
4. Unverified assumptions: the new account can successfully log into this exact
   device's local web UI, the saved password matches that login, and remote
   live-view/channel rights are enabled. SDK error 1 does not definitively exclude
   firmware-specific account restrictions.
5. Alternatives: verify the new account through the known local web-admin path
   and inspect its remote live-view permissions; or trace the browser's accepted
   login locally/offline to identify credential handling differences before any
   further recorder authentication.
6. Simplest next path: establish a successful local-device web login for the new
   account and inspect its account/channel permissions. Stop automated attempts
   with only three reported attempts remaining.
7. Verification: new evidence of accepted device credentials before another
   bounded login; after successful login, verify a live stream and decoded frames.

The results do not support an admin-only remote-access restriction. They also
do not yet prove an encryption incompatibility: no media reached a decoder.

## Accepted RTSP login with the first 16 password characters

On 10 October 2026, the user authorized the password-prefix hypothesis test.
One RTSP session with the new account and the first 16 password characters
passed authentication and reached HEVC parsing. FFmpeg could not recover valid
codec parameters or decode video, and the attempted capture remained empty.
The credential file was unchanged, no SDK login was attempted, and the
encryption code was not applied. See [test results](rtsp-first16-results.md).
