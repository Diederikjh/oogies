# Unauthenticated recorder probe

Date: 9 October 2026. Host: `192.0.2.10`.

Read-only TCP, HTTP and RTSP probes were performed without credentials.
No settings were changed and no video was obtained.

| Check | Observed result |
| --- | --- |
| TCP 80 | Reachable |
| TCP 443 | Connection refused |
| TCP 554 | Reachable |
| TCP 8000 | Reachable; service protocol not tested |
| HTTP GET `/` | 200; page redirects to web login |
| HTTP GET `/ISAPI/System/deviceInfo` | 401; Digest authentication, MD5, qop auth |
| HTTP GET `/ISAPI/Streaming/channels` | 401; Digest authentication, MD5, qop auth |
| RTSP OPTIONS `/` | 404; root URI not accepted for this request |
| RTSP DESCRIBE `/Streaming/channels/102` | 401; Digest authentication, MD5 |
| RTSP DESCRIBE `/Streaming/channels/101` | 401; Digest authentication, MD5 |

## Interpretation

RTSP is listening and responds to standard RTSP requests. The tested stream
URIs require authentication before exposing session descriptions. These 401
responses do not prove that the URIs identify active channels, nor do they
establish whether the media payload is encrypted.

The user confirms that stream encryption is enabled. Its effect on local RTSP
remains untested. Login authentication and stream encryption must be evaluated
separately: first authenticate using the local recorder account, then inspect
the session description and attempt a bounded video decode. If encrypted media
is returned, the Hik-Connect verification code may be needed through a supported
vendor playback path; it should not be assumed to be the RTSP login password.

## Next input

The local recorder username and password are needed for the authenticated test.
A git-ignored template is available at `.local/nvr-credentials.json`. Its fields
are initially empty. The optional `verification_code` field is for the separate
stream-encryption key if needed. Do not add credentials to this report.

Reproduce the credential-free protocol checks with:

```sh
python3 tools/probe_unauthenticated.py
```

The execution sandbox blocks LAN sockets, so this session required the tool's
network permission adjustment. The checks succeeded after that adjustment.
