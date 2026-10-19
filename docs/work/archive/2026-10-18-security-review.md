# Security review: release images and application

Reviewed: 18 October 2026 (Africa/Johannesburg).
Status: initial review complete; findings remain open. Remediation is tracked in
[security hardening](../security-hardening.md).
Source reviewed: `c321c7d`; packaged `0.0.2` source: `a1f86bd`.

## Scope and result

Reviewed the deployed `0.0.1` and published `0.0.2` images, Debian dependencies,
bundled SDK libraries, Python/C++/browser code, Docker configuration and release
workflow. A trusted access network and absence of application login are accepted
constraints. They are not reported as findings. Browser requests from another
origin remain relevant even when the service is only on loopback.

The most urgent result is a **confirmed origin-check bypass caused by unread
request bodies on persistent HTTP connections**. A real browser created a
synthetic live session despite rejection of its cross-origin outer request.
Dependency scanning also identifies patchable OS packages and an outdated SDK
OpenSSL copy that normal Debian updates will not replace.

No application fixes, image rebuilds, deployments or recorder probes were made.
All new scanners ran in resource-limited Docker containers. Dynamic tests used
synthetic cameras, no owner files, no published ports, disabled networking and
zero SDK logins. The production container was left running on `0.0.1`.

## Findings, ordered by remediation priority

| ID | Priority | Finding | Evidence / next action |
| --- | --- | --- | --- |
| S1 | High | Rejected request body can become another HTTP request, bypassing origin checks | Confirmed against the packaged application and Chromium; close connections whenever a body is rejected or left unread. |
| S2 | High maintenance priority | SDK bundles OpenSSL 1.1.1u outside Debian package management | Version strings and explicit library paths confirmed; investigate a supported SDK bundle and verify compatibility at the adapter seam. Exploitability of individual OpenSSL CVEs was not established. |
| S3 | Medium | Pinned base retains packages with available security fixes | Both images contain `perl-base` `5.36.0-7+deb12u3`; database lists `+deb12u4` fixes for 13 findings. Refresh base/security packages and rescan. |
| S4 | Medium, availability | HTTP connections have no initial read timeout or application connection limit | Accepted connection timeout was `None`; thread-per-connection server has no admission bound. Add deadlines and bounded admission. |
| S5 | Medium, retention/storage | Private decoded frames outlive playback sessions and export retention | Stopping a playback removed its in-memory entry but retained its frame file; add bounded cleanup of runtime output. |
| S6 | Low, defense in depth | Native bridge lacks some compiler/linker protections | ELF has PIE, non-executable stack and partial RELRO; no stack-protector import or immediate binding was observed. Enable and verify hardening flags. |
| S7 | Medium, maintenance | Release CI has no dependency vulnerability scan or recurring rescan | Workflow verifies behavior/privacy but does not monitor newly disclosed package/SDK vulnerabilities. Add scan reports and a triaged policy. |

### S1: persistent connection request-boundary bypass

