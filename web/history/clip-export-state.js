// Request identity and feedback lifetime are independent of DOM and backend jobs.
export class ClipExportState {
  constructor({post, key = () => crypto.randomUUID(), schedule = (callback, delay) => setTimeout(callback, delay),
    cancel = timer => clearTimeout(timer), onChange = () => {}}) {
    this.post = post; this.key = key; this.schedule = schedule; this.cancel = cancel; this.onChange = onChange;
    this.state = Object.freeze({submitting:false, feedback:null});
    this.generation = 0; this.retry = null; this.timer = undefined;
  }
  publish(change) {
    this.state = Object.freeze({...this.state, ...change});
    this.onChange(this.state);
  }
  clearFeedback() {
    ++this.generation;
    if (this.timer !== undefined) this.cancel(this.timer);
    this.timer = undefined;
    this.publish({feedback:null});
  }
  async submit({body, cameraName}) {
    if (this.state.submitting) return;
    // Export bodies contain only primitive values. Snapshot before any await.
    const request = Object.freeze({...body}), serialized = JSON.stringify(request);
    if (this.retry?.body !== serialized) this.retry = {body:serialized, key:this.key()};
    const key = this.retry.key;
    this.clearFeedback(); const generation = this.generation;
    this.publish({submitting:true, feedback:Object.freeze({kind:"pending"})});
    try {
      await this.post(request, key);
      this.retry = null;
      if (generation !== this.generation) return;
      this.timer = this.schedule(() => {
        if (generation === this.generation) this.clearFeedback();
      }, 60000);
      this.publish({feedback:Object.freeze({kind:"success", cameraName})});
    } catch (error) {
      if (generation === this.generation) this.publish({feedback:Object.freeze({kind:"error", message:error.message})});
    } finally {
      this.publish({submitting:false});
    }
  }
}
