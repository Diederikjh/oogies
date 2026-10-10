const MODES = ["16:9", "4:3", "original"];
const key = id => `home-cameras.${id}.display-aspect.v1`;

export function readAspect(id, fallback = "16:9") {
  let value = fallback;
  try { value = localStorage.getItem(key(id)) || fallback; } catch (_) {}
  return MODES.includes(value) ? value : "16:9";
}

export function saveAspect(id, value) {
  const aspect = MODES.includes(value) ? value : "16:9";
  try { localStorage.setItem(key(id), aspect); } catch (_) {}
  return aspect;
}