Relevant code: [body validation](../../../docker/hikvision-sdk/grid_server.py#L62),
[control error responses](../../../docker/hikvision-sdk/grid_server.py#L116), and
[HTTP/1.1 configuration](../../../docker/hikvision-sdk/browser_server.py#L184).

`body()` rejects an unexpected Origin or content type before reading the body.
Those two branches do not set `close_connection`; the error response preserves
the connection. The next request parser reads the rejected body as a new HTTP
request. The nested request can supply an allowed Host, JSON content type and
no Origin, so it passes the checks that rejected the outer request.

Observed results in a container running packaged `0.0.2`:

- Rejected-origin case: `403 Forbidden`, then `201 Created`; one empty synthetic
  viewing session was created from the unread body.
- Rejected-content-type case: `415 Unsupported Media Type`, then `201 Created`;
  one synthetic session was created.
- Chromium `154.0.8037.92`, using a page on a different loopback origin and an
  ordinary cross-origin fetch, also created one session. Fetch itself reported
  `TypeError` because CORS prevented reading the response. That did not prevent
  the server-side action.

The browser test establishes the bypass between controlled local origins; it
does not establish that every public website/browser combination can reach
localhost without local-network permission or other browser restrictions.
Actions were demonstrated, not cross-origin reading of footage or credentials.
Nevertheless, this defeats an explicit browser protection independently of
the accepted lack of login.

Close a connection whenever the handler cannot safely account for the complete
request body. Cover early Origin/content-type failures, unexpected bodies on
other methods, and unsupported/ambiguous request framing. An explicit
connection-close policy for control responses is one small implementation
option. Preserve separate long-lived frame feeds. Add raw-socket regressions
that verify no second action occurs after rejection, plus one browser wiring
case; ordinary same-origin actions must still work.
Python documents how
[close_connection controls subsequent parsing](https://docs.python.org/3/library/http.server.html#http.server.BaseHTTPRequestHandler.close_connection).
Private reproduction scripts and payloads remain outside the public source.

### S2: vendor OpenSSL is a separate update problem

Both `/sdk/lib/libcrypto.so.1.1` and `/sdk/lib/libssl.so.1.1` identify themselves
as **OpenSSL 1.1.1u, 30 May 2023**. The native
[initializer](../../../docker/hikvision-sdk/live_grid.cpp#L49) explicitly selects
these files. Debian's separate `libssl3` package is OpenSSL 3.0.22.

OpenSSL 1.1.1 reached upstream end of life in September 2023, and later security
fixes exist. A version string alone cannot rule out vendor backports, but no
evidence of those backports was established here.
See the [upstream lifecycle notice](https://openssl-corporation.org/blog/2023-06-15-1.1.1-EOL-Reminder.html)
and [1.1.1 advisories](https://openssl-library.org/news/vulnerabilities-1.1.1/index.html).

The package scanner reported no language-specific files and did not inventory
this OpenSSL copy as a Debian package. Its absence from the vulnerability table
is a coverage gap, not a clean result. Updating `libssl3` will not replace it.
Investigate an updated vendor SDK/profile rather than substituting incompatible
OpenSSL 3 libraries under 1.1 filenames. Require offline decoder checks, then
bounded live/playback/export validation before any production switch. Closed
vendor decoder internals and static third-party components were not audited.

### S3: base refresh and CVE triage

Both images have identical inventories of **304 OS packages** on Debian 12.15
and identical scan totals:

| Scanner severity | Package/CVE findings | Distinct CVE IDs |
| --- | ---: | ---: |
| Critical | 11 | 11 |
| High | 285 | 78 |
| Medium | 471 | 146 |
| Low | 259 | 152 |
| Unknown | 36 | 28 |
| Total | 1,062 | 415 |

These are scanner advisories, not 415 demonstrated application exploits.
Source-level advisories can appear against several binary packages; scanner
severity is not application reachability. Thirteen rows list a fixed Debian
version, all on `perl-base`; three are marked Critical, four High and six Medium.

The [release Dockerfile](../../../docker/release/Dockerfile#L2) pins a base digest
and installs selected packages. `apt-get update` refreshes package lists; it
does not upgrade every package inherited from the base. Refresh the base digest
or deliberately upgrade inherited security packages during a new build, then
verify the exact artifact. Merely rebuilding with cached layers is insufficient.

Examples showing why triage matters:

- The Critical zlib entry `CVE-2023-45853` concerns MiniZip code that Debian says
  is not built into the affected Bookworm zlib binary packages. It should not be
  described as an exploitable zlib flaw in this image.
  [Debian's package-specific notes](https://security-tracker.debian.org/tracker/CVE-2023-45853).
- `CVE-2026-8376` is described as a 32-bit Perl issue; this image is amd64.
  [Debian's advisory details](https://security-tracker.debian.org/tracker/CVE-2026-8376).
- Other Perl findings still require patch/reachability review. The reviewed
  application uses Python/C++ and does not execute Perl or pass uploaded archives
  to it. Debian publishes the replacement package version.
  [Example fixed-version record](https://security-tracker.debian.org/tracker/CVE-2026-13221).
- FFmpeg brings a wide codec/protocol dependency tree. The app passes validated
  raw YUV through stdin, creates H.264 MP4 locally and probes that generated file;
  it exposes no general file-upload/transcode API. Many decoder advisories
  therefore have no established route through the application's FFmpeg use.
  The SDK's independent decoder still processes NVR streams.

Do not suppress entire packages or all unfixed findings. Record affected
component, reachability, vendor status and review date for each disposition.
Consider reducing codec dependencies after measuring compatibility and effort.

### S4–S6: availability, private output and native hardening

The HTTP server uses `ThreadingHTTPServer`. The five-second body timeout begins
only after header parsing and validation; it does not cover initial headers or
every idle keep-alive connection. Frame/session limits do not bound HTTP handler
threads. Compose's PID/memory limits contain host impact, but reaching them can
still deny service. Add a header/idle deadline and bounded connection admission,
and verify quiet playback feeds and reconnects remain valid. No production load
or connection-exhaustion test was performed.

`GridWorker.stop_playback()` removes the session but does not remove its
`playback-<id>` directory. A fixture confirmed its JPEG remained afterwards.
New worker runs also use new `grid-<id>` directories. Logs are bounded per run,
but there is no overall output retention budget. Export expiry only covers
`/exports`, not these private decoded frames. Cleanup should coordinate with
native stop acknowledgements and active readers, preserve active files and
limit old output across restarts. Files remain private; no HTTP route to browse
runtime directories was found.

The native ELF has PIE, a non-executable stack and GNU RELRO, but no BIND_NOW or
`__stack_chk_fail` import. Add appropriate optimization, fortification, stack
protector and full-RELRO linker options, then verify the produced ELF and native
behavior. This is a mitigation improvement; no native memory-corruption exploit
was demonstrated in Oogies' own bridge.

## Existing protections and scanner triage

- Production is non-root, read-only, drops all capabilities, sets
  `no-new-privileges`, mounts credentials/config read-only, publishes loopback
  only and has CPU/memory/PID/log limits. The Docker socket is not mounted.
- Static assets use an explicit allowlist; session/export IDs use strict route
  patterns. Isolated traversal attempts returned 404; bad Host returned 403;
  ordinary bad Origin returned 403, non-JSON 415 and oversized bodies 400.
  S1 explains why rejection alone did not prove request-boundary safety.
- CSP, `nosniff`, `no-store` and frame-ancestor restrictions are present.
  Camera names/errors use `textContent`; the observed `innerHTML` template is
  static. No direct DOM injection route was identified in the reviewed code.
- Native/FFmpeg launches use argument lists, not an HTTP-controlled shell.
  Credentials travel through private stdin, not command-line arguments.
  JSON bodies, frame sizes, timeline ranges, export queue/storage and viewer
  lifetimes have explicit bounds. This does not replace the HTTP admission work.
- Bandit 1.9.4 completed without analysis errors: 296 alerts, 37 Medium and 259
  Low, no High. Medium alerts cover container binding, development/check-tool
  URLs/temp paths and legacy investigation XML parsers. These are not 37 proven
  production vulnerabilities. The manual request-boundary finding was not
  detected by Bandit.
- Trivy source checks returned three configuration alerts: root user in the
  development Dockerfile and missing Dockerfile HEALTHCHECK in both Dockerfiles.
  The production image is non-root and Compose supplies its healthcheck.
- Trivy reported zero secrets in either image/config or the public source
  snapshot. The repository-specific publication/history audit also passed.
  The browser package has no npm dependencies; the runtime Python code uses
  standard-library/distro packages rather than a pip dependency environment.
- CI actions are pinned by commit, tokens are scoped, checkout credentials are
  not persisted and release uploads use an explicit report allowlist. Add
  dependency scanning/SBOM reporting alongside these checks; a version-tag-only
  scan cannot detect advisories published after release without rescanning.

## Provenance, evidence and limits

Registry image references scanned:

- `ghcr.io/diederikjh/oogies@sha256:d0508907cb78ae67f31b87ab1126423c8fe3003faa17536578d42b67afcaa405` (`0.0.1`, deployed).
- `ghcr.io/diederikjh/oogies@sha256:1f64eb6d70d0bb846dfbc7daf57d51337fa40eb3c14649569dad7bac42d5714e` (`0.0.2`, fetched for review only).

Scanner images:

- Trivy 0.75.0: `aquasec/trivy@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa`.
- Bandit 1.9.4: `ghcr.io/pycqa/bandit/bandit@sha256:e4719e136e3a4fa8d19cfb0e58e292b253d3202b4a32e7433c98df963391210e`.
- Trivy vulnerability database updated `2026-10-18T13:11:41Z`, downloaded
  `2026-10-18T19:03:32Z`. Counts are a dated snapshot.

Saved image archives were scanned without a Docker socket. Source scans mounted
an explicit tracked-file snapshot excluding private state, Git metadata, SDK ZIP
and screenshot binaries. The 41 packaged backend/support/web files compared
match the reviewed source. The browser test used this matching source with the
existing offline browser image; the raw HTTP test used packaged `0.0.2` directly.

Private evidence: `.local/security-review-2026-10-18/` contains
`trivy-image-0.0.{1,2}.json`, `trivy-source.json`, `bandit.json`,
`scan-summary.json`, `sdk-versions.json`, `http-probes.json`,
`browser-probes.json`, reproduction scripts, ELF reports,
`packaged-source-comparison.json` and `oogies-0.0.2.cdx.json` (CycloneDX SBOM).
Raw scanner reports and image archives are ignored, not release uploads.
To repeat image scanning, use Docker's image archive export and Trivy's
[documented archive input](https://trivy.dev/docs/latest/guide/target/container_image/),
with the scanner digest above, `--scanners vuln,secret`,
`--image-config-scanners secret`, `--list-all-pkgs` and JSON output.

This was an initial scan/manual review, not a complete penetration test. Vendor
binary internals, NVR firmware, SDK wire-protocol cryptography, host kernel/
Docker CVEs and every advisory's exploitability remain outside verified scope.
No broad application suite was rerun because application code did not change;
the isolated security probes and documentation/publication checks verify this
review's concrete claims.
