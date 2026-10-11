import {api} from "/shared/api.js";
import {Timeline} from "/history/timeline.js";

export class HistoryView {
  constructor(panel) {
    this.panel = panel;
    this.camera = panel.querySelector("#history-camera");
    this.hours = panel.querySelector("#history-hours");
    this.message = panel.querySelector("#history-message");
    this.active = false; this.generation = 0; this.recent = true;
    this.timeline = new Timeline(panel, () => { this.recent = false; });
    this.camera.addEventListener("change", () => { this.timeline.selected = undefined; this.load(); });
    this.hours.addEventListener("change", () => { this.recent = true; this.load(); });
    panel.querySelector("#history-recent").addEventListener("click", () => { this.recent = true; this.load(); });
    panel.querySelector("#history-refresh").addEventListener("click", () => this.load(true));
    for (const [id, direction] of [["history-earlier", -1], ["history-later", 1]]) {
      panel.querySelector(`#${id}`).addEventListener("click", () => {
        if (!this.end) return;
        this.end += direction * Number(this.hours.value) * 3600000;
        this.end = Math.min(this.end, this.now()); this.recent = false; this.load();
      });
    }
    for (const [id, direction] of [["history-previous", -1], ["history-next", 1]]) {
      panel.querySelector(`#${id}`).addEventListener("click", () => {
        const events = this.data?.motion.intervals || [], selected = this.timeline.selected;
        const event = direction > 0 ? events.find(item => selected === undefined || Date.parse(item.start) > selected) :
          [...events].reverse().find(item => selected === undefined || Date.parse(item.start) < selected);
        if (event) this.timeline.select(Date.parse(event.start));
      });
    }
  }

  now() { return Math.floor(Date.now() / 60000) * 60000; }

  async show() {
    this.active = true;
    const generation = ++this.generation;
    this.abort?.abort(); this.abort = new AbortController();
    this.message.textContent = "Loading cameras…";
    try {
      const inventory = await api("/api/cameras", "GET", undefined, {}, this.abort.signal);
      if (!this.active || generation !== this.generation) return;
      const previous = this.camera.value;
      this.camera.replaceChildren(...inventory.cameras.map(camera => new Option(camera.name, camera.id)));
      if ([...this.camera.options].some(option => option.value === previous)) this.camera.value = previous;
      this.camera.disabled = !inventory.cameras.length;
      if (!inventory.cameras.length) { this.message.textContent = "No configured cameras."; return; }
      this.load();
      clearInterval(this.refreshTimer);
      this.refreshTimer = setInterval(() => { if (this.active && this.recent) this.load(); }, 60000);
    } catch (error) {
      if (generation === this.generation && error.name !== "AbortError") this.message.textContent = error.message;
    }
  }

  async load(refresh = false) {
    if (!this.active || !this.camera.value) return;
    const generation = ++this.generation;
    this.abort?.abort(); this.abort = new AbortController();
    const signal = this.abort.signal;
    if (this.recent || !this.end) this.end = this.now();
    const begin = this.end - Number(this.hours.value) * 3600000;
    const cameraId = this.camera.value;
    const query = new URLSearchParams({from:new Date(begin).toISOString(), to:new Date(this.end).toISOString()});
    if (refresh) query.set("refresh", "1");
    this.data = null;
    this.timeline.render({from:new Date(begin).toISOString(), to:new Date(this.end).toISOString(), timezone:this.timeline.zone || "UTC",
      recordings:{state:"pending", intervals:null, complete:false}, motion:{state:"pending", intervals:null, complete:false}});
    this.eventControls(false);
    this.message.textContent = "Loading history…";
    try {
      for (let poll = 0; poll < 60; poll++) {
        const data = await api(`/api/cameras/${cameraId}/timeline?${query}`, "GET", undefined, {}, signal);
        if (!this.active || generation !== this.generation) return;
        this.timeline.render(data);
        if (data.recordings.state !== "pending" && data.motion.state !== "pending") {
          this.data = data;
          this.eventControls(Boolean(data.motion.intervals?.length));
          this.message.textContent = "";
          this.panel.querySelector("#history-later").disabled = this.end >= this.now();
          return;
        }
        query.delete("refresh");
        await new Promise(resolve => {
          const done = () => { clearTimeout(timer); signal.removeEventListener("abort", done); resolve(); };
          const timer = setTimeout(done, 500); signal.addEventListener("abort", done, {once:true});
        });
        if (signal.aborted) return;
      }
      throw new Error("History query timed out. Use Refresh to try again.");
    } catch (error) {
      if (this.active && generation === this.generation && error.name !== "AbortError") this.message.textContent = error.message;
    }
  }

  eventControls(enabled) {
    for (const id of ["history-previous", "history-next"]) this.panel.querySelector(`#${id}`).disabled = !enabled;
  }

  hide() {
    this.active = false; ++this.generation; this.abort?.abort(); clearInterval(this.refreshTimer);
  }
}
