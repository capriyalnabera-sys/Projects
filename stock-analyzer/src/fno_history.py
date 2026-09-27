"""F&O snapshot history — the shared foundation for the intraday tracker,
signal-change alerts, and signal backtesting.

While the web app runs, a background loop (web.py) analyzes each tracked index
every few minutes during market hours and appends a compact record here.
Storage, one JSON file per symbol per day:

    data/cache/fno/history/NIFTY_2026-09-26.json
        {"records": [ {ts, as_of, spot, score, bias, ...}, ... ]}

Records are deduped on NSE's own quote timestamp (as_of), so idle weekends or
a stale chain never pile up duplicates. Everything here is pure file I/O +
arithmetic — no network — so it's fully smoke-testable offline.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HISTORY_DIR = Path("data/cache/fno/history")

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_hours(dt: Optional[datetime] = None) -> bool:
    """NSE/BSE cash+derivatives hours, Mon-Fri 09:15-15:35 IST (a few minutes
    past close so the closing snapshot gets recorded). Exchange holidays are
    not modeled — the as_of dedup makes holiday polling harmless."""
    dt = dt or now_ist()
    if dt.weekday() >= 5:
        return False
    minutes = dt.hour * 60 + dt.minute
    return (9 * 60 + 15) <= minutes <= (15 * 60 + 35)


def _day_path(symbol: str, day: str) -> Path:
    return HISTORY_DIR / f"{symbol.upper()}_{day}.json"


def _load_day(symbol: str, day: str) -> list[dict]:
    p = _day_path(symbol, day)
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("records") or []
    except Exception:
        return []


def _to_record(a) -> dict:
    """FnoAnalysis → compact history record."""
    return {
        "ts": now_ist().isoformat(timespec="seconds"),
        "as_of": a.as_of,
        "spot": a.spot,
        "score": a.score,
        "bias": a.bias,
        "confidence": a.confidence,
        "pcr_band": a.pcr_oi_band,
        "pcr_total": a.pcr_oi,
        "max_pain": a.max_pain,
        "atm_iv": a.atm_iv,
        "straddle": a.straddle_price,
        "expected_move_pct": a.expected_move_pct,
        "ce_oi_change": a.ce_oi_change,
        "pe_oi_change": a.pe_oi_change,
        "support": a.supports[0]["strike"] if a.supports else None,
        "resistance": a.resistances[0]["strike"] if a.resistances else None,
        "expiry": a.expiry,
        "dte": a.days_to_expiry,
        "vix": a.vix,
        "oi_flow": a.oi_flow,
    }


def maybe_record(a) -> bool:
    """Append a record for this analysis unless the exchange timestamp is the
    one we already have (market closed / stale chain). Returns True if written."""
    if a is None or a.stale or not a.spot:
        return False
    day = now_ist().strftime("%Y-%m-%d")
    records = _load_day(a.symbol, day)
    if records and a.as_of and records[-1].get("as_of") == a.as_of:
        return False
    records.append(_to_record(a))
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        _day_path(a.symbol, day).write_text(
            json.dumps({"records": records}), encoding="utf-8")
        return True
    except Exception:
        return False


def intraday(symbol: str, day: Optional[str] = None) -> list[dict]:
    """All of today's records for a symbol (oldest first)."""
    return _load_day(symbol, day or now_ist().strftime("%Y-%m-%d"))


def daily_signals(symbol: str, max_days: int = 250) -> list[dict]:
    """One record per historical day — the LAST record of each day, i.e. the
    signal as of close. Powers the backtest. Sorted oldest→newest."""
    out: list[dict] = []
    pat = re.compile(rf"^{re.escape(symbol.upper())}_(\d{{4}}-\d{{2}}-\d{{2}})\.json$")
    if not HISTORY_DIR.exists():
        return out
    days = sorted(m.group(1) for f in HISTORY_DIR.iterdir()
                  if (m := pat.match(f.name)))
    for day in days[-max_days:]:
        recs = _load_day(symbol, day)
        if recs:
            r = dict(recs[-1])
            r["day"] = day
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Intraday shift analysis — what changed since open / since the last check.
# ---------------------------------------------------------------------------

