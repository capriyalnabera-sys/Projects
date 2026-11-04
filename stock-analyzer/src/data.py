from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import pandas as pd
import yfinance as yf

from .profiler import timed

if TYPE_CHECKING:
    pass


# Disk cache for yfinance .info dicts — biggest refresh speedup.
# yfinance.info is one HTTP request per ticker (~1-2s); a 30-min cache lets
# subsequent batches skip the call entirely for stocks already seen.
INFO_CACHE_DIR = Path("data/cache/yf_info")
# Name, sector, EPS, book value, debt and growth change with quarterly results;
# the price-based ratios are rescaled to the current price on use (see
# reprice_info), so .info only needs re-fetching every several days. Each
# ticker's TTL is spread over 5-9 days by a stable hash, so ~1/7 of the
# universe refreshes on any given day instead of all ~1,900 at once.
INFO_CACHE_TTL_SECONDS = 9 * 24 * 60 * 60   # upper bound (see _info_ttl)


def _info_ttl(ticker: str) -> int:
    import zlib
    return (5 + zlib.crc32(ticker.upper().encode()) % 5) * 24 * 60 * 60

# Per-ticker history cache (parquet would be smaller but JSON keeps zero deps).
# Used by /api/chart and other live paths to avoid re-fetching the same 2y of
# OHLC repeatedly. 10-min TTL — short enough to pick up today's bar quickly.
HISTORY_CACHE_DIR = Path("data/cache/yf_history")
HISTORY_CACHE_TTL_SECONDS = 10 * 60


def _read_cached_info(ticker: str) -> Optional[dict]:
    p = INFO_CACHE_DIR / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > _info_ttl(ticker):
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if d.get("_empty"):
        return {} if age < INFO_EMPTY_TTL_SECONDS else None
    return d


_PRICE_SCALED = ("trailingPE", "forwardPE", "priceToBook", "marketCap", "enterpriseValue")
_PRICE_INVERSE = ("dividendYield", "trailingAnnualDividendYield")


def _info_price(info: dict) -> Optional[float]:
    return next((float(info.get(k)) for k in ("currentPrice", "regularMarketPrice", "previousClose")
                 if isinstance(info.get(k), (int, float)) and info.get(k) > 0), None)


def _real_move_since_info(ticker: str, info: dict, hist) -> "Optional[float] | str":
    """Price move since the cached .info was fetched, read from the (split-
    adjusted) history — so a split or bonus doesn't look like a 50% crash.
    Returns the ratio, None if unknown, or 'corporate_action' when the info's
    own price disagrees with the history by a split-like factor."""
    p0 = _info_price(info or {})
    try:
        fetched = datetime.fromtimestamp((INFO_CACHE_DIR / f"{ticker.upper()}.json").stat().st_mtime)
        h = hist["Close"].dropna()
        idx = h.index.tz_localize(None) if getattr(h.index, "tz", None) is not None else h.index
        before = h[idx <= pd.Timestamp(fetched)]
        if before.empty:
            return None
        then = float(before.iloc[-1])
        now = float(h.iloc[-1])
    except Exception:
        return None
    if p0 and then > 0:
        gap = p0 / then          # info's price vs the adjusted close on that day
        if gap > 1.35 or gap < 1 / 1.35:
            return "corporate_action"
    return now / then if then > 0 else None


def reprice_info(info: dict, price: Optional[float], move: Optional[float] = None) -> dict:
    """Bring price-dependent .info ratios up to today's price. P/E, P/B and
    market cap scale with price; dividend yield scales inversely. The cached
    .info may be several days old. `move` is the real price change since it
    was fetched (from adjusted history); without it the info's own price is
    compared with today's."""
    if not info or not price:
        return info
    p0 = _info_price(info)
    if not p0:
        return info
    r = move if move else float(price) / float(p0)
    if not 0.2 < r < 5 or abs(r - 1) < 1e-9:
        return info                  # implausible jump (bad data) or nothing to do
    out = dict(info)
    for k in _PRICE_SCALED:
        if isinstance(out.get(k), (int, float)):
            out[k] = out[k] * r
    for k in _PRICE_INVERSE:
        if isinstance(out.get(k), (int, float)):
            out[k] = out[k] / r
    out["currentPrice"] = float(price)
    return out


