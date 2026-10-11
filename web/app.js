import {Overview} from "/live/overview.js";
import {HistoryView} from "/history/history-view.js";
import {DisplaySettings} from "/settings/display-settings.js";

const byId = id => document.getElementById(id);
let mode = "live";
const overview = new Overview(byId("camera-grid"), session => {
  const live = session?.cameras.filter(camera => camera.state === "live").length || 0;
  const total = session?.cameras.length || overview.tiles.size;
  byId("grid-summary").textContent = mode === "history" ? "Timeline" : session ? `${live} live · ${total} cameras` : "View paused";
  byId("stop").disabled = !session;
  byId("start").disabled = Boolean(session);
  if (session) byId("message").textContent = "";
}, message => { byId("message").textContent = message; byId("start").disabled = false; },
  () => settings.camerasReady(), cameraId => showMode("history", cameraId));
const history = new HistoryView(byId("history-panel"), () => settings.camerasReady());
const settings = new DisplaySettings(byId("display-settings"), overview.tiles, (id, aspect) => history.player.setAspect(id, aspect), () => history.cameras || []);

async function showMode(next, cameraId) {
  mode = next;
  byId("live-panel").hidden = next !== "live";
  byId("history-panel").hidden = next !== "history";
  byId("view-title").textContent = next === "history" ? "Camera history" : "Live overview";
  byId("view-note").textContent = next === "history" ? "Video only · Recorded footage" : "Video only · Overview quality";
  if (next === "history") byId("grid-summary").textContent = "Timeline";
  document.title = `Oogies · ${byId("view-title").textContent}`;
  for (const name of ["live", "history"]) {
    byId(name + "-tab").classList.toggle("selected", name === next);
    byId(name + "-tab").setAttribute("aria-pressed", String(name === next));
  }
  if (next === "history") { history.show(cameraId); await overview.stop(); }
  else { await history.hide(); if (mode === "live") await overview.start(); }
}

byId("start").addEventListener("click", () => overview.start());
byId("stop").addEventListener("click", () => overview.stop());
byId("live-tab").addEventListener("click", () => showMode("live"));
byId("history-tab").addEventListener("click", () => showMode("history"));
window.addEventListener("pagehide", () => { overview.releaseOnClose(); history.player.releaseOnClose(); history.hide(); });
window.addEventListener("pageshow", event => { if (event.persisted) {
  if (mode === "live") overview.stop().then(() => overview.start()); else history.show();
} });
overview.start();
