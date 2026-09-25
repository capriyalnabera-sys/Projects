"""NSE direct quote API — authoritative Indian-equity LTPs.

Why this over moneycontrol/yfinance:
  - NSE is the exchange itself: this IS the live trade tape.
  - yfinance has 15-20 min lag and intermittently misses Indian symbols.
  - moneycontrol's lookup endpoint is blocked by Akamai (no sccode resolution).

How it works:
  1. Warm session cookies by hitting nseindia.com once.
  2. Hit /api/quote-equity?symbol=<TICKER> — returns full priceInfo JSON.

Session/cookies are reused across calls in the same process; if NSE rotates
them we re-warm transparently. Returns None on failure (caller falls back).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import requests


_session_lock = threading.Lock()
_session: Optional[requests.Session] = None
_session_warmed_at: float = 0.0
_SESSION_TTL_SECONDS = 15 * 60  # rewarm every 15 minutes

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/get-quotes/equity",
}


def _get_session() -> requests.Session:
    global _session, _session_warmed_at
    with _session_lock:
        now = time.time()
        if _session is not None and (now - _session_warmed_at) < _SESSION_TTL_SECONDS:
            return _session
        s = requests.Session()
        try:
            s.get("https://www.nseindia.com/", headers=HEADERS, timeout=10)
        except Exception:
            pass
        _session = s
        _session_warmed_at = now
        return s


def fetch_quote(ticker: str) -> Optional[dict]:
    """Return a dict with normalized fields or None on failure.

    Keys: ltp, change, change_pct, prev_close, day_high, day_low, volume, as_of
    """
    sym = ticker.strip().upper()
    s = _get_session()
    for attempt in range(2):
        try:
            r = s.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={sym}",
                headers={**HEADERS, "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"},
                timeout=8,
            )
            if r.status_code == 403 and attempt == 0:
                # Cookie probably expired — force a rewarm and retry once.
                with _session_lock:
                    globals()["_session_warmed_at"] = 0
                s = _get_session()
                continue
            if r.status_code != 200:
                return None
            d = r.json()
        except Exception:
            return None
        price = d.get("priceInfo") if isinstance(d, dict) else None
        if not isinstance(price, dict):
            return None
        ltp = price.get("lastPrice")
        if ltp is None:
            return None
        ihl = price.get("intraDayHighLow") or {}
        ts = (d.get("metadata") or {}).get("lastUpdateTime") or ""
        return {
            "ltp": float(ltp),
            "change": float(price.get("change") or 0),
            "change_pct": float(price.get("pChange") or 0),
            "prev_close": float(price.get("previousClose") or 0) or None,
            "day_high": float(ihl.get("max")) if ihl.get("max") is not None else None,
            "day_low": float(ihl.get("min")) if ihl.get("min") is not None else None,
            "volume": int(price.get("totalTradedVolume") or 0) or None,
            "as_of": ts,
            "source": "nse",
        }
    return None


def fetch_quotes(tickers: list[str]) -> dict[str, dict]:
    """Fetch quotes for many tickers — sequential per-ticker, ~200-300ms each.
    Returns {ticker: quote_dict}; failures are absent from the result."""
    out: dict[str, dict] = {}
    s = _get_session()  # warm once
    for t in tickers:
        q = fetch_quote(t)
        if q:
            out[t.upper()] = q
    return out
