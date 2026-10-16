# Getting started

This project is a local browser viewer for Hikvision cameras. The current
service automatically shows discovered cameras in a live grid. The History tab
shows recent recording coverage and motion intervals returned by the SDK.

**Using a coding agent to set up your machine?** Give it
[GETTING_STARTED_AGENTS.md](GETTING_STARTED_AGENTS.md). That guide contains the
installation commands, prerequisite checks and verification checklist.

## What you need

- A Linux x86-64 machine with Git, native Git LFS, Python 3.9+ and Docker with build support.
- Docker working as your normal user **without sudo**. Verify with
  `docker info` and `docker run --rm hello-world`.
- A browser, internet access for initial setup, and network access to your NVR.
- Your NVR IP address, SDK/server port, timezone, account credentials and stream
  encryption password.

The Hikvision SDK is already included through Git LFS; no separate vendor
download is needed. Compilers, decoding libraries and additional project tools
run in Docker.

## Setup flow

1. Install native Git LFS, clone the repository, run
   `python3 tools/setup_git_lfs.py`, then retrieve its SDK archive with `git lfs pull`.
2. Build the Docker runtime, extract the SDK into `.local/`, and run the offline
   SDK check.
3. Save your account details in `.local/nvr-credentials.json`. Its
   `verification_code` field holds the full stream **Encryption Password**,
   which may differ from your login password. Keep the file private and outside
   Git.
4. Enter your NVR settings in `.local/nvr-config.json`; see the agent guide for
   its schema and optional camera overrides.
5. Start the service, open the page and check that live images move.

The [agent guide](GETTING_STARTED_AGENTS.md) has the exact commands for each step
and instructions for installing missing prerequisites.

The current SDK has been verified on the original DS-7108HGHI-K1, including
seven simultaneous analog/IP previews. Other recorder/firmware combinations need
verification. The repository remote must include the SDK's Git LFS object.

## Run the viewer

Once configuration, credentials and the SDK are ready:

```sh
python3 tools/run_browser_viewer.py
```

Open <http://localhost:8088/>. The live grid starts automatically. **Pause view**
releases your subscriptions; other viewers keep their cameras.

Camera availability is cached for one minute. Offline cameras are rechecked
while the grid is active and return automatically when they recover.

Click a camera picture to expand it; click again to collapse. Enter and Space
work too. Expand/collapse animates smoothly and scrolls the picture into view;
manual scrolling immediately takes control. Reduced-motion preferences are
respected. Expansion requests high quality and keeps overview video moving until
the upgraded picture is ready. Collapsing returns to overview. If high quality is
unavailable, the enlarged picture keeps overview quality and shows a short reason
in its quality label, with details in a tooltip; collapse and expand again to retry.
An interrupted video feed reconnects up to three times using the same session.
Delayed live pictures are dimmed and labeled; if recovery fails, use **Resume
view**. For History, select a time again. Recorder login is never retried automatically.
Change picture proportions
under **Settings → Picture proportions**; your browser remembers each camera’s
choice, including that camera's History playback.

Optional
`max_high_quality_sources` in `.local/nvr-config.json` defaults to one shared
high-quality source; zero disables it. Each high source needs an extra slot in
the total `max_live_sources` budget. Viewers expanding the same camera share that
source; another camera can stay at overview when capacity is occupied. See
[live quality](docs/live-quality-plan.md).

Use a camera's **History** button to open its timeline, or open the **History**
tab to select a camera and browse the last three hours. You can choose
1/6 hours and earlier ranges. Recording coverage and motion are separate tracks.
Click a band/event or commit a time-slider selection to play recorded footage.
To jump directly, enter **Date & time** and press **Go to time**. The displayed
recorder timezone applies; the chosen camera's timeline and playback move there.
Pause/Resume and Stop control your player; another time selection seeks, including
while paused. No saved footage is required. Switching views preserves other
viewers' streams. Speed buttons select **0.5×, 1×, 2× or 4×**; your choice is
preserved through seeking and Pause/Resume. One historical viewer slot is currently
admitted; Stop releases it. The installing user's source budget must have room
for live plus playback.

In History, use **Back/Forward 10s/30s** for finer seeking. **Download current
frame** saves a PNG directly, with your chosen picture proportions.
Use **Mark start**, **Mark end**, then **Queue export** to save a clip of up to
ten minutes. Setting both marks zooms the timeline around them. Drag either
Start/End handle to adjust the range; it cannot cross the other handle or exceed
the limit. Arrow keys also work. **Full range** restores the complete timeline.
The **Exports** tab lists shared
jobs and offers cancellation, MP4 download and deletion. Jobs keep running when
you close the browser; downloads are retained for 24 hours by default. An active
export needs one additional recorder stream slot. See [clip downloads](docs/clip-exports.md).

To stop the service:

```sh
python3 tools/run_browser_viewer.py --stop
```

The viewer is currently available only on the machine running it. A closed or
killed tab’s subscriptions expire within about 90 seconds of its last renewal;
the last subscriber leaving stops that camera stream.

See [progress.md](progress.md) for verified results and the
[implementation plan](docs/implementation-plan.md) for upcoming milestones.
Both getting-started guides will be updated as setup and behavior change.

Contributors can start with [the Python SDK adapter seam](docs/sdk-adapter-seam.md).

Developers can run [offline UI tests](docs/ui-testing.md) in Docker without a
recorder or private configuration.
