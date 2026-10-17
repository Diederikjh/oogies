import assert from "node:assert/strict";
import test from "node:test";
import {clipMark, clipStatus, clipBounds, editClipMark, clipKeyTarget} from "../../web/history/clip-model.js";

const base = Date.parse("2024-01-01T00:00:00Z");
const at = seconds => base + seconds * 1000;
const state = Object.freeze({begin:base, end:at(10800), from:at(600), to:at(630), maxSeconds:600});

for (const [label, from, to, maximum, valid, invalid] of [
  ["unset", undefined, undefined, 600, false, false],
  ["start only", at(0), undefined, 600, false, false],
  ["end only", undefined, at(30), 600, false, false],
  ["equal", at(30), at(30), 600, false, true],
  ["reversed", at(31), at(30), 600, false, true],
  ["sub-second", at(0), at(.999), 600, false, true],
  ["one second", at(0), at(1), 600, true, false],
  ["maximum", at(0), at(600), 600, true, false],
  ["overlong", at(0), at(601), 600, false, true],
  ["configured maximum", at(0), at(120), 120, true, false],
  ["configured overlong", at(0), at(121), 120, false, true],
]) {
  test(`clip validity: ${label}`, () => {
    const status = clipStatus(from, to, maximum);
    assert.equal(status.valid, valid);
    assert.equal(status.invalid, invalid);
  });
}

test("marking floors the displayed frame while editing rounds to nearest second", () => {
  assert.equal(clipMark(at(600.9)), at(600));
  assert.equal(editClipMark(at(600.9), [at(600), at(629)]), at(601));
  assert.equal(editClipMark(at(600.499), [at(600), at(629)]), at(600));
  assert.equal(editClipMark(at(600.5), [at(600), at(629)]), at(601));
});

test("marking preserves overlong/reversed values so they can be repaired", () => {
  assert.equal(clipMark(at(1200.8)), at(1200));
  assert.equal(clipStatus(base, clipMark(at(1200.8)), 600).valid, false);
  assert.equal(clipStatus(clipMark(at(631.9)), at(630), 600).duration, -1);
});

test("both marks define one-second ordering and maximum-duration bounds", () => {
  assert.deepEqual(clipBounds("from", state), [at(30), at(629)]);
  assert.deepEqual(clipBounds("to", state), [at(601), at(1200)]);
  assert.deepEqual(state, {begin:base, end:at(10800), from:at(600), to:at(630), maxSeconds:600});
});

test("unset opposite marks use loaded history bounds", () => {
  assert.deepEqual(clipBounds("from", {...state, to:undefined}), [base, at(10799)]);
  assert.deepEqual(clipBounds("to", {...state, from:undefined}), [at(1), at(10800)]);
});

test("partial marks may extend the editing domain beyond loaded history", () => {
  assert.deepEqual(clipBounds("from", {...state, from:at(12000), to:undefined}), [base, at(11999)]);
  assert.deepEqual(clipBounds("to", {...state, from:undefined, to:at(12000)}), [at(1), at(12000)]);
  assert.deepEqual(clipBounds("from", {...state, to:at(12000)}), [at(11400), at(11999)]);
});

test("start bounds retain the year-2000 floor", () => {
  const earliest = Date.UTC(2000, 0, 1);
  assert.deepEqual(clipBounds("from", {begin:earliest - 3600000, end:earliest + 3600000,
    to:earliest + 30000, maxSeconds:600}), [earliest, earliest + 29000]);
});

test("end editing cannot move past the latest loaded time when marks are inside it", () => {
  assert.deepEqual(clipBounds("to", {...state, from:at(10780), to:at(10790)}), [at(10781), at(10800)]);
});

for (const [name, requested, expected] of [
  ["to", 5000, 1200], ["from", 5000, 629], ["from", -5000, 30], ["to", -5000, 601],
]) {
  test(`clip edit clamps ${name} request ${requested}`, () => {
    assert.equal(editClipMark(at(requested), clipBounds(name, state)), at(expected));
  });
}

test("a configured limit is applied to both mark directions", () => {
  const configured = {...state, maxSeconds:120};
  assert.deepEqual(clipBounds("from", configured), [at(510), at(629)]);
  assert.deepEqual(clipBounds("to", configured), [at(601), at(720)]);
});

test("one edit repairs an overlong or reversed range", () => {
  const overlong = {...state, from:base, to:at(1200)};
  const repaired = editClipMark(at(1199), clipBounds("to", overlong));
  assert.equal(repaired, at(600));
  assert.equal(clipStatus(base, repaired, 600).valid, true);
  const reversed = {...state, from:at(700), to:at(630)};
  assert.equal(editClipMark(at(699), clipBounds("from", reversed)), at(629));
});

for (const [key, shift, expected] of [
  ["ArrowLeft", false, 609], ["ArrowRight", false, 611],
  ["ArrowLeft", true, 600], ["ArrowRight", true, 620], ["Home", false, 30], ["End", true, 629],
]) {
  test(`clip key ${key} with shift=${shift}`, () => {
    assert.equal(clipKeyTarget(key, at(610), clipBounds("from", state), shift), at(expected));
  });
}

test("unhandled keys do not request a mark edit", () => {
  assert.equal(clipKeyTarget("Enter", at(610), clipBounds("from", state)), undefined);
});
