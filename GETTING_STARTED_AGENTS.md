# Getting started for setup agents

This guide contains the installation commands, verification steps and completion
checklist for an agent preparing an owner's machine. The shorter
[human getting-started guide](GETTING_STARTED.md) explains the setup flow and
current limitations. Keep both guides current when configuration, dependencies,
startup commands or supported behavior changes.

## What works today

The current service displays discovered analog/IP substreams in an automatic live grid.
The Python backend runs in Docker and uses a C++ bridge to Hikvision's SDK and
PlayCtrl. The SDK archive is already tracked in this repository with Git LFS;
there is no separate vendor download step.

Live video has been verified on one Hikvision DS-7108HGHI-K1. Compatibility with
other recorders, firmware and authentication settings is not yet established.
History now displays recording coverage and SDK-returned motion intervals.
Clicking a time starts recorded video with pause/resume and seeking; see
[the playback notes](docs/history-playback.md),
[the timeline notes](docs/history-timeline.md) and
[the implementation plan](docs/implementation-plan.md).

The service now reads the owner’s IP/SDK port from `.local/nvr-config.json`.
Only the preserved HCNetSDK 6.1.9.48 profile is supported. Configuration support
does not establish compatibility with every recorder. Offline SDK checks do not
contact a device. See [live-grid implementation and results](docs/live-grid.md).

## Instructions for a setup agent

Inspect the machine first, install missing prerequisites according to the
owner's existing installation policy, and verify each stage below. Reuse working
installations and private configuration. Do not replace an existing Docker
installation, overwrite credentials, or delete `.local/` to repeat setup.

This project keeps compilers, decoder libraries and additional investigation
tools in Docker. Git LFS is installed on the host so it uses the same
authentication as Git and VS Code. Only the host essentials listed below need host installation if
absent. If the owner prohibits new host installations, report any missing host
essentials as blocked prerequisites. These instructions do not change that
policy; the current investigation machine uses existing host tools.

**Docker must work without `sudo` as the installing user.** Run Git, Git LFS
and Python launchers as that user too. A successful `sudo docker` test
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
| Git LFS | Host package `git-lfs`; configure this checkout using `python3 tools/setup_git_lfs.py` | `git lfs version` and `git lfs fsck` succeed; local filters use native `git-lfs` |
| Python 3.9+ | Host package `python3`; no pip packages needed | Version assertion below succeeds |
| Docker CLI and running daemon | Host Docker Engine or an existing compatible Docker installation | `docker info` succeeds **without sudo** |
| Docker build support | Host Buildx plugin when using Docker Engine | `docker buildx version` succeeds and the project images build |
| Current user's Docker access | Configure the existing Docker installation's user access | `docker run --rm hello-world` succeeds **without sudo** |
| Bash and core utilities | Normally provided by Linux; `bash` and `coreutils` packages if absent | `command -v bash sha256sum chmod mkdir mv id` succeeds |
| SDK ZIP | Already in repository; retrieve with native `git lfs pull` | Expected SHA-256 matches; archive is not an LFS pointer |
| SDK and decoder runtime | Build `cam-hik-sdk-runtime:local`; extract SDK to `.local/` | Offline SDK check exits 0 with zero login calls |
| Browser | Reuse the owner's browser; a browser on the service machine is needed for the current localhost-only UI | Viewer page opens and, during live validation, displays changing frames |
| Recorder settings and account | Owner provides them; they are not software to install | Private JSON validates; configured address matches the intended recorder |
| Network access | Internet for image/LFS retrieval, LAN route from Docker to the NVR | Builds/LFS pull succeed; bounded TCP check below reaches the SDK port |
| Resources and storage | Inspect machine and Docker capacity; leave headroom for the host | Runtime currently has a 2 GiB memory cap and a 2-CPU limit; adequate disk space for images, SDK and private outputs |

Docker Compose, host FFmpeg, host C++ compilers, Node.js and host
Selenium are not prerequisites for the current prototype. Automated browser
checks use a separate Docker image and are optional. The grid checker includes
History metadata/navigation; neither History nor offline UI tests need a private
historical clip.

### Detect the existing environment

Run each check separately so a failure is visible and later checks can still be
reported. These commands do not install anything:

