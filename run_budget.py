"""Cooperative wall-clock budgets shared by fetchers and delivery code.

The bot intentionally treats coverage as a best-effort problem: a slow or
blocked connector must return partial results rather than deciding how long a
run takes.  This module stays dependency-free so synchronous and async
connectors can both consult the same monotonic deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
import threading
import time
from typing import Any


@dataclass
class RunBudget:
    total_seconds: float
    started_at: float = field(default_factory=time.monotonic)
    phase_limits: dict[str, float] = field(default_factory=dict)
    phase_started: dict[str, float] = field(default_factory=dict)
    protected_phases: set[str] = field(default_factory=set)

    def start_phase(self, name: str, seconds: float, *, protected: bool = False) -> None:
        self.phase_limits[name] = max(0.0, float(seconds))
        self.phase_started[name] = time.monotonic()
        if protected:
            self.protected_phases.add(name)
        else:
            self.protected_phases.discard(name)

    def total_remaining(self) -> float:
        return max(0.0, self.total_seconds - (time.monotonic() - self.started_at))

    def phase_remaining(self, name: str) -> float:
        started = self.phase_started.get(name)
        limit = self.phase_limits.get(name)
        if started is None or limit is None:
            return self.total_remaining()
        phase_left = max(0.0, limit - (time.monotonic() - started))
        # Delivery is a bounded, reserved final phase.  Upstream work can
        # overrun the advisory run deadline (for example CPU-bound ML
        # classification), but it must never erase the Telegram window after
        # a real candidate pool has already been built.
        if name in self.protected_phases:
            return phase_left
        return min(self.total_remaining(), phase_left)

    def remaining(self, phase: str | None = None) -> float:
        return self.phase_remaining(phase) if phase else self.total_remaining()

    def expired(self, phase: str | None = None) -> bool:
        return self.remaining(phase) <= 0.0


_LOCK = threading.Lock()
_CURRENT: RunBudget | None = None
_SOURCE_LOCAL = threading.local()


def start_run(total_seconds: float) -> RunBudget:
    global _CURRENT
    with _LOCK:
        _CURRENT = RunBudget(total_seconds=max(1.0, float(total_seconds)))
        return _CURRENT


def current() -> RunBudget | None:
    with _LOCK:
        return _CURRENT


def start_phase(name: str, seconds: float, *, protected: bool = False) -> None:
    budget = current()
    if budget:
        budget.start_phase(name, seconds, protected=protected)


def remaining(phase: str | None = None) -> float:
    budget = current()
    return budget.remaining(phase) if budget else float("inf")


def cap_timeout(requested: float, *, phase: str | None = None, floor: float = 0.25) -> float:
    """Cap a request timeout without starting a request after the deadline."""
    left = remaining(phase)
    if left == float("inf"):
        return max(floor, requested)
    return max(floor, min(float(requested), left))


@contextmanager
def source_deadline(seconds: float):
    """Apply a cooperative per-source ceiling in the current worker thread.

    Fetchers that use the shared HTTP client automatically inherit this.  The
    context is thread-local so 70 parallel source tasks cannot shorten one
    another's request timeout.
    """
    previous = getattr(_SOURCE_LOCAL, "deadline", None)
    _SOURCE_LOCAL.deadline = time.monotonic() + max(0.0, float(seconds))
    try:
        yield
    finally:
        _SOURCE_LOCAL.deadline = previous


def source_remaining() -> float:
    deadline = getattr(_SOURCE_LOCAL, "deadline", None)
    if deadline is None:
        return float("inf")
    return max(0.0, deadline - time.monotonic())


def cap_source_timeout(requested: float, *, floor: float = 0.01) -> float:
    """Cap a single HTTP timeout to the current source's remaining time."""
    left = source_remaining()
    if left == float("inf"):
        return max(floor, float(requested))
    return max(floor, min(float(requested), left))


def snapshot() -> dict[str, Any]:
    budget = current()
    if not budget:
        return {"active": False}
    return {
        "active": True,
        "total_seconds": budget.total_seconds,
        "used_seconds": round(time.monotonic() - budget.started_at, 3),
        "remaining_seconds": round(budget.total_remaining(), 3),
        "phases": {
            key: {
                "limit_seconds": limit,
                "remaining_seconds": round(budget.phase_remaining(key), 3),
                "protected": key in budget.protected_phases,
            }
            for key, limit in budget.phase_limits.items()
        },
    }
