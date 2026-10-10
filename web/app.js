"use strict";
const byId = id => document.getElementById(id);
let attachedSession = null;
let pending = false;
let mode = "live";
let latestStatus = null;

function paint(status) {
  latestStatus = status;
  const active = ["connecting", "live", "stalled", "stopping"].includes(status.state);
  byId("start").disabled = active || pending;
  byId("stop").disabled = !active || status.state === "stopping" || pending;
  byId("badge").textContent = mode === "recording" ? "Recorded" : ({connecting:"Connecting",live:"Live",stalled:"Video delayed",stopping:"Stopping",stopped:"Stopped",ended:"Session ended",error:"Unable to connect"}[status.state] || "Stopped");
  byId("badge").dataset.state = mode === "live" ? status.state : "recorded";
  const image = byId("live-image");
  if (mode === "live" && active && status.state !== "stopping") {
    if (attachedSession !== status.session) {
      image.src = "/stream.mjpeg?session=" + encodeURIComponent(status.session);
      attachedSession = status.session;
    }
    image.hidden = !status.frames;
    byId("placeholder").hidden = Boolean(status.frames);
  } else {
    image.removeAttribute("src");
    attachedSession = null;
    image.hidden = true;
    byId("placeholder").hidden = false;
  }
  byId("metrics").textContent = status.frames && active ? `${status.width} × ${status.height} · ${status.frames} frames received` : "Camera is stopped";
  byId("message").textContent = status.error || ({connecting:"Connecting to camera 1…",stalled:"No fresh frames have arrived. Stop and start the camera to try again.",stopping:"Stopping the camera…",ended:"This session has ended. Start live view for another session."}[status.state] || `Each live session lasts up to ${Math.round(status.session_seconds / 60)} minutes.`);
  if (status.recording_available === false) {
    byId("recording-tab").disabled = true;
    byId("recording-note").textContent = "No extracted recording is available yet.";
  }
  if (status.recording_begin && status.recording_end) {
    byId("recording-time").textContent = `${status.recording_begin.replace("T", " · ")}–${status.recording_end.split("T")[1]} · recorder time`;
    byId("recording-duration").textContent = `${Number(status.recording_seconds)} seconds · Camera 1`;
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/status", {cache:"no-store"});
    if (!response.ok) throw new Error("Viewer unavailable");
    paint(await response.json());
  } catch (error) {
    byId("message").textContent = "The viewer is unavailable. Check that the local server is running.";
  }
}

async function action(name) {
  if (pending) return;
  pending = true;
  byId("start").disabled = byId("stop").disabled = true;
  try {
    const response = await fetch(`/api/${name}`, {method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const status = await response.json();
    pending = false;
    paint(status);
  } catch (error) {
    pending = false;
    byId("message").textContent = "The camera request could not be completed.";
  }
  await refresh();
}

function showMode(next) {
  mode = next;
  byId("live-panel").hidden = next !== "live";
  byId("recording-panel").hidden = next !== "recording";
  for (const name of ["live", "recording"]) {
    byId(name + "-tab").classList.toggle("selected", name === next);
    byId(name + "-tab").setAttribute("aria-pressed", String(name === next));
  }
  if (next === "recording") {
    byId("recording").src = "/recording.mp4";
  } else {
    byId("recording").pause();
  }
  if (latestStatus) paint(latestStatus);
}

byId("start").addEventListener("click", () => action("start"));
byId("stop").addEventListener("click", () => action("stop"));
byId("live-tab").addEventListener("click", () => showMode("live"));
byId("recording-tab").addEventListener("click", () => showMode("recording"));
refresh();
setInterval(refresh, 1000);
