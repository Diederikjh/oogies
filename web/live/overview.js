import {api} from "/shared/api.js";
import {FrameFeed} from "/shared/frame-feed.js";
import {CameraTile} from "/live/camera-tile.js";

export class Overview {
  constructor(grid, onStatus, onError) {
    this.grid = grid;
    this.onStatus = onStatus;
    this.onError = onError;
    this.tiles = new Map();
    this.session = null;
    this.feed = null;
    this.busy = false;
    this.active = false;
    this.generation = 0;
  }

  async start() {
    if (this.busy || this.session) return;
    this.busy = true;
    this.active = true;
    const generation = ++this.generation;
    try {
      const inventory = await api("/api/cameras");
      if (generation !== this.generation) return;
      for (const camera of inventory.cameras) {
        if (!this.tiles.has(camera.id)) this.tiles.set(camera.id, new CameraTile(camera, this.grid));
      }
      const selection = inventory.cameras.map(camera => ({id:camera.id, quality:"overview"}));
      const session = await api("/api/live/sessions", "POST", {cameras:selection}, {"Idempotency-Key":crypto.randomUUID()});
      if (generation !== this.generation) { await api(`/api/live/sessions/${session.id}`, "DELETE"); return; }
      this.session = session;
      this.paint(session);
      this.feed = new FrameFeed(session.media.url, (id, jpeg) => this.tiles.get(id)?.frame(jpeg));
      this.feed.run().catch(error => { if (this.active && error.name !== "AbortError") this.onError(error.message); });
      this.pollTimer = setInterval(() => this.poll(), 1000);
      this.renewTimer = setInterval(() => this.renew(), Math.max(3000, session.lease_seconds * 1000 / 3));
    } catch (error) {
      this.onError(error.message);
      this.active = false;
    } finally {
      this.busy = false;
    }
  }

  paint(session) {
    for (const camera of session.cameras) this.tiles.get(camera.id)?.paint(camera);
    this.onStatus(session);
  }

  async poll() {
    if (!this.session) return;
    const id = this.session.id;
    try {
      const status = await api(`/api/live/sessions/${id}`);
      if (this.session?.id === id) this.paint(status);
    } catch (error) {
      if (this.session?.id === id) { this.onError(error.message); await this.stop(); }
    }
  }

  async renew() {
    if (!this.session) return;
    try { await api(`/api/live/sessions/${this.session.id}`, "PATCH", {}); }
    catch (error) { this.onError(error.message); await this.stop(); }
  }

  async stop() {
    this.active = false;
    ++this.generation;
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
    if (this.session) fetch(`/api/live/sessions/${this.session.id}`, {method:"DELETE", keepalive:true}).catch(() => {});
    this.feed?.close();
  }
}
