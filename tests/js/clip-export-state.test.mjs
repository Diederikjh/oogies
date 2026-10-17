import assert from "node:assert/strict";
import test from "node:test";
import {ClipExportState} from "../../web/history/clip-export-state.js";
import {manualClock, deferred} from "./support/manual-time.mjs";

const request = () => ({cameraName:"Driveway", body:{camera_id:"camera-1",
  from:"2025-01-15T10:00:00.000Z", to:"2025-01-15T10:00:10.000Z", aspect_ratio:"16:9"}});

function fixture(post) {
  const clock = manualClock(), calls = [], changes = [];
  let keys = 0;
  const owner = new ClipExportState({
    key:() => `key-${++keys}`, schedule:clock.schedule, cancel:clock.cancel,
    post:(body, key) => {
      const reply = deferred(); calls.push({body, key, reply});
      return post ? post(body, key) : reply.promise;
    },
    onChange:state => changes.push(state)
  });
  return {owner, clock, calls, changes};
}

test("one submit publishes pending state, sends the body and key, then publishes success", async () => {
  const {owner, calls, changes, clock} = fixture();
  assert.deepEqual(owner.state, {submitting:false, feedback:null});
  const done = owner.submit(request());
  assert.deepEqual(owner.state, {submitting:true, feedback:{kind:"pending"}});
  assert.deepEqual(calls[0].body, request().body); assert.equal(calls[0].key, "key-1");
  assert.equal(clock.pending, 0);
  calls[0].reply.resolve({id:"accepted-job"}); await done;
  assert.deepEqual(owner.state, {submitting:false, feedback:{kind:"success", cameraName:"Driveway"}});
  assert.equal(clock.pending, 1);
  assert.equal(changes.at(-1).feedback, changes.at(-2).feedback, "guard release preserves feedback identity for rendering");
  assert.equal(Object.isFrozen(owner.state), true);
  assert.equal(Object.isFrozen(owner.state.feedback), true);
});

test("repeat submissions while pending cannot emit another POST, even after feedback is cleared", async () => {
  const {owner, calls} = fixture();
  const done = owner.submit(request());
  await owner.submit(request()); owner.clearFeedback();
  await owner.submit({...request(), body:{...request().body, camera_id:"camera-2"}});
  assert.equal(calls.length, 1); assert.equal(owner.state.submitting, true);
  calls[0].reply.resolve(); await done;
  assert.deepEqual(owner.state, {submitting:false, feedback:null});
});

test("request and confirmation retain camera, range, aspect and name from submission", async () => {
  const {owner, calls} = fixture(), input = request();
  const done = owner.submit(input);
  Object.assign(input.body, {camera_id:"camera-2", from:"changed", to:"changed", aspect_ratio:"4:3"});
  input.cameraName = "Storage";
  assert.deepEqual(calls[0].body, request().body);
  assert.equal(Object.isFrozen(calls[0].body), true);
  calls[0].reply.resolve(); await done;
  assert.equal(owner.state.feedback.cameraName, "Driveway");
});

test("success expires at 60000 ms, remains at 59999 and leaves the selection submit-ready", async () => {
  const {owner, calls, clock} = fixture();
  const done = owner.submit(request());
  clock.advance(90000); assert.equal(clock.pending, 0); // Pending time is not confirmation time.
  calls[0].reply.resolve(); await done;
  clock.advance(59999); assert.equal(owner.state.feedback.kind, "success");
  clock.advance(1); assert.deepEqual(owner.state, {submitting:false, feedback:null});
  assert.equal(clock.pending, 0); assert.equal(calls.length, 1);
});

test("errors remain visible without gaining a confirmation expiry timer", async () => {
  const {owner, calls, clock} = fixture();
  const done = owner.submit(request()); calls[0].reply.reject(new Error("Recorder busy")); await done;
  assert.deepEqual(owner.state, {submitting:false, feedback:{kind:"error", message:"Recorder busy"}});
  clock.advance(120000); assert.equal(owner.state.feedback.message, "Recorder busy");
  assert.equal(clock.pending, 0);
  owner.clearFeedback(); assert.equal(owner.state.feedback, null);
});

test("a synchronous POST error is handled and releases the guard", async () => {
  const {owner, clock} = fixture(() => { throw new Error("Connection unavailable"); });
  await owner.submit(request());
  assert.equal(owner.state.submitting, false);
  assert.equal(owner.state.feedback.message, "Connection unavailable");
  assert.equal(clock.pending, 0);
});

