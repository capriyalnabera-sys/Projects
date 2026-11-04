"""Market-cap filter for the ALL UNIVERSE list.

Market cap = shares outstanding × latest exchange closing price. Share counts
barely move, so each stock's count is fetched once from Yahoo (.info) and
reused for SHARES_TTL_DAYS; the price comes from the daily NSE/BSE files, so
the market cap stays current with no daily network calls.

Registry: data/cache/universe/_mcap.json
    {TICKER: {"shares": float|null, "checked": "YYYY-MM-DD"}}
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable, Optional

DEFAULT_MIN_CR = 500.0
SHARES_TTL_DAYS = 30
UNKNOWN_RECHECK_DAYS = 7
CRORE = 1e7


def min_cap_cr(cfg: Optional[dict]) -> float:
    try:
        return float(((cfg or {}).get("universe") or {}).get("min_market_cap_cr", DEFAULT_MIN_CR))
    except Exception:
        return DEFAULT_MIN_CR


def _path(cache_root: Path) -> Path:
    d = cache_root / "universe"
    d.mkdir(parents=True, exist_ok=True)
    return d / "_mcap.json"


def load(cache_root: Path) -> dict:
    p = _path(cache_root)
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(cache_root: Path, reg: dict) -> None:
    p = _path(cache_root)
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def shares_from_info(info: dict, close: Optional[float] = None) -> Optional[float]:
    if not info:
        return None
    for k in ("sharesOutstanding", "impliedSharesOutstanding"):
        v = info.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    mc = info.get("marketCap")
    px = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or close
    if isinstance(mc, (int, float)) and mc > 0 and isinstance(px, (int, float)) and px > 0:
        return float(mc) / float(px)
    return None


def _age_days(iso: Optional[str]) -> int:
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except Exception:
        return 10 ** 6


def _needs_check(entry: Optional[dict]) -> bool:
    if not entry:
        return True
    ttl = SHARES_TTL_DAYS if entry.get("shares") else UNKNOWN_RECHECK_DAYS
    return _age_days(entry.get("checked")) >= ttl


def _seed(tickers: list[str], reg: dict, closes: dict[str, float], cache_root: Path) -> int:
    """Fill share counts already on disk (past analyses, Yahoo info cache) —
    no network. Returns how many were filled."""
    from . import batch, data
    today = date.today().isoformat()
    n = 0
    for t in tickers:
        tk = t.upper()
        if not _needs_check(reg.get(tk)):
            continue
        shares = None
        try:
            p = data.INFO_CACHE_DIR / f"{tk}.json"
            if p.exists():
                shares = shares_from_info(json.loads(p.read_text(encoding="utf-8")), closes.get(tk))
        except Exception:
            shares = None
        if shares is None:
            r = batch.read_result(tk, cache_root) or {}
            mc, px = r.get("market_cap_cr"), r.get("last_close")
            if mc and px:
                shares = float(mc) * CRORE / float(px)
        if shares:
            reg[tk] = {"shares": shares, "checked": today}
            n += 1
    return n


def update(tickers: list[str], closes: dict[str, float], cache_root: Path,
           workers: int = 8, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Make sure every ticker has a recent share count. Returns the registry.
    Network: one Yahoo .info call per ticker not seen in SHARES_TTL_DAYS (the
    answer is also cached for the analysis that follows)."""
    from . import data
    reg = load(cache_root)
    _seed(tickers, reg, closes, cache_root)
    todo = [t.upper() for t in tickers if _needs_check(reg.get(t.upper()))]
    if todo:
        today = date.today().isoformat()
        lock = threading.Lock()
        done = {"n": 0}

        def one(tk: str) -> None:
            info = data.fetch_info(tk)
            shares = shares_from_info(info, closes.get(tk))
            # fetch_info caches only real answers (an empty one included), so a
            # cache file means Yahoo answered; none means a failed/throttled
            # request, which is retried next time rather than recorded.
            answered = bool(info) or (data.INFO_CACHE_DIR / f"{tk}.json").exists()
            with lock:
                if shares or answered:
                    reg[tk] = {"shares": shares, "checked": today}
                done["n"] += 1
                if progress and (done["n"] % 50 == 0 or done["n"] == len(todo)):
                    progress(done["n"], len(todo))

        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, todo))
        save(cache_root, reg)
    elif tickers:
        save(cache_root, reg)
    return reg


def market_cap_cr(ticker: str, reg: dict, closes: dict[str, float]) -> Optional[float]:
    e = reg.get(ticker.upper()) or {}
    px = closes.get(ticker.upper())
    if e.get("shares") and px:
        return e["shares"] * px / CRORE
    return None


def eligible(tickers: list[str], reg: dict, closes: dict[str, float],
             min_cr: float = DEFAULT_MIN_CR, always: Optional[set] = None) -> tuple[list[str], dict]:
    """Tickers with market cap ≥ min_cr (plus `always`, e.g. index members).
    Unknown market cap → left out (rechecked weekly)."""
    always = {a.upper() for a in (always or set())}
    keep, below, unknown = [], 0, 0
    for t in tickers:
        tk = t.upper()
        if tk in always:
            keep.append(t)
            continue
        mc = market_cap_cr(tk, reg, closes)
        if mc is None:
            unknown += 1
        elif mc >= min_cr:
            keep.append(t)
        else:
            below += 1
    return keep, {"listed": len(tickers), "eligible": len(keep), "below_min": below,
                  "unknown": unknown, "min_cr": min_cr}
