# Getting started

This project is a local browser viewer for Hikvision cameras. The current
prototype shows one encrypted live camera stream. A camera grid and historical
timeline are planned.

**Using a coding agent to set up your machine?** Give it
[GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md). That guide contains the
installation commands, prerequisite checks and verification checklist.

## What you need

- A Linux x86-64 machine with Git, Python 3.9+ and Docker with build support.
- Docker working as your normal user **without sudo**. Verify with
  `docker info` and `docker run --rm hello-world`.
- A browser, internet access for initial setup, and network access to your NVR.
- Your NVR IP address, SDK/server port, timezone, account credentials and stream
  encryption password.

The Hikvision SDK is already included through Git LFS; no separate vendor
download is needed. Compilers, decoding libraries and additional project tools
run in Docker.

## Setup flow

1. Clone the repository and retrieve its SDK archive through the Docker-based
   Git LFS wrapper.
2. Build the Docker runtime, extract the SDK into `.local/`, and run the offline
   SDK check.
3. Save your account details in `.local/nvr-credentials.json`. Its
   `verification_code` field holds the full stream **Encryption Password**,
   which may differ from your login password. Keep the file private and outside
   Git.
4. Enter your NVR settings once recorder configuration support is available.
5. Start the service, open the page and check that live images move.

The [agent guide](GETTING_STARTED_AGENTS.md) has the exact commands for each step
and instructions for installing missing prerequisites.

**Current limitation:** the prototype still targets `192.0.2.10:8000`.
Configurable recorder settings are the next milestone, so a fresh checkout
cannot yet view a different NVR without source changes. No public repository
remote has been configured yet. Live decoding has been verified on the original
DS-7108HGHI-K1; broader compatibility remains to be tested.

## Run the prepared prototype

Once setup is complete for the original recorder:

```sh
python3 tools/run_browser_viewer.py
```

Open <http://localhost:8088/> and choose **Start live view**. **Stop** ends the
camera stream. To stop the service:

```sh
python3 tools/run_browser_viewer.py --stop
```

The current viewer is available only on the machine running it. Camera sessions
end after ten minutes by default; closing a tab does not yet stop its session
automatically. A fresh clone has no saved footage for **Recorded clip**.

See [progress.md](progress.md) for verified results and the
[implementation plan](docs/implementation-plan.md) for upcoming milestones.
Both getting-started guides will be updated as setup and behavior change.
