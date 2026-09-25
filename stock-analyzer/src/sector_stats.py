"""Sector-relative metric helpers.

Computes sector-level medians and percentile thresholds across the cached
batch so the recommendation engine can compare a stock to its peers — not to
absolute thresholds.

Why: ROE 18% in IT (sector median 22%) is below-average. ROE 14% in Utilities
(sector median 9%) is excellent. Absolute thresholds get this wrong; relative
comparisons get it right.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Optional


METRICS = ("trailing_pe", "roe", "earnings_growth", "revenue_growth",
           "debt_to_equity", "profit_margin", "return_30d_pct")


def compute_sector_stats(cache_root: Path) -> dict[str, dict[str, dict[str, float]]]:
    """Walk all cached results, group by sector, return per-metric quartiles.

    Returns {sector: {metric: {"p25": X, "median": Y, "p75": Z, "n": count}}}
    """
    analysis = cache_root / "analysis"
    if not analysis.exists():
        return {}

    by_sector: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for f in analysis.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        sector = d.get("sector") or ""
        if not sector:
            continue
        for m in METRICS:
            v = d.get(m)
            if v is None:
                continue
            try:
                fv = float(v)
                if fv != fv:  # NaN
                    continue
                by_sector[sector][m].append(fv)
            except (TypeError, ValueError):
                continue

    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = (len(s) - 1) * p
        lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (idx - lo)

    out: dict[str, dict[str, dict[str, float]]] = {}
    for sector, metrics in by_sector.items():
        out[sector] = {}
        for m, vals in metrics.items():
            if len(vals) < 3:
                continue  # not enough sector peers to compare against
            out[sector][m] = {
                "p25": round(_percentile(vals, 0.25), 4),
                "median": round(median(vals), 4),
                "p75": round(_percentile(vals, 0.75), 4),
                "n": len(vals),
            }
    return out


def save_sector_stats(stats: dict, cache_root: Path) -> None:
    p = cache_root / "sector_stats.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_sector_stats(cache_root: Path) -> dict:
    p = cache_root / "sector_stats.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def percentile_bucket(value: Optional[float], sector_stat: Optional[dict]) -> Optional[str]:
    """Where does this value sit in its sector's distribution?
    Returns 'top', 'above_median', 'below_median', 'bottom', or None.
    """
    if value is None or sector_stat is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    if v >= sector_stat["p75"]:
        return "top"
    if v >= sector_stat["median"]:
        return "above_median"
    if v >= sector_stat["p25"]:
        return "below_median"
    return "bottom"
