# Diagnosing UI input timing

Input/request tracing is a temporary investigation technique, not part of the
normal UI suite. The former `tests/ui/live_action_trace.js` and its hooks have
been removed. Keep the native keyboard interactions, pause acknowledgement and
backend cleanup assertions in [test_live.py](../tests/ui/test_live.py) and
[browser_support.py](../tests/ui/browser_support.py).

## Why capture the input itself?

A timeout shows the page after the failure. For example, `animating:0` twelve
seconds later cannot tell us whether a button was moving when Selenium clicked.
Waiting for media or an HTTP reply does not guarantee stable pointer geometry.

During the Stop timeout investigation, a controlled 400 ms delay between moving
the pointer and pressing it allowed automatic scrolling to move Stop up 148
pixels. The click hit a camera button, no session DELETE was sent, and the
backend retained one viewer/nine sources. Ordinary runs passed. This demonstrated
a timing mechanism consistent with CI's state; the exact CI sequence was not
recorded. Evidence and test results are in [UI testing](ui-testing.md).

## What to record temporarily

Use a per-document ring buffer, capped at around 80 events. Record only the
offline fixture, and keep exported evidence under ignored `.local/` paths.

| Event | Useful fields |
| --- | --- |
| Captured `pointerdown`, `pointerup`, `click`, `keydown` | Event target/button ID, camera ID where available, coordinates or key, `performance.now()` timestamp |
| Geometry at each event | `scrollY`, Stop button rectangle/disabled state, number of `.camera-tile.is-animating` elements |
| Live-session POST/PATCH/DELETE | Method, relative path, dispatch/completion timestamps, response status or error |
| Failure snapshot | Page summary and backend viewer/source/start/stop counts |

Do not record credentials, request bodies, image data or real-recorder URLs.
Capture in the browser's event capture phase so the event-time state precedes
the application's click handler. Observe fetch outcomes without consuming or
altering response bodies, errors, abort signals or held-reply fault injection.
Label intercepted/simulated requests when a fault wrapper bypasses actual fetch.

## How to bring it back for an investigation

1. Add a temporary browser script in `tests/ui/` and load it before navigation
   from `browser_support.py` with Selenium's
   `Page.addScriptToEvaluateOnNewDocument`. Attach input listeners
   and wrap `window.fetch` to append the fields above to a bounded buffer.
2. Instrument each relevant tab separately. Registration on the initial tab
   does not automatically cover new tabs; navigation also creates a new trace.
3. Include the trace alongside the existing page/backend state in timeout
   diagnostics. Save `<test-name>.actions.json` during teardown before checking
   console errors, so failing tests still produce evidence.
4. Temporarily add `.local/ui-test-results/*.actions.json` to the artifact paths
   in `.github/workflows/ci.yml`, keeping the normal report and screenshots.
5. Verify the script on one offline case, including console errors, captured
   native input and successful DELETE, before expanding the run. Test-only
   instrumentation can itself affect scheduling.
6. Remove the script, hooks and extra artifact paths after investigation; retain
   the findings and the smallest verified test/application correction.

## Interpreting the trace

| Observation | Next investigation |
| --- | --- |
| Stop click absent, another target receives the press | Pointer geometry, animation or automatic scrolling |
| Stop click recorded, DELETE absent | Event handling, synchronous exception or application state |
| DELETE dispatched without a completion | Browser transport, fault injection or blocked HTTP handler |
| DELETE completes but resources remain | Backend ownership, reconciliation or native-stop acknowledgement |

Run ordinary reruns first. For a controlled reproduction, poll the held-reply
gate early, then use native `ActionChains` to move to Stop, pause and press at
the same pointer coordinates while automatic scrolling continues. Compare with
native Enter activation while the reply remains held. Slowing animation can
help exercise overlap, but is a separate experiment from ordinary CI timing.

Use keyboard activation for ownership tests whose purpose is lease/resource
behavior. Preserve dedicated pointer/animation tests. Do not replace a missing
activation with retries, larger cleanup timeouts or a JavaScript `.click()` that
bypasses native input. A controlled reproduction supports a mechanism; retain
uncertainty about CI until the failing CI event sequence is captured.
