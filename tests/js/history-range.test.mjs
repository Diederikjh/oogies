import assert from "node:assert/strict";
import test from "node:test";
import {currentMinute, historyWindow, shiftHistoryWindow, motionTime} from "../../web/history/history-range.js";

const time = text => Date.parse(text);

for (const [now, rounded] of [
  ["2024-12-31T23:59:59.999Z", "2024-12-31T23:59:00Z"],
  ["2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"],
  ["2024-03-01T00:00:00.001Z", "2024-03-01T00:00:00Z"],
]) {
  test(`history minute at ${now}`, () => assert.equal(currentMinute(time(now)), time(rounded)));
}

for (const [hours, begin] of [["1", "2024-06-15T11:34:00Z"], [3, "2024-06-15T09:34:00Z"], ["6", "2024-06-15T06:34:00Z"]]) {
  test(`recent ${hours}-hour range uses the supplied minute`, () => {
    assert.deepEqual(historyWindow({hours, recent:true, nowMs:time("2024-06-15T12:34:56Z")}),
      {begin:time(begin), end:time("2024-06-15T12:34:00Z")});
  });
}

test("an initial window and a recent window cross the year boundary correctly", () => {
  const nowMs = time("2025-01-01T00:00:01Z");
  const expected = {begin:time("2024-12-31T23:00:00Z"), end:time("2025-01-01T00:00:00Z")};
  assert.deepEqual(historyWindow({hours:1, recent:false, nowMs}), expected);
  assert.deepEqual(historyWindow({hours:1, recent:true, end:time("2024-12-31T22:00:00Z"), nowMs}), expected);
});

test("fixed Refresh windows remain pinned when the supplied clock advances", () => {
  const fixed = Object.freeze({end:time("2024-12-31T23:59:00Z"), hours:1, recent:false});
  const expected = {begin:time("2024-12-31T22:59:00Z"), end:fixed.end};
  assert.deepEqual(historyWindow({...fixed, nowMs:time("2024-12-31T23:59:59Z")}), expected);
  assert.deepEqual(historyWindow({...fixed, nowMs:time("2025-01-01T00:30:01Z")}), expected);
});

test("returning to Recent releases the fixed range", () => {
  assert.deepEqual(historyWindow({end:time("2024-12-31T23:59:00Z"), hours:1, recent:true,
    nowMs:time("2025-01-01T00:30:59Z")}),
    {begin:time("2024-12-31T23:30:00Z"), end:time("2025-01-01T00:30:00Z")});
});

for (const [end, earlier] of [
  ["2025-01-01T00:00:00Z", "2024-12-31T23:00:00Z"],
  ["2024-03-01T00:00:00Z", "2024-02-29T23:00:00Z"],
  ["2025-03-01T00:00:00Z", "2025-02-28T23:00:00Z"],
]) {
  test(`Earlier crosses calendar boundary at ${end}`, () => {
    assert.equal(shiftHistoryWindow(time(end), "1", -1, time(end)), time(earlier));
  });
}

test("Later returns one window forward but cannot pass the current minute", () => {
  const end = time("2025-01-01T00:00:00Z");
  assert.equal(shiftHistoryWindow(end, 1, 1, time("2025-01-01T02:00:00Z")), time("2025-01-01T01:00:00Z"));
  assert.equal(shiftHistoryWindow(end, 1, 1, time("2025-01-01T00:30:59Z")), time("2025-01-01T00:30:00Z"));
});

const events = Object.freeze([0, 10, 10, 20].map(second => Object.freeze({start:new Date(second * 1000).toISOString()})));
for (const [label, selected, direction, expected] of [
  ["first without selection", undefined, 1, 0], ["last without selection", undefined, -1, 20000],
  ["next skips equal starts", 10000, 1, 20000], ["previous skips equal starts", 10000, -1, 0],
  ["next from between events", 5000, 1, 10000], ["previous from between events", 5000, -1, 0],
  ["no previous at start", 0, -1, undefined], ["no next at end", 20000, 1, undefined],
]) {
  test(`motion navigation: ${label}`, () => assert.equal(motionTime(events, selected, direction), expected));
}

test("empty motion results do not produce a navigation target", () => {
  assert.equal(motionTime([], undefined, 1), undefined);
  assert.equal(motionTime([], 10000, -1), undefined);
});

test("previous-event lookup does not reorder recorder results", () => {
  assert.equal(motionTime(events, 15000, -1), 10000);
  assert.deepEqual(events.map(event => Date.parse(event.start)), [0, 10000, 10000, 20000]);
});
