# Versioned releases and host installation

Status: milestones 1–4 verified through public `0.0.1` installation.
Upgrade/rollback maintenance remains milestone 5.
Prepared: 18 October 2026 (Africa/Johannesburg).

## Goal and chosen approach

Package a fixed version of Oogies as a Linux x86-64 Docker image. Build locally
first, then add host operation, remote publishing and installation from published
images. Keep the existing development launcher for source-based work.

The current launcher mounts backend/frontend sources from the checkout and
compiles the SDK bridge at startup. A release contains its application code,
frontend, precompiled bridge, verified SDK runtime/resources and runtime tools.
Changing a development checkout must not change the running release.

Alternatives considered: a tagged checkout is easy but retains source mounts and
startup compilation; native packaging adds SDK/host dependency management. A
self-contained container fits the existing Docker tooling and lets contributors
eventually install without a compiler, SDK extraction, Node or Git LFS.

## Artifact and state boundaries

- Initially support only the verified `hcnet-6.1.9.48-linux64` SDK profile and
  `linux/amd64`. Preserve the SDK library tree, dynamic components and notices.
  Select this profile at the existing Python adapter seam; do not invent a
  universal packaging abstraction before a second SDK exists.
- Build the native bridge in Docker. The final runtime needs no compiler,
  Chromium, Selenium, headers or startup compilation. Keep Python, FFmpeg and
  the native/system libraries actually required by the SDK and encoder.
- Record version, source revision, SDK profile and working-tree status. Local
  development builds must identify dirty sources honestly. Future published
  releases build from clean version tags and promote the checked image digest.
- Use an explicit source allowlist for the build context. Private `.local/`,
  credentials, recorder addresses, recordings, exports and Git history must not
  enter any image layer or intermediate build stage.
- Keep configuration and credentials as read-only host files. Export storage
  and runtime output remain writable host state under a stable installation
  directory's `.local/`, independent of the development checkout.
- A release must start without source mounts or a previously extracted SDK on
  the host. Retain non-root operation, loopback HTTP binding, bounded resources
  and logs, and lazy recorder login.
- Development and release must not simultaneously own the same export manifest.
  Real-device cutover uses one production instance. Offline verification uses
  synthetic configuration and no recorder access.

## Milestone 1: local release image

1. Add a dedicated multistage release build and narrow context preparation.
   Restore the checked SDK archive from Git LFS, verify its existing SHA-256,
   extract/compile in Docker and copy only application/runtime artifacts into
   the final image. Do not install a toolchain on the host.
2. Add a small release build command producing a local versioned image and
   recording build metadata. Do not publish an image or change the running
   development service in this milestone.
3. Let release startup select its packaged bridge through the adapter seam;
   development startup keeps its current compile path. Fail clearly for a
   missing packaged binary or unsupported SDK instead of compiling a fallback.
4. Verify the exact image: offline SDK/decoder initialization with zero logins,
   HTTP startup and bundled asset bytes, external writable state, no compiler,
   no source/SDK host mounts, metadata and graceful stop. Exercise it with
   networking disabled and synthetic settings, without the owner's credentials.
5. Add targeted regressions for bridge selection and build/context safeguards;
   run the backend suite and appropriate artifact/integration checks. Update
   release instructions, both setup guides and `progress.md` with results.

**Review gate:** a local release image works from outside the checkout with only
synthetic configuration/state mounts, no runtime compiler and no recorder login.
Source edits after building do not change its served files. Record limitations
honestly; real-recorder cutover belongs to milestone 2.

### Milestone 1 results

Implemented the [local build and artifact-check commands](release-images.md).
All 149 Python tests pass, including context privacy/checksum safeguards and
packaged/development bridge selection. The local dirty development image passed
offline verification from outside the checkout: SDK/decoder initialization,
24 served asset hashes, bundled backend/support hashes, non-root execution,
synthetic H.264 encoding, external state and graceful stop, with zero logins.
The final runtime has no compiler or SDK headers; no source/SDK host mounts
were supplied. Artifact identity and detailed results are recorded privately in
`.local/releases/last-build.json` and `last-check.json`.

