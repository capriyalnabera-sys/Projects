"""Intraday and short-term trading signals.

Pulls intraday bars (5min default) for today + a few prior sessions, computes:
  - VWAP (volume-weighted average price)
  - Today's open / high / low / change %
  - Pre-market gap vs prior close
  - Opening Range (first 30 min) high/low → ORB breakout/breakdown signal
  - Position vs VWAP (above = strength, below = weakness)
  - Intraday RSI on 15m bars
  - Today's volume vs 20-day average

Plus short-term swing signals on daily bars:
  - 5d / 10d MAs
  - Bollinger Band(20,2) position + squeeze detection
  - Stochastic %K / %D
  - ADX(14) trend strength
  - Recent breakout from 10-day range
  - Relative strength vs NIFTY 50 (last 5d, 20d returns)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class IntradaySignal:
    available: bool = False
    last_price: Optional[float] = None
    open_price: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    prev_close: Optional[float] = None
    day_change_pct: Optional[float] = None
    gap_pct: Optional[float] = None  # open vs prev close
    vwap: Optional[float] = None
    vs_vwap_pct: Optional[float] = None
    or_high: Optional[float] = None  # opening range (first 30 min)
    or_low: Optional[float] = None
    orb_signal: str = "—"            # "breakout" / "breakdown" / "inside range"
    intraday_rsi: Optional[float] = None  # RSI on 15m bars
    volume_ratio: Optional[float] = None  # today vs 20-day avg
    bias: str = "neutral"            # bullish / bearish / neutral
    notes: list[str] = field(default_factory=list)


@dataclass
class ShortTermSignal:
    available: bool = False
    sma_5: Optional[float] = None
    sma_10: Optional[float] = None
    sma_20: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_pct_b: Optional[float] = None   # 0-1 where 0 = lower band, 1 = upper
    bb_squeeze: bool = False
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    breakout_10d: Optional[str] = None  # "up" / "down" / None
    rs_5d_vs_nifty: Optional[float] = None
    rs_20d_vs_nifty: Optional[float] = None
    setup: str = "neutral"
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- helpers


def _yf_symbol(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if "." in t else f"{t}.NS"


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3):
    ll = low.rolling(k).min()
    hh = high.rolling(k).max()
    pk = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    pd_ = pk.rolling(d).mean()
    return pk, pd_


def _adx(df: pd.DataFrame, period: int = 14):
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    # Where movement is in the wrong direction, zero it.
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


# ------------------------------------------------------------------- intraday


def intraday_signal(ticker: str) -> IntradaySignal:
    sig = IntradaySignal()
    try:
        # 5d of 5-min bars: covers today + recent sessions for context.
        df = yf.Ticker(_yf_symbol(ticker)).history(period="5d", interval="5m", auto_adjust=False)
    except Exception:
        return sig
    if df is None or df.empty:
        return sig

    # Group by trading-session date (broker timezone).
    df = df.copy()
    df["date"] = df.index.tz_convert("Asia/Kolkata").date if df.index.tz is not None else df.index.date
    sessions = sorted(df["date"].unique())
    if not sessions:
        return sig

    today = df[df["date"] == sessions[-1]]
    prev = df[df["date"] == sessions[-2]] if len(sessions) >= 2 else pd.DataFrame()
    if today.empty:
        return sig

    sig.available = True
    sig.last_price = float(today["Close"].iloc[-1])
    sig.open_price = float(today["Open"].iloc[0])
    sig.day_high = float(today["High"].max())
    sig.day_low = float(today["Low"].min())
    sig.prev_close = float(prev["Close"].iloc[-1]) if not prev.empty else None
    if sig.prev_close:
        sig.day_change_pct = (sig.last_price / sig.prev_close - 1) * 100
        sig.gap_pct = (sig.open_price / sig.prev_close - 1) * 100

    # VWAP across today only.
    typical = (today["High"] + today["Low"] + today["Close"]) / 3
    cum_vp = (typical * today["Volume"]).cumsum()
    cum_v = today["Volume"].cumsum().replace(0, np.nan)
    vwap_series = cum_vp / cum_v
    if not vwap_series.empty and not pd.isna(vwap_series.iloc[-1]):
        sig.vwap = float(vwap_series.iloc[-1])
        sig.vs_vwap_pct = (sig.last_price / sig.vwap - 1) * 100

    # Opening range = first 30 minutes (six 5-min bars).
    or_window = today.head(6)
    if not or_window.empty:
        sig.or_high = float(or_window["High"].max())
        sig.or_low = float(or_window["Low"].min())
        if sig.last_price > sig.or_high:
            sig.orb_signal = "breakout"
        elif sig.last_price < sig.or_low:
            sig.orb_signal = "breakdown"
        else:
            sig.orb_signal = "inside range"

    # Intraday RSI on resampled 15-min bars.
    bars15 = today["Close"].resample("15min").last().dropna()
    if len(bars15) >= 14:
        sig.intraday_rsi = float(_rsi(bars15).iloc[-1])

    # Today's cumulative volume vs prior 4 sessions' avg same-time-of-day.
    if not prev.empty and len(sessions) >= 5:
        prior_total = float(df[df["date"].isin(sessions[-5:-1])]["Volume"].sum() / 4)
        today_total = float(today["Volume"].sum())
        if prior_total > 0:
            sig.volume_ratio = today_total / prior_total

    # Bias synthesis.
    score = 0
    if sig.gap_pct is not None:
        if sig.gap_pct > 0.5: score += 1
        elif sig.gap_pct < -0.5: score -= 1
    if sig.vs_vwap_pct is not None:
        if sig.vs_vwap_pct > 0.2: score += 1
        elif sig.vs_vwap_pct < -0.2: score -= 1
    if sig.orb_signal == "breakout": score += 2
    elif sig.orb_signal == "breakdown": score -= 2
    if sig.intraday_rsi is not None:
        if sig.intraday_rsi > 70: score -= 1  # exhaustion risk
        elif sig.intraday_rsi < 30: score += 1
    if sig.volume_ratio is not None:
        if sig.volume_ratio > 1.5 and (sig.day_change_pct or 0) > 0: score += 1
        elif sig.volume_ratio > 1.5 and (sig.day_change_pct or 0) < 0: score -= 1

    if score >= 2: sig.bias = "bullish"
    elif score <= -2: sig.bias = "bearish"
    else: sig.bias = "neutral"

    notes: list[str] = []
    if sig.gap_pct is not None and abs(sig.gap_pct) > 0.5:
        notes.append(f"Gap {sig.gap_pct:+.2f}% at open")
    if sig.vs_vwap_pct is not None:
        notes.append(f"{'Above' if sig.vs_vwap_pct > 0 else 'Below'} VWAP by {abs(sig.vs_vwap_pct):.2f}%")
    if sig.orb_signal in ("breakout", "breakdown"):
        notes.append(f"Opening-range {sig.orb_signal} (OR {sig.or_low:.2f} – {sig.or_high:.2f})")
    if sig.intraday_rsi is not None and (sig.intraday_rsi > 70 or sig.intraday_rsi < 30):
        notes.append(f"Intraday RSI {sig.intraday_rsi:.0f}")
    if sig.volume_ratio is not None and sig.volume_ratio > 1.5:
        notes.append(f"Volume {sig.volume_ratio:.1f}x prior 4-day avg")
    sig.notes = notes
    return sig


# -------------------------------------------------------- short-term (swing)


def _bollinger(close: pd.Series, period: int = 20, n_std: float = 2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = mid + n_std * sd
    lower = mid - n_std * sd
    width = (upper - lower) / mid.replace(0, np.nan)
    return upper, mid, lower, width


def short_term_signal(ticker: str, daily_history: Optional[pd.DataFrame] = None) -> ShortTermSignal:
    sig = ShortTermSignal()
    df = daily_history
    if df is None:
        try:
            df = yf.Ticker(_yf_symbol(ticker)).history(period="1y", auto_adjust=False)
        except Exception:
            return sig
    if df is None or len(df) < 30:
        return sig

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    sig.available = True
    sig.sma_5 = float(close.rolling(5).mean().iloc[-1])
    sig.sma_10 = float(close.rolling(10).mean().iloc[-1])
    sig.sma_20 = float(close.rolling(20).mean().iloc[-1])

    # Bollinger Bands(20,2)
    upper, mid, lower, width = _bollinger(close, 20, 2.0)
    sig.bb_upper = float(upper.iloc[-1])
    sig.bb_lower = float(lower.iloc[-1])
    last = float(close.iloc[-1])
    if not pd.isna(upper.iloc[-1]) and not pd.isna(lower.iloc[-1]) and (upper.iloc[-1] - lower.iloc[-1]) > 0:
        sig.bb_pct_b = (last - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
    if len(width) >= 100:
        recent_w = width.iloc[-1]
        median_w = float(width.tail(100).median())
        sig.bb_squeeze = bool(not pd.isna(recent_w) and recent_w < 0.6 * median_w)

    # Stochastic(14, 3)
    pk, pd_ = _stochastic(high, low, close, 14, 3)
    if not pd.isna(pk.iloc[-1]):
        sig.stoch_k = float(pk.iloc[-1])
    if not pd.isna(pd_.iloc[-1]):
        sig.stoch_d = float(pd_.iloc[-1])

    # ADX(14)
    adx, plus_di, minus_di = _adx(df, 14)
    if not pd.isna(adx.iloc[-1]):
        sig.adx = float(adx.iloc[-1])
        sig.plus_di = float(plus_di.iloc[-1])
        sig.minus_di = float(minus_di.iloc[-1])

    # 10-day breakout
    if len(close) >= 11:
        prior_high = float(high.iloc[-11:-1].max())
        prior_low = float(low.iloc[-11:-1].min())
        if last > prior_high:
            sig.breakout_10d = "up"
        elif last < prior_low:
            sig.breakout_10d = "down"

    # Relative strength vs NIFTY (use ^NSEI)
    try:
        nifty = yf.Ticker("^NSEI").history(period="60d", auto_adjust=False)["Close"]
        if len(nifty) >= 21 and len(close) >= 21:
            stk_5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
            stk_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100
            nif_5 = (nifty.iloc[-1] / nifty.iloc[-6] - 1) * 100
            nif_20 = (nifty.iloc[-1] / nifty.iloc[-21] - 1) * 100
            sig.rs_5d_vs_nifty = stk_5 - nif_5
            sig.rs_20d_vs_nifty = stk_20 - nif_20
    except Exception:
        pass

    # Synthesize setup
    score = 0
    notes: list[str] = []
    if sig.sma_5 and sig.sma_10 and sig.sma_20:
        if sig.sma_5 > sig.sma_10 > sig.sma_20:
            score += 2
            notes.append("Short-term MAs aligned bullish (5>10>20)")
        elif sig.sma_5 < sig.sma_10 < sig.sma_20:
            score -= 2
            notes.append("Short-term MAs aligned bearish (5<10<20)")
    if sig.breakout_10d == "up":
        score += 2
        notes.append("Closed above 10-day high — breakout")
    elif sig.breakout_10d == "down":
        score -= 2
        notes.append("Closed below 10-day low — breakdown")
    if sig.bb_squeeze:
        notes.append("Bollinger squeeze — pending range expansion")
    if sig.bb_pct_b is not None:
        if sig.bb_pct_b > 1: notes.append("Closed above upper Bollinger Band")
        elif sig.bb_pct_b < 0: notes.append("Closed below lower Bollinger Band")
    if sig.stoch_k is not None and sig.stoch_d is not None:
        if sig.stoch_k > 80: notes.append(f"Stochastic overbought ({sig.stoch_k:.0f}/{sig.stoch_d:.0f})")
        elif sig.stoch_k < 20: notes.append(f"Stochastic oversold ({sig.stoch_k:.0f}/{sig.stoch_d:.0f})")
        if sig.stoch_k > sig.stoch_d and sig.stoch_k < 30: score += 1
        elif sig.stoch_k < sig.stoch_d and sig.stoch_k > 70: score -= 1
    if sig.adx is not None and sig.adx > 25:
        if (sig.plus_di or 0) > (sig.minus_di or 0):
            notes.append(f"Strong uptrend (ADX {sig.adx:.0f}, +DI > -DI)")
            score += 1
        else:
            notes.append(f"Strong downtrend (ADX {sig.adx:.0f}, -DI > +DI)")
            score -= 1
    if sig.rs_20d_vs_nifty is not None:
        if sig.rs_20d_vs_nifty > 5:
            score += 1
            notes.append(f"Outperforming NIFTY by {sig.rs_20d_vs_nifty:+.1f}% over 20d")
        elif sig.rs_20d_vs_nifty < -5:
            score -= 1
            notes.append(f"Underperforming NIFTY by {sig.rs_20d_vs_nifty:.1f}% over 20d")

    if score >= 3: sig.setup = "strong bullish"
    elif score >= 1: sig.setup = "bullish"
    elif score <= -3: sig.setup = "strong bearish"
    elif score <= -1: sig.setup = "bearish"
    else: sig.setup = "neutral"
    sig.notes = notes
    return sig
