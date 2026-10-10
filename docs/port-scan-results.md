# Focused recorder port scan

Date: 9 October 2026, 20:20 South Africa time.
Host: `192.0.2.10`.

A TCP connect scan checked nine usual service ports. Four checks ran at most
concurrently, with a three-second connection timeout. No application requests,
credentials or authentication attempts were sent.

| TCP port | Result |
| --- | --- |
| 80 | Open |
| 443 | Closed; connection refused |
| 554 | Open |
| 8000 | Open |
| 8001 | Closed; connection refused |
| 8080 | Closed; connection refused |
| 8443 | Closed; connection refused |
| 8554 | Closed; connection refused |
| 10554 | Closed; connection refused |

Port 10554, mentioned in the RTSP article, is not listening on this recorder.
The previously observed RTSP service is on port 554. This scan covers the
listed ports, not all TCP ports, and does not check whether an account is locked.

The scheduled authentication pause still ends at 20:32:38 South Africa time.
The port-10554 stream test has no listening service to use. Check actual
credential URL encoding after the pause; do not automatically repeat the failed
port-554 login.

## Credential URL check after the pause

At 20:32:55 South Africa time, after the full 25-minute pause, the actual saved
credentials were checked locally without displaying either raw or encoded
values. The username requires no percent escaping. The password requires
escaping and is encoded with `urllib.parse.quote(..., safe="")`.

Both encoded components decode exactly to their original file values. Parsing
the resulting RTSP URL preserves the intended host, port and stream path, with
no accidental query or fragment. Neither input contains whitespace/control
characters or percent-escape patterns suggesting a pre-encoded value.
The URL contains no verification code.

No network requests or login attempts were made by the encoding check. No
authentication attempts were made during this turn. Port 10554 was found
closed, and port 554 was not automatically retried. The encoding checks do not
prove that the credentials are accepted or that the account lock has expired.

Reproduce the focused connection scan with `python3 tools/scan_recorder_ports.py`.
Detailed timestamped results are stored privately under `.local/`.
