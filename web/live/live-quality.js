import {api} from "/shared/api.js";

// One document owns one lease. Serialize full selections; local intent wins over
// responses and JPEG decodes which finish after the user changes their mind.
export class LiveQuality {
  constructor(tiles, onChange) {
    this.tiles = tiles;
    this.onChange = onChange;
    this.epoch = 0;
    this.intents = new Map();
  }

  attach(session) {
    this.detach();
    this.id = session.id;
    this.revision = session.selection_revision;
    this.intents = new Map(session.cameras.map(camera => {
      const tile = this.tiles.get(camera.id), high = tile.view.getAttribute("aria-expanded") === "true";
      tile.setQualityIntent(high);
      return [camera.id, {high, version:0, sentRevision:null, blocked:null, acknowledged:false}];
    }));
    this.paint(session);
    if ([...this.intents.values()].some(intent => intent.high)) this.schedule();
  }

  detach() {
    ++this.epoch;
    this.id = null;
    this.pending?.controller.abort();
    this.pending = null;
    this.dirty = false;
    this.cleanupNext = false;
    for (const tile of this.tiles.values()) tile.cancelDecode();
  }

  change(id, high) {
    this.tiles.get(id)?.setQualityIntent(high);
    const previous = this.intents.get(id);
    if (!this.id || !previous) return;
    this.intents.set(id, {high, version:previous.version+1, sentRevision:null, blocked:null, acknowledged:false});
    this.schedule();
  }

  schedule() {
    this.dirty = true;
    queueMicrotask(() => this.flush());
  }

  async flush() {
    if (!this.id || this.pending || !this.dirty) return;
    this.dirty = false;
    const snapshot = new Map([...this.intents].map(([id, intent]) => [id, {...intent}]));
    const pending = {id:this.id, epoch:this.epoch, snapshot, controller:new AbortController(), cleanup:this.cleanupNext};
    this.cleanupNext = false;
    this.pending = pending;
    for (const [id, intent] of snapshot) {
      if (intent.high && !intent.blocked) this.intents.get(id).sentRevision = this.revision+1;
    }
    const cameras = [...snapshot].map(([id, intent]) => ({id, quality:intent.high && !intent.blocked ? "high" : "overview"}));
    const retry_high = [...snapshot].filter(([id, intent]) => intent.high && !intent.blocked && !intent.acknowledged).map(([id]) => id);
    const timer = setTimeout(() => pending.controller.abort(), 15000);
    try {
      const session = await api(`/api/live/sessions/${pending.id}`, "PATCH", {cameras, retry_high}, {}, pending.controller.signal);
      if (!this.current(pending)) return;
      for (const [id, sent] of snapshot) {
        const intent = this.intents.get(id);
        if (intent?.version === sent.version && sent.high && !sent.blocked) {
          intent.sentRevision = session.selection_revision;
          intent.acknowledged = true;
        }
      }
      this.paint(session);
    } catch (error) {
      if (!this.current(pending)) return;
      for (const [id, sent] of snapshot) {
        const intent = this.intents.get(id);
        if (intent?.version !== sent.version || !sent.high || sent.blocked || sent.acknowledged) continue;
        intent.blocked = {code:"quality_request_failed", message:"Could not change picture quality. Collapse and expand to retry."};
        this.tiles.get(id).qualityUnavailable(intent.blocked);
      }
      // The recorder may have applied a request whose HTTP reply was lost.
      // Release unconfirmed upgrades once, without retrying high quality.
      if (!pending.cleanup) { this.cleanupNext = true; this.dirty = true; }
      this.onChange();
    } finally {
      clearTimeout(timer);
      if (this.pending === pending) {
        this.pending = null;
        if (this.dirty) queueMicrotask(() => this.flush());
      }
    }
  }

  current(request) { return this.id === request.id && this.epoch === request.epoch; }

  paint(session) {
    if (session.id !== this.id || session.selection_revision < this.revision) return false;
    this.revision = session.selection_revision;
    for (const camera of session.cameras) {
      const intent = this.intents.get(camera.id), tile = this.tiles.get(camera.id);
      if (!intent || !tile) continue;
      if (intent.high && !intent.blocked && intent.sentRevision === session.selection_revision && camera.requested_quality === "high" &&
          !["pending", "active"].includes(camera.upgrade_state)) {
        intent.blocked = camera.quality_reason || {code:"unavailable", message:"High quality is unavailable."};
        tile.qualityUnavailable(intent.blocked);
      }
      tile.paint(camera);
    }
    this.onChange(session);
    return true;
  }

  frame(id, jpeg, header) {
    if (!this.id || !this.intents.has(id) || !["overview", "high"].includes(header.quality) ||
        !Number.isInteger(header.generation) || !Number.isInteger(header.sequence) ||
        !Number.isInteger(header.selection_revision) || header.selection_revision < this.revision) return;
    this.revision = header.selection_revision;
    const request = {id:this.id, epoch:this.epoch};
    this.tiles.get(id)?.frame(jpeg, header, () => this.current(request) && header.selection_revision === this.revision);
  }
}
