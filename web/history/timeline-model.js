// Loaded history, visible zoom and the slider seek range are separate domains.
export function timelineSelection(value, begin, end, seekBegin, sliderMax) {
  const selected = Math.max(begin, Math.min(end - 1000, Math.round(value / 1000) * 1000));
  return {selected, offset:Math.max(0, Math.min(sliderMax, (selected - seekBegin) / 1000))};
}

export function seekWindow(begin, end, viewBegin, viewEnd) {
  const seekBegin = Math.max(begin, viewBegin), seekEnd = Math.min(end, viewEnd);
  return {begin:seekBegin, end:seekEnd, max:Math.max(0, (seekEnd - seekBegin) / 1000 - 1),
    disabled:seekEnd - seekBegin < 1000};
}

export function clipDomain(begin, end, from, to) {
  const marks = [from, to].filter(Number.isFinite);
  return [Math.min(begin, ...marks), Math.max(end, ...marks)];
}

export function fitView(center, width, [min, max]) {
  width = Math.min(width, max - min);
  const begin = Math.max(min, Math.min(max - width, Math.floor((center - width / 2) / 1000) * 1000));
  return [begin, begin + width];
}

export function clipZoom(from, to) {
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  return [(from + to) / 2, Math.max(60000, Math.ceil(Math.abs(to - from) * 1.4 / 1000) * 1000)];
}
