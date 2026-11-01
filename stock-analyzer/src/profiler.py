"""Lightweight timing for the refresh pipeline.

Two kinds of measurement, both thread-safe:
  stage("name")   wall-clock of a pipeline phase (with-block)
  call("kind")    one network/disk call inside workers — summed per kind,
                  so overlapping calls show as more "call time" than wall time

The batch saves the result to data/cache/analysis/_last_profile.json; the
home page shows a summary and /api/profile returns it whole.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


class Profiler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.perf_counter()
        self.stages: list[dict] = []
        self.calls: dict[str, dict] = {}
        self.meta: dict = {}

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            with self._lock:
                self.stages.append({"stage": name, "seconds": round(time.perf_counter() - t0, 2)})

    @contextmanager
    def call(self, kind: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add(kind, time.perf_counter() - t0)

    def mark(self, name: str, t0: float) -> float:
        """Record a stage that started at t0 (perf_counter); returns now."""
        now = time.perf_counter()
        with self._lock:
            self.stages.append({"stage": name, "seconds": round(now - t0, 2)})
        return now

    def add(self, kind: str, seconds: float) -> None:
        with self._lock:
            c = self.calls.setdefault(kind, {"count": 0, "seconds": 0.0, "max": 0.0})
            c["count"] += 1
            c["seconds"] += seconds
            c["max"] = max(c["max"], seconds)

    def report(self) -> dict:
        total = time.perf_counter() - self.started
        with self._lock:
            calls = {k: {"count": v["count"], "seconds": round(v["seconds"], 2),
                         "avg_ms": round(v["seconds"] / max(v["count"], 1) * 1000, 1),
                         "max_s": round(v["max"], 2)}
                     for k, v in sorted(self.calls.items(), key=lambda kv: -kv[1]["seconds"])}
            stages = list(self.stages)
        slowest = max(stages, key=lambda s: s["seconds"]) if stages else None
        return {"total_seconds": round(total, 1), "stages": stages, "calls": calls,
                "bottleneck": slowest["stage"] if slowest else None, **self.meta}


# The batch installs a profiler here for its duration so helpers deep in the
# call stack (data.fetch_info, screener, earnings) can record calls.
_current: Optional[Profiler] = None


def current() -> Optional[Profiler]:
    return _current


def install(p: Optional[Profiler]) -> None:
    global _current
    _current = p


@contextmanager
def timed(kind: str):
    p = _current
    if p is None:
        yield
        return
    with p.call(kind):
        yield


def save(report: dict, cache_root: Path) -> None:
    try:
        p = cache_root / "analysis" / "_last_profile.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=1), encoding="utf-8")
    except Exception:
        pass


def load(cache_root: Path) -> dict:
    try:
        return json.loads((cache_root / "analysis" / "_last_profile.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
