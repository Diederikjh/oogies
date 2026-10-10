# Authentication mechanism comparison

Date: 9 October 2026. This investigation used cached recorder JavaScript,
the supplied Hik-Connect APK and the downloaded Linux SDK. No requests were
made to the recorder, and no additional account attempts were consumed.

## Findings

| Path | Password handling observed | What it establishes |
| --- | --- | --- |
| Device browser login | Iterated SHA-256 using username, salt and challenge | Browser session login differs from RTSP and the SDK API |
| Earlier Python browser-session probe | Same irreversible hash expression and iteration bounds as cached device JavaScript | No algorithm mismatch found; its locked response did not validate the password |
| APK local SDK V40 login | Copies username/password bytes into the login structure; default protocol/TLS flags are zero | This inspected local path uses the same API-level credential handling as our probe |
| APK SDK V30 Java wrapper | Encodes username as GB2312 into a 64-byte buffer; passes the password string unchanged to JNI | Encoding can matter for non-ASCII usernames, but the current credentials are ASCII |
| APK configurable SDK V40 helper | Copies raw UTF-8 credential bytes; accepts explicit protocol and TLS flags | The APK supports additional modes, but the mode used by this recorder is not known |
| APK device model | Separates login password from verification/encryption password and local from remote connection paths | Successful phone viewing does not identify which credentials or transport were used |

The current username/password are ASCII, fit the SDK's byte buffers, and contain
no colon, double quote or non-ASCII whitespace. They do not have the shape of
common hexadecimal password hashes. Prior checks also found no wrapping quotes,
surrounding whitespace or control characters. These checks did not print or
modify the credentials. They do not prove that the values are accepted by the
device.

## Browser challenge-response

Cached `.local/web-utils.js` defines `encodePwd(password, parameters,
isIrreversible)`. For the device's previously observed irreversible mode:

```text
H = SHA256(username + salt + password)
H = SHA256(H + challenge)
repeat SHA256(H) for iteration indexes 2 through iterations-1
submit H in SessionLogin.password
```

Cached `.local/web-auth.js` obtains these parameters from
`/ISAPI/Security/sessionLogin/capabilities`, then posts to
`/ISAPI/Security/sessionLogin`. It includes session ID/version and optional
session-tag fields. The earlier Python implementation in
`tools/probe_web_session.py` matches the hash sequence and iteration bounds.
That live attempt received an already-locked response, so it was inconclusive
about credential correctness. It was not repeated in this investigation.

This browser hash is specific to that session endpoint. The static comparison
does not justify supplying it as the RTSP password or SDK `sPassword` value.

## APK evidence

