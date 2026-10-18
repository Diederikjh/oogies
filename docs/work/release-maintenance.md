# Release delivery and maintenance

Updated: 18 October 2026 (Africa/Johannesburg).
Status: milestones 1–4 complete; milestone 5 planned, not started.

## Goal and plan

Ship fixed Oogies images that run independently of the source checkout, with
private persistent configuration/exports and deliberate, recoverable updates.
The [release plan](../release-plan.md) contains the milestone scope and gates.

## Current state

- Local image builds, independent host Compose operation, version-tag GHCR
  publication and installation from public `0.0.1` are verified.
- The host runs the public image with preserved settings and clips. Docker and
  containerd are enabled; `unless-stopped` provides automatic startup. The owner
  confirmed Oogies remained available after the requested reboot.
- Current Compose binds IPv4 and IPv6 loopback. The immutable `v0.0.1` setup
  download predates that fix, so its install instructions use `127.0.0.1`.
- Implementation and installation results through commit `9e932f3` are preserved
  in the [archive](archive/2026-10-18-progress.md#release-build-and-host-installation-plan).

## Next step: milestone 5 review

Before implementation, review the upgrade/rollback procedure from
[release milestone 5](../release-plan.md#milestone-5-upgrades-rollback-and-maintenance):

- Select a fixed version, finish active exports, and back up private state.
- Replace the container, verify readiness and retained settings/exports, and
  explicitly restore the previous image when needed.
- Define compatibility for manifest/schema changes; restoring an image alone
  cannot be assumed to reverse data migrations.
- Verify restart, upgrade/downgrade behavior and export persistence. Keep
  updates manual.

## Verification already completed

- Anonymous public image/setup downloads, fresh isolated installation and one
  bounded real-camera check; configuration and ready clip hashes preserved.
- Seven installation unit tests and isolated Compose integration checks passed,
  including dual-loopback contract, crash recovery, graceful stop/start and
  persisted export download with zero SDK logins.
- IPv4/IPv6 localhost HTTP checks returned 200. Actual reboot startup was
  subsequently confirmed by the owner.
- Publication/history audit and diff checks passed before commit `9e932f3`.
  Private evidence remains under `.local/`; see the archive for exact paths.

## Follow-ups and related guides

- Include the dual-loopback Compose fix in a future version's setup download;
  published `v0.0.1` remains unchanged.
- Alternate host ports require a separate fix: the HTTP Host allowlist currently
  follows the internal port. Only the documented port 8088 is verified.
- [Image installation](../../INSTALL.md), [host operation](../host-release.md),
  [local builds](../release-images.md), [publication](../release-publication.md).
