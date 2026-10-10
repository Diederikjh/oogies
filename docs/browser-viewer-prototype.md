# Browser viewing prototype

Update: [picture proportions](image-display-aspect.md) now use a shared frontend
module with selectable 16:9/4:3/Original display ratios for live and recorded
views. The encoded dimensions and saved files are unchanged.

Verified on 10 October 2026 using Chromium inside Docker. Historical extraction
was committed separately as `a123e1f` before this prototype was developed.

## Working behavior

Open `http://localhost:8088/` on this computer. **Start live view** starts one
SDK login/preview for camera 1's substream. PlayCtrl applies the full verification
code and decodes the encrypted video. A native worker converts the latest raw
YV12 frame to JPEG at up to 10 updates per second; the Python backend serves
those frames as `multipart/x-mixed-replace` for an ordinary browser `<img>`.

The page shows live status and received-frame counts. **Stop** closes the shared
preview, releases PlayCtrl, logs out and cleans up the SDK. A session also ends
after ten minutes by default; there is no automatic login or reconnect. Opening
or refreshing the page and adding viewers do not create new recorder sessions.
Repeated Start while a session exists is idempotent. Stop affects all viewers
of the shared camera.

**Recorded clip** plays the previously extracted five-second H.264 MP4 using a
native HTML `<video>` with browser controls. This does not contact the recorder.
HTTP byte ranges support seeking, and the displayed clip times are taken from
its extraction report. The prototype does not provide arbitrary historical
queries or a recording calendar yet.

The browser receives images, the extracted MP4 and status counters. Credentials
and encryption codes stay in the backend's read-only file mount and native
process stdin; they are absent from URLs, HTML, JavaScript and status responses.

## Run and stop

Uses the existing SDK runtime image; no new tools are installed on the host:

```sh
python3 tools/run_browser_viewer.py
# Open http://localhost:8088/ and click Start live view.

python3 tools/run_browser_viewer.py --stop
```

Optional settings: `--port 8088`, `--session-seconds 600` (maximum 900).
The launcher publishes only `127.0.0.1`, so this prototype is available on the
local computer. The recorder remains reachable from Docker's bridge network.
The server compiles the native bridge once at startup; it performs no device
login until Start is requested.

The launcher mounts only the SDK, backend source, frontend assets, shared
credential loader, private credential file and private output directory. If a
historical MP4 exists, only the latest such file is mounted for playback. It
does not expose the workspace or general filesystem through HTTP.

Docker limits the backend to 2 CPUs, 2 GiB memory and 512 processes, with a
read-only container root and a 128 MiB temporary directory. Frame buffering
retains the latest decoded frame/JPEG; slow clients skip frames rather than
queueing them. There are at most eight MJPEG viewers with socket write timeouts.
No growing live-video recording is saved. Session reports and the latest frame
are private under `.local/browser-viewer/` and ignored by Git.

## Why MJPEG for this milestone

It directly bridges the already verified decoded frames into a browser, with
little infrastructure and no browser plugin or cloud service. It is video only
and less bandwidth-efficient than H.264. The next transport investigation can
compare H.264 delivery through HLS or WebRTC when bandwidth, audio and latency
requirements are established.

The prototype uses the HTTP multipart media type and ordinary image rendering;
references: [MDN Content-Type](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Type),
[HTML image element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/img),
and [HTML video element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/video).

## Verification

- Native SDK initialization, PlayCtrl key configuration and dummy-frame JPEG
  conversion passed offline, with networking disabled and no credentials.
- Four unit-test groups passed, including concurrent Start sharing one process,
  status reads causing no new process, Stop cleanup, HTTP byte-range validation,
  and credential truncation/preservation checks.
- Chromium played the MP4: 960 × 1088, duration 5 seconds; its decoded-frame
  counter and playback position advanced.
- Chromium displayed live camera imagery at 352 × 288. Canvas pixel hashes
  changed over two seconds, and 49 received frames were observed before Stop.
- An explicit repeated Start request and a page refresh reused the same session.
- The native result confirms **one login call**, SDK error 0, 81 decoded video
  frames, 50 published JPEGs, video encryption type 2, and decoder error 0.
- Stop returned the server to its stopped state. No camera session is left
  running after verification; the local web server remains ready for the user.
- Private-file paths return 404. Foreign Host/Origin requests and non-JSON Start
  requests are rejected. Recorded-video range requests return 206 correctly.

Screenshots and verification JSON are private in `.local/browser-check/`.
The tested native report is
`.local/browser-viewer/browser-20261010T131221Z-4324e0e4/result.json`.

The reproducible browser check lives in `tools/check_browser_viewer.py` and uses
the existing `cam-hik-sdk-browser:local` image. The default check plays only the
saved clip; `--live` explicitly starts one camera session and stops it afterward.
Chromium's read-only container needs writable temporary XDG config/cache paths.

## Scope

This is a single-camera local viewing prototype, with no audio, camera selector,
arbitrary historical playback UI or automatic reconnect. Recording search still
requires compatibility investigation. Further work can extend these capabilities
incrementally from the proven acquisition and browser-rendering paths.
