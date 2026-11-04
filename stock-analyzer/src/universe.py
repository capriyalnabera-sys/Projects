"""Predefined and fetched ticker universes for batch analysis."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests


NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "INFY", "ITC",
    "SBIN", "LT", "BAJFINANCE", "HINDUNILVR", "ASIANPAINT", "HCLTECH", "MARUTI",
    "AXISBANK", "M&M", "TITAN", "KOTAKBANK", "SUNPHARMA", "ULTRACEMCO", "NTPC",
    "ADANIPORTS", "NESTLEIND", "POWERGRID", "ONGC", "TATAMOTORS", "COALINDIA",
    "JSWSTEEL", "TATASTEEL", "INDUSINDBK", "SBILIFE", "GRASIM", "BRITANNIA",
    "HINDALCO", "HEROMOTOCO", "BAJAJFINSV", "EICHERMOT", "BAJAJ-AUTO", "CIPLA",
    "TECHM", "DIVISLAB", "DRREDDY", "APOLLOHOSP", "BPCL", "TATACONSUM", "WIPRO",
    "HDFCLIFE", "UPL", "LTIM", "ADANIENT",
]


NIFTY_NEXT_50 = [
    "ABB", "ADANIGREEN", "ADANIPOWER", "ATGL", "AMBUJACEM", "DMART", "BAJAJHLDNG",
    "BANKBARODA", "BERGEPAINT", "BEL", "BOSCHLTD", "CANBK", "CHOLAFIN", "COLPAL",
    "DLF", "DABUR", "GAIL", "GODREJCP", "HAVELLS", "HAL", "ICICIGI", "ICICIPRULI",
    "IOC", "IRCTC", "NAUKRI", "INDIGO", "JINDALSTEL", "JIOFIN", "LICI", "MARICO",
    "MOTHERSON", "MUTHOOTFIN", "PIDILITIND", "PFC", "PNB", "RECLTD", "SHREECEM",
    "SIEMENS", "SRF", "SBICARD", "TVSMOTOR", "TATAPOWER", "TRENT", "UNITDSPR",
    "VEDL", "VBL", "ZOMATO", "ZYDUSLIFE", "INDUSTOWER", "MANKIND",
]


def get_universe(name: str, cache_dir: Optional[Path] = None) -> list[str]:
    name = name.lower().replace(" ", "").replace("_", "")
    if name in ("nifty50", "n50"):
        return list(NIFTY_50)
    if name in ("niftynext50", "next50", "nn50"):
        return list(NIFTY_NEXT_50)
    if name in ("nifty100", "n100"):
        return list(NIFTY_50) + list(NIFTY_NEXT_50)
    if name in ("nifty200", "n200"):
        out = _try_fetch_nse_index("ind_nifty200list.csv", cache_dir)
        if out:
            return out
        return list(NIFTY_50) + list(NIFTY_NEXT_50)
    if name in ("nifty500", "n500"):
        out = _try_fetch_nse_index("ind_nifty500list.csv", cache_dir)
        if out:
            return out
        return list(NIFTY_50) + list(NIFTY_NEXT_50)
    if name in ("niftymidcap150", "midcap150", "nm150"):
        out = _try_fetch_nse_index("ind_niftymidcap150list.csv", cache_dir)
        if out:
            return out
        return []
    if name in ("niftysmallcap250", "smallcap250", "ns250"):
        out = _try_fetch_nse_index("ind_niftysmallcap250list.csv", cache_dir)
        if out:
            return out
        return []
    if name in ("niftymidsmall400", "midsmall400", "nms400", "midcap400"):
        # Official "Nifty MidSmallcap 400" = Midcap 150 + Smallcap 250.
        out = _try_fetch_nse_index("ind_niftymidsmallcap400list.csv", cache_dir)
        if out:
            return out
        # Synthesize from the two component indices if the combined CSV is missing.
        mid = _try_fetch_nse_index("ind_niftymidcap150list.csv", cache_dir) or []
        small = _try_fetch_nse_index("ind_niftysmallcap250list.csv", cache_dir) or []
        return list(dict.fromkeys(mid + small))  # de-dup, preserve order
    if name in ("all", "everything"):
        # Deduplicated union of every defined NIFTY index — typically ~700-800 unique tickers.
        seen: set[str] = set()
        out: list[str] = []
        for u in ("nifty50", "nifty100", "nifty500", "midcap150", "smallcap250", "midsmall400"):
            try:
                for t in get_universe(u, cache_dir=cache_dir):
                    tk = t.upper()
                    if tk not in seen:
                        seen.add(tk)
                        out.append(t)
            except Exception:
                continue
        return out
    if name in ("sensex", "sensex30", "bse30"):
        return list(SENSEX_30)
    if name in ("liveset", "live", "nsebselive", "tradeable"):
        # Proven-liquid NSE+BSE names from the last full sweep (~1,900).
        # Falls back to the complete listing until a sweep has run.
        live = load_live_set(cache_dir)
        return live if live else get_all_listed(cache_dir)
    if name in ("alllisted", "allnse", "allbse", "nsebse", "everylisted"):
        # Every NSE + BSE equity (deduplicated by ISIN) with market cap at or
        # above universe.min_market_cap_cr (default ₹500 cr), as built by the
        # last Refresh all. Before the first build: the complete listing.
        cap = load_mcap_universe(cache_dir)
        return cap["tickers"] if cap and cap.get("tickers") else get_all_listed(cache_dir)
    raise ValueError(f"Unknown universe: {name}")


# BSE SENSEX 30 constituents (NSE symbols, since price data comes via NSE).
# BSE reviews the index twice a year — update this list when membership
# changes. As of late 2025: JSW Steel out (Dec 2024), Zomato/Eternal in.
SENSEX_30 = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "BHARTIARTL",
    "LT", "KOTAKBANK", "SBIN", "AXISBANK", "ASIANPAINT", "MARUTI", "M&M",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "BAJFINANCE",
    "BAJAJFINSV", "NTPC", "POWERGRID", "HCLTECH", "TECHM", "TATASTEEL",
    "TATAMOTORS", "INDUSINDBK", "HINDUNILVR", "ADANIPORTS", "ETERNAL",
]


# --------------------------------------------------------------------------
# Full NSE + BSE listed universe (ISIN-deduplicated)
# --------------------------------------------------------------------------
# NSE names use their plain symbol (→ <SYM>.NS downstream). BSE-only names —
# those whose ISIN is NOT also on NSE — use a "<SCRIP_ID>.BO" ticker, which
# the data layer passes through to yfinance unchanged. This keeps NSE the
# preferred line for dual-listed companies (better liquidity + data) while
# still surfacing the ~3,000 BSE-exclusive names.

NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
# NSE Emerge (SME platform) listings live in a separate file.
NSE_SME_LIST_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
# Main-board series kept: EQ (normal), BE / BZ (trade-for-trade — still listed).
NSE_MAIN_SERIES = ("EQ", "BE", "BZ")
NSE_SME_SERIES = ("SM", "ST")
# A symbol counts as alive if it traded in the price files this recently.
TRADED_LOOKBACK_DAYS = 60
BSE_SCRIP_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"
ALL_LISTED_TTL_SECONDS = 7 * 86400  # 7 days


def _fetch_nse_all(cache_dir: Path) -> list[dict]:
    """All NSE main-board equities (EQ / BE / BZ). Returns [{symbol, isin}]."""
    return _fetch_nse_csv(cache_dir, NSE_EQUITY_LIST_URL, "_nse_equity_all.json", NSE_MAIN_SERIES)


def _fetch_nse_sme(cache_dir: Path) -> list[dict]:
    """All NSE Emerge (SME) equities. Returns [{symbol, isin}]."""
    return _fetch_nse_csv(cache_dir, NSE_SME_LIST_URL, "_nse_sme_all.json", NSE_SME_SERIES)


def _fetch_nse_csv(cache_dir: Path, url: str, cache_name: str, series_ok: tuple) -> list[dict]:
    cache_path = cache_dir / cache_name
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime < ALL_LISTED_TTL_SECONDS):
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/csv,*/*"},
            timeout=20,
        )
        if r.status_code != 200 or not r.text:
            return []
        # Columns: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,
        #          MARKET LOT, ISIN NUMBER, FACE VALUE
        out: list[dict] = []
        for line in r.text.strip().splitlines()[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue
            sym = parts[0].strip().strip('"')
            series = parts[2].strip().upper()
            isin = parts[6].strip()
            if not sym or series not in series_ok:
                continue
            out.append({"symbol": sym, "isin": isin})
        if out:
            cache_path.write_text(json.dumps(out), encoding="utf-8")
        return out
    except Exception:
        return []


def _fetch_bse_all(cache_dir: Path) -> list[dict]:
    """All active BSE-listed equities. Returns
    [{scrip_id, scrip_code, isin, mktcap, group}]."""
    cache_path = cache_dir / "_bse_equity_all.json"
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime < ALL_LISTED_TTL_SECONDS):
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(
            BSE_SCRIP_LIST_URL,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json",
                "Referer": "https://www.bseindia.com/",
            },
            timeout=25,
        )
        if r.status_code != 200 or not r.text:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            scrip_id = (row.get("scrip_id") or "").strip().upper()
            isin = (row.get("ISIN_NUMBER") or "").strip()
            if not scrip_id:
                continue
            try:
                mktcap = float(row.get("Mktcap") or 0)
            except (TypeError, ValueError):
                mktcap = 0.0
            out.append({
                "scrip_id": scrip_id,
                "scrip_code": (row.get("SCRIP_CD") or "").strip(),
                "isin": isin,
                "mktcap": mktcap,
                "group": (row.get("GROUP") or "").strip(),
            })
        if out:
            cache_path.write_text(json.dumps(out), encoding="utf-8")
        return out
    except Exception:
        return []


def get_all_listed(cache_dir: Optional[Path] = None) -> list[str]:
    """Every listed Indian equity: NSE main board + NSE SME + BSE, plus any
    symbol that traded in the exchanges' daily price files recently (catches
    listings the scrip lists miss). NSE symbols first; BSE-only names (by
    ISIN) appended as ``<SCRIP_ID>.BO``. Saved as a flat ticker list."""
    if cache_dir is None:
        cache_dir = Path("data/cache/universe")
    cache_dir.mkdir(parents=True, exist_ok=True)
    combined_path = cache_dir / "_all_listed.json"

    nse_rows = _fetch_nse_all(cache_dir) + _fetch_nse_sme(cache_dir)
    bse_rows = _fetch_bse_all(cache_dir)
    try:
        from . import exchange_prices as ep
        traded_nse = ep.recent_symbols("NSE", TRADED_LOOKBACK_DAYS)
        traded_bse = ep.recent_symbols("BSE", TRADED_LOOKBACK_DAYS)
        isin_nse, isin_bse = ep.isins("NSE"), ep.isins("BSE")
    except Exception:
        traded_nse, traded_bse, isin_nse, isin_bse = set(), set(), {}, {}

    tickers: list[str] = []
    seen: set[str] = set()
    nse_isins: set[str] = set()
    for row in nse_rows:
        sym = row["symbol"].upper()
        if sym not in seen:
            seen.add(sym)
            tickers.append(sym)
        if row.get("isin"):
            nse_isins.add(row["isin"])
    for sym in sorted(traded_nse):              # traded but missing from the lists
        if sym not in seen:
            seen.add(sym)
            tickers.append(sym)
        if isin_nse.get(sym):
            nse_isins.add(isin_nse[sym])

    nse_syms = set(seen)
    bse_candidates = [(r["scrip_id"], r.get("isin")) for r in bse_rows] + \
                     [(s, isin_bse.get(s)) for s in sorted(traded_bse)]
    for sym, isin in bse_candidates:
        sym = (sym or "").strip().upper()
        if not sym:
            continue
        if isin and isin in nse_isins:
            continue                              # dual-listed: covered by NSE
        if not isin and sym in nse_syms:
            continue                              # same symbol, no ISIN: assume dual
        bo = f"{sym}.BO"
        if bo not in seen:
            seen.add(bo)
            tickers.append(bo)

    if not tickers:
        try:                                      # offline and no store: last good list
            return json.loads(combined_path.read_text(encoding="utf-8"))
        except Exception:
            return []
    try:
        combined_path.write_text(json.dumps(tickers), encoding="utf-8")
    except Exception:
        pass
    return tickers


def load_all_listed_cached(cache_dir: Optional[Path] = None) -> list[str]:
    """The full NSE+BSE listing from disk only, whatever its age — for page
    rendering, which must never block on the exchange downloads that
    get_all_listed() does when its cache is stale."""
    if cache_dir is None:
        cache_dir = Path("data/cache/universe")
    try:
        return json.loads((cache_dir / "_all_listed.json").read_text(encoding="utf-8"))
    except Exception:
        return []


# --------------------------------------------------------------------------
# Market-cap universe — every listed stock at or above the market-cap floor,
# rebuilt on each Refresh all (see mcap.py). Behind the ALL UNIVERSE tab.
# --------------------------------------------------------------------------

def _mcap_universe_path(cache_dir: Optional[Path]) -> Path:
    return (cache_dir or Path("data/cache/universe")) / "_mcap_universe.json"


def load_mcap_universe(cache_dir: Optional[Path] = None) -> Optional[dict]:
    """{"tickers": [...], "stats": {...}, "updated_at": iso} or None."""
    p = _mcap_universe_path(cache_dir)
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def save_mcap_universe(tickers: list[str], stats: dict, cache_dir: Optional[Path] = None) -> None:
    p = _mcap_universe_path(cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "tickers": tickers, "stats": stats,
            "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Live set — the subset of a big universe that actually had data + cleared the
# liquidity floor on the last full sweep. Routine refreshes re-run only this,
# so the big universe stays usable without 20-minute batches every time.
# --------------------------------------------------------------------------

def live_set_path(cache_dir: Optional[Path] = None) -> Path:
    if cache_dir is None:
        cache_dir = Path("data/cache/universe")
    return cache_dir / "_live_set.json"


def load_live_set(cache_dir: Optional[Path] = None) -> Optional[list[str]]:
    p = live_set_path(cache_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("tickers") if isinstance(data, dict) else data
    except Exception:
        return None


def save_live_set(tickers: list[str], cache_dir: Optional[Path] = None) -> None:
    p = live_set_path(cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({
            "tickers": tickers,
            "count": len(tickers),
            "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
    except Exception:
        pass


def _try_fetch_nse_index(csv_name: str, cache_dir: Optional[Path]) -> Optional[list[str]]:
    """Fetch ticker list from NSE archives. Cached for 7 days. Returns None on failure."""
    if cache_dir is None:
        cache_dir = Path("data/cache/universe")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / csv_name.replace(".csv", ".json")
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime < 7 * 86400):
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    url = f"https://archives.nseindia.com/content/indices/{csv_name}"
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
                "Accept": "text/csv,*/*",
            },
            timeout=15,
        )
        if r.status_code != 200 or not r.text:
            return None
        # NSE CSV columns: Company Name, Industry, Symbol, Series, ISIN Code
        lines = r.text.strip().splitlines()
        symbols = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                sym = parts[2].strip().strip('"')
                if sym and sym.isupper() or "-" in sym or "&" in sym:
                    symbols.append(sym)
        if not symbols:
            return None
        cache_path.write_text(json.dumps(symbols), encoding="utf-8")
        return symbols
    except Exception:
        return None
