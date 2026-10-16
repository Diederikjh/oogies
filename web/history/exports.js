import {api} from "/shared/api.js";

function progressIndicator() {
  const ring = document.createElement("span"); ring.className = "export-progress";
  ring.setAttribute("role", "progressbar"); ring.setAttribute("aria-valuemin", "0"); ring.setAttribute("aria-valuemax", "100");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 48 48"); svg.setAttribute("aria-hidden", "true");
  for (const name of ["track", "value"]) {
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("class", `export-progress-${name}`);
    for (const [key, value] of Object.entries({cx:24, cy:24, r:20, pathLength:100})) circle.setAttribute(key, value);
    if (name === "value") circle.setAttribute("transform", "rotate(-90 24 24)");
    svg.append(circle);
  }
  const percent = document.createElement("span"); percent.setAttribute("aria-hidden", "true");
  ring.append(svg, percent); return ring;
}

export class ExportsView {
  constructor(panel) {
    this.panel = panel; this.list = panel.querySelector("#export-jobs");
    this.message = panel.querySelector("#exports-message"); this.generation = 0;
    panel.querySelector("#exports-refresh").addEventListener("click", () => this.poll());
  }
  show() { this.active = true; this.poll(); clearInterval(this.timer); this.timer = setInterval(() => this.poll(), 1000); }
  hide() { this.active = false; ++this.generation; clearInterval(this.timer); }
  async poll() {
    if (!this.active || this.loading) return;
    const generation = this.generation; this.loading = true;
    try {
      const data = await api("/api/exports");
      if (!this.active || generation !== this.generation) return;
      this.panel.querySelector("#exports-limits").textContent = `Clips up to ${data.limits.max_duration_seconds} seconds · One export at a time · Downloads kept for ${data.limits.retention_hours} hours`;
      const existing = new Map([...this.list.children].map(row => [row.dataset.jobId, row]));
      let position = 0;
      for (const job of data.jobs) {
        let row = existing.get(job.id); existing.delete(job.id);
        if (!row) {
          row = document.createElement("li"); row.className = "export-job"; row.dataset.jobId = job.id;
          const title = document.createElement("h2"), range = document.createElement("p"), status = document.createElement("p"), actions = document.createElement("div");
          range.className = "subtitle"; status.className = "export-status"; status.setAttribute("role", "status"); actions.className = "actions";
          const label = document.createElement("span"); label.className = "export-status-label";
          status.append(progressIndicator(), label);
          row.append(title, range, status, actions);
        }
        // Keep the API's newest-first order when adding jobs to an existing list.
        // Leave rows already in place untouched during routine polling.
        if (this.list.children[position] !== row) this.list.insertBefore(row, this.list.children[position] || null);
        ++position;
        row.dataset.state = job.state;
        const [title, range, status, actions] = row.children;
        title.textContent = job.camera_name;
        const time = new Intl.DateTimeFormat(undefined, {timeZone:job.timezone, dateStyle:"medium", timeStyle:"medium"});
        range.textContent = `${time.format(new Date(job.from))} - ${time.format(new Date(job.to))} · ${job.timezone} · ${job.duration_seconds} seconds · ${job.aspect_ratio}`;
        const [ring, label] = status.children;
        ring.hidden = job.state !== "running";
        if (!ring.hidden) {
          const percent = Math.round(Math.max(0, Math.min(1, Number.isFinite(job.progress) ? job.progress : 0)) * 100);
          ring.setAttribute("aria-label", `Export progress for ${job.camera_name}`);
          ring.setAttribute("aria-valuenow", percent);
          ring.querySelector(".export-progress-value").setAttribute("stroke-dasharray", `${percent} 100`);
          ring.lastElementChild.textContent = `${percent}%`;
        }
        label.textContent = job.error || job.waiting_reason || (job.state === "running" ? "Exporting" : job.state === "ready" ? `Ready · ${(job.bytes / 1024 / 1024).toFixed(1)} MiB · Expires ${new Date(job.expires_at).toLocaleString()}` : job.state);
        if (actions.dataset.state !== job.state) {
          actions.replaceChildren(); actions.dataset.state = job.state;
          if (job.state === "ready") {
            const link = document.createElement("a"); link.className = "export-download"; link.textContent = "Download MP4";
            link.href = job.media.url; link.download = job.media.filename; actions.append(link);
          }
          if (["queued", "running", "ready"].includes(job.state)) {
            const button = document.createElement("button"); button.textContent = job.state === "ready" ? "Delete clip" : "Cancel export";
            button.addEventListener("click", async () => {
              button.disabled = true;
              try { await api(`/api/exports/${job.id}`, "DELETE"); await this.poll(); }
              catch (error) { this.message.textContent = error.message; button.disabled = false; }
            }); actions.append(button);
          }
        }
      }
      for (const row of existing.values()) row.remove();
      this.message.textContent = data.jobs.length ? "" : "No exports yet. Mark a start and end in History to queue a clip.";
    } catch (error) { if (generation === this.generation) this.message.textContent = error.message; }
    finally { this.loading = false; }
  }
}
