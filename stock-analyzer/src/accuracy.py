"""Tool-accuracy tracker.

Walks daily snapshots in data/cache/snapshots/<date>.json and grades each
historical verdict against subsequent realized returns at multiple horizons.

Reports per-verdict:
  - Sample count
  - Average return at +5d, +20d, +60d
  - Hit rate (% > 0%) and "big-win rate" (% > +5%)
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Optional

import yfinance as yf

from . import data as data_mod


# Cache the computed accuracy result on disk so the page renders instantly
# instead of bulk-fetching ~500 tickers every page load (~30s).
ACCURACY_CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def _list_snapshots(snap_dir: Path) -> list[tuple[date, Path]]:
    if not snap_dir.exists():
        return []
    out = []
    for p in snap_dir.glob("*.json"):
        try:
            d = date.fromisoformat(p.stem)
            out.append((d, p))
        except Exception:
            continue
    return sorted(out)


def _close_at(history, target_date: date) -> Optional[float]:
    """Return close price ON or AFTER target_date (next trading day if weekend)."""
    if history is None or history.empty:
        return None
    try:
        # history index is timezone-aware DatetimeIndex; compare via date()
        for ts in history.index:
            if ts.date() >= target_date:
                return float(history.loc[ts, "Close"])
    except Exception:
        pass
    return None


def evaluate(snap_dir: Path, horizons_days: tuple[int, ...] = (5, 20, 60), force: bool = False, stale_ok: bool = False) -> dict:
    """Walk-forward backtest of past verdicts.

    ``stale_ok=True`` returns whatever's on disk regardless of TTL — used by
    the /accuracy route to serve a fast cached view while a background thread
    rebuilds. Without this, every cache expiry would make the page block on
    a ~50s yfinance bulk fetch.
    """
    cache_path = snap_dir / "_accuracy_cache.json"
    if not force and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if stale_ok or age < ACCURACY_CACHE_TTL_SECONDS:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cached["computed_age_seconds"] = int(age)
                cached["cache_stale"] = (age >= ACCURACY_CACHE_TTL_SECONDS)
                return cached
            except Exception:
                pass

    snapshots = _list_snapshots(snap_dir)
    today = date.today()
    if not snapshots:
        return {"available": False, "reason": "No snapshots yet — verdicts archive once batches start running daily."}

    # For each ticker we'll need price history covering the snapshot range.
    tickers_seen: set[str] = set()
    rows: list[tuple[str, date, dict]] = []  # (ticker, snap_date, verdict_record)
    for snap_date, path in snapshots:
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ticker, rec in snap.items():
            if not isinstance(rec, dict) or "verdict" not in rec:
                continue
            tickers_seen.add(ticker)
            rows.append((ticker, snap_date, rec))

    if not rows:
        return {"available": False, "reason": "Snapshots exist but contain no verdict records."}

    # Bulk fetch all needed price histories in a single yfinance call —
    # one HTTP roundtrip vs N (used to take ~10 min for 500 tickers, now ~20s).
    earliest = min(d for _, d, _ in rows)
    span_days = (today - earliest).days + max(horizons_days) + 5
    period = f"{max(span_days, 60)}d"
    price_cache = data_mod.bulk_fetch_histories(sorted(tickers_seen), period=period)

    # Bucket realized returns by verdict and horizon
    buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    # Sector buckets: (verdict, horizon, sector) → returns
    sector_buckets: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    # Score-bucket calibration: (score_bin, horizon) → returns
    score_buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    big_win_threshold = 5.0  # % gain considered a "big win"

    def _score_bin(score: float) -> str:
        if score >= 2.0: return "≥+2"
        if score >= 1.0: return "+1 to +2"
        if score >= 0.0: return "0 to +1"
        if score >= -1.0: return "-1 to 0"
        return "≤-1"

    for ticker, snap_date, rec in rows:
        verdict = rec.get("verdict")
        if verdict not in ("BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID"):
            continue
        hist = price_cache.get(ticker)
        if hist is None:
            continue
        entry_close = _close_at(hist, snap_date)
        if not entry_close:
            continue
        sector = rec.get("sector") or "Unknown"
        score = rec.get("combined_score") or 0
        score_bin = _score_bin(score)
        for h_days in horizons_days:
            target = snap_date + timedelta(days=h_days)
            if target > today:
                continue
            exit_close = _close_at(hist, target)
            if not exit_close:
                continue
            ret_pct = (exit_close / entry_close - 1) * 100
            buckets[(verdict, h_days)].append(ret_pct)
            sector_buckets[(verdict, h_days, sector)].append(ret_pct)
            score_buckets[(score_bin, h_days)].append(ret_pct)

    # Aggregate
    summary: dict[str, dict] = {}
    verdict_order = ["BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID"]
    for v in verdict_order:
        entry: dict[str, dict] = {}
        for h_days in horizons_days:
            vals = buckets.get((v, h_days), [])
            if vals:
                entry[str(h_days)] = {
                    "n": len(vals),
                    "avg_return": round(mean(vals), 2),
                    "hit_rate": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
                    "big_win_rate": round(sum(1 for x in vals if x > big_win_threshold) / len(vals) * 100, 1),
                    "best": round(max(vals), 2),
                    "worst": round(min(vals), 2),
                }
            else:
                entry[str(h_days)] = None
        summary[v] = entry

    # Score-bin calibration: do higher scores actually produce higher returns?
    score_calibration: dict[str, dict] = {}
    for bin_label in ("≥+2", "+1 to +2", "0 to +1", "-1 to 0", "≤-1"):
        score_calibration[bin_label] = {}
        for h_days in horizons_days:
            vals = score_buckets.get((bin_label, h_days), [])
            if vals:
                score_calibration[bin_label][str(h_days)] = {
                    "n": len(vals),
                    "avg_return": round(mean(vals), 2),
                    "hit_rate": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
                }
            else:
                score_calibration[bin_label][str(h_days)] = None

    # Sector-level hit rates (only computed where we have ≥5 samples)
    sector_summary: dict[str, dict] = {}
    sectors_seen = sorted({s for (_, _, s) in sector_buckets.keys()})
    for sec in sectors_seen:
        sec_entry = {}
        for v in verdict_order:
            sec_entry[v] = {}
            for h in horizons_days:
                vals = sector_buckets.get((v, h, sec), [])
                if len(vals) >= 5:
                    sec_entry[v][str(h)] = {
                        "n": len(vals),
                        "avg_return": round(mean(vals), 2),
                        "hit_rate": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
                    }
                else:
                    sec_entry[v][str(h)] = None
        sector_summary[sec] = sec_entry

    # ---- Plain-language "headline" metric ---------------------------------
    # Prefer the longest available horizon — that's the most meaningful read.
    # Fall back to shorter horizons if longer ones don't have enough data yet.
    headline = None
    for h in sorted(horizons_days, reverse=True):
        positive_calls = buckets.get(("BUY", h), []) + buckets.get(("ACCUMULATE", h), [])
        if not positive_calls:
            continue
        avoid_calls = buckets.get(("REDUCE", h), []) + buckets.get(("AVOID", h), [])
        n = len(positive_calls)
        avg_ret = round(mean(positive_calls), 2)
        hit_rate = round(sum(1 for x in positive_calls if x > 0) / n * 100, 1)
        headline = {
            "horizon_days": h,
            "n_positive_calls": n,
            "avg_return_pct": avg_ret,
            "hit_rate_pct": hit_rate,
            "n_negative_calls": len(avoid_calls),
            "avg_return_negative_pct": round(mean(avoid_calls), 2) if avoid_calls else None,
        }
        break

    # Snapshot-progress message: when does the data become statistically meaningful?
    n_snap = len(snapshots)
    if n_snap < 10:
        progress = {"state": "early",   "message": f"Only {n_snap} snapshots so far — at least 10 needed for any read, 30+ for confident calibration."}
    elif n_snap < 30:
        progress = {"state": "limited", "message": f"{n_snap} snapshots collected — preliminary numbers, treat as directional. Confidence builds after 30+."}
    else:
        progress = {"state": "good",    "message": f"{n_snap} snapshots — calibration is statistically meaningful."}

    result = {
        "available": True,
        "snapshot_count": n_snap,
        "first_snapshot": snapshots[0][0].isoformat(),
        "last_snapshot": snapshots[-1][0].isoformat(),
        "tickers_evaluated": len(price_cache),
        "horizons_days": list(horizons_days),
        "by_verdict": summary,
        "by_sector": sector_summary,
        "score_calibration": score_calibration,
        "big_win_threshold_pct": big_win_threshold,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "headline": headline,
        "progress": progress,
    }
    try:
        cache_path.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
