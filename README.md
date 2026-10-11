# Oogies

For a fresh checkout, start with [GETTING_STARTED.md](GETTING_STARTED.md).
It gives the setup overview and current limitations. Detailed installation and
verification instructions for a setup agent are in
[GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md). Both guides are maintained
alongside architecture changes.

Current milestone: RTSP and HCNetSDK login work, and the encrypted camera
substream decodes successfully with PlayCtrl and the full verification code.
Historical time playback also works: a five-second recording was extracted
from one hour earlier. V30 recording search now works, and the History tab shows
recording coverage and SDK motion intervals over a selectable recent-hours range.
Clicking a History time now plays its recorded video, with pause/resume, seeking
and independent viewer state. See [History playback](docs/history-playback.md) and
[History timeline notes](docs/history-timeline.md) for the contract and evidence.
The browser now automatically displays a live grid: seven simultaneous previews
were verified, shared across tabs through one SDK login. Offline inputs remain
labeled tiles. See [live-grid notes](docs/live-grid.md) for the architecture,
implemented API and measured capacity.
See [progress.md](progress.md) for verified results and
links to the detailed investigation notes.

Planned milestones are recorded in [implementation-plan.md](docs/implementation-plan.md),
with the automatic live grid before motion-timeline investigation. The proposed
API calls and frontend module boundaries are in [backend-api-plan.md](docs/backend-api-plan.md).
The staged [History view plan](docs/history-view-plan.md) covers the recent-hours
timeline, SDK motion investigation, independent playback and required test changes.

The SDK's recording APIs and the proposed bounded playback experiment are
documented in [historical-playback investigation](docs/historical-playback-investigation.md).
The successful extraction and its reproduction command are in
[historical-playback results](docs/historical-playback-results.md).

## Open the browser viewer

```sh
python3 tools/run_browser_viewer.py
```

Open <http://localhost:8088/>; the grid starts automatically. **Pause view**
releases only this page’s subscriptions. Abandoned views expire after 90 seconds
by default; other viewers keep their streams. **History** shows a selected
camera's recording/motion timeline without requiring a saved private clip.
Click a time or motion interval to play its footage; Pause/Resume and Stop
control only your playback. One historical viewer slot is currently admitted.
Expand uses overview quality. Credentials stay in
the Docker backend. To stop the web server:

```sh
python3 tools/run_browser_viewer.py --stop
```

## Native Git LFS

The complete original Linux64 SDK archive is in `vendor/hikvision/` using Git
LFS. It includes the vendor binaries and documents, so they can be restored
without repeating the difficult download. Extracted files stay in `.local/`.

Install Git LFS on the host so it shares Git and VS Code authentication.
On Ubuntu/Debian, install it and configure this checkout:

```sh
sudo apt-get install git-lfs
python3 tools/setup_git_lfs.py
git lfs version
```

The setup script replaces older Docker LFS filters with native ones and
configures `core.hooksPath` to the committed `.githooks` directory. It preserves
the publication pre-push hook, which scans history before `git lfs pre-push`.
Run Git and the setup script as your normal user, without sudo. Compilers,
decoder libraries and investigation/browser tools still run in Docker.

After cloning from a future remote that stores the LFS objects, run the setup
above, then retrieve and materialize the SDK:

```sh
git lfs pull
git lfs fsck
```

The ZIP's Git LFS object lives in `.git/lfs/objects/`, while Git history contains
an LFS pointer. The remote must support LFS; pushing through the configured hook
uploads those objects as well as history. Native Git LFS uses host Git's
credentials, including VS Code's authentication when pushing from VS Code.
For terminal pushes to GitHub, configure the already-installed GitHub CLI:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
git push --set-upstream origin main
```

GitHub CLI's login is interactive; complete it yourself. Keep tokens out of
remote URLs and repository files. Use the setup script rather than
`git lfs install --force` alone, which could overwrite the publication hook.

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
For an offline PlayCtrl/key-setter check, use `check --decrypt`. See
[encrypted-stream investigation](docs/encrypted-stream-investigation.md) for
the verified full-key call sequence and the separate live probe command.

## Private credentials and validation

Enter your NVR IP, SDK port and settings in `.local/nvr-config.json`; the viewer
and authenticated SDK runner use that file. The schema is in
[GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md).

Live probes read `.local/nvr-credentials.json` with `username`, `password` and
optional `verification_code` fields. Keep its permissions at `0600` and its
parent directory at `0700`. The current SDK adapter limits only the login password
to its first 16 characters, preserving the full encryption code; see
[credential-loading.md](docs/credential-loading.md).

The current SDK's credential policy and native build/launch details are isolated
behind a small [Python adapter seam](docs/sdk-adapter-seam.md), with contributor
instructions for a later SDK implementation.

Credentials, camera captures, SDK debug logs and APK analysis are ignored.
Run the existing credential checks with:

```sh
python3 -m unittest discover -s tests -v
```

## UI tests without a recorder

Run `python3 tools/run_ui_tests.py --build` once to build the browser image, then
`python3 tools/run_ui_tests.py`. The suite uses Docker Chromium, the real HTTP
service and frontend, and a simulated worker with synthetic footage. No SDK or
private configuration is mounted and networking is disabled. See
[UI testing](docs/ui-testing.md) for coverage, single-case runs and result files.

The [GitHub Actions workflow](.github/workflows/ci.yml) runs both suites on pushes
and pull requests, with downloadable UI reports/screenshots. It uses synthetic
footage and skips the SDK download; no recorder secrets are needed. A local
commit is checked after pushing to GitHub. See [CI details](docs/ui-testing.md#github-actions).

Before publishing, run `python3 tools/check_publication.py --history`; the
pre-push hook also runs it. See [publication checks](docs/publication-checks.md)
for scan scope and private history backups.
