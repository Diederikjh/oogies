// Fit the full picture using its display ratio, which can differ from its raster.
const RATIOS = {"16:9": 16 / 9, "4:3": 4 / 3};

export class MediaDisplay {
  constructor(media, viewport) {
    this.media = media;
    this.viewport = viewport;
    this.mode = "16:9";
    this.sourceWidth = this.sourceHeight = 0;
    this.displayWidth = this.displayHeight = null;
    this.onMetadata = () => {
      // Preset ratios do not depend on each incoming JPEG's dimensions.
      if (this.mode !== "original") return;
      const width = media.naturalWidth || media.videoWidth;
      const height = media.naturalHeight || media.videoHeight;
      if (width !== this.sourceWidth || height !== this.sourceHeight) this.fit();
    };
    media.addEventListener("load", this.onMetadata);
    media.addEventListener("loadedmetadata", this.onMetadata);
    this.observer = new ResizeObserver(() => this.fit());
    this.observer.observe(viewport);
  }

  setAspect(mode) {
    this.mode = ["16:9", "4:3", "original"].includes(mode) ? mode : "16:9";
    this.fit();
  }

  fit() {
    const sourceWidth = this.media.naturalWidth || this.media.videoWidth;
    const sourceHeight = this.media.naturalHeight || this.media.videoHeight;
    this.sourceWidth = sourceWidth;
    this.sourceHeight = sourceHeight;
    const ratio = RATIOS[this.mode] || sourceWidth / sourceHeight;
    const availableWidth = this.viewport.clientWidth;
    const availableHeight = this.viewport.clientHeight;
    if (!Number.isFinite(ratio) || ratio <= 0 || !availableWidth || !availableHeight) return;
    const width = Math.min(availableWidth, availableHeight * ratio);
    const height = width / ratio;
    if (width === this.displayWidth && height === this.displayHeight) return;
    this.displayWidth = width;
    this.displayHeight = height;
    this.media.style.width = `${width}px`;
    this.media.style.height = `${height}px`;
  }

  dispose() {
    this.observer.disconnect();
    this.media.removeEventListener("load", this.onMetadata);
    this.media.removeEventListener("loadedmetadata", this.onMetadata);
  }
}
