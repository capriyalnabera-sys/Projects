"""Earnings calendar — flag stocks whose results are within N trading days.

Why this matters: buying *before* earnings is a coin flip — the verdict is
based on stale data that's about to be replaced. Treating these as 'verdict
pending' avoids false confidence in the days leading up to a result.

Source: NSE's corporate event calendar — one request covering every NSE
company's announced results board meetings (listed companies must give
advance notice of a results meeting, so it covers the 5-day window used
here). Fetched once and cached 12 h. BSE-only stocks, and NSE stocks when the
calendar is unavailable, fall back to a cached per-stock Yahoo lookup.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

from . import data as data_mod


EARNINGS_CACHE_DIR = Path("data/cache/earnings")
EARNINGS_CACHE_TTL_SECONDS = 24 * 60 * 60   # kept for callers; see below
KNOWN_DATE_TTL_SECONDS = 7 * 24 * 60 * 60
UNKNOWN_DATE_TTL_SECONDS = 3 * 24 * 60 * 60


def _cache_path(ticker: str) -> Path:
    return EARNINGS_CACHE_DIR / f"{ticker.upper()}.json"


NSE_CALENDAR_URLS = (
    "https://www.nseindia.com/api/event-calendar",
    "https://www.nseindia.com/api/event-calendar?index=equities",
)
NSE_CALENDAR_TTL_SECONDS = 12 * 60 * 60
NSE_CALENDAR_RETRY_SECONDS = 60 * 60     # after a failed fetch
_calendar_lock = threading.Lock()


def _calendar_path() -> Path:
    return EARNINGS_CACHE_DIR / "_nse_event_calendar.json"


def parse_nse_event_calendar(payload) -> dict[str, str]:
    """NSE event-calendar JSON → {SYMBOL: earliest upcoming results date ISO}.
    Only results board meetings count (purpose mentions 'result')."""
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    today = date.today()
    out: dict[str, str] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        purpose = " ".join(str(r.get(k) or "") for k in ("purpose", "bm_purpose", "bm_desc"))
        if not sym or "result" not in purpose.lower():
            continue
        raw = str(r.get("date") or r.get("bm_date") or "").strip()
        d = None
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
            try:
                d = datetime.strptime(raw[:11], fmt).date()
                break
            except ValueError:
                continue
        if d is None or d < today:
            continue
        if sym not in out or d.isoformat() < out[sym]:
            out[sym] = d.isoformat()
    return out


def nse_calendar() -> Optional[dict[str, str]]:
    """{SYMBOL: date ISO} from NSE, or None when unavailable (callers then
    use the per-stock Yahoo lookup). One fetch serves every caller."""
    p = _calendar_path()

    def cached() -> Optional[dict]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        age = time.time() - d.get("ts", 0)
        if d.get("failed"):
            return {"_failed": True} if age < NSE_CALENDAR_RETRY_SECONDS else None
        return d.get("dates") if age < NSE_CALENDAR_TTL_SECONDS else None

    hit = cached()
    if hit is not None:
        return None if hit.get("_failed") else hit
    with _calendar_lock:
        hit = cached()                       # another thread may have fetched it
        if hit is not None:
            return None if hit.get("_failed") else hit
        dates: Optional[dict[str, str]] = None
        try:
            from . import nse_quote
            from .profiler import timed
            s = nse_quote._get_session()
            headers = {**nse_quote.HEADERS,
                       "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar"}
            for url in NSE_CALENDAR_URLS:
                with timed("net: NSE event calendar"):
                    r = s.get(url, headers=headers, timeout=15)
                if r.status_code == 200 and r.text.strip():
                    parsed = parse_nse_event_calendar(r.json())
                    # An empty parse means the format changed: don't silently
                    # report "no results scheduled" for every stock.
                    if parsed:
                        dates = parsed
                        break
        except Exception:
            dates = None
        try:
            EARNINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"ts": time.time(), "dates": dates} if dates is not None
                                    else {"ts": time.time(), "failed": True}), encoding="utf-8")
        except Exception:
            pass
        return dates


def next_earnings_date(ticker: str) -> Optional[date]:
    """Return the next earnings date if known, else None."""
    tk = ticker.upper()
    if not tk.endswith(".BO"):
        cal = nse_calendar()
        if cal is not None:
            v = cal.get(tk.replace(".NS", ""))
            return date.fromisoformat(v) if v else None
    p = _cache_path(tk)
    if p.exists():
        age = time.time() - p.stat().st_mtime
        try:
            cached = json.loads(p.read_text(encoding="utf-8"))
            v = cached.get("next_earnings_date")
            if v:
                d = date.fromisoformat(v)
                # A scheduled results date rarely moves: trust it for a week,
                # until it passes. Unknown dates are re-asked after 3 days.
                if age < KNOWN_DATE_TTL_SECONDS and d >= date.today():
                    return d
            elif age < UNKNOWN_DATE_TTL_SECONDS:
                return None
        except Exception:
            pass

    out: Optional[date] = None
    try:
        from .profiler import timed
        with timed("net: yahoo earnings calendar"):
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