def fetch_info(ticker: str) -> dict:
    """Yahoo .info for a ticker via the disk cache — one network call per
    ticker per ~day. Used by the batch's parallel prefetch and by fetch()."""
    cached = _read_cached_info(ticker)
    if cached is not None:
        return cached
    try:
        with timed("net: yahoo info"):
            info = yf.Ticker(to_yf_symbol(ticker)).info or {}
    except Exception:
        # Failed or throttled request: don't cache — the next refresh retries.
        # Only a successful answer (even an empty one) is remembered.
        return {}
    _write_cached_info(ticker, info)
    return info


# Yahoo returned nothing for this ticker: remember that for a few hours so a
# refresh doesn't re-ask for every info-less stock (BSE-only names especially).
INFO_EMPTY_TTL_SECONDS = 6 * 60 * 60


def _write_cached_info(ticker: str, info: dict) -> None:
    if not info:
        info = {"_empty": True}
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


def history_strict(yt, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """yt.history() that tells "Yahoo has no data" apart from "the request
    failed". By default yfinance swallows network errors and returns an empty
    frame with a "possibly delisted" log line — indistinguishable from a dead
    symbol. Here a genuine missing-prices answer raises NoPriceHistory and
    anything else (throttling, timeouts, connection drops) propagates as a
    retryable error."""
    import warnings
    try:
        from yfinance.exceptions import YFPricesMissingError, YFTzMissingError
    except Exception:  # very old yfinance: no typed errors to distinguish
        return yt.history(period=period, interval=interval, auto_adjust=False)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return yt.history(period=period, interval=interval, auto_adjust=False,
                              raise_errors=True)
    except TypeError:
        # yfinance without raise_errors: fall back to the lenient call.
        return yt.history(period=period, interval=interval, auto_adjust=False)
    except (YFPricesMissingError, YFTzMissingError) as e:
        msg = str(e)
        # A Yahoo 5xx/429 surfaced as "prices missing" is a failed request,
        # not a dead symbol.
        if "status_code = 5" in msg or "status_code = 429" in msg:
            raise ConnectionError(msg)
        raise NoPriceHistory(msg)


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
        with timed("net: yahoo history (per stock)"):
            hist = history_strict(yt, period=period, interval=interval)
    if hist is None or hist.empty:
        raise NoPriceHistory(f"No price history for {sym}")
    # Drop rows where Close is NaN — yfinance bulk download sometimes returns
    # NaN for the most recent bar on weekends/holidays/before-close. Keeping
    # NaN there poisons last_close, technical indicators, and the JSON cache.
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise NoPriceHistory(f"No valid Close prices for {sym}")

    # Disk cache first — the batch normally warmed it in its parallel prefetch.
    # It may be several days old: rescale its price-based ratios to today.
    last = float(hist["Close"].iloc[-1])
    info = fetch_info(ticker)
    move = _real_move_since_info(ticker, info, hist)
    if move == "corporate_action":
        # Split/bonus since the cached .info: its per-share fields (EPS, book
        # value) are on the old share count. Fetch a fresh copy once.
        try:
            (INFO_CACHE_DIR / f"{ticker.upper()}.json").unlink()
        except Exception:
            pass
        info = fetch_info(ticker)
        move = None
    info = reprice_info(info, last, move=move)

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
        with timed("net: yahoo bulk download"):
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
            # yfinance keeps the (Ticker, Price) MultiIndex even for one symbol.
            if isinstance(df.columns, pd.MultiIndex):
                lv0 = df.columns.get_level_values(0)
                tdf = df[sym] if sym in lv0 else df.xs(sym, axis=1, level=1)
            else:
                tdf = df
            if hasattr(tdf, "dropna"):
                tdf = tdf.dropna(how="all")
            if tdf is not None and not tdf.empty:
                out[t.upper()] = tdf
        except (KeyError, AttributeError):
            continue
    return out
