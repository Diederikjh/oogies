import {api} from "/shared/api.js";
import {FrameFeed} from "/shared/frame-feed.js";
import {MediaDisplay} from "/shared/media-player.js";
import {readAspect, saveAspect} from "/shared/display-preferences.js";
import {downloadFrame} from "/history/frame-download.js";

const LABELS = {starting:"Loading recording…", seeking:"Seeking…", playing:"Playing", paused:"Paused",
  pausing:"Pausing…", resuming:"Resuming…", ended:"End of selected range", error:"Playback unavailable"};

export class PlaybackControls {
  constructor(panel, onPosition) {
    this.panel = panel; this.onPosition = onPosition;
    this.image = panel.querySelector("#history-image");
    this.placeholder = panel.querySelector("#history-placeholder");
    this.message = panel.querySelector("#history-playback-status");
    this.pauseButton = panel.querySelector("#history-pause");
    this.stopButton = panel.querySelector("#history-stop");
    this.speedButtons = [...panel.querySelectorAll("#history-speeds button")];
    this.speedMessage = panel.querySelector("#history-speed-status");
    this.stepButtons = [...panel.querySelectorAll("#history-steps button[data-seconds]")];
    this.downloadButton = panel.querySelector("#history-frame-download");
    this.downloadMessage = panel.querySelector("#history-frame-message");
    this.viewer = panel.querySelector("#history-viewer");
    this.display = new MediaDisplay(this.image, this.viewer);
    this.epoch = 0; this.renderEpoch = 0; this.controlVersion = 0; this.session = null;
    this.pauseButton.addEventListener("click", () => this.control());
    this.stopButton.addEventListener("click", () => this.stop());
    for (const button of this.speedButtons) button.addEventListener("click", () => this.changeRate(Number(button.dataset.rate)));
    for (const button of this.stepButtons) button.addEventListener("click", () => this.step(Number(button.dataset.seconds)));
    this.downloadButton.addEventListener("click", () => this.download());
    this.paint(null);
  }

  setAspect(cameraId, value) {
    if (this.camera?.id !== cameraId) return;
    this.display.setAspect(saveAspect(cameraId, value));
    this.paintFrameControls();
  }

  select(camera, position, from, to, rate = this.session?.camera_id === camera.id ? this.session.requested_rate : 1, autoplay = false) {
    const epoch = ++this.epoch;
    this.controlling = false;
    this.camera = camera;
    this.display.setAspect(readAspect(camera.id, camera.aspect_ratio || "16:9"));
    this.image.alt = `Recorded video from ${camera.name}`;
    this.pending = {camera, position, from, to, rate, autoplay, epoch};
    this.loading = true; this.bufferedFrame = null; this.clearPicture();
    this.paint({state:this.session ? "seeking" : "starting"});
    const bounds = this.viewer.getBoundingClientRect();
    if (bounds.top < 0 || bounds.bottom > innerHeight) this.viewer.scrollIntoView({block:"nearest", behavior:"instant"});
    if (!this.draining) {
      this.draining = this.drain().finally(() => { this.draining = null; });
    }
  }

  async drain() {
    while (this.pending) {
      const job = this.pending; this.pending = null;
      try {
        const sameCamera = this.session?.camera_id === job.camera.id;
        const sameRange = sameCamera && this.session.from === new Date(job.from).toISOString().replace(".000Z", "Z") &&
          this.session.to === new Date(job.to).toISOString().replace(".000Z", "Z");
        let status;
        if (sameCamera) {
          this.expectedGeneration = this.session.generation + 1;
          const update = {position:new Date(job.position).toISOString(), rate:job.rate};
          if (!sameRange) { update.from = new Date(job.from).toISOString(); update.to = new Date(job.to).toISOString(); }
          if (job.autoplay) update.state = "playing";
          status = await api(`/api/playback/sessions/${this.session.id}`, "PATCH", update);
        } else {
          await this.release();
          status = await api("/api/playback/sessions", "POST", {camera_id:job.camera.id,
            from:new Date(job.from).toISOString(), to:new Date(job.to).toISOString(), position:new Date(job.position).toISOString(), rate:job.rate});
        }
        this.session = status;
        if (job.epoch !== this.epoch) {
          if (!this.pending) await this.release();
          continue;
        }
        this.expectedGeneration = status.generation;
        this.loading = false;
        if (!this.feed) {
          const id = status.id;
          this.feed = new FrameFeed(status.media.url, (_, jpeg, header) => {
            if (this.session?.id === id) this.frame(jpeg, header);
          });
          this.feed.run().catch(error => {
            if (this.session?.id === id && error.name !== "AbortError") this.paint({state:"error", error:error.message});
          });
        }
        if (this.bufferedFrame) {
          const {jpeg, header} = this.bufferedFrame; this.bufferedFrame = null; this.frame(jpeg, header);
        }
        this.paint(status);
        clearInterval(this.pollTimer); clearInterval(this.renewTimer);
        this.pollTimer = setInterval(() => this.poll(), 500);
        this.renewTimer = setInterval(() => this.renew(), Math.max(1000, status.lease_seconds * 1000 / 3));
      } catch (error) {
        await this.release();
        if (job.epoch === this.epoch) {
          this.loading = false;
          this.paint({state:"error", error:error.message});
        }
      }
    }
  }

