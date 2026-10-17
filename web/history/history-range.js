// Callers supply time explicitly; recorder wall-time/DST resolution stays server-side.
export function currentMinute(nowMs) {
  return Math.floor(nowMs / 60000) * 60000;
}

export function historyWindow({end, hours, recent, nowMs}) {
  const windowEnd = recent || !end ? currentMinute(nowMs) : end;
  return {begin:windowEnd - Number(hours) * 3600000, end:windowEnd};
}

export function shiftHistoryWindow(end, hours, direction, nowMs) {
  return Math.min(end + direction * Number(hours) * 3600000, currentMinute(nowMs));
}

export function motionTime(intervals, selected, direction) {
  const event = direction > 0 ? intervals.find(item => selected === undefined || Date.parse(item.start) > selected) :
    [...intervals].reverse().find(item => selected === undefined || Date.parse(item.start) < selected);
  return event ? Date.parse(event.start) : undefined;
}
