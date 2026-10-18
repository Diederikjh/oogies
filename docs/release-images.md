# Local release images

The [release plan](release-plan.md) starts with a self-contained local image.
This is local build tooling for contributors. [Host installation with Compose](host-release.md)
is available for local images. Publication and installing from a published image
follow in later milestones.

## Prerequisites

- Linux x86-64, Python 3.9+, Git and Docker usable without sudo.
- The verified SDK archive retrieved with native Git LFS. Run `git lfs pull`
  if the archive is still an LFS pointer. The builder checks its SHA-256 before
  Docker receives it; the Docker build verifies it again before extraction.
- Network access for Docker's base image/package setup on the first build.

SDK extraction, a compiler, FFmpeg, Node and browser tools are not required on
the host. Compiling and SDK extraction happen inside the Docker builder stage.
No owner credentials, NVR settings or existing captures are needed for these
build/check commands.

## Build

From the checkout:

```sh
python3 tools/build_release.py
```

The default tag is `oogies:dev-<revision>` with `-dirty` when the checkout has
changes. An explicit local version/tag can be selected:

```sh
python3 tools/build_release.py --version 0.1.0-dev --tag oogies:0.1.0-dev
```

An explicit version does not hide dirty sources: metadata still records them.
Do not describe a dirty development build as a published release from a tag.
The command only builds locally; it does not push or restart a running service.

The builder sends an explicit tar context, not the checkout directory. It lists
backend/support modules, native sources, the verified vendor ZIP and frontend
files referenced by the HTTP asset allowlist. Symlink/missing/traversing inputs
fail. Private `.local/`, Git history, credentials, exports, unrelated web files
and test tools are excluded. Temporary tar contexts are removed after building.

The final image contains Python, FFmpeg, SDK libraries/dynamic components and
notices, application/frontend files and the precompiled bridge. Compilers,
SDK headers/examples, archive-extraction tools and Chromium are confined to
build/test environments. SDK library search settings remain scoped to the
native worker rather than changing Python/FFmpeg's environment.

The development launcher continues using its compile path. Release startup uses
`OOGIES_LIVE_BRIDGE` through the Python adapter; a missing/non-executable packaged
bridge fails without compilation fallback. The underlying server also accepts
an explicit `--bridge` argument.

## Check the exact artifact offline

```sh
python3 tools/check_release_image.py
```

By default this reads the last build report's image ID, so changing a tag cannot
silently select another artifact. An existing local image can be selected with
`--image oogies:0.1.0-dev`; the checker resolves it to an image ID first.
It does not implicitly pull an image.

Checks run with networking disabled, non-root IDs, a read-only root filesystem,
two CPUs, 2 GiB memory/no extra swap and bounded PIDs. The SDK/decoder check
initializes its libraries with zero login calls. HTTP checks use synthetic
documentation-range settings, omit credentials and mount only configuration,
writable output and export directories. No SDK or application source is mounted.

The checker verifies bundled backend/support hashes and every served frontend
asset against the packaged manifest, labels/version/SDK identity, no compiler
or SDK headers, FFmpeg/FFprobe and a synthetic H.264 encode, external writable
state and graceful shutdown.
It also checks that a missing packaged bridge fails clearly. All temporary
containers and synthetic state are cleaned up, including failure paths.
This is dependency/startup verification; it does not establish a real recorder's
compatibility, video quality or capacity.

Build and check reports live under ignored `.local/releases/`:

- `last-build.json`: local tag, immutable local image ID, version, revision,
  dirty flag, SDK profile/checksum and packaged source hashes.
- `last-check.json`: artifact check outcome, including zero login calls.
- `last-native-check.log`, `last-http-check.log`, `last-check-container.log`:
  private diagnostic output; inspect these when a check fails.

The local image ID identifies this artifact in Docker. A registry manifest
digest will be recorded separately when publishing is implemented. Pinned base
images and a fixed artifact do not imply byte-identical rebuilds against mutable
package repositories.

Use [the host release guide](host-release.md) for Compose cutover/operation and
[the release plan](release-plan.md) for publication, published-image installation
and upgrade/rollback milestones.
