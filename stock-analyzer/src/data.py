from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import pandas as pd
import yfinance as yf

if TYPE_CHECKING:
    pass


# Disk cache for yfinance .info dicts — biggest refresh speedup.
# yfinance.info is one HTTP request per ticker (~1-2s); a 30-min cache lets
# subsequent batches skip the call entirely for stocks already seen.
INFO_CACHE_DIR = Path("data/cache/yf_info")
# Fundamentals / name / sector change slowly and price comes from the history
# fetch, so one .info call per ticker per day is enough. A 30-min TTL made
# every refresh re-pay ~1.5s × ~1,900 tickers.
INFO_CACHE_TTL_SECONDS = 20 * 60 * 60

# Per-ticker history cache (parquet would be smaller but JSON keeps zero deps).
# Used by /api/chart and other live paths to avoid re-fetching the same 2y of
# OHLC repeatedly. 10-min TTL — short enough to pick up today's bar quickly.
HISTORY_CACHE_DIR = Path("data/cache/yf_history")
HISTORY_CACHE_TTL_SECONDS = 10 * 60


def _read_cached_info(ticker: str) -> Optional[dict]:
    p = INFO_CACHE_DIR / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    if (time.time() - p.stat().st_mtime) > INFO_CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cached_info(ticker: str, info: dict) -> None:
    if not info:
        return
    try:
        INFO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (INFO_CACHE_DIR / f"{ticker.upper()}.json").write_text(
            json.dumps(info, default=str), encoding="utf-8"
        )
    except Exception:
        pass


def read_cached_history(ticker: str, period_key: str = "2y") -> Optional[pd.DataFrame]:
    """Read cached price history for a ticker if fresh. Returns None on miss/stale."""
    p = HISTORY_CACHE_DIR / f"{ticker.upper()}_{period_key}.csv"
    if not p.exists():
        return None
    if (time.time() - p.stat().st_mtime) > HISTORY_CACHE_TTL_SECONDS:
        return None
    try:
        df = pd.read_csv(p, parse_dates=["Date"], index_col="Date")
        return df if not df.empty else None
    except Exception:
        return None


def write_cached_history(ticker: str, df: pd.DataFrame, period_key: str = "2y") -> None:
    if df is None or df.empty:
        return
    try:
        HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = HISTORY_CACHE_DIR / f"{ticker.upper()}_{period_key}.csv"
        df.to_csv(p, index_label="Date")
    except Exception:
        pass


# Companies that have rebranded or renamed their NSE listing — yfinance still
# uses the old symbol or doesn't track the new one. We remap on input.
TICKER_ALIASES = {
    "ZOMATO": "ETERNAL",  # Zomato Ltd renamed parent to Eternal Limited
}


def to_yf_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    t = TICKER_ALIASES.get(t, t)
    if "." in t:
        return t
    return f"{t}.NS"


class NoPriceHistory(ValueError):
    """Yahoo has no price history for this symbol (delisted, suspended, dead
    BSE shell). Permanent until proven otherwise — batch runs record these
    and skip them for a week instead of retrying them every sweep."""


@dataclass
class StockData:
    ticker: str
    yf_symbol: str
    name: str
    sector: Optional[str]
    industry: Optional[str]
    currency: str
    history: pd.DataFrame
    info: dict

    @property
    def last_close(self) -> float:
        return float(self.history["Close"].iloc[-1])


def fetch(
    ticker: str,
    period: str = "2y",
    interval: str = "1d",
    prefetched_history: Optional[pd.DataFrame] = None,
) -> StockData:
    """Fetch full StockData for a ticker. If prefetched_history is supplied
    (from a bulk yf.download call) we skip the per-ticker history HTTP roundtrip
    and only do the .info call — typically 5-10× faster for batch use."""
    sym = to_yf_symbol(ticker)
    yt = yf.Ticker(sym)

    if prefetched_history is not None and not prefetched_history.empty:
        hist = prefetched_history
    else:
        hist = yt.history(period=period, interval=interval, auto_adjust=False)
    if hist is None or hist.empty:
        raise NoPriceHistory(f"No price history for {sym}")
    # Drop rows where Close is NaN — yfinance bulk download sometimes returns
    # NaN for the most recent bar on weekends/holidays/before-close. Keeping
    # NaN there poisons last_close, technical indicators, and the JSON cache.
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise NoPriceHistory(f"No valid Close prices for {sym}")

    # Try the disk cache first — saves the slowest part of fetch (~1-2s per call).
    info = _read_cached_info(ticker) or {}
    if not info:
        try:
            info = yt.info or {}
            if info:
                _write_cached_info(ticker, info)
        except Exception:
            info = {}

    return StockData(
        ticker=ticker.upper(),
        yf_symbol=sym,
        name=info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector"),
        industry=info.get("industry"),
        currency=info.get("currency", "INR"),
        history=hist,
        info=info,
    )


# yfinance chokes on very large symbol lists in one call (URL length / timeout /
# partial failures that nuke the whole response). Chunk big universes.
BULK_CHUNK_SIZE = 100


def bulk_fetch_histories(tickers: list[str], period: str = "2y") -> dict[str, "pd.DataFrame"]:
    """Fetch many tickers' histories via yf.download, automatically chunked so
    large universes (e.g. ~5,500 NSE+BSE names) don't overflow a single call.
    Returns {TICKER: history_df}; tickers absent from the response are skipped.
    """
    if not tickers:
        return {}
    out = _bulk_fetch_all(tickers, period)
    # Second pass for names a throttled/failed chunk dropped. Yahoo rate-limits
    # big sweeps; without this every dropped name fell back to a slow
    # one-at-a-time fetch in the batch. Truly dead symbols just miss again —
    # cheap, since it's still a bulk call.
    missing = [t for t in tickers if t.upper() not in out]
    if missing and len(missing) < len(tickers):
        time.sleep(5)
        out.update(_bulk_fetch_all(missing, period))
    return out


def _bulk_fetch_all(tickers: list[str], period: str) -> dict[str, "pd.DataFrame"]:
    out: dict[str, "pd.DataFrame"] = {}
    for i in range(0, len(tickers), BULK_CHUNK_SIZE):
        chunk = tickers[i:i + BULK_CHUNK_SIZE]
        try:
            got = _bulk_fetch_chunk(chunk, period)
            if not got and len(chunk) > 1:
                # Whole chunk empty = throttled or timed out, not "all dead".
                time.sleep(3)
                got = _bulk_fetch_chunk(chunk, period)
            out.update(got)
        except Exception:
            # One bad chunk shouldn't sink the rest of the universe.
            continue
    return out


def _bulk_fetch_chunk(tickers: list[str], period: str) -> dict[str, "pd.DataFrame"]:
    """One yf.download call for up to BULK_CHUNK_SIZE tickers."""
    if not tickers:
        return {}
    yf_symbols = [to_yf_symbol(t) for t in tickers]
    try:
        df = yf.download(
            yf_symbols,
            period=period,
            group_by="ticker",
            progress=False,
            auto_adjust=False,
            threads=True,
            timeout=60,  # max 60s for this chunk
        )
    except Exception:
        return {}
    out: dict[str, "pd.DataFrame"] = {}
    for t in tickers:
        sym = to_yf_symbol(t)
        try:
            tdf = df[sym] if len(yf_symbols) > 1 else df
            if hasattr(tdf, "dropna"):
                tdf = tdf.dropna(how="all")
            if tdf is not None and not tdf.empty:
                out[t.upper()] = tdf
        except (KeyError, AttributeError):
            continue
    return out