```sh
cat /etc/os-release
uname -s
uname -m
command -v git python3 docker bash sha256sum chmod mkdir mv id
git --version
git lfs version
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
sudo apt-get install git git-lfs python3 bash coreutils
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
python3 tools/setup_git_lfs.py
git lfs pull
git lfs fsck
```

The setup script configures native Git LFS in this checkout and enables the
repository's publication pre-push hook. It replaces any older Docker filter
configuration without overwriting the committed hook. Git history contains a small pointer to the SDK;
`pull` retrieves the actual ZIP. The published remote must hold the LFS object
as well as the Git history.

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
authentication must be available to host Git if the remote is private. Native
Git LFS uses host Git's authentication, including VS Code's credential helper.
For GitHub, have the user complete `gh auth login --hostname github.com
--git-protocol https --web`, then run `gh auth setup-git --hostname github.com`.
Do not ask the user to paste a token into chat. Use the setup script rather than
`git lfs install --force` alone, which could overwrite the publication hook.

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

## 4. Enter private recorder configuration

Create `.local/nvr-config.json` using the owner's actual IP address and SDK port:

```json
{
  "host": "192.0.2.10",
  "sdk_port": 8000,
  "timezone": "Africa/Johannesburg",
  "sdk_profile": "hcnet-6.1.9.48-linux64",
  "max_live_sources": 8,
  "max_high_quality_sources": 1,
  "lease_seconds": 90,
  "camera_overrides": {}
}
```

```sh
chmod 600 .local/nvr-config.json
python3 - <<'PYCONFIG'
import sys
sys.path.insert(0, 'tools')
from nvr_config import load_config
load_config()
print('Recorder settings validate; no device connection attempted.')
PYCONFIG
```

This is now implemented for the viewer and authenticated SDK diagnostic.
Passwords remain in the separate credential file. Normalization belongs to the
selected SDK adapter; `login_password_max_chars` is not a configuration field.
`max_live_sources` is an application budget (1–16), not a hardware limit; seven
concurrent previews have been verified on the original recorder. `lease_seconds`
can be 10–300; default 90 with frontend renewal every 30 seconds. The timezone
sets the recorder's clock context for historical range conversion;
live OSD timestamps are unchanged.

`max_high_quality_sources` is an optional integer from 0–16, default one; zero
disables high-quality live sources. It limits distinct camera main streams,
shared across viewers, within the existing total `max_live_sources` budget.
An upgrade retains its overview fallback, so it consumes one additional slot.
Historical playback and exports also use the total budget; closing native live
sources count until their stop acknowledgement arrives. If there is no room,
the API returns overview quality with an explicit refusal reason. Refused/failed
upgrades are not queued or automatically retried. Restart after changing limits.
Current frontend expansion still uses overview. Verify the backend through the
API and `/api/status`; do not claim high quality from tile size alone. See
[live quality](docs/live-quality-plan.md) for the staged checks and measurements.

Optional `exports` settings are a nested object in that same private JSON:

```json
{
  "max_duration_seconds": 600,
  "max_waiting_jobs": 3,
  "retention_hours": 24,
  "storage_bytes": 1073741824,
  "max_file_bytes": 268435456
}
```

Omitting `exports` keeps these defaults; there is one active worker. Duration
may be 1–600 seconds, waiting jobs 1–20, retention 1–168 hours, file cap 1 MiB–1 GiB,
and storage 1 MiB–16 GiB. Storage must allow at least twice the file cap for
finalization headroom. Unknown fields and noninteger values are rejected.
Retain the owner's existing settings when adding this optional object.
The launcher creates private `.local/exports/` and mounts it writable at `/exports`;
keep it across restarts. Its manifest and ready clips are durable. Confirm free
disk space for the configured quota in addition to Docker images and SDK files.
FFmpeg and FFprobe are already in the runtime; no host codec installation is needed.

Optional `camera_overrides` keys are SDK channel numbers, for example:
`"1": {"name":"Driveway", "aspect_ratio":"16:9"}` or
`"4": {"enabled":false}`. Names and online state otherwise come from discovery.
Only overview quality is implemented; clicking a picture toggles expansion
without starting a main stream. Aspect controls live under Settings → Picture
proportions, with per-camera browser preferences applied to live and History video.
Restart the service after editing settings or credentials. See
[the grid notes](docs/live-grid.md) for the implemented API and limits.

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
prove SDK or encryption compatibility.

