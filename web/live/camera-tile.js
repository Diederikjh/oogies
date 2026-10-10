import {MediaDisplay} from "/shared/media-player.js";
import {readAspect, saveAspect} from "/shared/display-preferences.js";

const LABELS = {starting:"Connecting", live:"Live", stale:"Video delayed", offline:"Offline",
  error:"Unavailable", capacity_limited:"Stream limit", stopping:"Stopping", stopped:"Stopped"};

export class CameraTile {
  constructor(camera, grid) {
    this.camera = camera;
    this.element = document.createElement("article");
    this.element.className = "camera-tile";
    this.element.dataset.cameraId = camera.id;
    this.element.innerHTML = `<div class="tile-heading"><h2></h2><span class="tile-badge">Connecting</span></div>
      <button type="button" class="viewer camera-view" aria-expanded="false"><img hidden><span class="tile-placeholder">Connecting to camera…</span>
        <span class="expand-hint" aria-hidden="true">Expand</span></button>
      <div class="tile-controls"><span class="tile-metrics">Overview</span></div>`;
    this.element.querySelector("h2").textContent = camera.name;
    this.image = this.element.querySelector("img");
    this.image.alt = `Live video from ${camera.name}`;
    this.placeholder = this.element.querySelector(".tile-placeholder");
    this.badge = this.element.querySelector(".tile-badge");
    this.metrics = this.element.querySelector(".tile-metrics");
    this.view = this.element.querySelector(".camera-view");
    grid.append(this.element);
    this.display = new MediaDisplay(this.image, this.view);
    this.aspect = readAspect(camera.id, camera.aspect_ratio || "16:9");
    this.display.setAspect(this.aspect);
    this.view.setAttribute("aria-label", `Expand ${camera.name}`);
    this.view.addEventListener("click", () => {
      const expanded = this.element.classList.toggle("is-expanded");
      this.view.setAttribute("aria-expanded", String(expanded));
      this.view.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${camera.name}`);
      this.element.querySelector(".expand-hint").textContent = expanded ? "Collapse" : "Expand";
    });
    this.url = null;
    this.decoding = false;
    this.hasFrame = false;
    this.disposed = false;
  }

  setAspect(value) {
    this.aspect = saveAspect(this.camera.id, value);
    this.display.setAspect(this.aspect);
  }

  frame(jpeg) {
    if (this.decoding || this.disposed) return; // Slow tiles skip frames instead of buffering.
    this.decoding = true;
    const previous = this.url;
    const next = URL.createObjectURL(new Blob([jpeg], {type:"image/jpeg"}));
    this.url = next;
    this.image.onload = () => {
      if (previous) URL.revokeObjectURL(previous);
      this.decoding = false;
      if (!this.disposed && !this.hasFrame) {
        this.hasFrame = true;
        this.image.hidden = false;
        this.placeholder.hidden = true;
      }
    };
    this.image.onerror = () => { if (previous) URL.revokeObjectURL(previous); this.decoding = false; };
    this.image.src = next;
  }

  paint(status) {
    this.element.dataset.state = status.state;
    this.badge.textContent = LABELS[status.state] || status.state;
    this.metrics.textContent = status.width ? `${status.width} × ${status.height} · Overview` : "Overview";
    this.placeholder.textContent = status.error || LABELS[status.state] || "Connecting…";
    this.element.title = status.error || "";
  }

  pause() { this.paint({state:"stopped"}); }

  dispose() {
    this.disposed = true;
    this.display.dispose();
    this.image.removeAttribute("src");
    if (this.url) URL.revokeObjectURL(this.url);
    this.element.remove();
  }
}
