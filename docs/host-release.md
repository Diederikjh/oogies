# Run a local release on the host

This is the milestone-2 path for an owner already running the development
viewer. It uses a locally built, checked Linux amd64 image. New users of a
published image should use [INSTALL.md](../INSTALL.md), which selects `0.0.2`.
End-to-end installation was previously verified with public `0.0.1`. See the
[release plan](release-plan.md).

Already using a Compose installation? Keep its directory and private `.local/`
state. Pull the chosen image using [INSTALL.md](../INSTALL.md), replace only
`OOGIES_IMAGE` in the existing `.env` with the pulled image ID, and run
`docker compose up -d --wait --wait-timeout 60` after exports finish. Do not
download example credentials over existing settings or run the new-directory
preparation command below. This was verified when switching the local build to
public version `0.0.1`; future schema-changing upgrades need their own procedure.

## Prepare and verify

Use your normal Linux user, with Docker and Docker Compose 2.20+ available
without sudo. Docker must be running; boot recovery also requires the Docker
daemon to start on boot. No additional host compiler, SDK extraction, Python
packages or Node installation is needed. Preparation/check scripts use existing
Python 3.9+ and Git, as described in [the local release guide](release-images.md).

```sh
docker info >/dev/null
docker compose version
python3 tools/build_release.py
python3 tools/check_release_image.py
python3 tools/check_host_release.py
```

The host check uses a temporary installation and synthetic export/configuration
with networking disabled. It renders the actual Compose settings, checks
readiness without logging into a recorder, crashes the application to verify
automatic recovery, and verifies a persisted export download and output marker
after restart and a graceful stop/start. It does not touch the owner's service.
Expect `passed: true` and `login_calls: 0` in
`.local/releases/last-host-check.json`; diagnostic logs are adjacent.

## Cut over from development

Schedule a brief interruption. Stop viewing and finish/cancel queued or running
exports first. Inspect `http://localhost:8088/api/status` and `/api/exports`;
`active_exports` must be zero and no export may be queued/running. Do not open
new views or queue jobs during the switch.

From the checkout, stop the development service:

```sh
python3 tools/run_browser_viewer.py --stop
python3 tools/install_release.py
```

The default installation is `$HOME/.local/share/oogies`, outside the checkout.
Use `--directory /path/to/oogies` for another location,
or `--image oogies:<local-version>` to select a previously checked
image. The installer resolves the image to its immutable local ID and checks
its platform/SDK profile. It refuses an existing installation, active source
containers, pending exports, missing ready clips and symlink state.

Preparation copies configuration, credentials and export storage into the new
installation's `.local/`. It verifies ready clip hashes, restricts permissions
and leaves the source state intact. It copies the Compose file and writes a
private `.env` containing the fixed image ID, host UID/GID, port and project
name. Runtime output starts in a separate directory. No service starts until
the next command; preparation can fail without replacing the old state.

```sh
cd "$HOME/.local/share/oogies"
docker compose config --quiet
docker compose up -d --wait --wait-timeout 60
docker compose ps
```

Open `http://localhost:8088`. Existing browser tabs should
be refreshed after cutover. Verify the existing ready exports, then make one
bounded live-view check and stop viewing. Authentication rejection requires
investigation; readiness checking must not trigger login retries.

## Operation and state

Run these commands from the installation directory; the checkout is not needed:

```sh
docker compose ps
docker compose logs --tail 100
docker compose stop
docker compose up -d --wait --wait-timeout 60
```

The copied Compose file mounts only `.local/nvr-config.json` and
`.local/nvr-credentials.json` read-only, plus writable `.local/exports` and
`.local/output`. Edit the installation's private configuration for future
settings, then recreate the container. Editing the development checkout does
not change the release's code or configuration. Preserve the installation
directory and do not give a second running instance its export manifest.

The service runs as the installing user, with a read-only root filesystem,
two CPUs, 2 GiB memory/no additional swap, bounded PIDs and a temporary `/tmp`.
HTTP is published only on loopback; the container can reach the NVR through its
ordinary Docker network. The current Compose file binds both `127.0.0.1` and
`::1`, so `localhost` works with IPv4 or IPv6. The published `v0.0.1` Compose
file binds IPv4 only; use `http://127.0.0.1:8088` with that file.
Logs rotate at 5 MiB with two files. Shutdown gets
30 seconds to release sessions/workers and close export state.

Readiness checks `/api/status` over container loopback; it neither starts the SDK
worker nor requests cameras. An HTTP-ready service can still report a recorder
authentication/video error. Docker's `unless-stopped` policy recovers a crashed
process and supports daemon/host restart, while an explicit stop remains stopped.
An unhealthy status alone does not restart the process or trigger recorder login.
See [Docker's restart policy documentation](https://docs.docker.com/engine/containers/start-containers-automatically/)
and [Compose service settings](https://docs.docker.com/reference/compose-file/services/).

The image uses `pull_policy: never`: local operation never silently downloads or
switches versions. Keep its image present. A future registry installation must
pull its selected version/digest explicitly before starting.

## Revert this cutover

If release startup fails, stop/remove its container with `docker compose down`
from the installation directory. Confirm it has stopped, then return to the
checkout and run `python3 tools/run_browser_viewer.py`. The development state
and SDK remain available. Do not run both instances against the same exports.

The original state is a cutover snapshot. New exports/settings created in the
release installation stay there when reverting; keep them and reconcile state
with both instances stopped before resuming development. This milestone does
not implement schema migration or automatic state rollback. Subsequent release
upgrades and rollback procedures belong to milestone 5.
