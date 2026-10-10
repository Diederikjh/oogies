# Getting started for setup agents

This guide contains the installation commands, verification steps and completion
checklist for an agent preparing an owner's machine. The shorter
[human getting-started guide](GETTING_STARTED.md) explains the setup flow and
current limitations. Keep both guides current when configuration, dependencies,
startup commands or supported behavior changes.

## What works today

The current prototype displays one encrypted camera substream in a browser.
The Python backend runs in Docker and uses a C++ bridge to Hikvision's SDK and
PlayCtrl. The SDK archive is already tracked in this repository with Git LFS;
there is no separate vendor download step.

Live video has been verified on one Hikvision DS-7108HGHI-K1. Compatibility with
other recorders, firmware and authentication settings is not yet established.
The grid, motion timeline and arbitrary historical playback UI are planned;
see [the implementation plan](docs/implementation-plan.md).

**Current setup limitation:** the prototype still hardcodes recorder address
`192.0.2.10` and SDK port `8000`. The steps below prepare a fresh checkout,
but starting live view on another recorder must wait for the configuration
support described below. The offline check does not contact a recorder.

## Instructions for a setup agent

Inspect the machine first, install missing prerequisites according to the
owner's existing installation policy, and verify each stage below. Reuse working
installations and private configuration. Do not replace an existing Docker
installation, overwrite credentials, or delete `.local/` to repeat setup.

This project keeps compilers, decoder libraries, Git LFS and additional tools
in Docker. Only the host essentials listed below need host installation if
absent. If the owner prohibits new host installations, report any missing host
essentials as blocked prerequisites. These instructions do not change that
policy; the current investigation machine uses existing host tools.

**Docker must work without `sudo` as the installing user.** Run Git, the LFS
wrapper and Python launchers as that user too. A successful `sudo docker` test
does not satisfy this requirement: the launchers invoke Docker directly.

Collect the checkout path, recorder IP, SDK port, recorder timezone and account
details from the owner's existing configuration or input. Keep passwords out of
command arguments, terminal output and the final setup report. Distinguish
environment readiness from recorder connectivity and successful live video.

## Prerequisite checklist

| Prerequisite | Install location / action if missing | Verification / pass condition |
| --- | --- | --- |
| Linux x86-64/amd64 | Use a compatible machine; other architectures and operating systems are unverified | `uname -s` is `Linux`; `uname -m` is `x86_64` |
| Git | Host package `git` | `git --version` succeeds |
| Python 3.9+ | Host package `python3`; no pip packages needed | Version assertion below succeeds |
| Docker CLI and running daemon | Host Docker Engine or an existing compatible Docker installation | `docker info` succeeds **without sudo** |
| Docker build support | Host Buildx plugin when using Docker Engine | `docker buildx version` succeeds and the project images build |
| Current user's Docker access | Configure the existing Docker installation's user access | `docker run --rm hello-world` succeeds **without sudo** |
| Bash and core utilities | Normally provided by Linux; `bash` and `coreutils` packages if absent | `command -v bash sha256sum chmod mkdir mv id` succeeds |
| SDK ZIP | Already in repository; retrieve its Git LFS object in Docker | Expected SHA-256 matches; archive is not an LFS pointer |
| SDK and decoder runtime | Build `cam-hik-sdk-runtime:local`; extract SDK to `.local/` | Offline SDK check exits 0 with zero login calls |
| Browser | Reuse the owner's browser; a browser on the service machine is needed for the current localhost-only UI | Viewer page opens and, during live validation, displays changing frames |
| Recorder settings and account | Owner provides them; they are not software to install | Private JSON validates; configured address matches the intended recorder |
| Network access | Internet for image/LFS retrieval, LAN route from Docker to the NVR | Builds/LFS pull succeed; bounded TCP check below reaches the SDK port |
| Resources and storage | Inspect machine and Docker capacity; leave headroom for the host | Runtime currently has a 2 GiB memory cap and a 2-CPU limit; adequate disk space for images, SDK and private outputs |

Docker Compose, host Git LFS, host FFmpeg, host C++ compilers, Node.js and host
Selenium are not prerequisites for the current prototype. Automated browser
checks use a separate Docker image and are optional; the existing browser check
also requires a saved historical clip, which a fresh checkout does not contain.

### Detect the existing environment

Run each check separately so a failure is visible and later checks can still be
reported. These commands do not install anything:

```sh
cat /etc/os-release
uname -s
uname -m
command -v git python3 docker bash sha256sum chmod mkdir mv id
git --version
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9+ required"; print(sys.version.split()[0])'
docker --version
docker buildx version
docker info
df -h .
```

