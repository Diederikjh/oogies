export class DisplaySettings {
  constructor(dialog, tiles, recording) {
    this.dialog = dialog;
    this.tiles = tiles;
    this.recording = recording;
    this.list = dialog.querySelector("#aspect-settings");
    document.getElementById("settings-open").addEventListener("click", () => {
      this.render();
      dialog.showModal();
    });
    document.getElementById("settings-close").addEventListener("click", () => dialog.close());
  }

  camerasReady() {
    const first = this.tiles.get("camera-1");
    if (first) this.recording.setAspect(first.aspect);
    if (this.dialog.open) this.render();
  }

  render() {
    this.list.replaceChildren();
    const cameras = [...this.tiles.values()].map(tile => ({id:tile.camera.id,
      name:tile.camera.name, aspect:tile.aspect, apply:value => tile.setAspect(value)}));
    if (!this.tiles.has("camera-1")) cameras.push({id:"camera-1", name:"Camera 1 · Recorded clip",
      aspect:this.recording.aspect, apply:() => {}});
    for (const camera of cameras) {
      const label = document.createElement("label");
      label.className = "aspect-setting";
      const name = document.createElement("span");
      name.textContent = camera.name;
      const select = document.createElement("select");
      select.dataset.cameraId = camera.id;
      for (const [value, text] of [["16:9","Widescreen (16:9)"], ["4:3","Standard (4:3)"], ["original","Original"]]) {
        select.add(new Option(text, value));
      }
      select.value = camera.aspect;
      select.addEventListener("change", () => {
        camera.apply(select.value);
        if (camera.id === "camera-1") this.recording.setAspect(select.value);
      });
      label.append(name, select);
      this.list.append(label);
    }
  }
}
