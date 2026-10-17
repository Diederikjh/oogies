import {api} from "/shared/api.js";
import {readAspect} from "/shared/display-preferences.js";
import {clipMark, clipStatus, clipBounds, editClipMark} from "./clip-model.js";

export class ClipSelection {
  constructor(panel, player, timeline, onExports) {
    this.panel = panel; this.player = player; this.timeline = timeline; this.onExports = onExports;
    this.start = panel.querySelector("#clip-start"); this.end = panel.querySelector("#clip-end");
    this.queue = panel.querySelector("#clip-queue"); this.message = panel.querySelector("#clip-message");
    this.maxSeconds = 600; this.messageGeneration = 0;
    timeline.onClipEdit = (name, value) => this.edit(name, value);
    timeline.clipBounds = name => this.bounds(name);
    for (const [name, button] of [["from", this.start], ["to", this.end]]) button.addEventListener("click", () => {
      const frame = player.snapshot; if (!frame) return;
      this[name] = clipMark(frame.position); this.paint();
      timeline.zoomToClip();
    });
    panel.querySelector("#clip-clear").addEventListener("click", () => {
      this.clearMessage(); timeline.cancelDrag(); this.from = this.to = undefined; this.paint(); timeline.fullRange();
    });
    this.queue.addEventListener("click", () => this.submit());
    panel.querySelector("#clip-view-exports").addEventListener("click", onExports);
    api("/api/exports").then(data => { this.maxSeconds = data.limits.max_duration_seconds; this.paint(); }).catch(() => {});
    this.paint();
  }
  cameraChanged(camera) {
    if (this.camera?.id !== camera?.id) { this.clearMessage(); this.timeline.cancelDrag(); this.from = this.to = undefined; }
    this.camera = camera; this.paint();
  }
  clearMessage() {
    ++this.messageGeneration; clearTimeout(this.messageTimer);
    this.messageAnimation?.cancel(); this.messageAnimation = null;
    this.message.classList.remove("clip-confirmation");
    this.messageTimer = undefined; this.message.replaceChildren();
  }
  bounds(name) {
    return clipBounds(name, {from:this.from, to:this.to, begin:this.timeline.begin,
      end:this.timeline.end, maxSeconds:this.maxSeconds});
  }
  edit(name, value) {
    this[name] = editClipMark(value, this.bounds(name));
    this.paint(); return this[name];
  }
  paint() {
    const frame = this.player.snapshot;
    this.start.disabled = this.end.disabled = !frame || frame.cameraId !== this.camera?.id;
    const {duration, valid} = clipStatus(this.from, this.to, this.maxSeconds);
    this.valid = valid;
    this.queue.disabled = !this.valid || this.submitting;
    const label = value => value === undefined ? "Not set" : this.timeline.time(value, true);
    this.panel.querySelector("#clip-range").textContent = `Start: ${label(this.from)} · End: ${label(this.to)}`;
    this.panel.querySelector("#clip-duration").textContent = Number.isFinite(duration) ?
      this.valid ? `${duration} seconds` : `Choose an end after the start, up to ${this.maxSeconds} seconds.` : `Maximum ${this.maxSeconds} seconds`;
    this.timeline.maxClipSeconds = this.maxSeconds;
    this.timeline.setClip(this.from, this.to);
  }
  async submit() {
    if (!this.valid || this.submitting) return;
    const body = {camera_id:this.camera.id, from:new Date(this.from).toISOString(), to:new Date(this.to).toISOString(),
      aspect_ratio:readAspect(this.camera.id, this.camera.aspect_ratio)};
    const serialized = JSON.stringify(body), cameraName = this.camera.name;
    if (this.submission?.body !== serialized) this.submission = {body:serialized, key:crypto.randomUUID()};
    this.clearMessage(); const generation = this.messageGeneration;
    this.submitting = true; this.paint(); this.message.textContent = "Queueing export…";
    try {
      await api("/api/exports", "POST", body, {"Idempotency-Key":this.submission.key});
      this.submission = null;
      if (generation !== this.messageGeneration) return;
      const link = document.createElement("a");
      link.href = "#exports-panel"; link.textContent = "Export"; link.setAttribute("aria-label", "View export jobs");
      link.addEventListener("click", event => { event.preventDefault(); this.onExports(); });
      this.message.replaceChildren(link, document.createTextNode(` queued for ${cameraName}. You can continue watching.`));
      this.message.classList.add("clip-confirmation");
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        this.messageAnimation = this.message.animate([
          {opacity:0, transform:"translateY(8px)", offset:0, easing:"ease-out"},
          {opacity:1, transform:"translateY(-3px)", offset:.6, easing:"ease-in-out"},
          {opacity:1, transform:"translateY(1px)", offset:.82, easing:"ease-out"},
          {opacity:1, transform:"translateY(0)", offset:1}
        ], {duration:480});
      }
      this.messageTimer = setTimeout(() => {
        if (generation === this.messageGeneration) this.clearMessage();
      }, 60000);
    } catch (error) { if (generation === this.messageGeneration) this.message.textContent = error.message; }
    finally { this.submitting = false; this.paint(); }
  }
}
