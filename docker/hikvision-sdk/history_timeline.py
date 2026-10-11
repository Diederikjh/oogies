"""Bounded historical metadata jobs, normalized at the Python SDK boundary."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import re
import threading
import time
from zoneinfo import ZoneInfo

from live_sessions import SessionError


def timestamp(value):
    if not isinstance(value, str) or len(value) > 50:
        raise SessionError("A timezone-aware timestamp is required.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SessionError("Invalid timestamp.") from None
    if result.tzinfo is None or not 2000 <= result.year <= 2100:
        raise SessionError("A timezone-aware timestamp between 2000 and 2100 is required.")
    return result.astimezone(timezone.utc).replace(microsecond=0)


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def recorder_wall(value, zone):
    wall = value.astimezone(zone).replace(tzinfo=None)
    if wall.replace(tzinfo=zone, fold=0).utcoffset() != wall.replace(tzinfo=zone, fold=1).utcoffset():
        raise SessionError("This SDK cannot distinguish repeated daylight-saving times.", 422)
    return wall.isoformat(timespec="seconds")


def recorder_utc(value, zone):
    wall = datetime.fromisoformat(value)
    if wall.tzinfo is not None:
        raise ValueError("Expected recorder wall time")
    first, second = wall.replace(tzinfo=zone, fold=0), wall.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall:
        raise ValueError("Ambiguous recorder wall time")
    return first.astimezone(timezone.utc)


class HistoryTimeline:
    cache_seconds = 60
    max_entries = 32
    max_jobs = 4

    def __init__(self, worker, timezone_name="Africa/Johannesburg", clock=time.monotonic, wall_clock=None):
        self.worker, self.clock = worker, clock
        self.zone = ZoneInfo(timezone_name)
        self.wall_clock = wall_clock or (lambda:datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.entries = {}
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-query")

    def query_local(self, camera_id, local_text, hours_text, refresh=False):
        if not isinstance(local_text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", local_text):
            raise SessionError("Choose a valid recorder date and time.", 422)
        if hours_text not in ("1", "3", "6"):
            raise SessionError("Choose a range of one, three or six hours.", 422)
        if not 2000 <= int(local_text[:4]) <= 2100:
            raise SessionError("Choose a recorder date/time between 2000 and 2100.", 422)
        try:
            position = recorder_utc(local_text, self.zone)
        except ValueError:
            raise SessionError("That date/time is invalid or ambiguous in the recorder timezone. Choose another time.", 422) from None
        position = timestamp(utc_text(position))
        now = self.wall_clock().astimezone(timezone.utc).replace(microsecond=0)
        if position >= now:
            raise SessionError("Choose a date/time earlier than now.", 422)
        # Centre older footage, clipping near now and the SDK's earliest year.
        earliest = max(datetime(2000, 1, 1, tzinfo=timezone.utc),
                       datetime(2000, 1, 1, tzinfo=self.zone).astimezone(timezone.utc))
        if position < earliest:
            raise SessionError("That date/time is before the supported recording range.", 422)
        span = timedelta(hours=int(hours_text))
        end = min(position + span / 2, now)
        begin = max(earliest, end - span)
        result, status = self.query(camera_id, utc_text(begin), utc_text(end), refresh)
        # The cached response belongs to its UTC range, not to one selected time.
        return dict(result, selected_time=utc_text(position)), status

    def query(self, camera_id, begin_text, end_text, refresh=False):
        begin, end = timestamp(begin_text), timestamp(end_text)
        if end <= begin or end - begin > timedelta(hours=6):
            raise SessionError("Choose a positive time range of at most six hours.", 422)
        # Validate before enqueueing; reject ranges that cross an ambiguous clock
        # transition even if their endpoints themselves are unambiguous.
        cursor = begin
        while cursor < end:
            recorder_wall(cursor, self.zone)
            cursor += timedelta(minutes=1)
        wall_begin, wall_end = recorder_wall(begin, self.zone), recorder_wall(end, self.zone)
        self.worker.ensure_ready()
        if camera_id not in self.worker.cameras:
            raise SessionError("Unknown camera.", 404)
        key = camera_id, begin, end
        with self.lock:
            if self.closed:
                raise SessionError("History service stopped.", 503)
            entry = self.entries.get(key)
            pending = entry is not None and not entry["future"].done()
            if not pending and (entry is None or refresh or self.clock() >= entry["expires"]):
                if sum(not item["future"].done() for item in self.entries.values()) >= self.max_jobs:
                    raise SessionError("History query queue is full.", 409)
                while len(self.entries) >= self.max_entries:
                    victim = next((other for other, item in self.entries.items() if item["future"].done()), None)
                    if victim is None:
                        raise SessionError("History query queue is full.", 409)
                    del self.entries[victim]
                entry = dict(future=self.executor.submit(self._load, camera_id, begin, end, wall_begin, wall_end),
                             expires=float("inf"))
                self.entries[key] = entry
                def completed(_future):
                    expiry = self.clock() + self.cache_seconds
                    with self.lock:
                        entry["expires"] = expiry
                entry["future"].add_done_callback(completed)
                pending = True
            if pending:
                return dict(camera_id=camera_id, **{"from":utc_text(begin), "to":utc_text(end)},
                    timezone=self.zone.key, recordings=self._pending(), motion=self._pending()), 202
            return entry["future"].result(), 200

    @staticmethod
    def _pending():
        return dict(state="pending", intervals=None, complete=False, error=None)

    def _dataset(self, raw, camera_id, begin, end, motion):
        state = raw.get("state", "error")
        source = raw.get("source")
        error = raw.get("sdk_error")
        result = dict(state=state, intervals=None, complete=False, source=source, error=None)
        if state != "ready":
            result["error"] = dict(code="history_query_failed", message=
                ("Motion information" if motion else "Recording coverage") +
                f" is unavailable (SDK code {error}).")
            return result
        intervals, seen = [], set()
        try:
            for item in raw["intervals"]:
                start, stop = recorder_utc(item["start"], self.zone), recorder_utc(item["end"], self.zone)
                if stop < start:
                    raise ValueError("Invalid interval")
                point = start == stop
                if (point and not begin <= start < end) or (not point and (stop <= begin or start >= end)):
                    continue
                token = f"{camera_id}:{source}:{item['start']}:{item['end']}:{item.get('recording_type')}"
                identifier = hashlib.sha256(token.encode()).hexdigest()[:24]
                if identifier in seen:
                    continue
                seen.add(identifier)
                intervals.append(dict(id=identifier, start=utc_text(max(begin, start)), end=utc_text(min(end, stop)),
                    source_start=utc_text(start), source_end=utc_text(stop), type="motion" if motion else "recording",
                    granularity="sdk_interval" if motion else "recording", source=source,
                    recording_type=item.get("recording_type")))
        except (ValueError, KeyError, TypeError):
            result.update(state="error", error=dict(code="invalid_recorder_time", message="Recorder returned an invalid or ambiguous interval."))
            return result
        result.update(intervals=sorted(intervals, key=lambda item:(item["start"], item["end"], item["id"])),
                      complete=raw.get("complete") is True)
        return result

    def _load(self, camera_id, begin, end, wall_begin, wall_end):
        try:
            raw = self.worker.query_timeline(camera_id, wall_begin, wall_end)
        except (OSError, ValueError):
            raw = {name:dict(state="error", sdk_error="unavailable") for name in ("recordings", "motion")}
        recorder_now = None
        if raw.get("recorder_now"):
            try:
                recorder_now = utc_text(recorder_utc(raw["recorder_now"], self.zone))
            except ValueError:
                pass
        return dict(camera_id=camera_id, **{"from":utc_text(begin), "to":utc_text(end)},
            timezone=self.zone.key, generated_at=utc_text(datetime.now(timezone.utc)), recorder_now=recorder_now,
            recordings=self._dataset(raw.get("recordings", {}), camera_id, begin, end, False),
            motion=self._dataset(raw.get("motion", {}), camera_id, begin, end, True))

    def close(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
