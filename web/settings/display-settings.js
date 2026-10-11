export class DisplaySettings {
  constructor(dialog, tiles) {
    this.dialog = dialog;
    this.tiles = tiles;
    this.list = dialog.querySelector("#aspect-settings");
    document.getElementById("settings-open").addEventListener("click", () => {
      this.render();
      dialog.showModal();
    });
    document.getElementById("settings-close").addEventListener("click", () => dialog.close());
  }

  camerasReady() {
    if (this.dialog.open) this.render();
  }

  render() {
    this.list.replaceChildren();
    const cameras = [...this.tiles.values()].map(tile => ({id:tile.camera.id,
      name:tile.camera.name, aspect:tile.aspect, apply:value => tile.setAspect(value)}));
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
      });
      label.append(name, select);
      this.list.append(label);
    }
  }
}
