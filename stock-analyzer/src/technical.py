from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TechnicalSnapshot:
    last_close: float
    sma_20: float
    sma_50: float
    sma_200: Optional[float]
    ema_12: float
    ema_26: float
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr_14: float
    high_52w: float
    low_52w: float
    pct_from_52w_high: float
    pct_from_52w_low: float
    volume_ratio: float
    avg_daily_value_cr: Optional[float] = None  # average ₹crore traded per day, last 20 sessions
    return_30d_pct: Optional[float] = None      # 30-day price return (momentum factor)
    score: float = 0.0
    notes: list[str] = None


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def analyze(history: pd.DataFrame) -> TechnicalSnapshot:
    df = history.copy()
    close = df["Close"]
    last = float(close.iloc[-1])

    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else np.nan

    ema12 = close.ewm(span=12, adjust=False).mean().iloc[-1]
    ema26 = close.ewm(span=26, adjust=False).mean().iloc[-1]
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    rsi = _rsi(close).iloc[-1]
    atr = _atr(df).iloc[-1]

    window_252 = df.tail(252) if len(df) >= 252 else df
    high_52w = float(window_252["High"].max())
    low_52w = float(window_252["Low"].min())
    pct_from_high = (last / high_52w - 1) * 100
    pct_from_low = (last / low_52w - 1) * 100

    vol_ratio = float(df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1])

    # Liquidity: average ₹crore traded per day over the last 20 sessions.
    # Used as a quality gate — illiquid stocks have unreliable signals.
    try:
        recent20 = df.tail(20)
        avg_value = float((recent20["Close"] * recent20["Volume"]).mean())
        avg_daily_value_cr = avg_value / 1e7 if avg_value > 0 else 0.0
    except Exception:
        avg_daily_value_cr = None

    # Pure momentum: 30-day price return (separate from RSI/MACD trend signals).
    return_30d_pct = None
    if len(close) > 30:
        try:
            return_30d_pct = float((close.iloc[-1] / close.iloc[-31] - 1) * 100)
        except Exception:
            pass

    score = 0.0
    notes: list[str] = []

    if not np.isnan(sma200):
        if last > sma50 > sma200:
            score += 1.5
            notes.append("Uptrend: price > 50SMA > 200SMA")
        elif last < sma50 < sma200:
            score -= 1.5
            notes.append("Downtrend: price < 50SMA < 200SMA")
        elif last > sma200:
            score += 0.5
            notes.append("Above 200SMA but mixed shorter trend")
        else:
            score -= 0.5
            notes.append("Below 200SMA")
    else:
        if last > sma50:
            score += 0.5
            notes.append("Above 50SMA (insufficient data for 200SMA)")
        else:
            score -= 0.5
            notes.append("Below 50SMA")

    if rsi < 30:
        score += 0.7
        notes.append(f"RSI oversold ({rsi:.0f})")
    elif rsi > 70:
        score -= 0.7
        notes.append(f"RSI overbought ({rsi:.0f})")
    elif 45 <= rsi <= 65:
        score += 0.2
        notes.append(f"RSI healthy ({rsi:.0f})")

    if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0:
        score += 0.8
        notes.append("MACD bullish crossover")
    elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0:
        score -= 0.8
        notes.append("MACD bearish crossover")
    elif macd_hist.iloc[-1] > 0:
        score += 0.3
    else:
        score -= 0.3

    if vol_ratio > 1.5 and macd_hist.iloc[-1] > 0:
        if rsi > 75:
            score -= 0.6
            notes.append(f"Heavy volume {vol_ratio:.1f}x at RSI {rsi:.0f} — exhaustion / blow-off risk")
        else:
            score += 0.4
            notes.append(f"Volume surge {vol_ratio:.1f}x with momentum")
    elif vol_ratio > 1.5 and macd_hist.iloc[-1] < 0:
        score -= 0.4
        notes.append(f"Volume surge {vol_ratio:.1f}x against price")

    if pct_from_high > -5 and score > 0:
        score += 0.3
        notes.append("Within 5% of 52w high — breakout watch")
    if pct_from_low < 10 and score < 0:
        score -= 0.3
        notes.append("Near 52w low — distress zone")

    # Pure momentum (absolute) — kept at HALF strength because cross-sectional
    # momentum (sector-relative rank) is added separately in fundamentals.analyze
    # via sector_stats. A stock that's strong absolutely AND relative to its
    # sector gets the full +0.5; sector-rally beneficiaries get only +0.25.
    if return_30d_pct is not None:
        if return_30d_pct >= 20:
            score += 0.25
            notes.append(f"Strong 30d momentum (+{return_30d_pct:.0f}%)")
        elif return_30d_pct >= 10:
            score += 0.15
        elif return_30d_pct <= -20:
            score -= 0.25
            notes.append(f"Severe 30d drawdown ({return_30d_pct:.0f}%)")
        elif return_30d_pct <= -10:
            score -= 0.15

    score = max(-3.0, min(3.0, score))

    return TechnicalSnapshot(
        last_close=last,
        sma_20=float(sma20),
        sma_50=float(sma50),
        sma_200=float(sma200) if not np.isnan(sma200) else None,
        ema_12=float(ema12),
        ema_26=float(ema26),
        rsi_14=float(rsi),
        macd=float(macd_line.iloc[-1]),
        macd_signal=float(signal_line.iloc[-1]),
        macd_hist=float(macd_hist.iloc[-1]),
        atr_14=float(atr),
        high_52w=high_52w,
        low_52w=low_52w,
        pct_from_52w_high=float(pct_from_high),
        pct_from_52w_low=float(pct_from_low),
        volume_ratio=vol_ratio,
        avg_daily_value_cr=avg_daily_value_cr,
        return_30d_pct=return_30d_pct,
        score=score,
        notes=notes,
    )
