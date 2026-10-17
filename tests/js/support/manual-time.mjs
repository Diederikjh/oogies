// Deliberately small: explicit advances, with callbacks removable from the timer
// queue before dispatch to model cancellation that comes too late.
export function manualClock() {
  let now = 0, next = 0;
  const tasks = new Map();
  const clock = {
    schedule(callback, delay) {
      const id = ++next; tasks.set(id, {at:now + delay, callback}); return id;
    },
    cancel(id) { tasks.delete(id); },
    takeDue(milliseconds) {
      now += milliseconds;
      const due = [...tasks].filter(([, task]) => task.at <= now).sort((a, b) => a[1].at - b[1].at);
      for (const [id] of due) tasks.delete(id);
      return due.map(([, task]) => task.callback);
    },
    advance(milliseconds) { for (const callback of clock.takeDue(milliseconds)) callback(); },
    get pending() { return tasks.size; }
  };
  return clock;
}

export function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
