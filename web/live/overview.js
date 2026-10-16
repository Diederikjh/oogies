import {api} from "/shared/api.js";
import {FrameFeed} from "/shared/frame-feed.js";
import {CameraTile} from "/live/camera-tile.js";
import {LiveQuality} from "/live/live-quality.js";

export class Overview {
  constructor(grid, onStatus, onError, onCameras = () => {}, onHistory = () => {}) {
    this.grid = grid;
    this.onStatus = onStatus;
    this.onError = onError;
    this.onCameras = onCameras;
    this.onHistory = onHistory;
    this.tiles = new Map();
    this.quality = new LiveQuality(this.tiles, session => {
      if (session) this.session = session;
      this.emitStatus();
    });
    this.session = null;
    this.feed = null;
    this.busy = false;
    this.active = false;
    this.generation = 0;
    this.pollCounter = this.appliedPoll = 0;
  }

  async start() {
    this.active = true;
    if (this.busy) { this.startQueued = true; return; }
    if (this.session) return;
    this.busy = true;
    this.startQueued = false;
    const generation = ++this.generation;
    try {
      const inventory = await api("/api/cameras");
      if (generation !== this.generation) return;
      for (const camera of inventory.cameras) {
        if (!this.tiles.has(camera.id)) this.tiles.set(camera.id, new CameraTile(camera, this.grid, this.onHistory,
          (id, expanded) => this.quality.change(id, expanded), () => this.emitStatus()));
      }
      this.onCameras();
      const selection = inventory.cameras.map(camera => ({id:camera.id, quality:"overview"}));
      const session = await api("/api/live/sessions", "POST", {cameras:selection}, {"Idempotency-Key":crypto.randomUUID()});
      if (generation !== this.generation) { await api(`/api/live/sessions/${session.id}`, "DELETE"); return; }
      this.session = session;
      this.quality.attach(session);
      const context = {id:session.id, generation};
      this.feed = new FrameFeed(session.media.url, (id, jpeg, header) => {
        if (this.session?.id === context.id && this.generation === context.generation) this.quality.frame(id, jpeg, header);
      }, {
        expectFrames: () => this.session?.cameras.some(camera => camera.state === "live"),
        onInterrupt: () => {
          if (this.session?.id !== context.id || this.generation !== context.generation) return;
          for (const tile of this.tiles.values()) tile.interruptFeed();
          this.emitStatus();
        }
      });
      this.feed.run().catch(async error => {
        if (this.session?.id === context.id && this.generation === context.generation) {
          this.onError(`${error.message} Press Resume view to reconnect.`);
          await this.stop();
        }
      });
      this.pollTimer = setInterval(() => this.poll(), 1000);
      this.renewTimer = setInterval(() => this.renew(), Math.max(3000, session.lease_seconds * 1000 / 3));
    } catch (error) {
      if (generation === this.generation) {
        this.onError(error.message);
        this.active = false;
      }
    } finally {
      this.busy = false;
      if (this.startQueued && this.active) this.start();
    }
  }

  paint(session) {
    this.quality.paint(session);
  }

  emitStatus() {
    const cameras = this.session?.cameras.map(camera => ({...camera, state:this.tiles.get(camera.id)?.element.dataset.state || camera.state}));
    const high = cameras?.filter(camera => camera.state === "live" && this.tiles.get(camera.id)?.rendered?.quality === "high").length || 0;
    this.onStatus(this.session ? {...this.session, cameras} : null, {high});
  }

  async poll() {
    if (!this.session) return;
    const id = this.session.id, generation = this.generation, poll = ++this.pollCounter;
    try {
      const status = await api(`/api/live/sessions/${id}`);
      if (this.session?.id === id && this.generation === generation && poll > this.appliedPoll) {
        this.appliedPoll = poll; this.paint(status);
      }
    } catch (error) {
      if (this.session?.id === id) { this.onError(error.message); await this.stop(); }
    }
  }

  async renew() {
    if (!this.session) return;
    const id = this.session.id, generation = this.generation;
    try { await api(`/api/live/sessions/${id}`, "PATCH", {}); }
    catch (error) { if (this.session?.id === id && this.generation === generation) { this.onError(error.message); await this.stop(); } }
  }

  async stop() {
    this.active = false;
    this.startQueued = false;
    ++this.generation;
    this.quality.detach();
    clearInterval(this.pollTimer); clearInterval(this.renewTimer);
    this.feed?.close(); this.feed = null;
    const session = this.session;
    this.session = null;
    for (const tile of this.tiles.values()) tile.pause();
    if (session) await api(`/api/live/sessions/${session.id}`, "DELETE").catch(() => {});
    this.onStatus(null);
  }

  releaseOnClose() {
    this.active = false;
    this.quality.detach();
    if (this.session) fetch(`/api/live/sessions/${this.session.id}`, {method:"DELETE", keepalive:true}).catch(() => {});
    this.feed?.close();
  }
}
