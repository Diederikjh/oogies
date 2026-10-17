"""Shared recorder capacity; feature services own their state and lifetimes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetSnapshot:
    overview: int
    high: int
    playback: int
    exports: int
    limit: int
    high_limit: int

    @property
    def reserved(self): return self.playback + self.exports

    @property
    def used(self): return self.overview + self.high + self.reserved

    @property
    def available(self): return max(0, self.limit - self.used)


@dataclass(frozen=True, eq=False)
class Reservation:
    kind: str
    owner_id: str


class StreamBudget:
    def __init__(self, condition, limit=8, high_limit=2):
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Invalid total source limit")
        if type(high_limit) is not int or not 0 <= high_limit <= 16:
            raise ValueError("Invalid high-quality limit")
        self.condition, self.limit, self.high_limit = condition, limit, high_limit
        self._live_usage = self._on_release = None
        self._reservations = {}

    def bind_live_usage(self, provider, on_release=None):
        with self.condition:
            if self._live_usage is not None:
                raise ValueError("Live occupancy is already bound")
            self._live_usage, self._on_release = provider, on_release

    def snapshot(self):
        with self.condition:
            if self._live_usage is None:
                raise ValueError("Bind live occupancy before admitting work")
            qualities = tuple(self._live_usage().values())
            return BudgetSnapshot(qualities.count("overview"), qualities.count("high"),
                sum(token.kind == "playback" for token in self._reservations.values()),
                sum(token.kind == "export" for token in self._reservations.values()), self.limit, self.high_limit)

    def check_live(self, quality):
        if quality not in ("overview", "high"): raise ValueError("Unknown live quality")
        with self.condition:
            usage = self.snapshot()
            if quality == "high" and usage.high >= self.high_limit: return "high_quality_limit"
            if not usage.available: return "source_limit"
            return None

    def try_reserve(self, kind, owner_id):
        if kind not in ("playback", "export") or not isinstance(owner_id, str) or not owner_id:
            raise ValueError("An identified playback/export owner is required")
        with self.condition:
            usage = self.snapshot()
            key = kind, owner_id
            if key in self._reservations: return self._reservations[key]
            if not usage.available: return None
            token = Reservation(kind, owner_id)
            self._reservations[key] = token
            return token

    def release(self, token):
        with self.condition:
            if not isinstance(token, Reservation): return False
            key = token.kind, token.owner_id
            if self._reservations.get(key) is not token: return False
            del self._reservations[key]
            try:
                if self._on_release is not None: self._on_release()
            finally:
                self.condition.notify_all()
            return True