## 5. Start, verify and stop the viewer

```sh
python3 tools/run_browser_viewer.py
```

The launcher publishes only `127.0.0.1:8088`. Startup compiles the native worker;
it does not log in. Readiness can be checked without opening a browser page:

```sh
python3 - <<'PYHTTP'
import json
from urllib.request import urlopen
for path in ('/', '/app.js', '/shared/frame-feed.js'):
    with urlopen('http://localhost:8088' + path, timeout=5) as response:
        assert response.status == 200
with urlopen('http://localhost:8088/api/status', timeout=5) as response:
    status = json.load(response)
assert status['state'] == 'stopped'
assert status['sdk_login_calls'] == 0
print('HTTP ready; recorder has not been contacted.')
PYHTTP
```

Allow up to 60 seconds for compilation/startup; inspect `docker logs
cam-browser-viewer` if readiness fails. `--port` changes the HTTP port; change
verification URLs accordingly. Docker resource limits remain 2 CPUs, 2 GiB and
512 processes. No new images or host packages are required for this milestone.

**Opening the page starts live viewing automatically.** GET `/api/cameras` opens
one SDK connection and performs read-only discovery; POST `/api/live/sessions`
starts the selected previews. For live acceptance, open the page once, confirm
all online tiles receive fresh moving frames, then Pause view. Two tabs should
share sources, and pausing one must preserve the other. Authentication rejection
ends the check; do not retry passwords or SDK profiles automatically. Report
actual discovered channels, tested concurrency and per-camera failures.

Click a camera picture to animate expand/collapse. Verify the picture stays in
focus and manual wheel/touch/keyboard/scrollbar input overrides automatic
scrolling. The transition preserves picture proportions and the existing
overview stream. Reduced-motion preferences disable the animation.

Camera availability expires after 60 seconds. Active views share one periodic
status query using the existing SDK login; recovered offline cameras resume
automatically. Recent video takes precedence over an offline status hint.
Unknown status keeps the previous known state until the next minute's query.
Idle views do not make background queries. Newly added/removed channels or
configuration changes still require service restart for full discovery.

Closing a tab attempts to release its lease immediately. A killed/disconnected
tab expires within about 90 seconds of its last heartbeat. Streams stop when
their last subscriber leaves; the shared recorder login persists until shutdown.
Switching to History releases this page's live subscriptions while other pages
keep theirs. Verify the camera selector, default three-hour range and separate
recording/motion tracks. An accepted empty motion result differs from an error
or unsupported query. Check that range labels agree with the configured recorder
timezone. Clicking a time or motion interval starts recorded video. Verify the
visible recorder timestamp, Pause/Resume, a second time selection while paused,
and Stop releasing the playback. No private MP4 is required on a fresh clone. The existing
historical extraction diagnostic uses the same private recorder configuration.
Verify each live camera's History button selects that camera, including offline
cameras with recordings. Check 0.5×, 1×, 2× and 4× controls against the visible
recorded timestamp, preservation through seeks and Pause/Resume, and changing
speed while paused without advancing the picture. A rejected decoder speed
change must show an error and preserve moving video at its confirmed speed.
Verify Date & time shows the configured recorder timezone. Choose a known older
date/time for a non-default camera, press Go to time, and check its moving
footage/recorded clock and surrounding timeline. It starts playback even if
previously paused, retains that camera's selected speed and replaces the range
within the same session/slot. Refresh should retain the chosen window; Recent
returns to the current hours. Blank, future or ambiguous/nonexistent daylight-
saving times must not start SDK playback. A rejected date leaves the prior
window/picture working. Check keyboard submission and mobile fit as well.

Inside the runtime, verify the configured IANA timezone can be loaded with
Python's `zoneinfo.ZoneInfo`. It requires timezone data in Docker; install
`tzdata` in the runtime image if a different base image lacks it, rather than
adding a host Python dependency. Do not replace the owner's timezone with a
default simply to make this check pass.

