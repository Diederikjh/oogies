// Timeline rendering and local time selection; recorder calls belong to the view.
export class Timeline {
  constructor(panel, onSelect) {
    this.panel = panel;
    this.onSelect = onSelect;
    this.slider = panel.querySelector("#history-position");
    this.slider.addEventListener("pointerdown", () => { this.scrubbing = true; });
    this.slider.addEventListener("pointercancel", () => { this.scrubbing = false; });
    this.slider.addEventListener("pointerup", () => { this.scrubbing = false; });
    this.slider.addEventListener("input", () => { this.scrubbing = true; this.select(this.seekBegin + Number(this.slider.value) * 1000, false); });
    this.slider.addEventListener("change", () => { this.scrubbing = false; this.select(this.seekBegin + Number(this.slider.value) * 1000); });
    this.tracks = new Map(["recordings", "motion"].map(name => [name, panel.querySelector(`#history-${name}`)]));
    this.markers = panel.querySelector("#history-clip-marks");
    panel.querySelector("#history-zoom-clip").addEventListener("click", () => this.zoomToClip());
    panel.querySelector("#history-zoom-out").addEventListener("click", () => this.zoomOut());
    panel.querySelector("#history-full-range").addEventListener("click", () => this.fullRange());
    this.markers.addEventListener("pointerdown", event => this.startDrag(event, this.markers));
    this.markers.addEventListener("pointermove", event => this.moveDrag(event));
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) this.markers.addEventListener(type, event => this.endDrag(event));
    this.markers.addEventListener("keydown", event => this.editKey(event));
    for (const track of this.tracks.values()) track.addEventListener("click", event => {
      if (this.suppressClick) { this.suppressClick = false; return; }
      if (event.target.closest("button") || !this.begin || track.dataset.state !== "ready") return;
      const bounds = track.getBoundingClientRect();
      const value = this.viewBegin + Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * (this.viewEnd - this.viewBegin);
      if (value >= this.begin && value < this.end) this.select(value);
    });
  }

  time(value, full = false) {
    return new Intl.DateTimeFormat(undefined, {timeZone:this.zone || "UTC",
      ...(full ? {year:"numeric", month:"short", day:"numeric"} : {}), hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"}).format(new Date(value));
  }

  select(value, notify = true) {
    this.selected = Math.max(this.begin, Math.min(this.end - 1000, Math.round(value / 1000) * 1000));
    this.slider.value = String(Math.max(0, Math.min(Number(this.slider.max), (this.selected - this.seekBegin) / 1000)));
    const label = this.time(this.selected, true) + (this.selected < this.viewBegin || this.selected >= this.viewEnd ? " · Outside zoom" : "");
    this.slider.setAttribute("aria-valuetext", label);
    this.panel.querySelector("#history-selected").textContent = label;
    const percent = (this.selected - this.viewBegin) / (this.viewEnd - this.viewBegin) * 100;
    for (const track of this.tracks.values()) {
      track.querySelector(".timeline-cursor")?.remove();
      const cursor = document.createElement("span"); cursor.className = "timeline-cursor";
      cursor.style.left = `${percent}%`; cursor.setAttribute("aria-hidden", "true"); track.append(cursor);
    }
    if (notify) this.onSelect(this.selected);
  }

  render(data) {
    this.data = data;
    // Hold the time-to-pixel mapping steady for the whole pointer gesture.
    if (this.drag) { this.deferredRender = true; return; }
    const changed = this.begin !== Date.parse(data.from) || this.end !== Date.parse(data.to);
    this.begin = Date.parse(data.from); this.end = Date.parse(data.to); this.zone = data.timezone;
    if (changed || !Number.isFinite(this.viewBegin)) { this.viewBegin = this.begin; this.viewEnd = this.end; }
    this.draw();
  }

  draw() {
    const data = this.data;
    if (!data) return;
    this.seekBegin = Math.max(this.begin, this.viewBegin); this.seekEnd = Math.min(this.end, this.viewEnd);
    this.slider.max = String(Math.max(0, (this.seekEnd - this.seekBegin) / 1000 - 1));
    this.slider.disabled = this.seekEnd - this.seekBegin < 1000;
    const unknown = this.viewBegin < this.begin || this.viewEnd > this.end ? " · Coverage outside the loaded range is unknown" : "";
    this.panel.querySelector("#history-range").textContent = `${this.time(this.viewBegin, true)} – ${this.time(this.viewEnd, true)} · ${this.zone}${this.isZoomed() ? " · Zoomed" : ""}${unknown}`;
    this.panel.querySelector("#history-axis").replaceChildren(...Array.from({length:5}, (_, index) => {
      const tick = document.createElement("span"); tick.textContent = this.time(this.viewBegin + (this.viewEnd - this.viewBegin) * index / 4); return tick;
    }));
    const events = this.panel.querySelector("#history-events"); events.replaceChildren();
    for (const [name, track] of this.tracks) {
      const dataset = data[name]; track.replaceChildren();
      track.dataset.viewFrom = String(this.viewBegin); track.dataset.viewTo = String(this.viewEnd);
      track.dataset.state = dataset.state;
      track.dataset.complete = String(dataset.complete);
      const noun = name === "motion" ? "motion intervals" : "recordings";
      const message = dataset.state === "pending" ? "Loading…" : dataset.state !== "ready" ?
        dataset.error?.message || `${noun} unavailable` : !dataset.complete ?
        "Partial results · unsearched coverage is unknown" : !dataset.intervals.length ? `No ${noun} in this range` :
        `${dataset.intervals.length} ${noun}`;
      this.panel.querySelector(`#history-${name}-status`).textContent = message;
      for (const [start, end] of [[this.viewBegin, Math.min(this.begin, this.viewEnd)], [Math.max(this.end, this.viewBegin), this.viewEnd]]) if (start < end) {
        const unknown = document.createElement("span"); unknown.className = "timeline-unknown";
        unknown.title = "Recording coverage outside the loaded range is unknown.";
        unknown.style.left = `${(start - this.viewBegin) / (this.viewEnd - this.viewBegin) * 100}%`;
        unknown.style.width = `${(end - start) / (this.viewEnd - this.viewBegin) * 100}%`; track.append(unknown);
      }
      for (const interval of dataset.intervals || []) {
        const start = Date.parse(interval.start), end = Date.parse(interval.end);
        const label = `${name === "motion" ? "Motion" : "Recording"} · ${this.time(start)}${end !== start ? ` – ${this.time(end)}` : ""}`;
        const button = document.createElement("button"); button.className = "timeline-interval";
        button.dataset.intervalId = interval.id; button.setAttribute("aria-label", label); button.title = label;
        button.style.left = `${(Math.max(start, this.viewBegin) - this.viewBegin) / (this.viewEnd - this.viewBegin) * 100}%`;
        button.style.width = `${(Math.min(end, this.viewEnd) - Math.max(start, this.viewBegin)) / (this.viewEnd - this.viewBegin) * 100}%`;
        button.classList.toggle("is-point", start === end);
        button.addEventListener("click", event => {
          if (name === "motion" || !event.detail) this.select(start);
          else {
            const bounds = track.getBoundingClientRect();
            this.select(this.viewBegin + (event.clientX - bounds.left) / bounds.width * (this.viewEnd - this.viewBegin));
          }
        });
        if (start < this.viewEnd && end >= this.viewBegin) track.append(button);
        if (name === "motion") {
          const entry = document.createElement("li"), action = document.createElement("button");
          action.textContent = label; action.dataset.intervalId = interval.id;
          action.addEventListener("click", () => this.select(start)); entry.append(action); events.append(entry);
        }
      }
    }
    if (this.selected !== undefined && this.begin <= this.selected && this.selected < this.end) this.select(this.selected, false);
    else { this.selected = undefined; this.slider.value = "0"; this.panel.querySelector("#history-selected").textContent = "Choose a time"; }
    this.drawClip();
  }

  setClip(from, to) {
    if (Object.is(this.clipFrom, from) && Object.is(this.clipTo, to)) return;
    this.clipFrom = from; this.clipTo = to;
    this.drawClip();
  }

  drawClip() {
    const from = this.clipFrom, to = this.clipTo;
    const percent = value => (value - this.viewBegin) / (this.viewEnd - this.viewBegin) * 100;
    this.panel.querySelector("#history-zoom-clip").disabled = !Number.isFinite(from) || !Number.isFinite(to);
    for (const id of ["history-zoom-out", "history-full-range"]) this.panel.querySelector(`#${id}`).disabled = !this.isZoomed();
    for (const track of this.tracks.values()) {
      for (const item of track.querySelectorAll(".clip-boundary,.clip-shade")) item.remove();
      if (from < to && from < this.viewEnd && to > this.viewBegin) {
        const shade = document.createElement("span"); shade.className = "clip-shade";
        shade.style.left = `${percent(Math.max(from, this.viewBegin))}%`;
        shade.style.width = `${percent(Math.min(to, this.viewEnd)) - percent(Math.max(from, this.viewBegin))}%`; track.append(shade);
      }
      for (const [name, label, value] of [["from", "Start", from], ["to", "End", to]]) {
        if (!(value >= this.viewBegin && value <= this.viewEnd)) continue;
        const boundary = document.createElement("span"); boundary.className = "clip-boundary";
        boundary.style.left = `${percent(value)}%`; track.append(boundary);
      }
    }
    for (const [name, label, value] of [["from", "Start", from], ["to", "End", to]]) {
      let flag = this.markers.querySelector(`.clip-marker[data-bound="${name}"]`);
      if (!(value >= this.viewBegin && value <= this.viewEnd)) { flag?.remove(); continue; }
      if (!flag) {
        flag = document.createElement("button"); flag.type = "button"; flag.className = "clip-marker";
        flag.dataset.bound = name; flag.textContent = label; flag.setAttribute("role", "slider");
        flag.setAttribute("aria-label", `Clip ${name === "from" ? "start" : "end"}`); this.markers.append(flag);
      }
      flag.style.left = `clamp(22px, ${percent(value)}%, calc(100% - 22px))`;
      flag.title = `${label}: ${this.time(value, true)} · Drag or use arrow keys`;
      flag.setAttribute("aria-valuenow", String(value / 1000)); flag.setAttribute("aria-valuetext", this.time(value, true));
      const [min, max] = this.clipBounds?.(name) || [this.begin, this.end];
      flag.setAttribute("aria-valuemin", String(min / 1000)); flag.setAttribute("aria-valuemax", String(max / 1000));
    }
  }

  isZoomed() { return Number.isFinite(this.viewBegin) && (this.viewBegin !== this.begin || this.viewEnd !== this.end); }
  invalidClip() {
    const duration = this.clipTo - this.clipFrom;
    return Number.isFinite(duration) && (duration < 1000 || duration > this.maxClipSeconds * 1000);
  }

  domain() {
    const marks = [this.clipFrom, this.clipTo].filter(Number.isFinite);
    return [Math.min(this.begin, ...marks), Math.max(this.end, ...marks)];
  }

  setView(center, width) {
    const [min, max] = this.domain(); width = Math.min(width, max - min);
    this.viewBegin = Math.max(min, Math.min(max - width, Math.floor((center - width / 2) / 1000) * 1000));
    this.viewEnd = this.viewBegin + width; this.draw();
  }

  zoomToClip() {
    if (!Number.isFinite(this.clipFrom) || !Number.isFinite(this.clipTo) || this.drag) return;
    this.setView((this.clipFrom + this.clipTo) / 2, Math.max(60000, Math.ceil(Math.abs(this.clipTo - this.clipFrom) * 1.4 / 1000) * 1000));
  }
  zoomOut() { if (!this.drag) this.setView((this.viewBegin + this.viewEnd) / 2, (this.viewEnd - this.viewBegin) * 2); }
  fullRange() { if (!this.drag) { this.viewBegin = this.begin; this.viewEnd = this.end; this.draw(); } }

  startDrag(event, track) {
    const flag = event.target.closest(".clip-marker");
    if (!flag || this.drag || !event.isPrimary || event.button !== 0) return;
    event.preventDefault(); flag.focus({preventScroll:true});
    this.drag = {id:event.pointerId, track, name:flag.dataset.bound, x:event.clientX,
      time:flag.dataset.bound === "from" ? this.clipFrom : this.clipTo,
      scale:(this.viewEnd - this.viewBegin) / track.getBoundingClientRect().width, repairing:this.invalidClip()};
    this.scrubbing = true; this.suppressClick = true;
    track.setPointerCapture(event.pointerId);
  }
  moveDrag(event) {
    const drag = this.drag;
    if (!drag || event.pointerId !== drag.id) return;
    const requested = drag.time + (event.clientX - drag.x) * drag.scale;
    const actual = this.onClipEdit(drag.name, requested);
    drag.time = actual === Math.round(requested / 1000) * 1000 ? requested : actual;
    drag.x = event.clientX;
  }
  endDrag(event) {
    if (!this.drag || event.pointerId !== this.drag.id) return;
    const drag = this.drag; this.drag = null; this.scrubbing = false;
    if (drag.track.hasPointerCapture(drag.id)) drag.track.releasePointerCapture(drag.id);
    if (event.type === "pointercancel") this.suppressClick = false;
    setTimeout(() => { this.suppressClick = false; }, 0);
    if (this.deferredRender) { this.deferredRender = false; this.render(this.data); }
    if ((drag.repairing && !this.invalidClip()) || this.clipFrom < this.viewBegin || this.clipTo > this.viewEnd) this.zoomToClip();
  }
  cancelDrag() {
    if (this.drag) this.endDrag({pointerId:this.drag.id, type:"pointercancel"});
  }
  editKey(event) {
    const flag = event.target.closest(".clip-marker");
    if (!flag) return;
    const name = flag.dataset.bound, current = name === "from" ? this.clipFrom : this.clipTo;
    const [min, max] = this.clipBounds(name), step = event.shiftKey ? 10000 : 1000;
    const target = {ArrowLeft:current-step, ArrowRight:current+step, Home:min, End:max}[event.key];
    if (target === undefined) return;
    const track = this.markers;
    const repairing = this.invalidClip();
    event.preventDefault(); this.onClipEdit(name, target);
    if (repairing || this.clipFrom < this.viewBegin || this.clipTo > this.viewEnd) {
      this.zoomToClip(); track.querySelector(`.clip-marker[data-bound="${name}"]`)?.focus({preventScroll:true});
    }
  }
}
