# Cross-product Hikvision authentication research

Date: 10 October 2026. Searches targeted Hikvision SDK/RTSP authentication
across device families, not the recorder model. No recorder requests or
settings changes were made. Local verification ran in Docker with networking
disabled and no real credentials mounted.

## Leading finding: the web form limits passwords to 16 characters

The broader search found an original user's report of the same symptom:
[web login succeeds but RTSP reports wrong credentials](https://www.reddit.com/r/Hikvision/comments/13ozmml/).
That user traced their failure to a 17-character password and a 16-character
limit. This is a first-hand anecdote from another device, not proof of this
recorder's firmware behavior.

Independent vendor sources support investigating the limit:

- Hikvision's [network/security capability schema](https://open.hikvision.com/hardware/v2/08%E5%8D%8F%E8%AE%AE%E9%80%8F%E4%BC%A0/%E7%BD%91%E7%BB%9C%E5%92%8C%E5%AE%89%E5%85%A8.html)
  includes `SecurityLimits/LoginPasswordLenLimit` with a 16-character maximum
  in its example. Actual device capability responses may differ.
- The supplied official English SDK General Developer Guide's
  `NET_DVR_DEVICEINFO_V40` remarks also describe a maximum length of 16.
  Its wording says “bits”; the surrounding password-length discussion uses
  that word for character counts. This text should not be treated as a universal
  constraint for all current firmware.
- Most decisively, the cached login HTML from **our recorder** has
  `<input type="password" id="password" ... maxlength="16" ...>`.

Only threshold metadata was read from the credential file: the current saved
password exceeds both 16 characters and 16 UTF-8 bytes. Its characters and exact
length were not printed. It is ASCII, so UTF-16 code units and character counts
are equivalent for this value.

A network-disabled Chromium/Selenium run loaded that actual cached HTML and
typed a 25-character **dummy** password. The field retained 16 characters,
matching the dummy string's first 16 exactly. There were zero recorder logins,
and the browser container had no access to the real credential file.

[The HTML password-input documentation](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/password#maxlength)
defines `maxlength` as the maximum user-entered length. Browser autofill or
programmatic assignment can behave differently, so this typing experiment does
not establish the exact value in the user's previously successful session.

**Inference:** the successful web login may be sending a hash of the first 16
characters, while our SDK and RTSP tools send the full saved password. That
would explain rejection without an additional password-encoding scheme. The
earlier check only established that the password fit the SDK's 64-byte buffer;
it missed the device web form's smaller input limit.

## SDK authentication has independently configurable modes

The [vendor security configuration reference](https://open.hikvision.com/hardware/v2/%E7%BB%93%E6%9E%84%E4%BD%93/NET_DVR_SECURITY_CFG.html)
documents private-protocol compatibility/security settings separately from
RTSP and web authentication and stream encryption. Its remarks describe
protocol/version requirements that can prevent login. The page has legacy
field-name inconsistencies, so the downloaded SDK header is the appropriate
ABI reference.

The supplied `HCNetSDK.h` declares the **client-side** structure
`NET_DVR_LOCAL_SECURITY` and configuration type
`NET_SDK_LOCAL_CFG_TYPE_SECURITY` (11):

| Client security value | Meaning in the vendor header |
| --- | --- |
| 0 | Compatibility mode |
| 1 | Security mode, MD5 |
| 2 | Security mode, RSA |

An offline compiled C++ getter initialized SDK 6.1.9.48 and called
`NET_DVR_GetSDKLocalCfg` for type 11. It succeeded and returned **0**. No
configuration was changed and no login API was called. Result metadata is in
`.local/hik-sdk/sdk-security-default.json`.

This reveals a setting our previous diagnostic did not inspect; it does not
show which authentication mechanism was ultimately negotiated on the wire or
establish that forcing a different mode would fix the device rejection.

Hikvision's [network security hardening guide, section 2.17](https://display.hikvision.com/content/dam/hikvision/eu/support/cybersecurity/Network-Security-Hardening-Guide-new-1.pdf)
also documents an Enhanced SDK Service over TLS and separate SDK service
settings. A [firmware release note](https://assets.hikvision.com/prd/public/all/files/202408/releasenote%5CIDPE_L_H8_V5.8.10_Release_Note.pdf)
records adding Compatible/Security authentication modes in that product family.
These show variation across firmware; they do not establish this recorder's
current settings. SDK login modes and TLS encryption should not be inferred
from the stream-encryption switch alone.

## RTSP digest compatibility is another lead, with weaker local evidence

Hikvision's hardening guide, sections 2.14–2.15, documents MD5, SHA256 and
mixed digest choices and notes possible client compatibility issues. This is
consistent with the [RTSP digest configuration reference](https://enpinfo.hikvision.com/hkwsen/unzip/20230410194813_20373_doc/GUID-14923E9F-4DA3-4FA7-AB20-9EBD72031C68.html).

The [upstream FFmpeg 6.1.1 authentication implementation](https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/libavformat/httpauth.c)
accepts MD5/MD5-sess and rejects unsupported digest algorithms. Therefore a
SHA256-only challenge can fail with that version. Our earlier custom RTSP
probe, however, observed **MD5**, making a SHA256 mismatch a lower-priority
explanation unless settings or the advertised challenge changed.

The raw RTSP probe used unencoded password text in the Digest calculation and
also failed with the earlier account, so URL percent escaping alone cannot
explain all recorded failures. Standard RTSP Digest and the browser's iterated
SHA256 session login are distinct exchanges; sharing a password does not mean
that the caller should share a pre-hashed password value.

## Strategy reset and verification plan

1. Actual goal: establish accepted protocol credentials, then decode live video.
2. Previous approach: compare SDK, RTSP and browser algorithms using full saved
   credentials, then prepare more SDK logs.
3. Evidence for a revised approach: saved password exceeds 16; the device's
   cached browser form enforces 16; an offline browser verified clipping; the
   user confirmed that the local browser login succeeds. Against treating this
   as solved: no accepted live SDK/RTSP login using the clipped value exists,
   and the user's actual form value was not observed.
4. Unverified assumptions: the live UI matches the cached form, the successful
   browser entry used ordinary typing/pasting, and the accepted password is the
   first 16 characters of the saved value.
5. Alternatives: make one explicitly authorized probe using the same first-16
   value the form accepts; or collect a redacted accepted browser request and
   SDK negotiation logs to inspect protocol-specific behavior.
6. Simplest next path: test the first-16 hypothesis before changing SDK security
   modes or creating a new password. Substitute only in memory and preserve
   the user's credential file and recorder settings.
7. Verification: one accepted RTSP/SDK login, followed by one stream capture and
   correctly decoded frames. If the clipped password is rejected, stop rather
   than trying additional lengths or hash variations.

No live prefix-password test was performed in this research turn.

Subsequently, the user authorized the proposed prefix test. At 12:46 South
Africa time on 10 October, one RTSP session passed authentication with the
first 16 characters and reached HEVC parsing. Decoding failed and no usable
capture was produced. See [the completed test results](rtsp-first16-results.md).
