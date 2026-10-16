// One fetch connection carries the original JPEGs for every subscribed camera.
export class FrameFeed {
  constructor(url, onFrame, {onInterrupt = () => {}, expectFrames = () => false} = {}) {
    this.url = url;
    this.onFrame = onFrame;
    this.onInterrupt = onInterrupt;
    this.expectFrames = expectFrames;
    this.abort = new AbortController();
  }

  async run() {
    let failures = 0;
    while (!this.abort.signal.aborted) {
      const started = performance.now();
      this.lastFrame = null;
      try { await this.read(); }
      catch (error) {
        if (this.abort.signal.aborted) return;
        // A stable connection earns a fresh retry budget, not each packet.
        if (this.lastFrame !== null && performance.now() - started >= 30000) failures = 0;
        if (error.terminal || failures >= 3) throw error;
        this.onInterrupt();
        await this.delay(1000 * 2 ** failures++);
      }
    }
  }

  delay(ms) {
    return new Promise(resolve => {
      const finish = () => { clearTimeout(timer); this.abort.signal.removeEventListener("abort", finish); resolve(); };
      const timer = setTimeout(finish, ms);
      this.abort.signal.addEventListener("abort", finish, {once:true});
      if (this.abort.signal.aborted) finish();
    });
  }

  async read() {
    const connection = new AbortController();
    const close = () => connection.abort();
    this.abort.signal.addEventListener("abort", close, {once:true});
    if (this.abort.signal.aborted) close();
    const handshake = setTimeout(close, 10000);
    let expectedSince = performance.now(), reader;
    const watchdog = setInterval(() => {
      if (!this.expectFrames()) expectedSince = performance.now();
      else if (performance.now() - Math.max(expectedSince, this.lastFrame ?? expectedSince) > 10000) close();
    }, 1000);
    try {
      const response = await fetch(this.url, {signal:connection.signal, cache:"no-store"});
      clearTimeout(handshake);
      if (!response.ok) {
        const error = new Error("The camera frame feed is unavailable.");
        error.terminal = response.status >= 400 && response.status < 500 && response.status !== 409;
        await response.body?.cancel().catch(() => {});
        throw error;
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = new Uint8Array(0);
      while (true) {
        const {value, done} = await reader.read();
        if (done) throw new Error("The camera frame connection ended.");
        const joined = new Uint8Array(pending.length + value.length);
        joined.set(pending); joined.set(value, pending.length);
        let offset = 0;
        while (joined.length - offset >= 4) {
          const length = new DataView(joined.buffer, offset, 4).getUint32(0);
          if (length < 3 || length > 4 * 1024 * 1024 + 1024) throw new Error("Invalid camera frame size.");
          if (joined.length - offset < 4 + length) break;
          const headerLength = new DataView(joined.buffer, offset + 4, 2).getUint16(0);
          if (!headerLength || headerLength > 512 || headerLength + 2 >= length) throw new Error("Invalid frame header.");
          const header = JSON.parse(decoder.decode(joined.subarray(offset + 6, offset + 6 + headerLength)));
          const jpeg = joined.subarray(offset + 6 + headerLength, offset + 4 + length);
          this.onFrame(header.camera_id, jpeg, header);
          this.lastFrame = performance.now();
          offset += 4 + length;
        }
        pending = joined.slice(offset);
      }
    } finally {
      clearInterval(watchdog);
      clearTimeout(handshake);
      this.abort.signal.removeEventListener("abort", close);
      close();
      if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    }
  }

  close() { this.abort.abort(); }
}