The APK was not executed. A standard-library DEX index narrowed SDK-login
call-site candidates; each finding below was checked against selected decompiled
classes rather than trusting raw code-unit matches. Decompilation used the
[official jadx 1.5.6 release](https://github.com/skylot/jadx/releases/tag/v1.5.6)
inside the existing Java/Ghidra container, with networking disabled, no
credential mount, one CPU, 1.5 GiB memory and a 900 MiB Java heap per container.
No tools were installed on the host.

The release archive was verified against its GitHub asset digest. SHA-256:
`545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974`.

Relevant private output under `.local/apk-auth/decompiled`:

- `LoginHelper1.java`, original class `eo8` in `classes11.dex`: local-device
  login methods `f` and `g`, calling SDK V30 and V40 respectively. Method `g`
  copies device address, username and password into arrays, sets the service
  port, writes the JNA structure and calls `NET_DVR_Login_V40`. No password
  hash or verification-code substitution appears in that method.
- `AndroidLoginInfo.java`, original class
  `hik.common.os.hcnetsdk.HCNetSDKByJNA$NET_DVR_USER_LOGIN_INFO` in
  `classes18.dex`: allocates username/password buffers; protocol, TLS and
  asynchronous-login fields retain Java zero/false defaults. No constructor
  enabling adaptive or TLS login was found.
- `LoginHelper2.java`, original class `ns9` in `classes23.dex`: V40 helper `j`
  accepts protocol/TLS byte arguments, copies raw UTF-8 credentials and sets
  `byLoginMode` and `byHttps`. It records SDK error 1 as a credential error.
- `AndroidSdkWrapper.java`, original `com.hikvision.netsdk.HCNetSDK` in
  `classes10.dex`: the V30 wrapper converts the username to GB2312 bytes and
  calls a native overload with the password string unchanged. JNI/native
  handshake internals have not been analyzed.
- `DeviceInfoEx.java`, original
  `com.hikvision.hikconnect.sdk.device.DeviceInfoEx` in `classes9.dex`: separates
  `loginName`/`loginPassword` from verification/safe-mode passwords. Local login
  is delegated to `LocalDeviceService`; its remote login code also calls V30
  with login credentials. Static code does not identify the user's active path.
- `SdkJnaInstance.java`: loads `hcnetsdk` through JNA without an additional
  authentication configuration in that wrapper.
- `SdkLoginTask.java`: another V40 call copies the supplied device password
  directly. This belongs to a network-repair task, not proof of live-view use.

Some JADX output warns about missing dependency type hierarchies because only
selected DEX files were supplied. The relevant calls and field assignments are
visible, but broader control-flow reconstruction and upstream credential loading
remain unverified. The ARM native libraries were not executed or reverse
engineered. No claim is made that every APK login path was inspected.

## Reassessed approach

1. Actual goal: explain authentication rejection before attempting video access.
2. Approach: compare a working application's static login code with the browser
   and our SDK probe, avoiding another recorder attempt.
3. Evidence for unexpected behavior: browser session login is custom, and the
   APK supports multiple connection/protocol paths. Evidence against an omitted
   application password hash: inspected local V40 helpers use raw credential
   bytes and the same default mode as our diagnostic. ASCII credentials also
   eliminate the observed GB2312/UTF-8 difference for this account.
4. Unverified assumptions: a successful local web login for the new account,
   the phone's actual LAN/cloud path, device SDK/TLS settings, and native SDK
   wire-level behavior.
5. Alternatives: establish the accepted browser login and compare its request
   shape/response; or inspect SDK logs and an accepted phone connection to
   determine protocol negotiation. Guessing additional password transformations
   lacks evidence from the inspected code.
6. Simplest next path: confirm the new account's local web login. If it succeeds
   with the saved credentials, investigate protocol negotiation using SDK debug
   logs and the recorder's actual service settings. The user was asked for that
   local-login confirmation while offline work continued.
7. Verification: establish a known accepted login and explain any difference
   before another separately authorized bounded test. Keep any request capture
   and session material private; report only redacted conclusions.

The hypothesis remains possible, especially inside firmware/native negotiation,
but this comparison found no evidence that an extra password hash belongs in
our SDK login fields. No stream decryption was attempted.

## Local login confirmed, 10 October 2026

The user confirmed that the new non-admin account successfully logs into
`http://192.0.2.10` with the same password saved in the credentials file.
This is user-observed acceptance through the local browser path; it changes
the leading hypothesis to a protocol-specific authentication/negotiation issue
rather than assuming the credentials are incorrect. It does not establish
acceptance through SDK or RTSP, or identify the firmware's rejection reason.

Reassessment: the goal is now to explain why accepted local browser credentials
are rejected by the private SDK. Alternatives are an instrumented private SDK
login or an explicit SDK ISAPI login through HTTP. The simplest next diagnostic
is adding logs to the existing private-protocol test, keeping the known port,
credentials and mode. Logs may expose negotiation details that the final SDK
error hides. Protocol changes should follow evidence from logs/service settings.

The runner now supports `--sdk-log`. It creates a new private log directory per
run, enables level-3 SDK logging after initialization, and aborts before login
if enabling logs fails. Log-directory mode is 700 and log-file mode is 600;
stdout reports only log counts and sizes, not raw contents. Native logs may
contain sensitive authentication material and remain under gitignored `.local/`.

At **12:06:15 South Africa time / 10:06:15 UTC**, this command passed:

```sh
python3 tools/run_hik_sdk.py check --sdk-log
```

The check compiled and initialized SDK 6.1.9.48, enabled logging, wrote a
250-byte SDK log, and cleaned up with **zero login calls**, networking disabled
and no credentials mounted.

Prepared live diagnostic, not executed in this turn:

```sh
python3 tools/run_hik_sdk.py probe --sdk-log --capture-seconds 60
```

It makes one `NET_DVR_Login_V40` call with the existing raw local credentials
and private protocol on port 8000, then conditionally captures one substream
if accepted. No adaptive fallback, alternative password or API-level retry is
introduced. Packet-level SDK behavior remains to be established from logs.
The previously authorized single SDK attempt was already completed, so an
additional live attempt requires a new instruction from the user. No recorder
traffic occurred during logging preparation.

## Stronger lead from subsequent cross-product research

The broader web search uncovered a password-length hypothesis. The current
saved password exceeds 16 characters, while the recorder's cached login HTML
sets `maxlength="16"`. A network-disabled browser test using a 25-character
dummy value retained exactly its first 16 characters. The earlier SDK buffer
check did not cover this UI limit.

This supersedes debug logging as the simplest next diagnostic: an explicitly
authorized single probe with the first 16 characters substituted in memory.
The real accepted password prefix remains unverified; neither the credential
file nor recorder settings were changed and no additional login was attempted.
See [cross-product authentication research](hikvision-authentication-web-research.md)
for primary references, the offline SDK security-mode check and the revised plan.
