// Timeline rendering and local time selection; recorder calls belong to the view.
export class Timeline {
  constructor(panel, onSelect) {
    this.panel = panel;
    this.onSelect = onSelect;
    this.slider = panel.querySelector("#history-position");
    this.slider.addEventListener("input", () => this.select(this.begin + Number(this.slider.value) * 1000));
    this.tracks = new Map(["recordings", "motion"].map(name => [name, panel.querySelector(`#history-${name}`)]));
    for (const track of this.tracks.values()) track.addEventListener("click", event => {
      if (event.target.closest("button") || !this.begin || track.dataset.state !== "ready") return;
      const bounds = track.getBoundingClientRect();
      this.select(this.begin + Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * (this.end - this.begin));
    });
  }

  time(value, full = false) {
    return new Intl.DateTimeFormat(undefined, {timeZone:this.zone || "UTC",
      ...(full ? {month:"short", day:"numeric"} : {}), hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"}).format(new Date(value));
  }

  select(value, notify = true) {
    this.selected = Math.max(this.begin, Math.min(this.end - 1000, Math.round(value / 1000) * 1000));
    this.slider.value = String((this.selected - this.begin) / 1000);
    this.slider.setAttribute("aria-valuetext", this.time(this.selected, true));
    this.panel.querySelector("#history-selected").textContent = this.time(this.selected, true);
    const percent = (this.selected - this.begin) / (this.end - this.begin) * 100;
    for (const track of this.tracks.values()) {
      track.querySelector(".timeline-cursor")?.remove();
      const cursor = document.createElement("span"); cursor.className = "timeline-cursor";
      cursor.style.left = `${percent}%`; cursor.setAttribute("aria-hidden", "true"); track.append(cursor);
    }
    if (notify) this.onSelect(this.selected);
  }

  render(data) {
    this.begin = Date.parse(data.from); this.end = Date.parse(data.to); this.zone = data.timezone;
    this.slider.max = String((this.end - this.begin) / 1000 - 1);
    this.slider.disabled = false;
    this.panel.querySelector("#history-range").textContent = `${this.time(this.begin, true)} – ${this.time(this.end, true)} · ${this.zone}`;
    this.panel.querySelector("#history-axis").replaceChildren(...Array.from({length:5}, (_, index) => {
      const tick = document.createElement("span"); tick.textContent = this.time(this.begin + (this.end - this.begin) * index / 4); return tick;
    }));
    const events = this.panel.querySelector("#history-events"); events.replaceChildren();
    for (const [name, track] of this.tracks) {
      const dataset = data[name]; track.replaceChildren();
      track.dataset.state = dataset.state;
      track.dataset.complete = String(dataset.complete);
      const noun = name === "motion" ? "motion intervals" : "recordings";
      const message = dataset.state === "pending" ? "Loading…" : dataset.state !== "ready" ?
        dataset.error?.message || `${noun} unavailable` : !dataset.complete ?
        "Partial results · unsearched coverage is unknown" : !dataset.intervals.length ? `No ${noun} in this range` :
        `${dataset.intervals.length} ${noun}`;
      this.panel.querySelector(`#history-${name}-status`).textContent = message;
      for (const interval of dataset.intervals || []) {
        const start = Date.parse(interval.start), end = Date.parse(interval.end);
        const label = `${name === "motion" ? "Motion" : "Recording"} · ${this.time(start)}${end !== start ? ` – ${this.time(end)}` : ""}`;
        const button = document.createElement("button"); button.className = "timeline-interval";
        button.dataset.intervalId = interval.id; button.setAttribute("aria-label", label); button.title = label;
        button.style.left = `${(start - this.begin) / (this.end - this.begin) * 100}%`;
        button.style.width = `${(end - start) / (this.end - this.begin) * 100}%`;
        button.classList.toggle("is-point", start === end);
        button.addEventListener("click", () => this.select(start)); track.append(button);
        if (name === "motion") {
          const entry = document.createElement("li"), action = document.createElement("button");
          action.textContent = label; action.dataset.intervalId = interval.id;
          action.addEventListener("click", () => this.select(start)); entry.append(action); events.append(entry);
        }
      }
    }
    if (this.selected !== undefined && this.begin <= this.selected && this.selected < this.end) this.select(this.selected, false);
    else { this.selected = undefined; this.slider.value = "0"; this.panel.querySelector("#history-selected").textContent = "Choose a time"; }
  }
}