  frame(jpeg, header) {
    if (header.generation !== this.expectedGeneration) return;
    if (this.loading) { this.bufferedFrame = {jpeg, header}; return; }
    if (this.drawing) return;
    this.drawing = true;
    const epoch = this.renderEpoch, previous = this.url;
    const blob = new Blob([jpeg], {type:"image/jpeg"});
    const next = URL.createObjectURL(blob); this.url = next;
    this.image.onload = () => {
      if (previous) URL.revokeObjectURL(previous);
      if (epoch !== this.renderEpoch || this.image.currentSrc !== next) return;
      this.drawing = false; this.image.hidden = false; this.placeholder.hidden = true;
      this.snapshot = header.position ? Object.freeze({blob, cameraId:this.camera.id, cameraName:this.camera.name,
        generation:header.generation, sequence:header.sequence, position:Date.parse(header.position),
        width:this.image.naturalWidth, height:this.image.naturalHeight}) : null;
      this.paintFrameControls();
      if (header.position) this.onPosition(Date.parse(header.position));
    };
    this.image.onerror = () => { if (previous) URL.revokeObjectURL(previous); this.drawing = false; };
    this.image.src = next;
  }

  paint(status) {
    const state = status?.state;
    this.panel.querySelector("#history-player").dataset.state = state || "idle";
    this.message.textContent = status?.error || LABELS[state] || "Select a time or motion interval to play its recording.";
    this.placeholder.textContent = this.message.textContent;
    this.pauseButton.textContent = state === "paused" ? "Resume" : "Pause";
    const rate = status?.rate ?? this.session?.rate ?? 1;
    const pendingRate = this.session && this.session.requested_rate !== this.session.rate;
    const controlsEnabled = this.session && ["playing", "paused"].includes(state) && !this.loading && !this.controlling && !pendingRate;
    this.pauseButton.disabled = !controlsEnabled;
    for (const button of this.speedButtons) {
      button.setAttribute("aria-pressed", String(Number(button.dataset.rate) === rate));
      button.disabled = !controlsEnabled || !this.session.supported_rates?.includes(Number(button.dataset.rate));
    }
    this.speedMessage.textContent = status?.rate_error || (pendingRate ? "Changing playback speed…" : "");
    this.stopButton.disabled = !this.session;
    if (state === "error") { this.image.hidden = true; this.snapshot = null; }
    this.paintFrameControls();
  }

  paintFrameControls() {
    const ready = this.snapshot && !this.loading && !this.controlling && this.session && ["playing", "paused"].includes(this.session.state);
    for (const button of this.stepButtons) {
      const delta = Number(button.dataset.seconds);
      button.disabled = !ready || (delta < 0 ? this.snapshot.position <= Date.parse(this.session.from) : this.snapshot.position >= Date.parse(this.session.to) - 1000);
    }
    this.downloadButton.disabled = !this.snapshot || this.downloading;
    this.onSnapshot?.();
  }

  step(seconds) {
    if (!this.snapshot || !this.session || this.loading || this.controlling) return;
    const position = Math.max(Date.parse(this.session.from), Math.min(Date.parse(this.session.to) - 1000, this.snapshot.position + seconds * 1000));
    this.select(this.camera, position, Date.parse(this.session.from), Date.parse(this.session.to), this.session.requested_rate);
  }

