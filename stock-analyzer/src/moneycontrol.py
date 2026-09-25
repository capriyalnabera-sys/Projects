"""MoneyControl as primary price source (yfinance is noisy for Indian stocks).

Two-step:
  1. Resolve NSE ticker -> moneycontrol 'sccode' via their autosuggestion endpoint
     (sccode is moneycontrol's internal ID, e.g. 'RI' for RELIANCE).
  2. Fetch live quote from /pricefeed/nse/equitycash/<sccode>.

sccode is persisted in a JSON file at data/cache/moneycontrol/sccode_map.json
since it never changes per ticker — that mapping survives across restarts and
makes subsequent fetches a single HTTP call per ticker.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import requests


SCCODE_MAP_PATH = Path("data/cache/moneycontrol/sccode_map.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moneycontrol.com/",
}

_sccode_lock = threading.Lock()
_sccode_cache: Optional[dict] = None


def _load_map() -> dict:
    global _sccode_cache
    with _sccode_lock:
        if _sccode_cache is not None:
            return _sccode_cache
        if SCCODE_MAP_PATH.exists():
            try:
                _sccode_cache = json.loads(SCCODE_MAP_PATH.read_text(encoding="utf-8"))
                return _sccode_cache
            except Exception:
                pass
        _sccode_cache = {}
        return _sccode_cache


def _save_map() -> None:
    global _sccode_cache
    if _sccode_cache is None:
        return
    try:
        SCCODE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCCODE_MAP_PATH.write_text(json.dumps(_sccode_cache, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def get_sccode(ticker: str) -> Optional[str]:
    """Resolve an NSE ticker to its moneycontrol sccode. Cached on first lookup."""
    tk = ticker.strip().upper()
    cache = _load_map()
    if tk in cache:
        return cache[tk] or None

    # Autosuggestion endpoint — returns JSON list of matches.
    url = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
    params = {"query": tk, "type": "1", "format": "json"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except Exception:
            # Sometimes wrapped in JSONP; strip
            text = r.text
            i, j = text.find("("), text.rfind(")")
            if 0 < i < j:
                data = json.loads(text[i + 1:j])
            else:
                return None
    except Exception:
        return None

    sccode = None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            # Common field names across moneycontrol's variants:
            sym = (item.get("link_src") or item.get("symbol") or item.get("nse_id") or "").upper()
            sc = item.get("sc_id") or item.get("sc_did") or item.get("id")
            if sym == tk and sc:
                sccode = sc
                break
        if not sccode and data:
            first = data[0] if isinstance(data[0], dict) else {}
            sccode = first.get("sc_id") or first.get("sc_did") or first.get("id")

    with _sccode_lock:
        # Persist either the resolved code or an empty string (cache the failure
        # for a session — we'll retry on next process start).
        _sccode_cache[tk] = sccode or ""
        _save_map()
    return sccode


def fetch_quote(ticker: str) -> Optional[dict]:
    """Live quote from moneycontrol's price feed.
    Returns dict with ltp / change / change_pct / volume / day_high / day_low /
    prev_close / as_of, or None if unavailable."""
    sccode = get_sccode(ticker)
    if not sccode:
        return None
    url = f"https://priceapi.moneycontrol.com/pricefeed/nse/equitycash/{sccode}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        body = r.json()
    except Exception:
        return None
    d = body.get("data") if isinstance(body, dict) else None
    if not isinstance(d, dict):
        return None

    def _f(key):
        v = d.get(key)
        if v in (None, "", "NA"):
            return None
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None

    ltp = _f("pricecurrent") or _f("LTP")
    if ltp is None:
        return None
    change = _f("pricechange") or 0.0
    return {
        "ltp": ltp,
        "change": change,
        "change_pct": _f("pricepercentchange") or 0.0,
        "volume": int(_f("VOL") or 0),
        "day_high": _f("HP") or _f("dayhigh"),
        "day_low": _f("LP") or _f("daylow"),
        "prev_close": ltp - change if ltp and change is not None else None,
        "as_of": d.get("lastupdated") or d.get("LDT") or "",
        "sccode": sccode,
        "source": "moneycontrol",
    }
