import {MediaDisplay} from "/shared/media-player.js";
import {readAspect, saveAspect} from "/shared/display-preferences.js";
import {TileExpansion} from "/live/tile-expansion.js";

const LABELS = {starting:"Connecting", live:"Live", stale:"Video delayed", offline:"Offline",
  error:"Unavailable", capacity_limited:"Stream limit", stopping:"Stopping", stopped:"Stopped"};
const QUALITY_REASONS = {high_quality_limit:"stream limit", source_limit:"stream limit", unsupported:"unsupported",
  offline:"camera offline", stream_failed:"stream failed", quality_request_failed:"request failed"};

export class CameraTile {
  constructor(camera, grid, onHistory = () => {}, onExpansion = () => {}, onFrame = () => {}) {
    this.camera = camera;
    this.element = document.createElement("article");
    this.element.className = "camera-tile";
    this.element.dataset.cameraId = camera.id;
    this.element.innerHTML = `<div class="tile-heading"><h2></h2><span class="tile-badge">Connecting</span></div>
      <button type="button" class="viewer camera-view" aria-expanded="false"><img hidden><span class="tile-placeholder">Connecting to camera…</span>
        <span class="expand-hint" aria-hidden="true">Expand</span></button>
      <div class="tile-controls"><span class="tile-metrics" role="status" aria-live="polite">Overview</span><button type="button" class="camera-history">History</button></div>`;
    this.element.querySelector("h2").textContent = camera.name;
    const history = this.element.querySelector(".camera-history");
    history.setAttribute("aria-label", `View history for ${camera.name}`);
    history.addEventListener("click", () => onHistory(camera.id));
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
    this.expansion = new TileExpansion(this.element, this.view, () => this.display.fit());
    this.view.setAttribute("aria-label", `Expand ${camera.name}`);
    this.view.addEventListener("click", () => this.expansion.toggle(() => {
      const expanded = this.element.classList.toggle("is-expanded");
      this.view.setAttribute("aria-expanded", String(expanded));
      this.view.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${camera.name}`);
      this.element.querySelector(".expand-hint").textContent = expanded ? "Collapse" : "Expand";
      onExpansion(camera.id, expanded);
    }));
    this.url = null;
    this.onFrame = onFrame;
    this.sources = new Map();
    this.generations = new Map();
    this.hasFrame = false;
    this.disposed = false;
  }

  setAspect(value) {
    this.aspect = saveAspect(this.camera.id, value);
    this.display.setAspect(this.aspect);
  }

  setQualityIntent(high) {
    this.wantsHigh = high;
    this.qualityReason = null;
    this.cancelDecode();
    this.paintQuality();
  }

  qualityUnavailable(reason) {
    this.qualityReason = reason;
    this.cancelDecode();
    this.paintQuality();
  }

  cancelDecode() {
    const pending = this.pending;
    this.pending = null;
    if (pending) { pending.image.removeAttribute("src"); URL.revokeObjectURL(pending.url); }
  }

  async frame(jpeg, header, isCurrent = () => true) {
    if (this.disposed || !isCurrent() || (header.quality === "high" && (!this.wantsHigh || this.qualityReason))) return;
    if (header.generation < (this.generations.get(header.quality) || 0)) return;
    this.generations.set(header.quality, header.generation);
    const previous = this.sources.get(header.quality);
    if (previous && (header.generation < previous.generation ||
        (header.generation === previous.generation && header.sequence <= previous.sequence && header.selection_revision <= previous.revision))) return;
    const pending = this.pending;
    if (pending && (pending.header.quality !== header.quality || pending.header.generation !== header.generation ||
        pending.header.selection_revision !== header.selection_revision)) this.cancelDecode();
    if (this.pending) return; // Slow tiles skip frames rather than queue them.
    const image = new Image(), url = URL.createObjectURL(new Blob([jpeg], {type:"image/jpeg"}));
    const job = {image, url, header}; this.pending = job;
    image.src = url;
    try {
      await image.decode();
      if (this.pending !== job || this.disposed || !isCurrent() ||
          (header.quality === "high" && (!this.wantsHigh || this.qualityReason))) return;
      const old = this.url;
      const qualityChanged = this.rendered?.quality !== header.quality;
      this.url = url;
      this.rendered = {quality:header.quality, width:image.naturalWidth, height:image.naturalHeight};
      this.sources.set(header.quality, {generation:header.generation, sequence:header.sequence, revision:header.selection_revision});
      this.image.src = url;
      this.image.hidden = false; this.placeholder.hidden = true; this.hasFrame = true;
      this.lastPaintedAt = performance.now();
      this.feedInterrupted = false;
      this.element.dataset.quality = header.quality;
      this.element.dataset.sourceGeneration = String(header.generation);
      this.paintQuality();
      if (this.status && this.element.dataset.state === "stale") this.paint(this.status);
      if (qualityChanged) this.onFrame();
      if (old) URL.revokeObjectURL(old);
    } catch (_) {
      // A superseded/corrupt JPEG must not replace the last painted picture.
    } finally {
      if (this.pending === job) this.pending = null;
      if (this.url !== url) URL.revokeObjectURL(url);
    }
  }

  paintQuality() {
    const picture = this.rendered;
    let label = picture?.quality === "high" ? "High quality" : "Overview";
    if (this.wantsHigh && this.qualityReason) {
      const reason = QUALITY_REASONS[this.qualityReason.code];
      label += ` · High quality unavailable${reason ? ` (${reason})` : ""}`;
    }
    else if (this.wantsHigh && picture?.quality !== "high") label += " · Upgrading…";
    else if (!this.wantsHigh && picture?.quality === "high") label += " · Returning to overview…";
    const text = picture ? `${picture.width} × ${picture.height} · ${label}` : label;
    if (this.metrics.textContent !== text) this.metrics.textContent = text;
    this.metrics.title = this.qualityReason?.message || "";
  }

  interruptFeed() {
    this.feedInterrupted = true;
    this.cancelDecode();
    if (this.status) this.paint(this.status);
  }

  paint(status) {
    this.status = status;
    const delayed = status.state === "live" && (this.feedInterrupted || this.lastPaintedAt === undefined || performance.now() - this.lastPaintedAt > 5000);
    const state = delayed ? "stale" : status.state;
    this.element.dataset.state = state;
    this.badge.textContent = delayed && this.feedInterrupted ? "Reconnecting…" : LABELS[state] || state;
    this.paintQuality();
    this.placeholder.textContent = status.error || LABELS[state] || "Connecting…";
    this.element.title = status.error || "";
  }

  pause() { this.cancelDecode(); this.sources.clear(); this.generations.clear(); this.feedInterrupted = false; this.lastPaintedAt = undefined; this.paint({state:"stopped"}); }

  dispose() {
    this.disposed = true;
    this.cancelDecode();
    this.expansion.dispose();
    this.display.dispose();
    this.image.removeAttribute("src");
    if (this.url) URL.revokeObjectURL(this.url);
    this.element.remove();
  }
}