Current production admits one historical viewer and reserves a slot in
`max_live_sources` while it owns that lease, including while paused. Seven live
previews and one playback fit the default application budget of eight, but that
is not a measured hardware guarantee. A full budget returns a capacity error
and preserves existing viewers. Resume/seek reopen only that playback context
at the confirmed/selected time; native combined pause was not usable on the
verified profile. Speed changes adjust that viewer's file-mode decoder in place;
audio is not implemented. The bounded manual speed check is
`python3 tools/check_playback_rates.py` through the already-running service.

Verify ±10/30-second steps preserve pause/speed and clamp at the timeline window.
Download a paused current frame: it should be a PNG with the selected camera,
recorded time and corrected proportions, without an export job. Mark a start/end
while viewing; verify independent Start/End flags and shaded selection. Reject
reversed/zero/over-limit ranges. Queue a short clip and verify viewing continues.
Setting both marks should zoom around them, even when initially overlong. Verify
mouse/touch dragging and arrow-key editing of both handles. Edits must clamp to
at least one second, stay below the configured maximum, and leave video/speed
unchanged. Full range must restore the queried window without an SDK request.
An explicit lower export limit in private configuration still takes precedence
over the new ten-minute default; change that value only when the owner wants it.
Open Exports, check progress, download its MP4 and verify moving video and aspect.
Cancel another job and verify its partial file and reserved stream slot are
released. A full recorder budget waits without evicting existing streams.

Verify `.local/exports` mode 0700, `jobs.json` mode 0600, and that a ready download
survives a service restart. Expiry/deletion blocks new downloads and defers
unlinking any download already open. Closing a browser releases only viewing
leases; export jobs continue without a browser heartbeat. An active export
reserves one additional source slot. Current real evidence covers one live,
one playback and one export together; full-grid coexistence is not a measured
hardware guarantee. Clip bounds are second precision, not frame-exact.

An explicit recorder validation ladder is:

```sh
python3 tools/check_clip_exports.py --seconds 1 60 300 --with-views
```

This contacts the configured recorder, takes roughly six minutes, and saves
private clips/reports under `.local/export-checks/`. Run only as an authorized
recording check; routine CI uses synthetic media. See [clip exports](docs/clip-exports.md).
For the ten-minute boundary, use `--seconds 600 --with-views`; this takes about
ten minutes plus preparation/finalization. Export bounds are reported at second
precision; final duration must be within one second and encoded frame count
must match captured frames, with independent recorded-coverage/gap validation.

Stop with:

```sh
python3 tools/run_browser_viewer.py --stop
docker ps --filter 'name=^/cam-browser-viewer$' --format '{{.Names}}'
```

The second command must produce no name. Shutdown stops previews/decoders and
logs out. Stop/start after source/configuration changes; do not reuse an old
container with missing support mounts.

The current real-browser acceptance tool is `tools/check_live_grid.py`, run in
the existing browser Docker image. It opens the automatic grid, checks sharing,
proportions and playback, and releases its views. The old one-camera browser and
saved-media aspect scripts describe the preceding frontend; use the grid tool
for this milestone.

## Optional: offline UI acceptance

Run `python3 tools/run_ui_tests.py --build` to build the browser image and run the
UI suite, then omit `--build` on later runs. This can be done before SDK/NVR setup:
synthetic media and a fake worker exercise the actual browser/API/session layers
with container networking disabled. No credentials, SDK archive or saved footage
are mounted. See [UI testing](docs/ui-testing.md). UI success establishes browser
behavior and does not establish compatibility with the owner's recorder.

The [GitHub workflow](.github/workflows/ci.yml) runs the unit and UI suites on
pushes and pull requests without recorder setup or Git LFS retrieval. It retains
synthetic UI screenshots and the JSON report as run artifacts; details are in
[the CI notes](docs/ui-testing.md#github-actions).

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
- [ ] Every online camera displays fresh frames, views share sources, and Pause/expiry releases only that viewer.
- [ ] Service stop verified, or service deliberately left running for the owner.

An agent can currently complete environment preparation on a supported machine.
Report repository distribution as blocked if the remote/LFS object is unavailable,
and device compatibility as unverified until its actual live check passes. Do not describe an environment-only pass as a working
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

Before a GitHub push, run the [publication check](docs/publication-checks.md).
The pre-push hook checks reachable history before the native Git LFS transfer.
Private recorder configuration, credentials and captures must remain in `.local/`.
