"""F&O data layer — index option chains from the exchanges themselves.

Sources (all free, no API key):
  - NSE  option-chain API  → NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY
  - BSE  option-chain API  → SENSEX (best-effort; BSE's API is less stable)

Same session-warmup pattern as nse_quote.py: hit the human page once to get
Akamai cookies, then call the JSON API with a matching Referer. Responses are
cached on disk (short TTL) and served stale-with-a-flag when the exchange
blocks us — the analytics layer still works on a slightly old chain.

Normalized chain shape (what fno_signals consumes):
  {
    "symbol": "NIFTY", "spot": 25012.5, "as_of": "25-Sep-2026 15:30:00",
    "source": "nse", "stale": false, "expiries": ["30-Sep-2026", ...],
    "expiry": "30-Sep-2026",            # the expiry the rows below belong to
    "rows": [
      {"strike": 24800.0,
       "ce": {"oi": 1000, "oi_change": 200, "volume": 5000, "iv": 12.1,
              "ltp": 250.0, "bid": 249.0, "ask": 251.0},
       "pe": {...}},
      ...
    ]
  }
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from . import nse_quote


# ---------------------------------------------------------------------------
# Index metadata. Lot sizes / strike steps are exchange-notified and change a
# couple of times a year — treat these as fallbacks and allow config.yaml
# (fno.lot_sizes) to override without a code change.
# ---------------------------------------------------------------------------
INDEX_META = {
    "NIFTY":      {"exchange": "NSE", "lot": 75,  "step": 50,  "yf": "^NSEI",
                   "label": "NIFTY 50"},
    "BANKNIFTY":  {"exchange": "NSE", "lot": 35,  "step": 100, "yf": "^NSEBANK",
                   "label": "BANK NIFTY"},
    "FINNIFTY":   {"exchange": "NSE", "lot": 65,  "step": 50,  "yf": "NIFTY_FIN_SERVICE.NS",
                   "label": "FIN NIFTY"},
    "MIDCPNIFTY": {"exchange": "NSE", "lot": 140, "step": 25,  "yf": "NIFTY_MID_SELECT.NS",
                   "label": "MIDCAP NIFTY"},
    "SENSEX":     {"exchange": "BSE", "lot": 20,  "step": 100, "yf": "^BSESN",
                   "label": "SENSEX"},
}

# Symbols shown as tabs in the web UI, in display order.
DISPLAY_ORDER = ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]

CACHE_DIR = Path("data/cache/fno")
CHAIN_TTL_SECONDS = 3 * 60          # re-fetch after 3 min during market hours
STALE_MAX_AGE_SECONDS = 36 * 3600   # serve stale up to 36h with stale=True

OC_PAGE = "https://www.nseindia.com/option-chain"
OC_API_CLASSIC = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
OC_API_V3 = "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={expiry}"
OC_CONTRACT_INFO = "https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}"

# BSE SENSEX option chain — undocumented, shape shifts occasionally. We try the
# known endpoints in order and parse defensively; any failure → None and the
# caller degrades to spot-only analytics.
BSE_HEADERS = {
    "User-Agent": nse_quote.HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
BSE_EXPIRY_URLS = [
    # scripcode 1 = SENSEX derivatives underlying
    "https://api.bseindia.com/BseIndiaAPI/api/ddlExpiry_IV/w?ProductType=IO&scripcode=1&seriesid=",
]
BSE_CHAIN_URLS = [
    "https://api.bseindia.com/BseIndiaAPI/api/OptionChain_IV/w?scripcode=1&expdate={expiry}&seriesid=",
    "https://api.bseindia.com/BseIndiaAPI/api/GetOptionChain_IV/w?scripcode=1&expirydate={expiry}&seriesid=",
]


_oc_session_lock = threading.Lock()
_oc_session: Optional[requests.Session] = None
_oc_warmed_at: float = 0.0
_OC_SESSION_TTL = 10 * 60


def _oc_get_session() -> requests.Session:
    """NSE session warmed against the /option-chain page (its APIs check for
    cookies the plain homepage warmup doesn't always set)."""
    global _oc_session, _oc_warmed_at
    with _oc_session_lock:
        now = time.time()
        if _oc_session is not None and (now - _oc_warmed_at) < _OC_SESSION_TTL:
            return _oc_session
        s = requests.Session()
        try:
            s.get("https://www.nseindia.com/", headers=nse_quote.HEADERS, timeout=10)
            s.get(OC_PAGE, headers=nse_quote.HEADERS, timeout=10)
        except Exception:
            pass
        _oc_session = s
        _oc_warmed_at = now
        return s


def _oc_headers() -> dict:
    return {**nse_quote.HEADERS, "Referer": OC_PAGE}


def _force_rewarm() -> None:
    global _oc_warmed_at
    with _oc_session_lock:
        _oc_warmed_at = 0.0


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol.upper()}_chain.json"


