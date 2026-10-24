"""Opportunities — named setup scanners over the cached analysis rows.

Six scanners, each a specific recognizable setup with machine-checkable
criteria (designed by a trend-trader / value-investor / risk-manager panel and
merged by a judge), plus a composite 0-100 opportunity score that weights
verdict, conviction, risk:reward, liquidity, setup strength, market regime and
the model's own per-stock track record.

Pure computation over row dicts — no network — so it's fully testable offline.
Every scanner carries an honest caution the page must show: this is decision
support, not a tip sheet. An empty scanner is information, not a bug.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None


def _verdict(row: dict) -> Optional[str]:
    return row.get("verdict") or row.get("raw_verdict")


def _rr(row: dict) -> Optional[float]:
    """Risk:reward from the model's own target/stop. None when either side is
    missing — callers decide whether that's a skip or a flag."""
    up, down = _f(row, "upside_pct"), _f(row, "downside_pct")
    if up is None or down is None:
        return None
    return round(max(up, 0.0) / max(abs(down), 0.5), 2)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class _Check:
    """Collects pass/fail + human-readable 'why it qualified' chips + flags."""

    def __init__(self, row: dict):
        self.row = row
        self.reasons: list[str] = []
        self.flags: list[str] = []
        self.ok = True

    def require(self, cond: bool, chip: Optional[str] = None) -> "_Check":
        if not self.ok:
            return self
        if not cond:
            self.ok = False
        elif chip:
            self.reasons.append(chip)
        return self

    def flag(self, text: str) -> "_Check":
        if text not in self.flags:
            self.flags.append(text)
        return self


# ---------------------------------------------------------------------------
# Scanners. Each returns (passes, reasons, flags, rank_value) — rank_value
# sorts candidates within the scanner, higher = better.
# ---------------------------------------------------------------------------