def _fmt_k(v) -> str:
    return f"{v:,.0f}" if v is not None else "—"


def intraday_shifts(records: list[dict]) -> dict:
    """Compare the latest record against the day's first (and previous) one.
    Returns {available, since, latest, changes: [...], series: {...}} where
    changes are human-readable shift readings and series feed sparklines."""
    if len(records) < 2:
        return {"available": False, "count": len(records)}
    first, prev, last = records[0], records[-2], records[-1]
    changes: list[dict] = []

    def add(kind: str, text: str, tone: str = "neutral"):
        changes.append({"kind": kind, "text": text, "tone": tone})

    # PCR drift — writers changing their lean.
    p0, p1 = first.get("pcr_band"), last.get("pcr_band")
    if p0 and p1 and abs(p1 - p0) >= 0.08:
        tone = "pos" if p1 > p0 else "neg"
        add("pcr", f"PCR {p0:.2f} → {p1:.2f} since open — "
            f"{'put writers stepping in (bullish drift)' if p1 > p0 else 'call writers stepping in (bearish drift)'}", tone)

    # Max pain drift — the expiry magnet moving.
    m0, m1 = first.get("max_pain"), last.get("max_pain")
    if m0 and m1 and m1 != m0:
        add("maxpain", f"Max pain moved {_fmt_k(m0)} → {_fmt_k(m1)}",
            "pos" if m1 > m0 else "neg")

    # Wall shifts — the strikes writers defend moving up/down.
    r0, r1 = first.get("resistance"), last.get("resistance")
    if r0 and r1 and r1 != r0:
        add("wall", f"Resistance wall {_fmt_k(r0)} → {_fmt_k(r1)} — "
            f"{'call writers retreating higher (bullish)' if r1 > r0 else 'call writers pressing lower (bearish)'}",
            "pos" if r1 > r0 else "neg")
    s0, s1 = first.get("support"), last.get("support")
    if s0 and s1 and s1 != s0:
        add("wall", f"Support wall {_fmt_k(s0)} → {_fmt_k(s1)} — "
            f"{'put writers stepping up (bullish)' if s1 > s0 else 'put writers backing off lower (bearish)'}",
            "pos" if s1 > s0 else "neg")

    # IV move — fear premium coming in or out.
    v0, v1 = first.get("atm_iv"), last.get("atm_iv")
    if v0 and v1 and abs(v1 - v0) >= 0.5:
        add("iv", f"ATM IV {v0:.1f}% → {v1:.1f}% — "
            f"{'premium sellers in control (calm)' if v1 < v0 else 'vol bid up (event/fear)'}",
            "neutral")

    # Bias flip during the day.
    b0, b1 = first.get("bias"), last.get("bias")
    if b0 and b1 and b0 != b1:
        add("bias", f"Signal flipped {b0} → {b1} intraday",
            "pos" if b1 == "BULLISH" else "neg" if b1 == "BEARISH" else "neutral")

    def series(key) -> list:
        return [r.get(key) for r in records if r.get(key) is not None]

    return {
        "available": True,
        "count": len(records),
        "since": first.get("ts", "")[11:16],
        "latest_ts": last.get("ts", "")[11:16],
        "changes": changes,
        "delta_prev": {
            "spot": (last.get("spot") or 0) - (prev.get("spot") or 0),
            "pcr": round((last.get("pcr_band") or 0) - (prev.get("pcr_band") or 0), 2),
        },
        "series": {
            "spot": series("spot"),
            "pcr": series("pcr_band"),
            "max_pain": series("max_pain"),
            "atm_iv": series("atm_iv"),
        },
        "first": first, "last": last,
    }


def spark_points(values: list, width: int = 120, height: int = 30) -> str:
    """SVG polyline points for a sparkline, with 2px padding top/bottom."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pad = 3
    step = width / (len(vals) - 1)
    pts = []
    for i, v in enumerate(vals):
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        pts.append(f"{i * step:.1f},{y:.1f}")
    return " ".join(pts)