  async download() {
    if (!this.snapshot || this.downloading) return;
    const snapshot = this.snapshot, aspect = readAspect(snapshot.cameraId, this.camera.aspect_ratio);
    this.downloading = true; this.paintFrameControls(); this.downloadMessage.textContent = "Saving frame…";
    try { await downloadFrame(snapshot, aspect); this.downloadMessage.textContent = "Frame downloaded."; }
    catch (error) { this.downloadMessage.textContent = error.message; }
    finally { this.downloading = false; this.paintFrameControls(); }
  }

  async poll() {
    if (!this.session || this.loading || this.controlling) return;
    const id = this.session.id, epoch = this.epoch, controlVersion = this.controlVersion;
    try {
      const status = await api(`/api/playback/sessions/${id}`);
      if (epoch !== this.epoch || controlVersion !== this.controlVersion || this.session?.id !== id || status.generation !== this.expectedGeneration) return;
      this.session = status; this.paint(status);
    } catch (error) { if (epoch === this.epoch) this.paint({state:"error", error:error.message}); }
  }

  async control() {
    if (!this.session || this.loading || this.controlling) return;
    const id = this.session.id, epoch = this.epoch;
    const state = this.session.state === "paused" ? "playing" : "paused";
    if (state === "playing") {
      this.loading = true; this.expectedGeneration = this.session.generation + 1;
      this.clearPicture(); this.paint({state:"resuming"});
    }
    ++this.controlVersion; this.controlling = true; this.paint({state:state === "playing" ? "resuming" : "pausing"});
    try {
      const status = await api(`/api/playback/sessions/${id}`, "PATCH", {state});
      if (epoch === this.epoch && this.session?.id === id) {
        this.session = status; this.expectedGeneration = status.generation; this.loading = false; this.controlling = false; this.paint(status);
        if (this.bufferedFrame) { const {jpeg, header} = this.bufferedFrame; this.bufferedFrame = null; this.frame(jpeg, header); }
      }
    } catch (error) { if (epoch === this.epoch) { this.controlling = false; this.paint({state:"error", error:error.message}); } }
  }

  async changeRate(rate) {
    if (!this.session || this.loading || this.controlling || this.session.requested_rate !== this.session.rate || rate === this.session.rate) return;
    const id = this.session.id, epoch = this.epoch;
    ++this.controlVersion; this.controlling = true; this.paint(this.session);
    try {
      const status = await api(`/api/playback/sessions/${id}`, "PATCH", {rate});
      if (epoch === this.epoch && this.session?.id === id) {
        this.session = status; this.controlling = false; this.paint(status);
      }
    } catch (error) {
      if (epoch === this.epoch) { this.controlling = false; this.paint(this.session); this.speedMessage.textContent = error.message; }
    }
  }

  async renew() {
    if (!this.session) return;
    const id = this.session.id, epoch = this.epoch;
    try { await api(`/api/playback/sessions/${id}`, "PATCH", {}); }
    catch (error) { if (epoch === this.epoch) this.paint({state:"error", error:error.message}); }
  }

  clearPicture() {
    this.snapshot = null; this.downloadMessage.textContent = "";
    ++this.renderEpoch; this.drawing = false;
    this.image.onload = this.image.onerror = null; this.image.removeAttribute("src");
    if (this.url) URL.revokeObjectURL(this.url); this.url = null;
    this.image.hidden = true; this.placeholder.hidden = false;
    this.paintFrameControls();
  }

  async release() {
    clearInterval(this.pollTimer); clearInterval(this.renewTimer);
    this.feed?.close(); this.feed = null;
    const session = this.session; this.session = null;
    if (session) await api(`/api/playback/sessions/${session.id}`, "DELETE").catch(() => {});
  }

  async stop() {
    const epoch = ++this.epoch; this.pending = null; this.loading = true; this.controlling = false; this.clearPicture(); this.paint(null);
    if (this.draining) await this.draining;
    if (epoch === this.epoch) { await this.release(); this.loading = false; this.paint(null); }
  }

  releaseOnClose() {
    if (this.session) fetch(`/api/playback/sessions/${this.session.id}`, {method:"DELETE", keepalive:true}).catch(() => {});
    this.stop();
  }
}
