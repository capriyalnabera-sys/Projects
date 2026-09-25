"""Market regime detection — overlays the per-stock verdicts.

Logic:
  - Risk-off: NIFTY 50 below 200-day SMA, OR (ADX > 25 AND -DI > +DI).
    The market is in a downtrend; even fundamentally-strong stocks tend to
    drift down with it. Downgrade all positive verdicts by one band.
  - Risk-on:  NIFTY 50 above 200-day SMA AND ADX > 20 AND +DI > -DI.
    The market is in a confirmed uptrend; verdicts get to stand.
  - Neutral:  in between (no edge either way).

Cached on disk for 30 minutes so we don't fetch ^NSEI on every page load.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


REGIME_CACHE = Path("data/cache/regime.json")
REGIME_TTL_SECONDS = 30 * 60


def _adx(df: pd.DataFrame, period: int = 14):
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    mask = plus_dm > minus_dm
    plus_dm = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx, plus_di, minus_di


def get_regime(force: bool = False) -> dict:
    """Return current NIFTY regime. Cached on disk for REGIME_TTL_SECONDS."""
    if not force and REGIME_CACHE.exists():
        age = time.time() - REGIME_CACHE.stat().st_mtime
        if age < REGIME_TTL_SECONDS:
            try:
                return json.loads(REGIME_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        df = yf.Ticker("^NSEI").history(period="2y", auto_adjust=False)
    except Exception:
        df = None
    if df is None or df.empty:
        return {"state": "unknown", "reason": "NIFTY data unavailable",
                "nifty_close": None, "sma_200": None, "adx": None,
                "plus_di": None, "minus_di": None}
    df = df.dropna(subset=["Close"])
    if len(df) < 200:
        return {"state": "unknown", "reason": "Less than 200 trading days of data",
                "nifty_close": float(df["Close"].iloc[-1]) if len(df) else None,
                "sma_200": None, "adx": None, "plus_di": None, "minus_di": None}

    last = float(df["Close"].iloc[-1])
    sma_200_series = df["Close"].rolling(200).mean()
    sma_200 = float(sma_200_series.iloc[-1])
    adx_s, p_di, m_di = _adx(df)
    adx = float(adx_s.iloc[-1]) if pd.notna(adx_s.iloc[-1]) else 0.0
    pdi = float(p_di.iloc[-1]) if pd.notna(p_di.iloc[-1]) else 0.0
    mdi = float(m_di.iloc[-1]) if pd.notna(m_di.iloc[-1]) else 0.0

    distance_from_200_pct = (last / sma_200 - 1) * 100

    # Regime hysteresis — count consecutive sessions on each side of the 200SMA.
    # Real regime changes need confirmation; this prevents flipping on a single
    # close that crosses the line.
    last_n_closes = df["Close"].tail(10).tolist()
    last_n_smas = sma_200_series.tail(10).tolist()
    streak_below = 0
    streak_above = 0
    for c, s in zip(reversed(last_n_closes), reversed(last_n_smas)):
        if pd.isna(s):
            break
        if c < s:
            if streak_above:
                break
            streak_below += 1
        else:
            if streak_below:
                break
            streak_above += 1

    # Classify with hysteresis: 5 sessions to enter risk_off, 3 to enter risk_on
    if streak_below >= 5:
        state = "risk_off"
        reason = f"NIFTY {last:,.0f} below 200SMA ({sma_200:,.0f}) for {streak_below} sessions — downtrend confirmed"
    elif streak_below >= 1 and adx > 25 and mdi > pdi:
        # Strong downtrend regardless of streak length
        state = "risk_off"
        reason = f"Strong downtrend (ADX {adx:.0f}, -DI > +DI), {streak_below}d below 200SMA"
    elif streak_above >= 3 and adx > 20 and pdi > mdi:
        state = "risk_on"
        reason = f"NIFTY {last:,.0f} above 200SMA for {streak_above}d, ADX {adx:.0f} confirms uptrend"
    else:
        state = "neutral"
        if streak_below > 0:
            reason = f"Borderline — {streak_below}d below 200SMA but trend weak (ADX {adx:.0f})"
        else:
            reason = f"NIFTY {last:,.0f} above 200SMA ({streak_above}d) but trend not confirmed (ADX {adx:.0f})"

    # Fetch India VIX for volatility-adaptive HOLD zone sizing.
    vix = None
    try:
        vdf = yf.Ticker("^INDIAVIX").history(period="5d", auto_adjust=False)
        if vdf is not None and not vdf.empty:
            vc = vdf["Close"].dropna()
            if len(vc) > 0:
                vix = float(vc.iloc[-1])
    except Exception:
        pass

    # HOLD zone width scales with VIX. High VIX = signals noisier = wider zone.
    if vix is None:
        hold_zone = 0.8
        vix_label = "default"
    elif vix >= 25:
        hold_zone = 1.5
        vix_label = "very-high (VIX≥25)"
    elif vix >= 20:
        hold_zone = 1.2
        vix_label = "high (VIX≥20)"
    elif vix >= 15:
        hold_zone = 0.8
        vix_label = "normal"
    else:
        hold_zone = 0.5
        vix_label = "calm (VIX<15)"

    payload = {
        "state": state,
        "reason": reason,
        "nifty_close": round(last, 2),
        "sma_200": round(sma_200, 2),
        "distance_from_200_pct": round(distance_from_200_pct, 2),
        "adx": round(adx, 1),
        "plus_di": round(pdi, 1),
        "minus_di": round(mdi, 1),
        "vix": round(vix, 2) if vix is not None else None,
        "vix_label": vix_label,
        "hold_zone": hold_zone,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        REGIME_CACHE.parent.mkdir(parents=True, exist_ok=True)
        REGIME_CACHE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    return payload


def apply_to_verdict(verdict: str, regime_state: str) -> tuple[str, Optional[str]]:
    """Return adjusted verdict + rationale note (or None if no change)."""
    if regime_state == "risk_off":
        if verdict == "BUY":
            return "ACCUMULATE", "[!] Regime: NIFTY risk-off — downgraded BUY → ACCUMULATE. Even strong stocks drift in a market downtrend."
        if verdict == "ACCUMULATE":
            return "HOLD", "[!] Regime: NIFTY risk-off — downgraded ACCUMULATE → HOLD. Wait for market regime to confirm before adding."
    elif regime_state == "risk_on":
        # In confirmed uptrend, no downgrades. Optionally we could upgrade
        # very-strong setups, but conservative for now.
        return verdict, None
    return verdict, None