The initial HTTP check caught an import of the legacy development probe helper.
That import now stays inside the standalone legacy viewer entry point, so the
grid runtime does not depend on diagnostic tooling. The rebuilt artifact passes.
Milestone 1 did not change the owner's service or exports, or publish an image.
Host operation and real-device verification are covered by milestone 2 below.

## Milestone 2: run a release on this host

- Add Compose and a stable installation directory using private `.local/` files.
  Configure version/digest selection, user IDs, mounts, resource limits, loopback
  port publishing, logging and sufficient shutdown grace.
- Add readiness checks that do not initiate recorder login. Use Docker's restart
  policy for process recovery/optional boot startup; recorder rejection must
  not become an authentication retry loop.
- Reuse existing configuration and ready exports during an explicit cutover,
  after checking for queued/running exports and stopping the old instance.
- Verify start/stop, process restart, persisted exports, source cleanup and a
  bounded real-device viewing check. Keep the previous installation available
  for reverting. Update human/agent host-operation instructions.

**Review gate:** the host runs the fixed release independently of source edits,
with existing state preserved and a verified stop/revert procedure.

### Milestone 2 results

Added the [host release guide](host-release.md), copied-installation Compose file,
`tools/install_release.py` and `tools/check_host_release.py`. Installation pins
the local image ID outside the checkout, copies private configuration/credentials
and export state with ready-clip hash verification, and rejects existing
destinations, active source mounts, pending exports and SDK/platform mismatches.
Compose supplies bounded resources/logs, non-root state mounts, loopback HTTP,
30-second shutdown, lazy status readiness and `unless-stopped` recovery.

All 156 Python tests pass. Offline artifact and Compose checks pass, including
automatic recovery from an application crash and persisted export downloads
through stop/start, with networking disabled and zero logins. The owner was
cut over to the clean `dev-17fef5dc6c84` image; the ready export is unchanged.
One bounded real-camera check received advancing JPEG frames using one login;
deleting the session released all viewer/source/feed/reservation slots.
A rollback drill verified clean release shutdown, lazy development restart,
preserved exports and return to a healthy release. Docker is enabled at boot;
an actual host reboot was not performed. The full browser suite was not repeated
because frontend behavior is unchanged. Evidence is private under
`.local/releases/` and `.local/release-m2-cutover.json`. No image was published.

## Milestone 3: remote build and image publication

- Add a version-tag release workflow gated by the existing Python, JavaScript
  and browser/native jobs. Only the release build retrieves the SDK LFS object.
- Build once, verify that artifact and publish it to GitHub Container Registry;
  record its digest, version, source revision and SDK profile. Never bake owner
  credentials/configuration into CI or require access to a home recorder.
- Use scoped workflow publishing credentials and deliberate release versions.
  Do not automatically deploy to the host or silently replace running versions.

**Review gate:** a published image can be pulled and verified by digest, with
checksums/metadata tied to the passing source revision. Publishing is a later
explicit action after the concrete artifact/workflow is reviewable.

### Milestone 3 implementation and local evidence

Added the [publication workflow/maintainer guide](release-publication.md).
Version-tag releases reuse the existing CI jobs, retrieve the SDK only in the
release job, build once and require matching artifact/Compose reports for the
exact image ID. The publisher checks clean tag/revision/version/SDK identity,
refuses existing registry versions, pushes the tested image, records its digest,
pulls that reference and repeats the offline checks. Source repository metadata
supports forks. JSON-only release reports and the digest summary identify the
artifact; package write permission is scoped to the publishing job.

Both workflows pass actionlint 1.7.12. All 169 Python tests pass, including publication
version/context, stale/failed check, registry error, existing version and
post-push failure regressions. A disposable clean source snapshot and tag passed
the actual build/check/push/pull/recheck flow against a temporary loopback-only
registry, including refusal to overwrite the resulting version. SDK/Compose
checks used disabled networking and zero recorder logins. No release tag was
created in the owner's repository and no image was pushed to GHCR; the installed
host release was unchanged.

