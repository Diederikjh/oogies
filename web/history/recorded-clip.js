import {MediaDisplay} from "/shared/media-player.js";

export class RecordedClip {
  constructor(panel) {
    this.video = panel.querySelector("video");
    this.display = new MediaDisplay(this.video, panel.querySelector(".viewer"));
    this.display.setAspect("16:9");
    const select = panel.querySelector("select");
    select.addEventListener("change", () => this.display.setAspect(select.value));
  }
  show() { if (!this.video.getAttribute("src")) this.video.src = "/recording.mp4"; }
  hide() { this.video.pause(); }
}
