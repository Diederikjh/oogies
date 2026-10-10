import {api} from "/shared/api.js";
import {Overview} from "/live/overview.js";
import {RecordedClip} from "/history/recorded-clip.js";
import {DisplaySettings} from "/settings/display-settings.js";

const byId = id => document.getElementById(id);
let mode = "live";
const overview = new Overview(byId("camera-grid"), session => {
  const live = session?.cameras.filter(camera => camera.state === "live").length || 0;
  const total = session?.cameras.length || overview.tiles.size;
  byId("grid-summary").textContent = session ? `${live} live · ${total} cameras` : "View paused";
  byId("stop").disabled = !session;
  byId("start").disabled = Boolean(session);
  if (session) byId("message").textContent = "Overview streams are shared across browser viewers.";
}, message => { byId("message").textContent = message; byId("start").disabled = false; }, () => settings.camerasReady());
const recording = new RecordedClip(byId("recording-panel"));
const settings = new DisplaySettings(byId("display-settings"), overview.tiles, recording);

async function showMode(next) {
  mode = next;
  byId("live-panel").hidden = next !== "live";
  byId("recording-panel").hidden = next !== "recording";
  for (const name of ["live", "recording"]) {
    byId(name + "-tab").classList.toggle("selected", name === next);
    byId(name + "-tab").setAttribute("aria-pressed", String(name === next));
  }
  if (next === "recording") { await overview.stop(); recording.show(); }
  else { recording.hide(); await overview.start(); }
}

byId("start").addEventListener("click", () => overview.start());
byId("stop").addEventListener("click", () => overview.stop());
byId("live-tab").addEventListener("click", () => showMode("live"));
byId("recording-tab").addEventListener("click", () => showMode("recording"));
window.addEventListener("pagehide", () => overview.releaseOnClose());
window.addEventListener("pageshow", event => { if (event.persisted && mode === "live") { overview.stop().then(() => overview.start()); } });

api("/api/status").then(status => {
  byId("recording-tab").disabled = !status.recording_available;
  if (status.recording_begin) byId("recording-time").textContent = `${status.recording_begin.replace("T", " · ")}–${status.recording_end.split("T")[1]} · recorder time`;
}).catch(() => {});
overview.start();
