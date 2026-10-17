// Clip rules in recorder timestamps (milliseconds); no DOM, clock or requests.
export function clipMark(position) {
  return Math.floor(position / 1000) * 1000;
}

export function clipStatus(from, to, maxSeconds) {
  const duration = (to - from) / 1000;
  const finite = Number.isFinite(duration);
  return {duration, valid:finite && duration >= 1 && duration <= maxSeconds,
    invalid:finite && (duration < 1 || duration > maxSeconds)};
}

export function clipBounds(name, {from, to, begin, end, maxSeconds}) {
  const earliest = Date.UTC(2000, 0, 1), latest = Math.max(end || earliest, from || earliest, to || earliest);
  if (name === "from") return [Math.max(earliest, Number.isFinite(to) ? to - maxSeconds * 1000 : begin),
    Number.isFinite(to) ? to - 1000 : latest - 1000];
  return [Number.isFinite(from) ? from + 1000 : begin + 1000,
    Math.min(latest, Number.isFinite(from) ? from + maxSeconds * 1000 : latest)];
}

export function editClipMark(value, [min, max]) {
  return Math.max(min, Math.min(max, Math.round(value / 1000) * 1000));
}

export function clipKeyTarget(key, current, [min, max], shift = false) {
  const step = shift ? 10000 : 1000;
  switch (key) {
    case "ArrowLeft": return current - step;
    case "ArrowRight": return current + step;
    case "Home": return min;
    case "End": return max;
    default: return undefined;
  }
}