def _scan_breakout(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Fresh Highs, Fresh Money — 52w-high breakout on volume, full trend."""
    c = _Check(row)
    liq, mcap = _f(row, "avg_daily_value_cr"), _f(row, "market_cap_cr")
    close, hi = _f(row, "last_close"), _f(row, "high_52w")
    vol, s50, s200 = _f(row, "volume_ratio"), _f(row, "sma_50"), _f(row, "sma_200")
    rsi, day = _f(row, "rsi_14"), _f(row, "day_change_pct")
    v = _verdict(row)
    rr = _rr(row)

    hi_frac = 0.985 if state == "risk_off" else 0.97
    vol_min = 2.0 if state == "risk_off" else 1.5
    rr_min = 2.0 if state == "risk_off" else 1.5
    rsi_hi = 82 if state == "risk_on" else 78
    verdicts = {"BUY", "ACCUMULATE", "HOLD"} if state == "risk_on" else {"BUY", "ACCUMULATE"}

    c.require(liq is not None and liq >= 15)
    c.require(mcap is not None and mcap >= 1000)
    c.require(close is not None and hi is not None and close >= hi_frac * hi,
              f"{(close / hi - 1) * 100:+.1f}% from 52w high" if close and hi else None)
    c.require(vol is not None and vol >= vol_min, f"volume {vol:.1f}× avg" if vol else None)
    c.require(s200 is not None and close is not None and close > s200, "above 200-DMA")
    c.require(s50 is not None and close is not None and close > s50)
    if rsi is not None:
        c.require(55 <= rsi <= rsi_hi, f"RSI {rsi:.0f} in momentum zone")
    if day is not None:
        c.require(day <= 9)
    c.require(v in verdicts, f"verdict {v}")
    c.require(rr is not None and rr >= rr_min, f"R:R {rr:.1f} ≥ {rr_min:.1f}" if rr else None)

    rank = 0.0
    if c.ok and vol is not None and hi and close:
        rank = vol * (1 - 10 * (hi - close) / hi) + (_f(row, "return_30d_pct") or 0) / 1000
    return c.ok, c.reasons, c.flags, rank


def _scan_pullback(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Leader Pullback — uptrend leader resting at a rising 50-DMA, RSI reset."""
    c = _Check(row)
    close, s50, s200 = _f(row, "last_close"), _f(row, "sma_50"), _f(row, "sma_200")
    hi, rsi = _f(row, "high_52w"), _f(row, "rsi_14")
    r30, vol, day = _f(row, "return_30d_pct"), _f(row, "volume_ratio"), _f(row, "day_change_pct")
    liq, cs = _f(row, "avg_daily_value_cr"), _f(row, "combined_score")
    v, rr, down = _verdict(row), _rr(row), _f(row, "downside_pct")

    band_lo, band_hi = (0.97, 1.05) if state == "risk_on" else (0.98, 1.04)
    rsi_lo = 32 if state == "risk_on" else (40 if state == "risk_off" else 35)
    rr_min = 3.0 if state == "risk_off" else 2.0
    stop_max = 6.0 if state == "risk_off" else 8.0

    c.require(liq is not None and liq >= 10)
    c.require(s50 is not None and s200 is not None and close is not None
              and s50 > s200 and close > s200, "uptrend intact (50>200 DMA)")
    c.require(close is not None and s50 is not None and band_lo * s50 <= close <= band_hi * s50,
              f"sitting at 50-DMA ({(close / s50 - 1) * 100:+.1f}%)" if close and s50 else None)
    c.require(hi is not None and close is not None and close >= 0.80 * hi)
    c.require(rsi is not None and rsi_lo <= rsi <= 50, f"RSI reset to {rsi:.0f}" if rsi else None)
    c.require(r30 is not None and r30 > -12)
    if vol is not None:
        c.require(vol <= 1.5, "quiet pullback, no distribution")
    if day is not None:
        c.require(day > -4.5)
    c.require(v in ("BUY", "ACCUMULATE"), f"verdict {v}")
    c.require(rr is not None and down is not None and rr >= rr_min and abs(down) <= stop_max,
              f"R:R {rr:.1f}, stop {abs(down):.1f}% away" if rr and down else None)
    if state == "risk_off":
        c.require(cs is not None and cs >= 1)
    c.flag("Watch until bounce confirms")

    rank = (rr or 0) + (cs or 0) / 100 + (liq or 0) / 100000
    return c.ok, c.reasons, c.flags, rank if c.ok else 0.0


def _scan_washout(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Quality Washout — oversold high-ROCE, low-debt compounders."""
    c = _Check(row)
    liq, mcap, rsi = _f(row, "avg_daily_value_cr"), _f(row, "market_cap_cr"), _f(row, "rsi_14")
    roe, roce, de = _f(row, "roe"), _f(row, "roce"), _f(row, "debt_to_equity")
    fs, pm, eg = _f(row, "fundamental_score"), _f(row, "profit_margin"), _f(row, "earnings_growth")
    r30, close = _f(row, "return_30d_pct"), _f(row, "last_close")
    hi, lo, day = _f(row, "high_52w"), _f(row, "low_52w"), _f(row, "day_change_pct")
    dy, vol = _f(row, "dividend_yield"), _f(row, "volume_ratio")
    v, raw, rr = row.get("verdict"), row.get("raw_verdict"), _rr(row)

    # roe/roce are stored as fractions (0.15 = 15%) in yfinance-derived rows.
    quality = max((roe or 0) * 100, (roce or 0) * 100)
    rsi_hi = 35 if state == "risk_off" else (28 if state == "risk_on" else 32)
    de_max = 0.4 if state == "risk_off" else 0.5
    mcap_min = 5000 if state == "risk_off" else 2000
    rr_min = 2.5 if state == "risk_off" else 2.0

    c.require(liq is not None and liq >= 10)
    c.require(mcap is not None and mcap >= mcap_min)
    c.require(rsi is not None and 20 <= rsi <= rsi_hi, f"oversold RSI {rsi:.0f}" if rsi else None)
    c.require((roe is not None or roce is not None) and quality >= 15,
              f"quality: ROE/ROCE {quality:.0f}%")
    c.require(de is not None and de <= de_max, f"low debt (D/E {de:.2f})" if de is not None else None)
    c.require(fs is not None and fs >= 1)
    c.require(pm is not None and pm > 0)
    if eg is not None:
        c.require(eg >= -0.15)
    else:
        c.flag("earnings trend unverified")
    c.require(r30 is not None and r30 <= -10, f"{r30:.0f}% in 30d — stress, not collapse" if r30 else None)
    c.require(hi is not None and close is not None and 0.70 * hi <= close <= 0.85 * hi)
    if lo is not None and close is not None:
        c.require(close >= 1.05 * lo)
    if day is not None:
        c.require(day > -5)
    c.require(v in ("BUY", "ACCUMULATE", "HOLD") and raw not in ("REDUCE", "AVOID"), f"verdict {v}")
    c.require(rr is not None and rr >= rr_min, f"R:R {rr:.1f}" if rr else None)
    if state == "risk_off":
        c.require(dy is not None and (dy * 100 if dy < 1 else dy) >= 1)
    if c.ok and vol is not None and vol >= 2.0:
        c.flag("Capitulation climax — panic volume")
    c.flag("Watch until stabilization")

    rank = 0.0
    if c.ok and rsi is not None:
        rank = min(quality, 40) + (32 - rsi) * 1.5 + min(abs(r30 or 0), 30) * 0.5 + (vol or 0) / 100
    return c.ok, c.reasons, c.flags, rank


def _scan_compounder(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Forgotten Compounder — neglected growth at a fair price."""
    c = _Check(row)
    liq, mcap = _f(row, "avg_daily_value_cr"), _f(row, "market_cap_cr")
    tg = _f(row, "tg_mentions") or 0
    rg, eg = _f(row, "revenue_growth"), _f(row, "earnings_growth")
    roe, roce, de = _f(row, "roe"), _f(row, "roce"), _f(row, "debt_to_equity")
    pe = _f(row, "trailing_pe")
    fpe = _f(row, "forward_pe")
    rsi, up = _f(row, "rsi_14"), _f(row, "upside_pct")
    close, s200 = _f(row, "last_close"), _f(row, "sma_200")
    v, rr = _verdict(row), _rr(row)

    # growth fields are fractions (0.12 = 12%)
    rg_pct = rg * 100 if rg is not None else None
    eg_pct = eg * 100 if eg is not None else None
    quality = (roce or roe or 0) * 100
    liq_min = 8 if state == "risk_off" else 5
    mcap_min = 3000 if state == "risk_off" else 1000
    tg_max = 2 if state == "risk_on" else 1
    up_min = 12 if state == "risk_on" else 15

    c.require(liq is not None and liq >= liq_min)
    c.require(tg <= tg_max, "under the radar (no research buzz)")
    c.require(rg_pct is not None and eg_pct is not None and rg_pct >= 10 and eg_pct >= 10,
              f"growing: rev {rg_pct:.0f}%, earnings {eg_pct:.0f}%"
              if rg_pct is not None and eg_pct is not None else None)
    c.require((roce is not None or roe is not None) and quality >= 18, f"ROCE/ROE {quality:.0f}%")
    c.require(de is not None and de <= 0.5)
    use_pe = pe if (pe is not None and pe > 0) else fpe
    c.require(use_pe is not None and 0 < use_pe <= 30
              and (eg_pct is not None and eg_pct > 0 and use_pe / eg_pct <= 1.8),
              f"PE {use_pe:.0f} vs growth (PEG-sane)" if use_pe else None)
    c.require(mcap is not None and mcap_min <= mcap <= 50000)
    if rsi is not None:
        c.require(35 <= rsi <= 60)
    c.require(up is not None and up >= up_min, f"{up:.0f}% model upside" if up else None)
    if s200 is not None and close is not None:
        c.require(close >= s200)
    c.require(v in ("BUY", "ACCUMULATE"), f"verdict {v}")
    if rr is not None:
        c.require(rr >= 1.8)
    else:
        c.flag("no RR — position setup, size accordingly")

    rank = 0.0
    if c.ok:
        rank = (min(quality, 40) + min(eg_pct or 0, 40) * 0.5 + min(rg_pct or 0, 40) * 0.5
                - min(use_pe or 30, 30) * 0.5 + (up or 0) * 0.3)
    return c.ok, c.reasons, c.flags, rank


def _scan_yield(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Paid to Wait — defensive yield + value, capital-preservation sleeve."""
    c = _Check(row)
    liq, dy = _f(row, "avg_daily_value_cr"), _f(row, "dividend_yield")
    pe, fpe, pb = _f(row, "trailing_pe"), _f(row, "forward_pe"), _f(row, "price_to_book")
    roe, roce, de = _f(row, "roe"), _f(row, "roce"), _f(row, "debt_to_equity")
    pm, eg = _f(row, "profit_margin"), _f(row, "earnings_growth")
    close, s200, lo, hi = (_f(row, "last_close"), _f(row, "sma_200"),
                           _f(row, "low_52w"), _f(row, "high_52w"))
    rsi, up = _f(row, "rsi_14"), _f(row, "upside_pct")
    v, rr, down = _verdict(row), _rr(row), _f(row, "downside_pct")

    dy_pct = dy * 100 if (dy is not None and dy < 1) else dy  # tolerate fraction or pct
    quality = (roce or roe or 0) * 100
    dy_min = 2.0 if state == "risk_off" else (3.0 if state == "risk_on" else 2.5)

    c.require(liq is not None and liq >= 8)
    c.require(dy_pct is not None and dy_pct >= dy_min, f"{dy_pct:.1f}% dividend yield" if dy_pct else None)
    use_pe, pe_cap = (pe, 20.0) if (pe is not None and pe > 0) else (fpe, 18.0)
    c.require(use_pe is not None and 0 < use_pe <= pe_cap, f"PE {use_pe:.0f}" if use_pe else None)
    if pb is not None:
        c.require(pb <= 3.0)
    else:
        c.flag("no P/B")
    c.require((roce is not None or roe is not None) and quality >= 15)
    c.require(de is not None and de <= 0.5, "low debt")
    c.require(pm is not None and pm > 0.05)
    if eg is None:
        c.flag("dividend-cut risk unverified")
    else:
        c.require(eg >= -0.05)
    if s200 is not None and close is not None:
        c.require(close >= 0.95 * s200, "not in freefall")
    elif lo is not None and close is not None:
        c.require(close >= 1.10 * lo, "not in freefall")
    else:
        c.require(False)
    if hi is not None and close is not None:
        c.require(close <= 0.90 * hi, "bought marked down, not at highs")
    if rsi is not None:
        c.require(rsi <= 55)
    c.require(v in ("BUY", "ACCUMULATE", "HOLD"), f"verdict {v}")
    if state == "risk_on":
        c.require(up is not None and up >= 15)
    if rr is not None and down is not None:
        c.require(abs(down) <= 8 and rr >= 1.5)
    else:
        c.flag("no defined stop")

    rank = 0.0
    if c.ok and dy_pct is not None:
        rank = dy_pct + (100 / use_pe if use_pe else 0) + quality / 1000
    return c.ok, c.reasons, c.flags, rank


def _scan_buzz(row: dict, state: str) -> tuple[bool, list, list, float]:
    """Quiet Accumulation — research buzz on a flat price, model agrees."""
    c = _Check(row)
    liq, mcap = _f(row, "avg_daily_value_cr"), _f(row, "market_cap_cr")
    tg, sent, tgs = _f(row, "tg_mentions") or 0, _f(row, "tg_avg_sentiment"), _f(row, "telegram_score")
    r30, cs, fs = _f(row, "return_30d_pct"), _f(row, "combined_score"), _f(row, "fundamental_score")
    close, s50, s200, rsi = (_f(row, "last_close"), _f(row, "sma_50"),
                             _f(row, "sma_200"), _f(row, "rsi_14"))
    v, rr = _verdict(row), _rr(row)
    tr = row.get("track_record") or {}

    mcap_min = 5000 if state == "risk_off" else 2000
    cs_min = 1.5 if state in ("risk_off", "neutral") else 1.0
    verdicts = {"BUY"} if state == "risk_off" else {"BUY", "ACCUMULATE"}

    c.require(liq is not None and liq >= 10)
    c.require(mcap is not None and mcap >= mcap_min)
    c.require(tg >= 3, f"{tg:.0f} research mentions this week")
    c.require(sent is not None and tgs is not None and sent >= 0.4 and tgs >= 1,
              f"warm sentiment ({sent:+.1f})" if sent is not None else None)
    c.require(r30 is not None and -8 <= r30 <= 8, "price hasn't moved yet")
    c.require(v in verdicts and cs is not None and cs >= cs_min, f"model agrees ({v}, {cs:+.1f})" if cs else None)
    c.require(fs is not None and fs >= 0)
    ma = s50 if s50 is not None else s200
    c.require(ma is not None and close is not None and close > ma)
    if rsi is not None:
        c.require(rsi <= 72)
    hit = tr.get("hit_rate") if isinstance(tr, dict) else None
    n = tr.get("n") if isinstance(tr, dict) else None
    if hit is not None and n is not None and n >= 5:
        c.require(hit >= 0.5)
    c.require(rr is not None and rr >= 2.0, f"R:R {rr:.1f}" if rr else None)

    rank = tg * max(sent or 0, 0) + (rr or 0) / 100 if c.ok else 0.0
    return c.ok, c.reasons, c.flags, rank


SCANNERS: list[dict] = [
    {"id": "fresh_highs_breakout", "title": "Fresh Highs, Fresh Money", "icon": "rocket",
     "group": "Act",
     "pitch": "52-week-high breakouts on confirmed volume with full trend alignment — no overhead supply, winners keep winning.",
     "caution": "Breakouts fail over half the time even in good tape — the edge is the payoff ratio, not the hit rate. Entries are T+1 off daily closes; a failed breakout reverses fast, so the stop at the breakout level is non-negotiable.",
     "fn": _scan_breakout, "cap": {"risk_off": 3, "default": 10}},
    {"id": "leader_pullback", "title": "Leader Pullback", "icon": "trending-down",
     "group": "Watch",
     "pitch": "Uptrend leaders resting quietly at their rising 50-DMA with RSI reset — buying weakness in strength with a tight, logical stop.",
     "caution": "A pullback and the start of a top look identical on day one. This finds the zone, not the trigger — wait for an up-day to confirm the bounce, and a close 2-3% below the 50-DMA invalidates the setup.",
     "fn": _scan_pullback, "cap": {"default": 10}},
    {"id": "quality_washout", "title": "Quality Washout", "icon": "life-buoy",
     "group": "Watch",
     "pitch": "High-ROCE, low-debt businesses knocked 15-30% off their highs into oversold RSI — quality on sale, fundamentals as the floor.",
     "caution": "RSI 32 can become RSI 18, and oversold quality is where governance surprises live — nothing in these fields sees pledges, auditors or fraud. Half-size positions, never average below the stop, and clustered same-sector hits are one bet, not five.",
     "fn": _scan_washout, "cap": {"default": 10}},
    {"id": "forgotten_compounder", "title": "Forgotten Compounder", "icon": "gem",
     "group": "Hold sleeve",
     "pitch": "Mid-caps compounding 10%+ revenue and earnings at 18%+ ROCE, PEG-sane, with model upside and near-zero research chatter — bought before the crowd arrives.",
     "caution": "Trailing growth can be one base-effect year, and Indian mid-cap numbers are the least reliable in the market. Low chatter can also mean informed investors looked and passed. Size smaller; neglect can persist for years.",
     "fn": _scan_compounder, "cap": {"default": 10}},
    {"id": "paid_to_wait", "title": "Paid to Wait", "icon": "piggy-bank",
     "group": "Hold sleeve",
     "pitch": "Cheap, self-funded, cash-returning businesses (2.5%+ yield, sub-20× earnings, low debt) not in freefall — yield while waiting for rerating.",
     "caution": "Value traps pay dividends too — right up until they cut them. Trailing yield is last year's payout, and the fattest yields sit one board meeting from a cut. The real risk here is opportunity cost, which no field can see.",
     "fn": _scan_yield, "cap": {"risk_off": 15, "default": 10}},
    {"id": "quiet_accumulation", "title": "Quiet Accumulation", "icon": "radio",
     "group": "Act",
     "pitch": "Names research groups are actively, positively discussing while price hasn't moved — and the model independently agrees.",
     "caution": "The scanner most exposed to manipulation: coordinated Telegram promotion is endemic in Indian mid-caps, and sentiment can't tell conviction from a paid campaign. The market-cap, fundamental and technical gates are the only thing separating this from a tip sheet.",
     "fn": _scan_buzz, "cap": {"risk_off": 5, "default": 10}},
]

_PROCYCLICAL = {"fresh_highs_breakout", "quiet_accumulation", "leader_pullback"}
_DEFENSIVE = {"quality_washout", "paid_to_wait"}

# Card order per regime — the page teaches regime fit by what it leads with.
_ORDER = {
    "risk_off": ["quality_washout", "paid_to_wait", "forgotten_compounder",
                 "leader_pullback", "quiet_accumulation", "fresh_highs_breakout"],
    "risk_on": ["fresh_highs_breakout", "leader_pullback", "quiet_accumulation",
                "forgotten_compounder", "quality_washout", "paid_to_wait"],
}

_CONTEXT_NOTES = {
    "risk_off": ("Risk-off: Quality Washout and Paid to Wait lead; breakout and "
                 "buzz setups are tightened and capped — shorter lists are the point."),
    "risk_on": ("Risk-on: breakout and pullback setups lead with relaxed bands; "
                "defensive sleeves are tightened so they don't fill the page with dead money."),
    "neutral": "Neutral regime: default thresholds everywhere; let the setups speak.",
}


def _band(score: int) -> str:
    if score >= 75:
        return "Prime"
    if score >= 60:
        return "Strong"
    if score >= 45:
        return "Decent"
    return "Marginal"


def _opportunity_score(row: dict, matched: list[str], best_pct: float,
                       state: str) -> tuple[int, Optional[str]]:
    """Composite 0-100 per the judge's spec. Returns (score, flag)."""
    v = _verdict(row)
    if v in ("REDUCE", "AVOID"):
        return 0, None
    verdict_pts = {"BUY": 20, "ACCUMULATE": 14, "HOLD": 6}.get(v or "", 0)

    cs = _f(row, "combined_score")
    if cs is None:
        parts = [x for x in (_f(row, "technical_score"), _f(row, "fundamental_score")) if x is not None]
        cs = sum(parts) / len(parts) if parts else None
    conviction = (clamp(cs, -3, 3) + 3) / 6 * 20 if cs is not None else 8.0

    rr, flag = _rr(row), None
    if rr is not None:
        rr_pts = min(rr, 4) / 4 * 25
    else:
        rr_pts, flag = 8.0, "no defined stop"

    liq = _f(row, "avg_daily_value_cr") or 0
    liq_pts = min(liq, 50) / 50 * 10

    base = {1: 8, 2: 14}.get(len(matched), 17)
    setup_pts = base + 8 * clamp(best_pct, 0, 1)

    if state == "risk_off":
        mult = 0.85 if all(m in _PROCYCLICAL for m in matched) else (
            1.10 if any(m in _DEFENSIVE for m in matched) else 1.0)
    elif state == "risk_on":
        mult = 1.05 if any(m in ("fresh_highs_breakout", "leader_pullback") for m in matched) else (
            0.90 if matched and all(m in _DEFENSIVE for m in matched) else 1.0)
    else:
        mult = 1.0

    tr = row.get("track_record") or {}
    hit, n = (tr.get("hit_rate"), tr.get("n")) if isinstance(tr, dict) else (None, None)
    track_mult = 0.90 if (hit is not None and n is not None and n >= 5 and hit < 0.40) else 1.0

    score = int(round(clamp((verdict_pts + conviction + rr_pts + liq_pts + setup_pts)
                            * mult * track_mult, 0, 100)))
    return score, flag


def nifty_fno_bias() -> Optional[str]:
    """Last tracked NIFTY options bias — from the F&O tracker's state file, so
    no network call. None when the tracker hasn't run yet."""
    try:
        p = Path("data/cache/fno/alert_state.json")
        if p.exists():
            return (json.loads(p.read_text(encoding="utf-8")).get("NIFTY") or {}).get("bias")
    except Exception:
        pass
    return None


def scan(rows: list[dict], regime: Optional[dict] = None, fii: Optional[dict] = None,
         fno_bias: Optional[str] = None) -> dict:
    """Run every scanner over the rows. Returns the full page payload."""
    state = (regime or {}).get("state") or "neutral"
    if state not in ("risk_on", "risk_off"):
        state = "neutral"

    per_scanner: dict[str, list[dict]] = {s["id"]: [] for s in SCANNERS}
    for row in rows:
        if not row.get("ticker"):
            continue
        for s in SCANNERS:
            try:
                ok, reasons, flags, rank = s["fn"](row, state)
            except Exception:
                continue
            if ok:
                per_scanner[s["id"]].append(
                    {"row": row, "reasons": reasons, "flags": flags, "rank": rank})

    # Rank within each scanner; remember each stock's best percentile + matches.
    matches: dict[str, dict] = {}
    for s in SCANNERS:
        cands = sorted(per_scanner[s["id"]], key=lambda c: -c["rank"])
        per_scanner[s["id"]] = cands
        n = len(cands)
        for i, cand in enumerate(cands):
            pct = 1.0 if n <= 1 else 1 - i / (n - 1)
            t = cand["row"]["ticker"]
            m = matches.setdefault(t, {"row": cand["row"], "scanners": [],
                                       "best_pct": 0.0, "best_scanner": s["id"],
                                       "reasons": [], "flags": []})
            m["scanners"].append(s["id"])
            if pct >= m["best_pct"]:
                m["best_pct"], m["best_scanner"] = pct, s["id"]
            m["reasons"].extend(r for r in cand["reasons"] if r not in m["reasons"])
            m["flags"].extend(f for f in cand["flags"] if f not in m["flags"])

    titles = {s["id"]: s["title"] for s in SCANNERS}
    scored: dict[str, dict] = {}
    for t, m in matches.items():
        score, flag = _opportunity_score(m["row"], m["scanners"], m["best_pct"], state)
        if flag and flag not in m["flags"]:
            m["flags"].append(flag)
        scored[t] = {**_display_fields(m["row"]),
                     "reasons": (m["flags"] + m["reasons"])[:4],
                     "opp_score": score, "band": _band(score),
                     "setup_title": titles[m["best_scanner"]],
                     "scanners": m["scanners"]}

    # Scanner cards in regime order, candidates capped.
    scanners_out = []
    order = _ORDER.get(state)
    ordered = sorted(SCANNERS, key=lambda s: order.index(s["id"])) if order else SCANNERS
    for s in ordered:
        cap = s["cap"].get(state, s["cap"]["default"])
        cands = []
        for cand in per_scanner[s["id"]][:cap]:
            t = cand["row"]["ticker"]
            base = dict(scored[t])
            base["reasons"] = (cand["flags"] + cand["reasons"])[:4]
            cands.append(base)
        # Sector-concentration note (page spec): 3+ hits from one sector = one bet.
        sectors: dict[str, int] = {}
        for cand in cands:
            sec = cand.get("sector") or ""
            if sec:
                sectors[sec] = sectors.get(sec, 0) + 1
        crowd = [sec for sec, n in sectors.items() if n >= 3]
        scanners_out.append({
            "id": s["id"], "title": s["title"], "pitch": s["pitch"], "icon": s["icon"],
            "group": s["group"], "caution": s["caution"], "candidates": cands,
            "sector_note": (f"{', '.join(crowd)} dominates this list — treat clustered "
                            f"hits as one macro bet, not several ideas.") if crowd else None,
        })

    top = sorted(scored.values(), key=lambda c: -c["opp_score"])
    top = [c for c in top if c["band"] != "Marginal"][:12]

    return {
        "has_rows": bool(rows),
        "regime_state": state,
        "fno_bias": fno_bias,
        "context_note": _CONTEXT_NOTES[state],
        "scanners": scanners_out,
        "top": top,
        "total_candidates": len(scored),
    }


def _display_fields(row: dict) -> dict:
    return {
        "ticker": row.get("ticker"), "name": row.get("name") or "",
        "sector": row.get("sector") or "",
        "last_close": _f(row, "last_close") or 0,
        "day_change_pct": _f(row, "day_change_pct"),
        "rsi_14": _f(row, "rsi_14"),
        "return_30d_pct": _f(row, "return_30d_pct"),
        "upside_pct": _f(row, "upside_pct"),
        "trade_target": _f(row, "trade_target"),
        "stop_loss": _f(row, "stop_loss"),
        "rr": _rr(row),
        "avg_daily_value_cr": _f(row, "avg_daily_value_cr"),
        "verdict": _verdict(row),
    }
