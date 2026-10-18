# Install Oogies from a Docker image

For a new installation on a Linux x86-64 computer that can reach your NVR.
You need Docker Engine, Docker Compose 2.20+ and `curl`. Git, Git LFS, Python,
Node, compilers and a separate SDK download are not needed.

**Release availability:** these instructions are prepared for published images.
The first GHCR publication has not yet been verified. Choose a version whose
**Release image** GitHub Actions run succeeded; `0.1.0` below is an example,
not a claim that this version is available. Existing local-build users should
follow [the host release guide](docs/host-release.md).

## 1. Create the installation directory

Verify Docker works as your normal user, **without sudo**:

```sh
docker info >/dev/null
docker compose version
```

If Docker is missing or access fails, follow [Docker's installation](https://docs.docker.com/engine/install/)
and [Linux setup instructions](https://docs.docker.com/engine/install/linux-postinstall/),
then repeat the checks.

Choose a published version and download its matching setup files. Use a new
directory; do not overwrite an existing installation's configuration:

```sh
OOGIES_VERSION=0.1.0
umask 077
mkdir -p "$HOME/.local/share/oogies/.local/exports" "$HOME/.local/share/oogies/.local/output"
cd "$HOME/.local/share/oogies"
curl -fL "https://raw.githubusercontent.com/Diederikjh/oogies/v${OOGIES_VERSION}/docker/release/compose.yaml" -o compose.yaml
curl -fL "https://raw.githubusercontent.com/Diederikjh/oogies/v${OOGIES_VERSION}/docker/release/nvr-config.example.json" -o .local/nvr-config.json
curl -fL "https://raw.githubusercontent.com/Diederikjh/oogies/v${OOGIES_VERSION}/docker/release/nvr-credentials.example.json" -o .local/nvr-credentials.json
```

Files will live here:

```text
~/.local/share/oogies/
├── compose.yaml
├── .env                        # Image, user IDs and web port; created below
└── .local/
    ├── nvr-config.json          # Your NVR address and timezone
    ├── nvr-credentials.json     # Your private login and encryption password
    ├── exports/                # Downloadable clips and export entries
    └── output/                 # Runtime output
```

## 2. Enter your NVR settings

Edit `.local/nvr-config.json`:

- **`host`**: replace the example `192.0.2.10` with your NVR's IP address.
- **`sdk_port`**: the NVR's SDK/server port, normally `8000`; this is separate
  from its website or RTSP port.
- **`timezone`**: your recorder's timezone, such as `Africa/Johannesburg`.

Edit `.local/nvr-credentials.json`:

- **`username`** and **`password`**: your NVR account login.
- **`verification_code`**: the full stream **Encryption Password** shown in the
  NVR/Hik-Connect settings. It may differ from the account password.

Keep the files as valid JSON strings; escape quotes as `\"` and backslashes as
`\\` inside a password.
Keep both files private. The downloaded examples contain placeholders, not
working credentials.

```sh
chmod 700 .local .local/exports .local/output
chmod 600 .local/nvr-config.json .local/nvr-credentials.json
```

## 3. Pull and start

From the same directory and terminal, with `OOGIES_VERSION` still set:

```sh
docker pull "ghcr.io/diederikjh/oogies:${OOGIES_VERSION}"
```

For a private package, run `docker login ghcr.io` first using your GitHub
username and a personal access token (classic) with `read:packages` access.
Public images need no login.
See [GitHub's registry instructions](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Pin the image you just pulled and use your user/group IDs for private files:

```sh
cat > .env <<EOF
# Oogies ${OOGIES_VERSION}
OOGIES_IMAGE=$(docker image inspect --format '{{.Id}}' "ghcr.io/diederikjh/oogies:${OOGIES_VERSION}")
OOGIES_UID=$(id -u)
OOGIES_GID=$(id -g)
OOGIES_PORT=8088
OOGIES_PROJECT=oogies
EOF
docker compose config --quiet
docker compose up -d --wait --wait-timeout 60
docker compose ps
```

Open **http://localhost:8088** on this computer. Confirm the live images move.
The published port is local to this computer. A healthy container means the
web service is ready; recorder login/video still depends on your settings.
Images are not automatically upgraded when you restart the computer.

## 4. Start automatically after reboot

On a standard Linux system using systemd, enable Docker at boot:

```sh
sudo systemctl enable --now docker.service containerd.service
systemctl is-enabled docker.service
docker inspect "$(docker compose ps -q viewer)" --format '{{.HostConfig.RestartPolicy.Name}}'
```

Expect `enabled` and `unless-stopped`. Administrator access is needed for the
system service command; continue running Docker commands as your normal user.
The Compose file already sets `restart: unless-stopped`, so Docker starts the
existing container when the host starts. No separate Oogies systemd unit or
login script is needed. See [Docker's boot setup](https://docs.docker.com/engine/install/linux-postinstall/#configure-docker-to-start-on-boot-with-systemd)
and [restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/).

If you explicitly run `docker compose stop`, it stays stopped across reboots.
Run `docker compose up -d --wait` to enable it again. `docker compose down`
removes the container; run `up` again to recreate it.

## Everyday commands

Run these from `~/.local/share/oogies`:

```sh
docker compose ps                 # Health/status
docker compose logs --tail 100    # Diagnose a startup or connection problem
docker compose stop              # Stop until you start it again
docker compose up -d --wait       # Start again
```

After editing the NVR settings or credentials, finish/cancel active exports,
then run `docker compose up -d --force-recreate --wait`. Preserve the installation
directory; configuration, credentials and exported clips live in its `.local/`.

For source-based development or agent-assisted setup, see [Getting started](GETTING_STARTED.md)
and [the agent guide](GETTING_STARTED_AGENTS.md).
