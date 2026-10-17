import assert from "node:assert/strict";
import test from "node:test";
import {timelineSelection, seekWindow, clipDomain, fitView, clipZoom} from "../../web/history/timeline-model.js";

const base = Date.parse("2024-01-01T00:00:00Z");
const at = seconds => base + seconds * 1000;

for (const [requested, selected, offset] of [
  [125.499, 125, 5], [125.5, 126, 6], [0, 100, 0], [200, 199, 59], [250, 199, 59],
  [110, 110, 0], [190, 190, 59],
]) {
  test(`selection ${requested}: loaded bounds and visible-slider offset are distinct`, () => {
    assert.deepEqual(timelineSelection(at(requested), at(100), at(200), at(120), 59),
      {selected:at(selected), offset});
  });
}

for (const [label, begin, end, viewBegin, viewEnd, expectedBegin, expectedEnd, max, disabled] of [
  ["visible subset", 100, 200, 120, 180, 120, 180, 59, false],
  ["visible superset", 100, 200, 0, 300, 100, 200, 99, false],
  ["no intersection", 100, 200, 0, 50, 100, 50, 0, true],
  ["sub-second range", 100, 100.5, 100, 200, 100, 100.5, 0, true],
  ["exactly one second", 100, 101, 100, 200, 100, 101, 0, false],
]) {
  test(`seek window: ${label}`, () => {
    assert.deepEqual(seekWindow(at(begin), at(end), at(viewBegin), at(viewEnd)),
      {begin:at(expectedBegin), end:at(expectedEnd), max, disabled});
  });
}

test("clip domain includes partial, reversed and out-of-history marks without changing loaded bounds", () => {
  assert.deepEqual(clipDomain(at(100), at(200)), [at(100), at(200)]);
  assert.deepEqual(clipDomain(at(100), at(200), NaN, Infinity), [at(100), at(200)]);
  assert.deepEqual(clipDomain(at(100), at(200), at(120), at(180)), [at(100), at(200)]);
  assert.deepEqual(clipDomain(at(100), at(200), at(50)), [at(50), at(200)]);
  assert.deepEqual(clipDomain(at(100), at(200), undefined, at(250)), [at(100), at(250)]);
  assert.deepEqual(clipDomain(at(100), at(200), at(250), at(50)), [at(50), at(250)]);
});

for (const [label, center, width, expectedBegin, expectedEnd] of [
  ["centered", 150, 60, 120, 180], ["left edge", 100, 60, 100, 160],
  ["right edge", 200, 60, 140, 200], ["over-wide", 150, 600, 100, 200],
  ["whole-second alignment", 150.75, 60, 120, 180],
]) {
  test(`zoom window: ${label}`, () => {
    const domain = Object.freeze([at(100), at(200)]);
    assert.deepEqual(fitView(at(center), width * 1000, domain), [at(expectedBegin), at(expectedEnd)]);
    assert.deepEqual(domain, [at(100), at(200)]);
  });
}

test("clip zoom needs both finite marks", () => {
  for (const marks of [[undefined, at(100)], [at(100), undefined], [NaN, at(100)], [at(100), Infinity]]) {
    assert.equal(clipZoom(...marks), null);
  }
});

test("short, equal and reversed clips retain minimum zoom and padding", () => {
  assert.deepEqual(clipZoom(at(100), at(130)), [at(115), 60000]);
  assert.deepEqual(clipZoom(at(120), at(120)), [at(120), 60000]);
  assert.deepEqual(clipZoom(at(180), at(120)), [at(150), 84000]);
  assert.deepEqual(clipZoom(at(100), at(161)), [at(130.5), 86000]);
});

test("minimum zoom fits shorter loaded history", () => {
  const zoom = clipZoom(at(110), at(111));
  assert.deepEqual(fitView(...zoom, [at(100), at(130)]), [at(100), at(130)]);
});

test("zooming to an invalid extended clip keeps SDK seek bounds inside loaded history", () => {
  const loaded = Object.freeze([at(100), at(200)]);
  const domain = clipDomain(...loaded, at(40), at(260));
  const view = fitView(...clipZoom(at(40), at(260)), domain);
  assert.deepEqual(view, [at(40), at(260)]);
  assert.deepEqual(seekWindow(...loaded, ...view), {begin:at(100), end:at(200), max:99, disabled:false});
  assert.deepEqual(loaded, [at(100), at(200)]);
});

test("zoom out grows around its center and eventually fits the complete domain", () => {
  assert.deepEqual(fitView(at(300), 120000, [at(0), at(600)]), [at(240), at(360)]);
  assert.deepEqual(fitView(at(300), 1200000, [at(0), at(600)]), [at(0), at(600)]);
});
