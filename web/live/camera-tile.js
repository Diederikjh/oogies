import {MediaDisplay} from "/shared/media-player.js";

const LABELS = {starting:"Connecting", live:"Live", stale:"Video delayed", offline:"Offline",
  error:"Unavailable", capacity_limited:"Stream limit", stopping:"Stopping", stopped:"Stopped"};

export class CameraTile {
  constructor(camera, grid) {
    this.camera = camera;
    this.element = document.createElement("article");
    this.element.className = "camera-tile";
    this.element.dataset.cameraId = camera.id;
    this.element.innerHTML = `<div class="tile-heading"><h2></h2><span class="tile-badge">Connecting</span></div>
      <div class="viewer"><img hidden><div class="tile-placeholder">Connecting to camera…</div></div>
      <div class="tile-controls"><select aria-label="Picture proportions"><option value="16:9">16:9</option>
        <option value="4:3">4:3</option><option value="original">Original</option></select>
        <span class="tile-metrics">Overview</span><button class="expand" aria-expanded="false">Expand</button></div>`;
    this.element.querySelector("h2").textContent = camera.name;
    this.image = this.element.querySelector("img");
    this.image.alt = `Live video from ${camera.name}`;
    this.placeholder = this.element.querySelector(".tile-placeholder");
    this.badge = this.element.querySelector(".tile-badge");
    this.metrics = this.element.querySelector(".tile-metrics");
    this.select = this.element.querySelector("select");
    this.preference = `home-cameras.${camera.id}.display-aspect.v1`;
    grid.append(this.element);
    this.display = new MediaDisplay(this.image, this.element.querySelector(".viewer"));
    let aspect = camera.aspect_ratio || "16:9";
    try { aspect = localStorage.getItem(this.preference) || aspect; } catch (_) {}
    this.select.value = ["16:9", "4:3", "original"].includes(aspect) ? aspect : "16:9";
    this.display.setAspect(this.select.value);
    this.select.addEventListener("change", () => {
      this.display.setAspect(this.select.value);
      try { localStorage.setItem(this.preference, this.select.value); } catch (_) {}
    });
    this.element.querySelector(".expand").addEventListener("click", event => {
      const expanded = this.element.classList.toggle("is-expanded");
      event.target.setAttribute("aria-expanded", String(expanded));
      event.target.textContent = expanded ? "Collapse" : "Expand";
    });
    this.url = null;
    this.decoding = false;
    this.hasFrame = false;
    this.disposed = false;
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
