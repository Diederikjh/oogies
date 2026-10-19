# Security hardening

Updated: 18 October 2026 (Africa/Johannesburg).
Status: initial review complete; remediation planned, not started.

## Goal and evidence

Address demonstrated application gaps and keep image/SDK dependencies current
within the accepted trusted-network, no-login design.
See the [dated security review](archive/2026-10-18-security-review.md) for image
identities, scan results, reachability caveats and isolated reproductions.

Both `0.0.1` and `0.0.2` were scanned; the running installation remains `0.0.1`.
The browser-request bypass was confirmed against fake cameras without any SDK
login. No app changes or production probes were made during the review.

## Proposed order

1. **S1, request-boundary protection:** close connections with rejected/unread
   bodies; cover origin/content type, unexpected bodies and ambiguous framing.
   Verify no nested action using raw HTTP plus one browser wiring case, then
   normal controls/feeds and a fixed release artifact.
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

## Next step

Review the S1 fix scope and implement it first. Do not treat the raw scanner's
Critical count as a count of exploitable app flaws; preserve per-finding triage.
Record remediation commits and verification here as each item is completed.
