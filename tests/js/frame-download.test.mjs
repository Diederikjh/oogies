import assert from "node:assert/strict";
import test from "node:test";
import {safeCameraName} from "../../web/history/frame-download.js";

const names = [
  ["ordinary name", "Driveway", "Driveway"],
  ["filesystem separators and punctuation", ' Garage:/\\<>"|?*\nDoor. ', "Garage-Door"],
  ["control characters", `Front${String.fromCharCode(...Array.from({length:32}, (_, i) => i))}Door`, "Front-Door"],
  ["format characters", "Front\u200b\u202eDoor", "Front-Door"],
  ["unpaired surrogate", "Front\ud800Door", "Front-Door"],
  ["repeated separators", "Front---Door", "Front-Door"],
  ["whitespace", "  Front \u00a0  porch  ", "Front porch"],
  ["leading and trailing dots and separators", "...-- Garage --... ", "Garage"],
  ["empty name", "", "Camera"],
  ["dot-only path", "../..", "Camera"],
  ["punctuation-only name", ':<>/\\"|?*', "Camera"],
  ["null name", null, "Camera"],
  ["undefined name", undefined, "Camera"],
  ["numeric name", 42, "Camera"],
  ["object name", {name:"Driveway"}, "Camera"],
  ["accented name", "Café tuin", "Café tuin"],
  ["Unicode normalization", "e\u0301", "é"],
  ["reserved component with a safe full-filename prefix", "CON", "CON"],
  ["reserved component with extension", "NUL.txt", "NUL.txt"],
];

for (const [description, input, expected] of names) {
  test(`camera filename: ${description}`, () => assert.equal(safeCameraName(input), expected));
}

test("camera filename: exactly 128 ASCII bytes fit", () => {
  assert.equal(safeCameraName("a".repeat(128)), "a".repeat(128));
});

test("camera filename: longer ASCII names are bounded", () => {
  assert.equal(safeCameraName("a".repeat(200)), "a".repeat(128));
});

test("camera filename: normalization happens before the byte limit", () => {
  assert.equal(safeCameraName("e\u0301".repeat(100)), "é".repeat(64));
});

test("camera filename: a complete two-byte character fits at the boundary", () => {
  assert.equal(safeCameraName("a".repeat(126) + "éx"), "a".repeat(126) + "é");
});

for (const [description, prefix, character] of [["two-byte", 127, "é"], ["three-byte", 126, "€"], ["four-byte", 125, "🎥"]]) {
  test(`camera filename: never split a ${description} character at the byte limit`, () => {
    assert.equal(safeCameraName("a".repeat(prefix) + character), "a".repeat(prefix));
  });
}

test("camera filename: emoji are bounded by bytes, not UTF-16 length", () => {
  const result = safeCameraName("🎥".repeat(100));
  assert.equal(result, "🎥".repeat(32));
  assert.equal(new TextEncoder().encode(result).length, 128);
});
