import {api} from "/shared/api.js";
import {Timeline} from "/history/timeline.js";
import {PlaybackControls} from "/history/playback-controls.js";
import {DateTimeNavigation} from "/history/date-time-navigation.js";
import {ClipSelection} from "/history/clip-selection.js";

export class HistoryView {
  constructor(panel, onCameras = () => {}, onExports = () => {}) {
    this.panel = panel;
    this.onCameras = onCameras;
    this.camera = panel.querySelector("#history-camera");
    this.hours = panel.querySelector("#history-hours");
    this.message = panel.querySelector("#history-message");
    this.active = false; this.generation = 0; this.recent = true;
    this.player = new PlaybackControls(panel, position => {
      if (this.active && !this.timeline.scrubbing && this.timeline.begin <= position && position < this.timeline.end)
        this.timeline.select(position, false);
    });
    this.timeline = new Timeline(panel, position => this.play(position));
    this.clip = new ClipSelection(panel, this.player, this.timeline, onExports);
    this.player.onSnapshot = () => this.clip.paint();
    this.dateNavigation = new DateTimeNavigation(panel, localTime => {
      const rate = this.player.session?.camera_id === this.camera.value ? this.player.session.requested_rate : 1;
      this.load(false, {localTime, rate});
    });
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

  play(position, rate, autoplay = false) {
    this.recent = false;
    const camera = this.cameras?.find(camera => camera.id === this.camera.value);
    if (camera) this.player.select(camera, position, this.timeline.begin, this.timeline.end, rate, autoplay);
  }

  async show(cameraId) {
    this.active = true;
    const generation = ++this.generation;
    this.abort?.abort(); this.abort = new AbortController();
    this.message.textContent = "Loading cameras…";
    try {
      const inventory = await api("/api/cameras", "GET", undefined, {}, this.abort.signal);
      if (!this.active || generation !== this.generation) return;
      const previous = cameraId || this.camera.value;
      this.cameras = inventory.cameras;
      this.onCameras();
      this.camera.replaceChildren(...inventory.cameras.map(camera => new Option(camera.name, camera.id)));
      if ([...this.camera.options].some(option => option.value === previous)) this.camera.value = previous;
      if (cameraId) { this.recent = true; this.timeline.selected = undefined; }
      this.camera.disabled = !inventory.cameras.length;
      if (!inventory.cameras.length) { this.message.textContent = "No configured cameras."; return; }
      if (cameraId) this.camera.focus();
      this.load();
      clearInterval(this.refreshTimer);
      this.refreshTimer = setInterval(() => { if (this.active && this.recent) this.load(); }, 60000);
    } catch (error) {
      if (generation === this.generation && error.name !== "AbortError") this.message.textContent = error.message;
    }
  }

  async load(refresh = false, dateJob = null) {
    if (!this.active || !this.camera.value) return;
    const generation = ++this.generation;
    this.abort?.abort(); this.abort = new AbortController();
    const signal = this.abort.signal;
    const cameraId = this.camera.value;
    this.clip.cameraChanged(this.cameras?.find(item => item.id === cameraId));
    let query;
    if (dateJob) {
      query = new URLSearchParams({local_time:dateJob.localTime, hours:this.hours.value});
    } else {
      this.dateNavigation.error("");
      if (this.recent || !this.end) this.end = this.now();
      const begin = this.end - Number(this.hours.value) * 3600000;
      if (this.player.session && (this.player.session.camera_id !== cameraId || Date.parse(this.player.session.from) !== begin || Date.parse(this.player.session.to) !== this.end)) {
        this.player.stop(); this.timeline.selected = undefined;
      }
      query = new URLSearchParams({from:new Date(begin).toISOString(), to:new Date(this.end).toISOString()});
      this.data = null;
      this.timeline.render({from:new Date(begin).toISOString(), to:new Date(this.end).toISOString(), timezone:this.timeline.zone || "UTC",
        recordings:{state:"pending", intervals:null, complete:false}, motion:{state:"pending", intervals:null, complete:false}});
      this.eventControls(false);
    }
    if (refresh) query.set("refresh", "1");
    if (dateJob) this.dateNavigation.error("Opening selected time…");
    else this.message.textContent = "Loading history…";
    let dateStarted = false;
    try {
      for (let poll = 0; poll < 60; poll++) {
        const data = await api(`/api/cameras/${cameraId}/timeline?${query}`, "GET", undefined, {}, signal);
        if (!this.active || generation !== this.generation) return;
        if (dateJob && !dateStarted) {
          // Validation succeeded. Keep the same viewer's slot for a range jump;
          // its next playback PATCH replaces only that native context.
          this.recent = false; this.end = Date.parse(data.to); this.timeline.selected = undefined;
          this.data = null; this.eventControls(false); this.dateNavigation.error("");
          this.panel.querySelector(".history-date-picker").open = false;
        }
        this.timeline.render(data);
        this.dateNavigation.ready(data.timezone, this.timeline.selected ?? this.timeline.end - 1000);
        if (dateJob && !dateStarted) {
          this.timeline.select(Date.parse(data.selected_time), false);
          this.play(this.timeline.selected, dateJob.rate, true);
          dateStarted = true;
          // Poll/cache the fixed UTC window even if the wall clock moves.
          query = new URLSearchParams({from:data.from, to:data.to});
        }
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
      if (this.active && generation === this.generation && error.name !== "AbortError") {
        if (dateJob) this.dateNavigation.error(error.message);
        else this.message.textContent = error.message;
      }
    }
  }

  eventControls(enabled) {
    for (const id of ["history-previous", "history-next"]) this.panel.querySelector(`#${id}`).disabled = !enabled;
  }

  hide() {
    this.active = false; ++this.generation; this.abort?.abort(); clearInterval(this.refreshTimer);
    this.clip.clearMessage();
    this.panel.querySelector(".history-date-picker").open = false;
    return this.player.stop();
  }
}
