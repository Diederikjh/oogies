"""Shared UTC/recorder wall-time validation without feature state."""
from datetime import datetime, timezone

from service_errors import SessionError


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


