# Home camera viewing investigation

Current milestone: RTSP and HCNetSDK login both work; decoding the encrypted
live stream is next. See [progress.md](progress.md) for verified results and
links to the detailed investigation notes.

## Git LFS through Docker

The complete original Linux64 SDK archive is in `vendor/hikvision/` using Git
LFS. It includes the vendor binaries and documents, so they can be restored
without repeating the difficult download. Extracted files stay in `.local/`.

Git LFS runs in Docker rather than being installed on the host. On this Linux
amd64 setup, build the tool and configure repository-local filters and the
pre-push hook:

```sh
docker build --tag cam-git-lfs:local docker/git-lfs
python3 tools/setup_git_lfs.py
tools/git_lfs_docker.sh version
```

Normal host `git add`, `git status`, `git commit` and the pre-push hook then use
the Docker wrapper for LFS. Docker must be available to the current user. This
setup configures `core.hooksPath` to the committed `.githooks` directory.

After cloning from a future remote that stores the LFS objects, run the setup
above, then retrieve and materialize the SDK:

```sh
tools/git_lfs_docker.sh pull
tools/git_lfs_docker.sh fsck
```

The initial repository is local only. Its ZIP lives in `.git/lfs/objects/`,
while Git history contains an LFS pointer. A future remote must support LFS;
pushing through the configured hook uploads those objects as well as history.
Remote authentication can be configured when a destination is chosen.

## Restore the SDK and check it offline

Build the existing runtime:

```sh
docker build --target runtime --tag cam-hik-sdk-runtime:local docker/hikvision-sdk
```

With the archive materialized, extract it into the ignored cache using the
runtime's unzip tool. For a fresh checkout (without an existing `sdk` directory):

```sh
mkdir -p .local/hik-sdk
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" --cap-drop=ALL --security-opt=no-new-privileges \
  --mount "type=bind,source=$PWD/vendor/hikvision,target=/archives,readonly" \
  --mount "type=bind,source=$PWD/.local/hik-sdk,target=/cache" \
  cam-hik-sdk-runtime:local unzip -q \
  /archives/EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip -d /cache
mv .local/hik-sdk/EN-HCNetSDKV6.1.9.48_build20230410_linux64 .local/hik-sdk/sdk
python3 tools/run_hik_sdk.py check
```

The check initializes the SDK with networking disabled and does not log in.
Live probes are separate, bounded actions and are not part of this setup.

## Private credentials and validation

Live probes read `.local/nvr-credentials.json` with `username`, `password` and
optional `verification_code` fields. Keep its permissions at `0600` and its
parent directory at `0700`. The shared loader limits only the login password
to its first 16 characters, preserving the full encryption code; see
[credential-loading.md](docs/credential-loading.md).

Credentials, camera captures, SDK debug logs and APK analysis are ignored.
Run the existing credential checks with:

```sh
python3 -m unittest discover -s tests -v
```
