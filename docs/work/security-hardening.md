# Security hardening

Updated: 19 October 2026 (Africa/Johannesburg).
Status: S1 implemented and verified locally; production release pending.
Other remediation remains planned.

## Goal and evidence

Address demonstrated application gaps and keep image/SDK dependencies current
within the accepted trusted-network, no-login design.
See the [dated security review](archive/2026-10-18-security-review.md) for image
identities, scan results, reachability caveats and isolated reproductions.

Both `0.0.1` and `0.0.2` were scanned; the release installation is pinned to
`0.0.1`. It is currently stopped while the development server runs the S1 fix.
The browser-request bypass was confirmed against fake cameras without any SDK
login. No app changes or production probes were made during the review.

## Proposed order

1. **S1, request-boundary protection — implemented and verified:** one request
   per connection, strict framing and bodyless GET/DELETE. Socket regressions,
   browser wiring, normal feature behavior and the packaged artifact pass below.
2. **S3/S7, image maintenance:** refresh the pinned base/security packages;
   rescan the exact image, retain SBOM/report identity, and define reviewed CVE
   dispositions and recurring scans. Verify SDK startup and export encoding.
3. **S2, vendor dependencies:** investigate a supported SDK with updated bundled
   OpenSSL; use a separate profile and existing compatibility checks before
   considering a deployment.
4. **S4/S5, bounded resources and retention:** add HTTP deadlines/admission and
   safe cleanup of inactive frame/output directories. Verify active playback,
   feeds, stop acknowledgements and restart cleanup with isolated fixtures.
5. **S6, native build hardening:** enable appropriate compiler/linker options,
   check the ELF and run native/media regressions.

## S1 implementation and verification

The findings were committed as `ad32a53` before S1 implementation. The initial
socket regression reproduced two responses and an unintended nested action
against the vulnerable handler. S1 now uses one request per connection, rejects
ambiguous framing and rejects GET/DELETE bodies. Frame responses retain their
long-lived streaming behavior. Keeping HTTP/1.1 with explicit connection-close
responses avoids draining rejected bodies or relying on every early return to
consume them. It trades ordinary request connection reuse for a simple boundary;
frames still share one continuous response per feed.

Eight new Python cases exercise real sockets and session state, including the
original rejection bypass, invalid/duplicate lengths, transfer encoding,
unexpected bodies, malformed JSON, pipelined requests and ordinary controls.
One browser case covers cross-origin wiring and returns to moving live frames;
it waits for the complete rejected connection before asserting no new viewer.
The full matrix stays below the browser layer.

Verification on 19 October 2026:

- All **177 backend tests** passed in 9.288 seconds.
- The focused origin regression/moving-grid browser run passed both cases.
- The complete **93 browser/native cases** passed: 89 browser, four native,
  one media generation; suite time 885.316 seconds. No retries or skips.
- All **eight HTTP security cases** also passed against the packaged backend
  with networking disabled, only the test file mounted and no recorder login.
- Local image `oogies:security-s1-local`, version `dev-s1-ad32a53-dirty`, ID
  `sha256:88c4aa7b6c4222f40ce66bb875c76028ffea262b3599bd6607ea26f0656d1672`,
  passed SDK/decoder initialization, 24 asset hashes, bundled source hashes,
  synthetic H.264 encoding, readiness and graceful stop checks, with zero logins.
- Offline Compose checks passed readiness, crash recovery, graceful stop/start
  and persistent export download with zero logins.
- Publication/history, documentation-link and diff checks passed.

The first artifact check timed out starting `ffmpeg -version` at its existing
five-second limit while the browser suite was running. After that suite finished,
the unchanged artifact/check passed in isolation. No timeout was increased and
the cause of the initial timeout was not established. Diagnostics are preserved.

Private evidence: `.local/s1-{backend.log,focused-ui.log,focused-ui-report.json,
full-ui.log,full-ui-report.json,packaged-http.log,release-build.log,
release-artifact-isolated.log,host-artifact.log}`,
`.local/s1-artifact-first-failure/` and the copied build/artifact/Compose reports
under `.local/s1-release-evidence/`.

## Next step

Publish a new fixed version from committed source and update the host deliberately.
The local test image is explicitly dirty and was
not published or deployed. Existing `0.0.1`/`0.0.2` artifacts are unchanged and
do not acquire this fix automatically.
Other findings remain open. Preserve per-finding reachability triage rather than
treating the raw scanner's Critical count as a count of exploitable app flaws.

## Development viewing, 19 October 2026

At the owner's request, stopped the idle release container and started
`tools/run_browser_viewer.py` as `cam-browser-viewer`. Its source mounts include
the S1 fix; the installed release's image pin and private state are preserved.
Development uses the checkout's separate `.local/` configuration/export storage;
its credentials and recorder settings matched the installation before switching.

Added the same IPv6 loopback mapping to the development launcher as release
Compose. Both IPv4 and IPv6 `localhost:8088` returned 200 with connection-close
headers; the mounted handler hash matches the checkout. Readiness made zero SDK
logins. Evidence: `.local/s1-debug-switch/`. The release was explicitly stopped
and the development container has no boot restart policy; this mode does not
provide the earlier release's automatic startup after reboot.
