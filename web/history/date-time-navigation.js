// The server resolves recorder wall time; datetime-local never uses browser TZ.
export class DateTimeNavigation {
  constructor(panel, onNavigate) {
    this.form = panel.querySelector("#history-date-form");
    this.input = panel.querySelector("#history-date-time");
    this.button = panel.querySelector("#history-go-time");
    this.zoneLabel = panel.querySelector("#history-date-zone");
    this.message = panel.querySelector("#history-date-message");
    this.picker = panel.querySelector(".history-date-picker");
    document.addEventListener("pointerdown", event => {
      if (this.picker.open && !this.picker.contains(event.target)) this.picker.open = false;
    });
    this.picker.addEventListener("keydown", event => {
      if (event.key === "Escape") { this.picker.open = false; this.picker.querySelector("summary").focus(); }
    });
    this.form.addEventListener("submit", event => {
      event.preventDefault();
      if (!this.input.disabled && this.form.reportValidity()) {
        this.error(""); onNavigate(this.input.value);
      }
    });
  }

  ready(zone, reference) {
    this.zoneLabel.textContent = `Times in ${zone}`;
    if (!this.input.value) {
      const parts = new Intl.DateTimeFormat("en-CA", {timeZone:zone, year:"numeric", month:"2-digit", day:"2-digit",
        hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"}).formatToParts(new Date(reference));
      const fields = Object.fromEntries(parts.map(part => [part.type, part.value]));
      this.input.value = `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}:${fields.second}`;
    }
    this.input.disabled = false; this.button.disabled = false;
  }

  error(message) { this.message.textContent = message; }
}
