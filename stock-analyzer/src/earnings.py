"""Earnings calendar — flag stocks whose results are within N trading days.

Why this matters: buying *before* earnings is a coin flip — the verdict is
based on stale data that's about to be replaced. Treating these as 'verdict
pending' avoids false confidence in the days leading up to a result.

Per-ticker cache (1-day TTL) so we don't slam yfinance on every batch.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

from . import data as data_mod


EARNINGS_CACHE_DIR = Path("data/cache/earnings")
EARNINGS_CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_path(ticker: str) -> Path:
    return EARNINGS_CACHE_DIR / f"{ticker.upper()}.json"


def next_earnings_date(ticker: str) -> Optional[date]:
    """Return the next earnings date if known, else None. Cached for 24h."""
    tk = ticker.upper()
    p = _cache_path(tk)
    if p.exists() and (time.time() - p.stat().st_mtime) < EARNINGS_CACHE_TTL_SECONDS:
        try:
            cached = json.loads(p.read_text(encoding="utf-8"))
            v = cached.get("next_earnings_date")
            if not v:
                return None
            return date.fromisoformat(v)
        except Exception:
            pass

    out: Optional[date] = None
    try:
        cal = yf.Ticker(data_mod.to_yf_symbol(tk)).calendar
    except Exception:
        cal = None

    if cal is not None:
        # yfinance returns either a dict (newer versions) or a DataFrame (older).
        d = None
        if isinstance(cal, dict):
            d = cal.get("Earnings Date") or cal.get("earningsDate")
        else:
            try:
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    d = list(val) if hasattr(val, "__iter__") else val
            except Exception:
                d = None
        if isinstance(d, list) and d:
            d = d[0]
        if d is not None:
            try:
                if hasattr(d, "date"):
                    out = d.date()
                elif isinstance(d, str):
                    out = date.fromisoformat(d[:10])
                elif isinstance(d, (int, float)):
                    out = datetime.fromtimestamp(d).date()
            except Exception:
                out = None

    try:
        EARNINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "ticker": tk,
            "next_earnings_date": out.isoformat() if out else None,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
    except Exception:
        pass
    return out


def days_until_earnings(ticker: str, today: Optional[date] = None) -> Optional[int]:
    today = today or date.today()
    d = next_earnings_date(ticker)
    if d is None:
        return None
    delta = (d - today).days
    if delta < 0:
        return None  # earnings already passed; cache will refresh
    return delta


def is_pre_earnings(ticker: str, window_days: int = 5) -> tuple[bool, Optional[int]]:
    """True if results are within window_days from today. Returns (flag, days_left)."""
    days = days_until_earnings(ticker)
    if days is None:
        return (False, None)
    return (days <= window_days, days)