`docker info` must return server information without a permission/daemon error.
Docker reporting other existing containers is not an instruction to change them.

### Install missing host essentials on Ubuntu/Debian

Use this section only for missing requirements on those distributions. The
[Ubuntu package-management guide](https://ubuntu.com/server/docs/how-to/software/package-management/)
documents the package-manager operations. Other distributions need their own
package mapping; do not run these commands blindly.

```sh
sudo apt-get update
sudo apt-get install git python3 bash coreutils
```

If Docker already passes the checks above, skip its installation. For a fresh
Docker Engine installation, use the official
[Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/) or
[Debian instructions](https://docs.docker.com/engine/install/debian/). The
following repository-based recipe targets a fresh, non-conflicting installation
on either distribution; inspect existing Docker/containerd packages first.

```sh
. /etc/os-release
case "$ID" in
  ubuntu) camera_docker_os=ubuntu; camera_docker_release="${UBUNTU_CODENAME:-$VERSION_CODENAME}" ;;
  debian) camera_docker_os=debian; camera_docker_release="$VERSION_CODENAME" ;;
  *) echo "Use this distribution's Docker installation instructions"; exit 1 ;;
esac
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl --fail --silent --show-error --location \
  "https://download.docker.com/linux/$camera_docker_os/gpg" \
  --output /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/$camera_docker_os
Suites: $camera_docker_release
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin
sudo systemctl start docker
```

Use the distribution's supported release from the linked documentation. Do not
uninstall a working container stack to force this recipe. On a machine without
systemd, follow its service manager's instructions. An existing rootless Docker
setup can be retained if it passes the project's actual builds and launch checks.

### Required: verify Docker without sudo

For conventional Docker Engine, if only `sudo docker` works, use Docker's
[Linux user-access instructions](https://docs.docker.com/engine/install/linux-postinstall/).
Check that the `docker` group exists and add the installing account if needed:

```sh
getent group docker
id -nG
sudo usermod -aG docker "$(id -un)"
```

If `getent` finds no group on a conventional Engine installation, create it
with `sudo groupadd docker` before running `usermod`.

Log out and back in after changing membership, then rerun the following in the
actual shell used by the setup agent. A new group membership does not apply
retroactively to an existing agent process. An existing rootless installation
uses its own Docker context instead of this group step.

```sh
docker info
docker run --rm hello-world
```

Both commands must exit 0 **without sudo**. The test container should print its
success message and be removed. Do not work around a failure by running the
project as root or changing the Docker socket to be world-writable. Once this
passes, continue all setup commands as the installing user.

## 1. Clone and retrieve the bundled SDK

Replace `<repository-url>` with the repository's published Git URL:

```sh
GIT_LFS_SKIP_SMUDGE=1 git clone <repository-url> cam-visualiser
cd cam-visualiser
docker build --tag cam-git-lfs:local docker/git-lfs
python3 tools/setup_git_lfs.py
tools/git_lfs_docker.sh pull
tools/git_lfs_docker.sh fsck
```

The setup script configures this checkout to use Git LFS in Docker, including
the repository's pre-push hook. Git history contains a small pointer to the SDK;
`pull` retrieves the actual ZIP. The published remote must hold the LFS object
as well as the Git history. At present the investigation repository is local;
a public clone URL has not been configured.

Confirm the restored archive:

```sh
sha256sum vendor/hikvision/EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip
```

Expected SHA-256:

```text
8de553fb2e8dbb0ac441ee1bd73c5ecb73d720c1359396750479a6e169abf93f
```

If the file is a small text pointer, LFS retrieval has not finished. Resolve
that before extracting; the archive should be 67,235,848 bytes. Remote
authentication must be available to the containerized LFS command if the remote
is private; host Git authentication is not automatically forwarded by the
current wrapper.

## 2. Build the backend and extract the SDK

Run these extraction commands once in a fresh checkout. If
`.local/hik-sdk/sdk/lib/libhcnetsdk.so` already exists, retain the extracted SDK
and run its offline check instead of extracting over it:

```sh
docker build --target runtime --tag cam-hik-sdk-runtime:local docker/hikvision-sdk
mkdir -p .local/hik-sdk
chmod 700 .local
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" --cap-drop=ALL --security-opt=no-new-privileges \
  --mount "type=bind,source=$PWD/vendor/hikvision,target=/archives,readonly" \
  --mount "type=bind,source=$PWD/.local/hik-sdk,target=/cache" \
  cam-hik-sdk-runtime:local unzip -q \
  /archives/EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip -d /cache
mv .local/hik-sdk/EN-HCNetSDKV6.1.9.48_build20230410_linux64 .local/hik-sdk/sdk
python3 tools/run_hik_sdk.py check --decrypt
```

The check compiles the native bridge, loads the SDK and checks the decoder/key
setup with networking disabled. It does not read credentials or log in. The
extracted SDK and generated diagnostics remain in ignored `.local/` storage.
It must exit 0 and report `initialized: true`, `login_calls: 0`,
`decoder_ready: true` and `decoder_error: 0`. Also run the existing offline tests:

```sh
python3 -m unittest discover -s tests -v
```

All tests must pass; they use temporary files and a fake native process rather
than authenticating to the recorder.

## 3. Enter private credentials

Create `.local/nvr-credentials.json` in a text editor, replacing these example
values with your account and the full stream encryption password:

```json
{
  "username": "your-recorder-user",
  "password": "your-login-password",
  "verification_code": "your-stream-encryption-password"
}
```

```sh
chmod 700 .local
chmod 600 .local/nvr-credentials.json
```

`verification_code` is the recorder's **Encryption Password**, which may differ
from the account password. The current encrypted-view prototype requires it.

On the original NVR UI, find the stream encryption password under **Network →
Advanced Settings → Platform access → Encryption Password**. Press the eye
icon to reveal it. Menu names may differ on another firmware version.

The current Python SDK adapter uses the first 16 characters of the login
password and preserves the complete encryption password. The generic credential
reader preserves both values unchanged. We treat normalization as SDK-dependent;
the rule is verified only for the current device/SDK combination. Contributor
instructions are in [the adapter seam notes](docs/sdk-adapter-seam.md).

Credentials are read only by the backend and are excluded from Git. Captures,
private logs and generated clips are also stored under ignored `.local/`.

Verify the file without printing its contents:

```sh
python3 - <<'PY'
import os
from pathlib import Path
import stat
import sys
sys.path.insert(0, 'tools')
from credentials import load_credentials

path = Path('.local/nvr-credentials.json')
assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700, 'Expected private directory mode 0700'
assert stat.S_IMODE(path.stat().st_mode) == 0o600, 'Expected credential mode 0600'
assert path.stat().st_uid == os.getuid(), 'Credentials must belong to the installing user'
credentials = load_credentials(path)
key = credentials.get('verification_code', '')
assert key and len(key.encode('utf-8')) <= 128, 'A full encryption code of at most 128 UTF-8 bytes is required'
assert not any(ord(c) < 32 or ord(c) == 127 for c in key), 'Encryption code contains control characters'
print('Private credentials validate locally; no recorder login was attempted.')
PY
```

A pass confirms file permissions and format, not that the recorder accepts the
account. Retain an existing credential file unless the owner wants it changed.

## Recorder configuration — planned, not implemented

Every installing user will enter their NVR IP address; the application must not
require editing source code. The proposed `.local/nvr-config.json` starts with:

```json
{
  "host": "192.0.2.10",
  "sdk_port": 8000,
  "timezone": "Africa/Johannesburg"
}
```

This is an example of the intended configuration, **not a file the current
prototype reads**. `host` is the user's recorder IP, `sdk_port` is its configured
SDK/server port, and `timezone` describes the recorder's local clock. Credentials
stay in the separate file above. The frontend receives camera IDs and media
URLs from the backend; it does not need the recorder address.

Configuration support is a requirement of the first milestone. It must replace
the hardcoded address and port in both the viewer and authenticated SDK runner,
validate settings before login, and document the login-password policy. Camera
discovery will provide configured channels rather than requiring source edits.

### Check Docker-to-recorder connectivity without authentication

After building the runtime, an agent can check one TCP connection to the
owner-supplied IP and SDK port. Replace the example address first. This confirms
network reachability only; it does not send a password or start a video stream:

```sh
docker run --rm -i --read-only \
  --user "$(id -u):$(id -g)" --cap-drop=ALL --security-opt=no-new-privileges \
  --network bridge --cpus=1 --memory=128m --pids-limit=32 \
  cam-hik-sdk-runtime:local python3 - 192.0.2.10 8000 <<'PY'
import socket
import sys
with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3):
    print('Docker can reach the recorder SDK port; no authentication attempted.')
PY
```

Exit 0 is a pass. Timeout/refusal means connectivity is blocked; resolve the
address, port or route before a login attempt. An open SDK port alone does not
prove SDK or encryption compatibility. The hardcoded-address limitation still
blocks live setup for a different recorder even if this check succeeds.

## 4. Start and stop the current prototype

These commands currently target the original hardcoded recorder. For another
owner, use them after the configuration milestone has been implemented and
this section updated accordingly.

```sh
python3 tools/run_browser_viewer.py
```

Open <http://localhost:8088/>. Starting the server compiles the bridge but does
not log in to the recorder. **Start live view** starts one SDK session for the
first reported camera's substream. **Stop** ends that shared camera session.

The **Aspect ratio** selection applies to live and recorded pictures and is
remembered in this browser. The current camera's 16:9 default is confirmed by the
owner's Android screenshot. Compare other installations with a known-good view;
other cameras may require 4:3 or
Original. See [picture proportions](docs/image-display-aspect.md). After updating
backend code or mounts, use the launcher to stop/start the service so new Python
modules and allowed asset routes are loaded.

The current viewer is published only on the local machine. Other LAN computers
cannot access it yet. Sessions have a ten-minute maximum by default; closing a
tab does not yet implement the proposed viewer-lease cleanup. The planned
90-second leases and independent viewer sessions are described in the
[API proposal](docs/backend-api-plan.md).

Stop the service with:

```sh
python3 tools/run_browser_viewer.py --stop
```

After the stop command returns, this must produce no container name:

```sh
docker ps --filter 'name=^/cam-browser-viewer$' --format '{{.Names}}'
```

The launcher waits for auto-removal; an inspect of that container should then
report it absent.

Optional startup flags are `--port 8088` and `--session-seconds 600` (maximum
900). Stop an existing instance before changing its settings. To inspect
startup diagnostics, use `docker logs cam-browser-viewer`.

Once startup is applicable, verify HTTP readiness separately from live video:

```sh
python3 - <<'PY'
import json
from urllib.request import urlopen
with urlopen('http://localhost:8088/', timeout=5) as response:
    assert response.status == 200, 'Viewer page did not load'
with urlopen('http://localhost:8088/api/status', timeout=5) as response:
    status = json.load(response)
assert status['state'] == 'stopped', 'An existing camera session needs separate handling'
assert status['session'] is None, 'Unexpected native session at startup'
print('Viewer HTTP checks passed; camera remains stopped.')
PY
```

The launcher returns before compilation/server startup has necessarily
finished. A connection refusal immediately after launch is not proof of a
failure: inspect the container logs and retry the local HTTP check within a
bounded startup window (up to 60 seconds). These GET requests do not log in.
If using a different `--port`, change both URLs accordingly.

For a live acceptance check on the intended recorder, start once and confirm
the frame counter advances, received frames stay fresh and visible pixels
change. Stop and verify status returns to `stopped`. Authentication rejection
ends the check; report the SDK error rather than retrying passwords. If the
agent cannot inspect the browser, report visual verification as pending rather
than claiming video works from HTTP readiness alone.

An existing historical MP4 under `.local/hik-sdk/results/` is mounted by the
launcher for the **Recorded clip** view. A fresh clone has no saved camera
footage; live viewing does not depend on a recorded clip. Instructions for a
bounded historical extraction are in
[historical-playback results](docs/historical-playback-results.md); the current
authenticated runner shares the hardcoded recorder limitation.

## Maintaining this guide

The setup agent's final report should include this checklist with pass, fail,
blocked or not-run for each item, plus the concrete error for any incomplete
step. Never include credential values:

- [ ] Supported OS/architecture and required host commands verified.
- [ ] Docker daemon and test container work as the installing user, without sudo.
- [ ] SDK archive retrieved from Git LFS and checksum verified.
- [ ] Runtime image built, SDK extracted and offline SDK/decoder check passed.
- [ ] Existing offline tests passed.
- [ ] Private credential format, ownership and permissions verified.
- [ ] Owner's recorder settings supported and Docker TCP connectivity verified.
- [ ] Service starts and local HTTP readiness passes without starting a camera.
- [ ] One live session displays moving frames, then cleans up after Stop.
- [ ] Service stop verified, or service deliberately left running for the owner.

An agent can currently complete environment preparation on a supported machine.
It must report recorder-specific setup as blocked if configuration support is
needed but absent, or repository distribution as blocked if the remote/LFS
object is unavailable. Do not describe an environment-only pass as a working
installation for that owner's NVR.

Each milestone must update these instructions and the
[human guide](GETTING_STARTED.md) in the same change as any new setup requirement.
Keep the human guide brief and put installation/verification detail here.
Keep implemented steps separate from planned behavior.

Before claiming a new version is ready for other owners, verify a fresh checkout
with an empty `.local/` directory: retrieve the SDK through LFS, build the
containers, run the offline check, enter that owner's configuration and
credentials, then start and stop the service. Confirm private files and previous
camera captures are unnecessary for setup. Live validation is a separate,
explicit step using the configured recorder.

As the architecture grows, document configuration keys and defaults, startup
and shutdown commands, network binding, session cleanup, data retention,
supported platforms, upgrades and any new prerequisites here.
