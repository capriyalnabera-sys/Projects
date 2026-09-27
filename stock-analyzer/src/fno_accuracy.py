"""Backtest of the F&O composite signal — the options-side sibling of the
equity accuracy loop.

Every tracked day leaves one end-of-day signal record in fno_history. This
module joins those records against the index's actual closes afterwards:

  BULLISH / BEARISH  → did the index move in the signal's direction over the
                       next 1 and 3 trading days? (hit rate + avg signed move)
  RANGE-BOUND        → did the index stay inside the expected move (straddle-
                       implied %) between the signal and its expiry?
  NEUTRAL            → no claim, excluded from hit rates (counted separately).

Honest-metrics note: hit rate alone flatters coin-flips, so the average move
*in the signal's direction* is reported alongside — a real edge needs both.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import fno, fno_history

SPOT_CACHE_DIR = Path("data/cache/fno/spot")
SPOT_TTL_SECONDS = 30 * 60


def _spot_closes(symbol: str) -> dict[str, float]:
    """{'YYYY-MM-DD': close} for the index, ~6 months, disk-cached 30 min.
    Empty dict when yfinance is unreachable — evaluation then shows pending."""
    meta = fno.INDEX_META.get(symbol.upper())
    if not meta:
        return {}
    safe = meta["yf"].replace("^", "_").replace(".", "_")
    p = SPOT_CACHE_DIR / f"{safe}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < SPOT_TTL_SECONDS:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    out: dict[str, float] = {}
    try:
        import yfinance as yf
        h = yf.Ticker(meta["yf"]).history(period="6mo", auto_adjust=False)
        if h is not None and not h.empty:
            for ts, close in h["Close"].dropna().items():
                out[ts.strftime("%Y-%m-%d")] = round(float(close), 2)
    except Exception:
        pass
    if out:
        try:
            SPOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out), encoding="utf-8")
        except Exception:
            pass
    else:
        # Serve stale cache rather than nothing.
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return out


def _expiry_day(expiry: str) -> Optional[str]:
    dt = fno.parse_expiry_date(expiry) if expiry else None
    return dt.strftime("%Y-%m-%d") if dt else None


def evaluate(symbol: str, closes: Optional[dict[str, float]] = None) -> dict:
    """Join daily signal records with subsequent closes. `closes` is injectable
    for offline tests."""
    sym = symbol.upper()
    signals = fno_history.daily_signals(sym)
    closes = closes if closes is not None else _spot_closes(sym)
    trading_days = sorted(closes.keys())

    def close_after(day: str, n: int) -> Optional[float]:
        later = [d for d in trading_days if d > day]
        return closes[later[n - 1]] if len(later) >= n else None

    outcomes: list[dict] = []
    dir_hits1 = dir_n1 = dir_hits3 = dir_n3 = 0
    range_hits = range_n = neutral_n = 0
    sum_signed_r1 = 0.0

    for rec in signals:
        day, bias, spot = rec.get("day"), rec.get("bias"), rec.get("spot")
        if not day or not bias or not spot:
            continue
        o = {"day": day, "bias": bias, "spot": spot,
             "score": rec.get("score"), "outcome": "pending", "move_pct": None}

        if bias in ("BULLISH", "BEARISH"):
            sign = 1 if bias == "BULLISH" else -1
            c1, c3 = close_after(day, 1), close_after(day, 3)
            if c1 is not None:
                r1 = (c1 / spot - 1) * 100
                o["move_pct"] = round(r1, 2)
                hit = (r1 * sign) > 0
                o["outcome"] = "hit" if hit else "miss"
                dir_n1 += 1
                dir_hits1 += 1 if hit else 0
                sum_signed_r1 += r1 * sign
            if c3 is not None:
                r3 = (c3 / spot - 1) * 100
                o["move_3d_pct"] = round(r3, 2)
                dir_n3 += 1
                dir_hits3 += 1 if (r3 * sign) > 0 else 0
        elif bias == "RANGE-BOUND":
            exp_day = _expiry_day(rec.get("expiry") or "")
            em = rec.get("expected_move_pct")
            if exp_day and em and trading_days and trading_days[-1] >= exp_day:
                candidates = [d for d in trading_days if d <= exp_day]
                if candidates:
                    r = (closes[candidates[-1]] / spot - 1) * 100
                    o["move_pct"] = round(r, 2)
                    hit = abs(r) <= em
                    o["outcome"] = "hit" if hit else "miss"
                    range_n += 1
                    range_hits += 1 if hit else 0
        else:
            neutral_n += 1
            o["outcome"] = "no claim"
        outcomes.append(o)

    directional = dir_n1 > 0
    return {
        "symbol": sym,
        "days_recorded": len(signals),
        "directional": {
            "n": dir_n1,
            "hit_rate_1d": round(dir_hits1 / dir_n1 * 100, 1) if dir_n1 else None,
            "hit_rate_3d": round(dir_hits3 / dir_n3 * 100, 1) if dir_n3 else None,
            "avg_signed_move_1d_pct": round(sum_signed_r1 / dir_n1, 2) if dir_n1 else None,
        },
        "range": {
            "n": range_n,
            "hit_rate": round(range_hits / range_n * 100, 1) if range_n else None,
        },
        "neutral_days": neutral_n,
        "recent": list(reversed(outcomes[-15:])),
        "has_any_scored": directional or range_n > 0,
    }