test("failed identical submissions reuse the idempotency key, including after clearing feedback", async () => {
  const {owner, calls} = fixture();
  let done = owner.submit(request()); calls[0].reply.reject(new Error("Lost reply")); await done;
  owner.clearFeedback();
  done = owner.submit(request()); assert.equal(calls[1].key, "key-1");
  calls[1].reply.reject(new Error("Lost reply again")); await done;
  done = owner.submit(request()); assert.equal(calls[2].key, "key-1");
  calls[2].reply.resolve(); await done;
});

for (const [field, value] of [["camera_id", "camera-2"], ["from", "2025-01-15T09:59:59.000Z"],
  ["to", "2025-01-15T10:00:11.000Z"], ["aspect_ratio", "4:3"]]) {
  test(`changed ${field} after failure generates a new retry identity`, async () => {
    const {owner, calls} = fixture();
    let done = owner.submit(request()); calls[0].reply.reject(new Error("Lost reply")); await done;
    const changed = request(); changed.body[field] = value;
    done = owner.submit(changed); assert.equal(calls[1].key, "key-2");
    assert.deepEqual(calls[1].body, changed.body);
    calls[1].reply.resolve(); await done;
  });
}

test("a camera rename changes confirmation text without changing the failed request's key", async () => {
  const {owner, calls} = fixture();
  let done = owner.submit(request()); calls[0].reply.reject(new Error("Lost reply")); await done;
  done = owner.submit({...request(), cameraName:"Renamed driveway"});
  assert.equal(calls[1].key, "key-1"); calls[1].reply.resolve(); await done;
  assert.equal(owner.state.feedback.cameraName, "Renamed driveway");
});

for (const clear of [false, true]) {
  test(`success clears retry identity for another save (clear feedback=${clear})`, async () => {
    const {owner, calls, clock} = fixture();
    let done = owner.submit(request()); calls[0].reply.resolve(); await done;
    if (clear) owner.clearFeedback();
    done = owner.submit(request()); assert.equal(calls[1].key, "key-2");
    assert.equal(clock.pending, 0); // The old confirmation timer is cancelled.
    calls[1].reply.resolve(); await done; assert.equal(clock.pending, 1);
  });
}

for (const outcome of ["success", "error"]) {
  test(`feedback invalidation suppresses late ${outcome} and releases the guard`, async () => {
    const {owner, calls, clock} = fixture();
    const done = owner.submit(request());
    // All three UI paths invoke clearFeedback; browser tests cover their wiring.
    owner.clearFeedback(); owner.clearFeedback();
    assert.deepEqual(owner.state, {submitting:true, feedback:null});
    if (outcome === "success") calls[0].reply.resolve({id:"job-still-accepted"});
    else calls[0].reply.reject(new Error("Late error"));
    await done; // Rejections are handled by the owner.
    assert.deepEqual(owner.state, {submitting:false, feedback:null});
    assert.equal(clock.pending, 0);
    const again = owner.submit(request());
    assert.equal(calls[1].key, outcome === "success" ? "key-2" : "key-1");
    calls[1].reply.resolve(); await again;
    assert.equal(owner.state.feedback.kind, "success");
  });
}

test("clearing a confirmation cancels its timer without changing the accepted job", async () => {
  const {owner, calls, clock} = fixture();
  const done = owner.submit(request()); calls[0].reply.resolve(); await done;
  owner.clearFeedback(); assert.equal(clock.pending, 0);
  clock.advance(60000); assert.equal(owner.state.feedback, null);
  assert.equal(calls.length, 1, "clearing feedback sends no cancellation request");
});

for (const replacement of ["pending", "success", "error", "cleared"]) {
  test(`a previously queued expiry cannot clear ${replacement} feedback`, async () => {
    const {owner, calls, clock} = fixture();
    let done = owner.submit(request()); calls[0].reply.resolve(); await done;
    const [oldCallback] = clock.takeDue(60000); // Dispatch is queued; cancellation cannot remove it.
    done = owner.submit(request());
    if (replacement !== "pending") {
      if (replacement === "error") calls[1].reply.reject(new Error("New failure"));
      else calls[1].reply.resolve();
      await done;
      if (replacement === "cleared") owner.clearFeedback();
    }
    const current = owner.state;
    oldCallback(); assert.equal(owner.state, current);
    if (replacement === "pending") { calls[1].reply.resolve(); await done; }
    if (replacement === "success") {
      assert.equal(clock.pending, 1);
      clock.advance(59999); assert.equal(owner.state.feedback.kind, "success");
      clock.advance(1); assert.equal(owner.state.feedback, null);
    }
  });
}