def _read_cache(symbol: str, max_age: float) -> Optional[dict]:
    p = _cache_path(symbol)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > max_age:
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["cache_age_seconds"] = int(age)
        return d
    except Exception:
        return None


def _write_cache(symbol: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(symbol).write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# NSE fetch + parse
# ---------------------------------------------------------------------------

def _parse_leg(d: Optional[dict]) -> Optional[dict]:
    """One side (CE or PE) of an NSE chain row → normalized leg dict."""
    if not isinstance(d, dict):
        return None
    try:
        return {
            "oi": int(d.get("openInterest") or 0),
            "oi_change": int(d.get("changeinOpenInterest") or 0),
            "volume": int(d.get("totalTradedVolume") or 0),
            "iv": float(d.get("impliedVolatility") or 0) or None,
            "ltp": float(d.get("lastPrice") or 0) or None,
            "bid": float(d.get("bidprice") or 0) or None,
            "ask": float(d.get("askPrice") or 0) or None,
        }
    except (TypeError, ValueError):
        return None


def parse_nse_chain(raw: dict, symbol: str, expiry: Optional[str] = None) -> Optional[dict]:
    """NSE option-chain-indices JSON → normalized chain for ONE expiry
    (nearest by default). Kept separate from fetching so it's testable offline."""
    records = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(records, dict):
        return None
    expiries: list[str] = list(records.get("expiryDates") or [])
    data = records.get("data") or []
    spot = records.get("underlyingValue")
    if not expiries or not data or not spot:
        return None
    target = expiry if expiry in expiries else expiries[0]

    rows: list[dict] = []
    for item in data:
        if not isinstance(item, dict) or item.get("expiryDate") != target:
            continue
        strike = item.get("strikePrice")
        if strike is None:
            continue
        rows.append({
            "strike": float(strike),
            "ce": _parse_leg(item.get("CE")),
            "pe": _parse_leg(item.get("PE")),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: r["strike"])
    return {
        "symbol": symbol.upper(),
        "spot": float(spot),
        "as_of": records.get("timestamp") or "",
        "source": "nse",
        "stale": False,
        "expiries": expiries[:8],
        "expiry": target,
        "rows": rows,
    }


def _fetch_nse_chain(symbol: str, expiry: Optional[str] = None) -> Optional[dict]:
    s = _oc_get_session()
    url = OC_API_CLASSIC.format(symbol=symbol.upper())
    for attempt in range(2):
        try:
            r = s.get(url, headers=_oc_headers(), timeout=12)
            if r.status_code in (401, 403) and attempt == 0:
                _force_rewarm()
                s = _oc_get_session()
                continue
            if r.status_code != 200 or not r.text.strip():
                return None
            return parse_nse_chain(r.json(), symbol, expiry)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# BSE fetch + parse (SENSEX) — best effort
# ---------------------------------------------------------------------------

def _bse_get(url: str) -> Optional[object]:
    try:
        r = requests.get(url, headers=BSE_HEADERS, timeout=12)
        if r.status_code != 200 or not r.text.strip():
            return None
        return r.json()
    except Exception:
        return None


def _bse_expiries() -> list[str]:
    for url in BSE_EXPIRY_URLS:
        d = _bse_get(url)
        if not d:
            continue
        # Seen shapes: {"Table":[{"ExpiryDate":"30 Sep 2026"},...]} or a bare list
        items = d.get("Table") if isinstance(d, dict) else d
        if not isinstance(items, list):
            continue
        out = []
        for it in items:
            if isinstance(it, dict):
                v = it.get("ExpiryDate") or it.get("expdate") or it.get("Expiry")
                if v:
                    out.append(str(v).strip())
            elif isinstance(it, str):
                out.append(it.strip())
        if out:
            return out
    return []


def _bse_num(d: dict, *keys) -> Optional[float]:
    for k in keys:
        if k in d and d[k] not in (None, "", "-"):
            try:
                return float(str(d[k]).replace(",", ""))
            except (TypeError, ValueError):
                continue
    return None


def _parse_bse_rows(items: list) -> list[dict]:
    """BSE returns one flat record per strike with CE_/PE_ prefixed columns
    (column names have drifted over time — probe several spellings)."""
    rows: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        strike = _bse_num(it, "Strike_Price", "StrikePrice", "strike_price", "STRIKE")
        if strike is None:
            continue

        def leg(prefix: str) -> Optional[dict]:
            oi = _bse_num(it, f"{prefix}_OI", f"{prefix}_OpenInterest", f"{prefix}OI")
            ltp = _bse_num(it, f"{prefix}_LTP", f"{prefix}_LastPrice", f"{prefix}LTP")
            if oi is None and ltp is None:
                return None
            return {
                "oi": int(oi or 0),
                "oi_change": int(_bse_num(it, f"{prefix}_ChgOI", f"{prefix}_OIChange", f"{prefix}_Change_OI") or 0),
                "volume": int(_bse_num(it, f"{prefix}_Volume", f"{prefix}_Vol") or 0),
                "iv": _bse_num(it, f"{prefix}_IV", f"{prefix}_ImpliedVolatility"),
                "ltp": ltp,
                "bid": _bse_num(it, f"{prefix}_BidPrice", f"{prefix}_Bid"),
                "ask": _bse_num(it, f"{prefix}_AskPrice", f"{prefix}_Ask", f"{prefix}_OfferPrice"),
            }

        rows.append({"strike": strike, "ce": leg("CE"), "pe": leg("PE")})
    rows.sort(key=lambda r: r["strike"])
    return rows


def _fetch_bse_chain(expiry: Optional[str] = None) -> Optional[dict]:
    expiries = _bse_expiries()
    if not expiries:
        return None
    target = expiry if expiry in expiries else expiries[0]
    for url_tpl in BSE_CHAIN_URLS:
        d = _bse_get(url_tpl.format(expiry=requests.utils.quote(target)))
        if not d:
            continue
        items = d.get("Table") if isinstance(d, dict) else d
        if not isinstance(items, list) or not items:
            continue
        rows = _parse_bse_rows(items)
        if not rows:
            continue
        # Spot: some payloads carry it; else leave None and let the caller
        # fill from yfinance ^BSESN.
        spot = None
        if isinstance(d, dict):
            for k in ("UlaValue", "underlyingValue", "LTP", "CurrRate"):
                v = d.get(k)
                try:
                    if v:
                        spot = float(str(v).replace(",", ""))
                        break
                except (TypeError, ValueError):
                    continue
        return {
            "symbol": "SENSEX",
            "spot": spot,
            "as_of": datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
            "source": "bse",
            "stale": False,
            "expiries": expiries[:8],
            "expiry": target,
            "rows": rows,
        }
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_chain(symbol: str, expiry: Optional[str] = None, force: bool = False) -> Optional[dict]:
    """Normalized option chain for an index, disk-cached.

    Freshness ladder: fresh cache (≤3 min) → live fetch → stale cache (≤36h,
    flagged stale=True) → None."""
    sym = symbol.upper()
    if sym not in INDEX_META:
        return None
    cache_key = sym if expiry is None else f"{sym}_{expiry.replace(' ', '_')}"

    if not force:
        hit = _read_cache(cache_key, CHAIN_TTL_SECONDS)
        if hit is not None:
            return hit

    if INDEX_META[sym]["exchange"] == "BSE":
        live = _fetch_bse_chain(expiry)
    else:
        live = _fetch_nse_chain(sym, expiry)

    if live is not None:
        _write_cache(cache_key, live)
        return live

    stale = _read_cache(cache_key, STALE_MAX_AGE_SECONDS)
    if stale is not None:
        stale["stale"] = True
        return stale
    return None


def parse_expiry_date(expiry: str) -> Optional[datetime]:
    """'30-Sep-2026' (NSE) or '30 Sep 2026' (BSE) → datetime, else None."""
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(expiry.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def days_to_expiry(expiry: str) -> Optional[int]:
    dt = parse_expiry_date(expiry)
    if dt is None:
        return None
    return max(0, (dt.date() - datetime.now().date()).days)


def lot_size(symbol: str, cfg: Optional[dict] = None) -> int:
    """Config override (fno.lot_sizes.SYMBOL) beats the built-in fallback —
    exchanges revise lots a couple of times a year."""
    sym = symbol.upper()
    if cfg:
        override = (cfg.get("fno", {}) or {}).get("lot_sizes", {}) or {}
        if sym in override:
            try:
                return int(override[sym])
            except (TypeError, ValueError):
                pass
    return INDEX_META.get(sym, {}).get("lot", 0)
