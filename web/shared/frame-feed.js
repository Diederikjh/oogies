// One fetch connection carries the original JPEGs for every subscribed camera.
export class FrameFeed {
  constructor(url, onFrame) {
    this.url = url;
    this.onFrame = onFrame;
    this.abort = new AbortController();
  }

  async run() {
    const response = await fetch(this.url, {signal:this.abort.signal, cache:"no-store"});
    if (!response.ok) throw new Error("The camera frame feed is unavailable.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = new Uint8Array(0);
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) return;
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
          this.onFrame(header.camera_id, jpeg);
          offset += 4 + length;
        }
        pending = joined.slice(offset);
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  close() { this.abort.abort(); }
}
