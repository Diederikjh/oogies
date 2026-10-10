import {MediaDisplay} from "/shared/media-player.js";
import {readAspect, saveAspect} from "/shared/display-preferences.js";

export class RecordedClip {
  constructor(panel) {
    this.video = panel.querySelector("video");
    this.display = new MediaDisplay(this.video, panel.querySelector(".viewer"));
    this.aspect = readAspect("camera-1");
    this.display.setAspect(this.aspect);
  }
  setAspect(value) { this.aspect = saveAspect("camera-1", value); this.display.setAspect(this.aspect); }
  show() { if (!this.video.getAttribute("src")) this.video.src = "/recording.mp4"; }
  hide() { this.video.pause(); }
}
