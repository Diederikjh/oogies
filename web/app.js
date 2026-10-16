import {Overview} from "/live/overview.js";
import {HistoryView} from "/history/history-view.js";
import {DisplaySettings} from "/settings/display-settings.js";
import {ExportsView} from "/history/exports.js";

const byId = id => document.getElementById(id);
const historyEvents = document.querySelector(".history-events-panel");
historyEvents.open = !window.matchMedia("(max-width: 900px)").matches;
let mode = "live";
const overview = new Overview(byId("camera-grid"), (session, quality = {high:0}) => {
  const live = session?.cameras.filter(camera => camera.state === "live").length || 0;
  const total = session?.cameras.length || overview.tiles.size;
  byId("grid-summary").textContent = mode === "history" ? "Timeline" : mode === "exports" ? "Downloads" : session ? `${live} live · ${total} cameras` : "View paused";
  byId("stop").disabled = !session;
  byId("start").disabled = Boolean(session);
  if (session) byId("message").textContent = "";
  if (mode === "live") byId("view-note").textContent = quality.high ? `Video only · ${quality.high} high quality` : "Video only · Overview quality";
}, message => { byId("message").textContent = message; byId("start").disabled = false; },
  () => settings.camerasReady(), cameraId => showMode("history", cameraId));
const history = new HistoryView(byId("history-panel"), () => settings.camerasReady(), () => showMode("exports"));
const exportsView = new ExportsView(byId("exports-panel"));
const settings = new DisplaySettings(byId("display-settings"), overview.tiles, (id, aspect) => history.player.setAspect(id, aspect), () => history.cameras || []);

async function showMode(next, cameraId) {
  mode = next;
  document.body.classList.toggle("history-mode", next === "history");
  byId("live-panel").hidden = next !== "live";
  byId("history-panel").hidden = next !== "history";
  byId("exports-panel").hidden = next !== "exports";
  byId("view-title").textContent = next === "history" ? "Camera history" : next === "exports" ? "Exports" : "Live overview";
  byId("view-note").textContent = next === "history" ? "Video only · Recorded footage" : next === "exports" ? "Video only · MP4 downloads" : "Video only · Overview quality";
  if (next === "history") byId("grid-summary").textContent = "Timeline";
  if (next === "exports") byId("grid-summary").textContent = "Downloads";
  document.title = `Oogies · ${byId("view-title").textContent}`;
  for (const name of ["live", "history", "exports"]) {
    byId(name + "-tab").classList.toggle("selected", name === next);
    byId(name + "-tab").setAttribute("aria-pressed", String(name === next));
  }
  exportsView.hide();
  if (next === "history") { history.show(cameraId); await overview.stop(); }
  else if (next === "exports") { exportsView.show(); await Promise.all([history.hide(), overview.stop()]); }
  else { await history.hide(); if (mode === "live") await overview.start(); }
}

byId("start").addEventListener("click", () => overview.start());
byId("stop").addEventListener("click", () => overview.stop());
byId("live-tab").addEventListener("click", () => showMode("live"));
byId("history-tab").addEventListener("click", () => showMode("history"));
byId("exports-tab").addEventListener("click", () => showMode("exports"));
window.addEventListener("pagehide", () => { overview.releaseOnClose(); history.player.releaseOnClose(); history.hide(); });
window.addEventListener("pageshow", event => { if (event.persisted) {
  if (mode === "live") overview.stop().then(() => overview.start()); else if (mode === "history") history.show(); else exportsView.show();
} });
overview.start();
