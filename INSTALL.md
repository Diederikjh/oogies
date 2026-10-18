# Install Oogies from a Docker image

For a new installation on a Linux x86-64 computer that can reach your NVR.
You need Docker Engine, Docker Compose 2.20+ and `curl`. Git, Git LFS, Python,
Node, compilers and a separate SDK download are not needed.

Version **0.0.1** is public and can be pulled without signing in to GitHub.
Existing local-build users should follow [the host release guide](docs/host-release.md)
to preserve their settings and exports.

## 1. Create the installation directory

Run all Docker commands as your normal user, **without sudo**. If Docker is
missing or access fails, follow [Docker's installation](https://docs.docker.com/engine/install/)
and [Linux setup instructions](https://docs.docker.com/engine/install/linux-postinstall/),
then continue below.

Choose a published version and download its matching setup files. Use a new
directory; do not overwrite an existing installation's configuration:

```sh
OOGIES_VERSION=0.0.1
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
├── .env                        # Image and user IDs; created below
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
The earlier `umask 077` keeps new files/directories private. The downloaded
examples contain placeholders, not working credentials.

## 3. Pull and start

From the same directory and terminal, with `OOGIES_VERSION` still set:

```sh
docker pull "ghcr.io/diederikjh/oogies:${OOGIES_VERSION}"
```

Pin the image you just pulled and use your user/group IDs for private files:

```sh
cat > .env <<EOF
# Oogies ${OOGIES_VERSION}
OOGIES_IMAGE=$(docker image inspect --format '{{.Id}}' "ghcr.io/diederikjh/oogies:${OOGIES_VERSION}")
OOGIES_UID=$(id -u)
OOGIES_GID=$(id -g)
EOF
docker compose up -d --wait --wait-timeout 60
```

Open **http://127.0.0.1:8088** on this computer. Confirm the live images move.
The `v0.0.1` Compose file binds IPv4 loopback only; use this address if your
browser resolves `localhost` to IPv6.
The published port is local to this computer. A healthy container means the
web service is ready; recorder login/video still depends on your settings.
Images are not automatically upgraded when you restart the computer.

## 4. Start automatically after reboot

The Compose file already sets `restart: unless-stopped`. Docker starts the
existing container when the host starts, provided Docker itself is enabled at
boot. On a standard Linux system using systemd, run this once if needed:

```sh
sudo systemctl enable --now docker.service containerd.service
```

Administrator access is needed for this system service command; continue running
Docker commands as your normal user. No separate Oogies systemd unit or
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
