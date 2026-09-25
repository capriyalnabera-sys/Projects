"""Market Pulse aggregations.

  - Index quotes (NIFTY, SENSEX, BANKNIFTY, India VIX)
  - Advance/decline breadth from cached batch results
  - Sector performance (avg day-change by sector)
  - Top gainers / losers
  - 52-week high / low counts
  - Heatmap rows (one entry per stock with what the heatmap needs)
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from . import batch


INDICES = [
    ("NIFTY 50",   "^NSEI"),
    ("SENSEX",     "^BSESN"),
    ("BANK NIFTY", "^NSEBANK"),
    ("INDIA VIX",  "^INDIAVIX"),
]


def fetch_indices() -> list[dict]:
    out: list[dict] = []
    for name, symbol in INDICES:
        try:
            t = yf.Ticker(symbol)
            h = t.history(period="5d", auto_adjust=False)
            if h is None or h.empty:
                continue
            # Drop NaN rows — yfinance can return NaN for today's incomplete bar.
            closes = h["Close"].dropna()
            if len(closes) < 2:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            if last != last or prev != prev or prev == 0:
                continue
            change = last - prev
            change_pct = (last / prev - 1) * 100
            out.append({
                "name": name, "symbol": symbol,
                "last": round(last, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            })
        except Exception:
            continue
    return out


def aggregate_universe(rows: list[dict]) -> dict:
    """Compute breadth, sector perf, gainers/losers from cached batch rows."""
    advances = declines = unchanged = 0
    near_52w_high = near_52w_low = 0
    sector_changes: dict[str, list[float]] = defaultdict(list)
    movers: list[dict] = []

    for r in rows:
        dc = r.get("day_change_pct")
        # Skip None and NaN — guards against poisoned cache entries
        if dc is None or (isinstance(dc, float) and dc != dc):
            continue
        if dc > 0.05: advances += 1
        elif dc < -0.05: declines += 1
        else: unchanged += 1

        sector = r.get("sector") or "Unknown"
        sector_changes[sector].append(dc)

        last = r.get("last_close") or 0
        hi = r.get("high_52w") or 0
        lo = r.get("low_52w") or 0
        if hi and last >= hi * 0.97: near_52w_high += 1
        if lo and last <= lo * 1.03: near_52w_low += 1

        movers.append({
            "ticker": r["ticker"],
            "name": r.get("name", ""),
            "sector": sector,
            "change_pct": dc,
            "last_close": last,
            "verdict": r.get("verdict", "HOLD"),
            "combined_score": r.get("combined_score", 0),
        })

    sector_perf = []
    for s, vals in sector_changes.items():
        if vals:
            sector_perf.append({
                "sector": s,
                "avg_change_pct": round(sum(vals) / len(vals), 2),
                "stock_count": len(vals),
                "advancing": sum(1 for v in vals if v > 0.05),
                "declining": sum(1 for v in vals if v < -0.05),
            })
    sector_perf.sort(key=lambda x: -x["avg_change_pct"])

    movers.sort(key=lambda x: -x["change_pct"])
    gainers = movers[:10]
    losers = movers[-10:][::-1]  # bottom 10, worst first

    breadth_total = advances + declines + unchanged
    ad_ratio = (advances / declines) if declines > 0 else (float(advances) if advances > 0 else 0)

    return {
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "ad_ratio": round(ad_ratio, 2),
        "breadth_total": breadth_total,
        "near_52w_high": near_52w_high,
        "near_52w_low": near_52w_low,
        "sector_perf": sector_perf,
        "gainers": gainers,
        "losers": losers,
    }


def heatmap_rows(rows: list[dict], color_by: str = "day_change_pct") -> list[dict]:
    """Lightweight per-stock entries for the heatmap. color_by can be
    'day_change_pct' or 'combined_score'."""
    out = []
    for r in rows:
        sector = r.get("sector") or "Unknown"
        out.append({
            "ticker": r["ticker"],
            "name": r.get("name", ""),
            "sector": sector,
            "day_change_pct": r.get("day_change_pct"),
            "combined_score": r.get("combined_score", 0),
            "verdict": r.get("verdict", "HOLD"),
            "last_close": r.get("last_close"),
            "color_value": (r.get(color_by) if color_by != "combined_score" else r.get("combined_score", 0)),
        })
    return out