Implementation committed as `d07a7a2`. The first remote release is now verified:
[run 39137424996](https://github.com/Diederikjh/oogies/actions/runs/39137424996)
succeeded for `v0.0.1` at source `5fc6892`. Pulling the public image with an empty
Docker credential configuration succeeded. Its source/version metadata match
that run, and the immutable reference is
`ghcr.io/diederikjh/oogies@sha256:d0508907cb78ae67f31b87ab1126423c8fe3003faa17536578d42b67afcaa405`.

## Milestone 4: install from the published release image

Published-image installation is verified with public version `0.0.1`.

- Add a short human guide and complete agent steps for pulling a chosen release,
  creating private NVR configuration/credentials and writable state, then starting
  the service. Offer the versioned Compose file with the release.
- Installing users need Docker/Compose and their recorder settings; they do not
  need Git LFS, SDK extraction, Node, a compiler or a source checkout to run the
  published image. Cloning remains an optional way to obtain deployment files.
- Explain image digest/version selection, user permissions, readiness, reboot
  startup, logs and stopping the installation. Public image users need no login.
- Verify from an empty installation directory without development `.local/`
  data. Separate offline readiness from the installing owner's live-device check.

**Review gate:** another owner or setup agent can follow the published-image
instructions using only release assets and their own private settings.

### Installation guide and published-image verification

[INSTALL.md](../INSTALL.md) is the short image-user entry point linked from the
README and both setup guides. It downloads a selected version's Compose file
and example JSONs into a new user-data directory; explains the NVR host/SDK port,
timezone, account credentials and full stream encryption password; pins the
pulled image with the owner's UID/GID; and shows Docker boot enablement with
`unless-stopped`. It distinguishes intentional stop from reboot recovery.

The versioned Compose/examples downloaded anonymously from the `v0.0.1` source
tag. A new temporary installation using those files and the public image started
healthy, initialized empty export storage and required only four state mounts.
Its networking was disabled to isolate it from the existing viewer; zero SDK
logins occurred. The shortened guide's shell syntax, minimal `.env`, default
port/project and private file permissions were verified separately.

The existing installation was then switched to that image and downloaded Compose
file, retaining its private JSON files and its ready export byte for byte. One
camera delivered three advancing JPEG frames using one SDK login, and deleting
the probe session released it. Docker/containerd were already enabled at boot,
so their enable command was unnecessary on this machine. `unless-stopped` is
configured. A subsequent requested host reboot completed, and the owner
confirmed Oogies remained available afterwards; automatic startup is now
owner-verified on this machine without a separate application systemd unit.

Removed private-registry login instructions, the unavailable example version,
duplicate Compose validation/status commands, explicit default port/project
variables and redundant permissions commands already covered by `umask 077`.
The guide remains a new-install recipe; an existing owner must retain private
settings/exports rather than download example credentials over them.

Only the documented port 8088 was verified. Source inspection found that changing
only the published host port leaves the server's Host allowlist on its internal
port, so the unverified alternate-port recommendation was removed from the host
guide. Correct alternate-port propagation is separate future work.

## Milestone 5: upgrades, rollback and maintenance

- Document selecting a new version, checking active exports, backing up state,
  replacing the container, readiness and explicit rollback to the previous image.
- Preserve configuration and completed exports. Future manifest/schema changes
  need backward compatibility or a documented state-restore procedure; reverting
  an image alone is not a promise to reverse arbitrary data migrations.
- Test restart, upgrade/downgrade compatibility and export persistence. Keep
  updates manual initially; avoid unattended upgrades during capture.

**Completion gate:** locally and remotely built releases have reproducible
deployment by digest, tested installation/upgrade instructions, persistent
private state and a documented rollback path. Byte-identical rebuilds from
mutable package repositories are not claimed.

## Reference documentation

- [Docker Compose service options](https://docs.docker.com/reference/compose-file/services/)
- [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [GitHub image publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
