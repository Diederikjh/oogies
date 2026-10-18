# Publish a versioned image

Milestone 3 provides `.github/workflows/release.yml`. Publication is triggered
by pushing a deliberate version tag after reviewing/committing the workflow.
Preparing the workflow does not publish an image or change the host installation.
This guide is for maintainers; [INSTALL.md](../INSTALL.md) gives the end-user
file/configuration/startup steps, verified against the public `0.0.1` release.

## Release flow

1. Push a new tag such as `v0.1.0` or `v0.1.0-rc.1`, pointing to the intended
   clean source commit. The tag format requires three version numbers, with an
   optional SemVer prerelease suffix. Build metadata (`+...`) is not supported
   because Docker image tags cannot contain `+`.
2. The release calls the existing CI workflow from the same commit. Python,
   JavaScript and offline browser/native jobs must all pass before the build
   job starts. Ordinary branch/PR CI still runs; version tags use the release
   invocation rather than running the test workflow twice.
3. Only the release job retrieves Git LFS content. It verifies the SDK checksum,
   checks publication privacy/history, and builds once through the explicit
   allowlist context. Dirty sources or a mismatch between tag, checked-out
   revision and GitHub's revision fail the release.
4. The exact local image ID must pass both offline checks: SDK/decoder/assets/
   synthetic encoding and Compose startup/crash recovery/persistent downloads.
   Neither check uses a real recorder, owner credentials or home settings.
5. The job authenticates with its scoped `GITHUB_TOKEN`, tags that checked image
   ID and pushes it to `ghcr.io/<owner>/<repository>:<version>`. Owner/repository
   names are lowercased for GHCR. For this repository, the image is
   `ghcr.io/diederikjh/oogies`; a `v0.1.0` source tag produces image tag `0.1.0`.
6. The push's registry digest is recorded. The workflow pulls that immutable
   reference, checks that it identifies the tested image and reruns both offline
   checks against it. It does not rebuild for publication or deployment.

The publisher refuses a version already present in the registry. Authentication
or registry lookup errors fail closed rather than being treated as a missing
version. Use a fresh version after correcting a failed release that already
uploaded an image; do not move/reuse an existing version tag.

If upload succeeds but pull/check fails, the image may already be in GHCR.
`publication.json` retains its digest and `verified_after_pull: false`. A green
release requires successful verification, not merely a successful upload.

## Repository setup and deliberate publication

GitHub Actions must be enabled and allowed to write packages for this repository.
Only the publishing job requests `packages: write`; other jobs have
`contents: read`. Registry login receives the built-in workflow token through
stdin, and logout runs on completion/failure. No personal access token or NVR
secrets are required. Checkout credentials are not persisted.

The OCI source label identifies the repository that built the image, including
forks. When an existing package has separate access rules, grant this repository
Actions access before publishing. Package visibility is a registry setting;
this workflow does not make a package public. Confirm the intended visibility
for new packages/forks. The `0.0.1` Oogies package has been verified publicly
accessible without registry credentials. See [GitHub's Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

After reviewing and committing the release implementation, choose an unused
version and push the intended source commit and that tag. For example:

```sh
git status --short
git tag -a v0.1.0 -m "Oogies 0.1.0"
git push origin main
git push origin v0.1.0
```

These commands publish once the release tests/checks pass; they are instructions,
not actions taken by preparing this milestone. Tag only the reviewed commit.
There is no `latest` alias, scheduled release or automatic host deployment.

## Evidence and checking a published artifact

The release run summary prints the immutable reference and source commit. Its
`release-reports` artifact retains JSON reports for 14 days:

- `target.json`: source tag, version, revision and intended registry target.
- `last-build.json`: built image ID, clean source metadata, SDK checksum and
  allowlisted file hashes.
- `last-check.json` and `last-host-check.json`: final offline checks tied to
  that exact image ID, with zero login calls.
- `publication.json`: registry digest/reference, source version/revision, SDK
  profile/checksum and post-pull verification result.

The artifact is an explicit JSON allowlist, not the entire `.local/` directory;
it does not include SDK archives, images, credentials, footage or raw SDK logs.
Keep the digest from a successful run as the durable artifact identity, since
workflow report retention is bounded. GitHub's registry digest differs from the
local Docker image ID; the report records both.

For a maintainer with Docker and this checkout, verify a published image by
using the exact reference from its successful report:

```sh
docker pull ghcr.io/diederikjh/oogies@sha256:<digest-from-report>
python3 tools/check_release_image.py --image ghcr.io/diederikjh/oogies@sha256:<digest-from-report>
python3 tools/check_host_release.py --image ghcr.io/diederikjh/oogies@sha256:<digest-from-report>
```

Replace the placeholder before running; authenticate to GHCR if the package is
private. These are offline artifact checks after pulling, not installation
instructions or a real-recorder compatibility test. The current host continues
running its selected fixed image until an explicit cutover/upgrade.

The workflow reuses [GitHub's reusable workflow mechanism](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
and follows its [container publication guidance](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).
