from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .fundamentals import FundamentalSnapshot
from .technical import TechnicalSnapshot


@dataclass
class TelegramSignal:
    mentions_7d: int = 0
    avg_sentiment: float = 0.0
    quoted_targets: list[float] = field(default_factory=list)


@dataclass
class Recommendation:
    verdict: str
    combined_score: float
    technical_score: float
    fundamental_score: float
    telegram_score: float
    fair_value: Optional[float]      # PE × forward EPS — informational, always shown if available
    trade_target: Optional[float]    # Action-target — only set when verdict is positive
    target_bull: Optional[float]     # Stretch target — only set when verdict is positive
    stop_loss: float
    horizon: str
    upside_pct: Optional[float]
    downside_pct: float
    rationale: list[str]
    entry_note: Optional[str] = None  # "wait for pullback" caveat when buying into overbought tech
    plain_summary: str = ""           # plain-English read for quick scanning
    raw_verdict: Optional[str] = None # verdict before regime/earnings overlays — used for persistence
    # Self-calibration metadata derived from accuracy backtest. Always shown
    # informationally on the UI. Only auto-applied to the verdict (demoting
    # BUYs below the learned floor to HOLD) once ≥30 snapshots exist.
    track_record: Optional[dict] = None         # {n, hit_rate, avg_return, horizon_days, guidance}
    sector_track_record: Optional[dict] = None  # {confidence, note, n, hit_rate, avg_return}
    calibration_applied: bool = False           # True iff the learned BUY floor demoted this verdict


def recommend(
    tech: TechnicalSnapshot,
    fund: FundamentalSnapshot,
    weights: dict[str, float],
    last_close: float,
    tg: Optional[TelegramSignal] = None,
    regime: Optional[dict] = None,
    earnings_days: Optional[int] = None,
    prior_verdict: Optional[str] = None,
    prior_score: Optional[float] = None,
    sector: Optional[str] = None,
) -> Recommendation:
    w_t = weights.get("technical_weight", 0.45)
    w_f = weights.get("fundamental_weight", 0.45)
    w_g = weights.get("telegram_weight", 0.10)

    tg_score = 0.0
    if tg and tg.mentions_7d > 0:
        tg_score = max(-3.0, min(3.0, tg.avg_sentiment * (1 + min(tg.mentions_7d / 5, 1.0))))

    combined_raw = tech.score * w_t + fund.score * w_f + tg_score * w_g

    # ---- Score EMA smoothing (G) -------------------------------------------
    # Blend with prior batch's score to dampen yfinance/data-source noise.
    # Adaptive: small changes get heavy smoothing (assume noise); large changes
    # get only moderate smoothing (assume real signal). Threshold based on
    # standard deviation of typical day-to-day score moves.
    if prior_score is not None:
        delta = abs(combined_raw - prior_score)
        if delta < 0.3:
            # Likely noise — heavy smoothing (mostly trust prior)
            combined = 0.3 * combined_raw + 0.7 * prior_score
        elif delta < 0.8:
            # Moderate move — equal weight
            combined = 0.5 * combined_raw + 0.5 * prior_score
        else:
            # Large move — likely real signal change, light smoothing
            combined = 0.8 * combined_raw + 0.2 * prior_score
    else:
        combined = combined_raw

    # ---- Noise-suppression gates ------------------------------------------
    # 0. LIQUIDITY: stocks with thin trading have unreliable signals — single
    # large trades skew the data. Force HOLD below the configured floor.
    liquidity_floor_cr = weights.get("liquidity_floor_cr", 0.5)
    illiquid = (
        tech.avg_daily_value_cr is not None
        and tech.avg_daily_value_cr < liquidity_floor_cr
    )

    # 1. DATA SUFFICIENCY: too many fundamental fields missing → can't trust verdict.
    fund_fields = (fund.trailing_pe, fund.roe, fund.debt_to_equity,
                   fund.earnings_growth, fund.revenue_growth, fund.profit_margin)
    fund_populated = sum(1 for f in fund_fields if f is not None)
    insufficient_data = fund_populated < 3

    # 2. CONFLUENCE: a BUY needs BOTH technical AND fundamental positive — not
    # one layer carrying a noisy other. Same for AVOID on the downside.
    both_layers_bullish  = tech.score >= 0.5 and fund.score >= 0.5
    both_layers_bearish  = tech.score <= -0.5 and fund.score <= -0.5

    # 3. VIX-ADAPTIVE HOLD ZONE: width scales with current volatility.
    # In high-VIX periods, all signals are noisier — widen the dead zone.
    hold_zone = (regime or {}).get("hold_zone", 0.8)
    buy_threshold = max(1.5, hold_zone + 0.7)  # BUY needs a wider margin in high-vol
    avoid_threshold = -max(1.5, hold_zone + 0.7)

    if illiquid:
        verdict = "HOLD"
    elif insufficient_data:
        verdict = "HOLD"
    elif combined >= buy_threshold and both_layers_bullish:
        verdict = "BUY"
    elif combined >= hold_zone and (tech.score >= 0.3 or fund.score >= 0.3):
        verdict = "ACCUMULATE"
    elif combined <= avoid_threshold and both_layers_bearish:
        verdict = "AVOID"
    elif combined <= -hold_zone:
        verdict = "REDUCE"
    else:
        verdict = "HOLD"

    # Target price logic ----------------------------------------------------
    fair_value: Optional[float] = None
    eps_for_valuation = fund.forward_eps if fund.forward_eps and fund.forward_eps > 0 else fund.trailing_eps
    if eps_for_valuation and eps_for_valuation > 0:
        fair_value = eps_for_valuation * fund.fair_pe_target

    trade_target: Optional[float] = None
    target_bull: Optional[float] = None
    upside: Optional[float] = None

    if combined >= 0.5:  # Only show action targets when the verdict is BUY or ACCUMULATE.
        pivot_resistance = tech.high_52w
        momentum_target = last_close * (1 + max(0.05, min(0.40, 0.10 + tech.score * 0.05)))
        if fair_value and fair_value > last_close:
            trade_target = (fair_value + momentum_target) / 2
        else:
            trade_target = momentum_target
        target_bull = max(pivot_resistance, trade_target * 1.15)
        upside = (trade_target / last_close - 1) * 100

    stop_loss = max(
        last_close - 2 * tech.atr_14,
        tech.sma_50 * 0.97,
        tech.low_52w * 1.02,
    )
    if stop_loss >= last_close:
        stop_loss = last_close - 2 * tech.atr_14

    downside = (stop_loss / last_close - 1) * 100

    # Holding horizon -------------------------------------------------------
    if abs(tech.score) > abs(fund.score) + 0.8:
        horizon = "Short term (1-3 months) — technical-led trade, manage actively"
    elif fund.score >= 1.5 and tech.score >= 0:
        horizon = "Long term (12+ months) — fundamentals support compounding"
    elif fund.score >= 0.5:
        horizon = "Medium term (6-12 months)"
    elif tech.score >= 1.0 and fund.score < 0:
        horizon = "Short term only (1-3 months) — fundamentals don't support holding"
    else:
        horizon = "Avoid new positions; review in 1-2 quarters"

    rationale = []
    rationale.extend(f"[T] {n}" for n in tech.notes)
    rationale.extend(f"[F] {n}" for n in fund.notes)
    if tg and tg.mentions_7d > 0:
        rationale.append(
            f"[G] {tg.mentions_7d} Telegram mentions in last 7d, avg sentiment {tg.avg_sentiment:+.2f}"
        )

    # Surface why a verdict was suppressed so the user can tell signal from noise.
    if illiquid:
        rationale.append(
            f"[!] HOLD forced — avg daily turnover only ₹{tech.avg_daily_value_cr:.2f} cr "
            f"(< ₹{liquidity_floor_cr:g} cr threshold). Signals on thinly-traded stocks are noise-dominated."
        )
    elif insufficient_data:
        rationale.append(
            f"[!] HOLD forced — only {fund_populated}/6 core fundamentals available "
            f"(need ≥3). Score not statistically reliable."
        )
    elif combined >= 1.5 and not both_layers_bullish:
        rationale.append(
            f"[!] Downgraded from BUY → ACCUMULATE: only one of the two layers is "
            f"strongly bullish (T={tech.score:+.2f}, F={fund.score:+.2f}). Need both."
        )
    elif combined <= -1.5 and not both_layers_bearish:
        rationale.append(
            f"[!] Upgraded from AVOID → REDUCE: only one layer is bearish "
            f"(T={tech.score:+.2f}, F={fund.score:+.2f}). Not full confluence."
        )
    elif verdict == "HOLD" and 0 < combined < hold_zone:
        rationale.append(
            f"[!] HOLD instead of ACCUMULATE — score {combined:+.2f} "
            f"inside ±{hold_zone} noise band (VIX-adaptive)."
        )
    elif verdict == "HOLD" and -hold_zone < combined < 0:
        rationale.append(
            f"[!] HOLD instead of REDUCE — score {combined:+.2f} "
            f"inside ±{hold_zone} noise band (VIX-adaptive)."
        )

    # ---- Verdict persistence smoothing (BEFORE overlays) -------------------
    # Persistence compares the RAW verdict (pre-overlay) to the prior batch's
    # raw verdict. This eliminates batch-to-batch flicker from minor score
    # noise (e.g. 1.49 ↔ 1.51 crossing the BUY threshold). Critically, this
    # happens BEFORE regime/earnings overlays so those always have the final
    # say — persistence doesn't let stale BUYs override regime downgrades.
    raw_verdict_for_storage = verdict
    if prior_verdict and prior_score is not None and prior_verdict != verdict:
        score_delta = abs(combined - prior_score)
        if score_delta < 0.3:
            rationale.append(
                f"[!] Raw verdict held at {prior_verdict} (would have been {verdict}). "
                f"Score moved only {score_delta:+.2f} from prior batch — under 0.3 noise threshold."
            )
            verdict = prior_verdict
            raw_verdict_for_storage = prior_verdict

    # ---- Market regime overlay (always has the last word) ------------------
    regime_note = None
    if regime and regime.get("state"):
        from . import regime as regime_mod
        new_verdict, regime_note = regime_mod.apply_to_verdict(verdict, regime["state"])
        if new_verdict != verdict:
            verdict = new_verdict
            if regime_note:
                rationale.append(regime_note)

    # ---- Earnings calendar gate --------------------------------------------
    # Within 5 trading days of results, the verdict is built on data that's
    # about to be replaced. Park positive verdicts as HOLD.
    if earnings_days is not None and 0 <= earnings_days <= 5:
        if verdict in ("BUY", "ACCUMULATE"):
            old = verdict
            verdict = "HOLD"
            rationale.append(
                f"[!] Results in {earnings_days} trading day{'s' if earnings_days != 1 else ''} — "
                f"downgraded {old} → HOLD. Wait for the print before adding."
            )

    # Entry-timing nuance: positive verdict but technicals are stretched.
    entry_note: Optional[str] = None
    if verdict in ("BUY", "ACCUMULATE") and tech.rsi_14 > 70:
        sma50 = tech.sma_50
        entry_note = (
            f"Don't chase here — RSI {tech.rsi_14:.0f}, price {((last_close/tech.high_52w-1)*100):+.1f}% from 52w high. "
            f"Wait for pullback to 50SMA (~{sma50:,.0f}) or RSI < 60 before adding."
        )

    # ---- Calibration overlay: learning from accuracy backtest -------------
    # Reads the disk-cached calibration produced after every batch refresh.
    # Always attaches track-record metadata; only DEMOTES the verdict when
    # we've collected enough snapshots that the learned floor is trustworthy.
    track_record: Optional[dict] = None
    sector_track_record: Optional[dict] = None
    calibration_applied = False
    try:
        from . import calibration as calib_mod
        calib = calib_mod.read_cached()
        if calib:
            track_record = calib_mod.lookup_confidence_for_score(calib, combined)
            sector_track_record = calib_mod.sector_confidence(calib, sector)
            if calib.get("apply_buy_floor"):
                floor = calib.get("learned_buy_min_score")
                if floor is not None and verdict in ("BUY", "ACCUMULATE") and combined < floor:
                    old = verdict
                    verdict = "HOLD"
                    calibration_applied = True
                    rationale.append(
                        f"[learned] {old} → HOLD: score {combined:+.2f} below "
                        f"data-learned floor of {floor:+.2f} (where past "
                        f"BUY+ACCUMULATE calls have been profitable on "
                        f"average, n={calib.get('n_snapshots')} snapshots)."
                    )
    except Exception:
        # Calibration is purely additive — never block a verdict on its absence.
        pass

    plain_summary = _plain_english(verdict, tech, fund, last_close)

    return Recommendation(
        verdict=verdict,
        combined_score=combined,
        technical_score=tech.score,
        fundamental_score=fund.score,
        telegram_score=tg_score,
        fair_value=fair_value,
        trade_target=trade_target,
        target_bull=target_bull,
        stop_loss=stop_loss,
        horizon=horizon,
        upside_pct=upside,
        downside_pct=downside,
        rationale=rationale,
        entry_note=entry_note,
        plain_summary=plain_summary,
        raw_verdict=raw_verdict_for_storage,
        track_record=track_record,
        sector_track_record=sector_track_record,
        calibration_applied=calibration_applied,
    )


def _plain_english(verdict: str, tech, fund, last_close: float) -> str:
    """Translate the technical+fundamental signals into a plain-language read.
    Same content as the rationale, but written for someone who doesn't know
    what RSI / MACD / SMA / D/E mean."""
    parts: list[str] = []

    # Trend in plain words
    if tech.sma_200 is not None:
        if last_close > tech.sma_50 > tech.sma_200:
            parts.append("The price is in a clean uptrend (above both its 50-day and 200-day averages)")
        elif last_close < tech.sma_50 < tech.sma_200:
            parts.append("The price is in a clean downtrend (below both its 50-day and 200-day averages)")
        elif last_close > tech.sma_200:
            parts.append("The longer-term trend is up but the short-term picture is mixed")
        else:
            parts.append("The price is below its long-term (200-day) average — bearish overall")
    else:
        if last_close > tech.sma_50:
            parts.append("The price is above its 50-day average (short-term positive)")
        else:
            parts.append("The price is below its 50-day average (short-term weak)")

    # RSI in plain words
    rsi = tech.rsi_14
    if rsi > 75:
        parts.append(f"momentum is overheated (RSI {rsi:.0f} — far above the 70 'overbought' line)")
    elif rsi > 70:
        parts.append(f"momentum is stretched (RSI {rsi:.0f} — near 'overbought')")
    elif rsi < 30:
        parts.append(f"momentum is oversold (RSI {rsi:.0f} — historical bounce zone)")
    elif 45 <= rsi <= 65:
        parts.append(f"momentum is healthy (RSI {rsi:.0f} — the goldilocks zone)")
    else:
        parts.append(f"momentum is neutral (RSI {rsi:.0f})")

    # 52-week context
    pct_high = (last_close / tech.high_52w - 1) * 100
    if pct_high > -3:
        parts.append("trading near 52-week highs (breakout watch but no margin of safety)")
    elif pct_high < -30:
        parts.append(f"sitting {-pct_high:.0f}% off its 52-week high (deep discount, but watch for reasons)")

    tech_sentence = "Technical read: " + ", ".join(parts) + "."

    # Fundamentals in plain words
    fparts: list[str] = []
    if fund.roe is not None:
        if fund.roe < 0:
            fparts.append(f"the company is loss-making (ROE {fund.roe*100:.0f}%)")
        elif fund.roe >= 0.20:
            fparts.append(f"return on equity is strong at {fund.roe*100:.0f}% (well-run business)")
        elif fund.roe >= 0.15:
            fparts.append(f"return on equity is healthy at {fund.roe*100:.0f}%")
        elif fund.roe < 0.05:
            fparts.append(f"return on equity is weak at {fund.roe*100:.0f}%")

    if fund.earnings_growth is not None and (fund.roe is None or fund.roe >= 0):
        eg_pct = fund.earnings_growth * 100
        if eg_pct >= 25:
            fparts.append(f"earnings growing fast at {eg_pct:.0f}% YoY")
        elif eg_pct < 0:
            fparts.append(f"earnings declining {eg_pct:.0f}% YoY")

    if fund.trailing_pe is not None and fund.trailing_pe > 0:
        if fund.trailing_pe < 15:
            fparts.append(f"valuation looks cheap at {fund.trailing_pe:.0f}× earnings")
        elif fund.trailing_pe > 60:
            fparts.append(f"valuation is rich at {fund.trailing_pe:.0f}× earnings (priced for perfection)")

    fund_sentence = ("Fundamentals: " + ", ".join(fparts) + ".") if fparts else "Fundamentals: data is sparse for this stock."

    # Overall verdict translation
    verdict_text = {
        "BUY":        "Verdict: strong setup. Both price action and business quality line up. Sized position, defined stop, you can buy.",
        "ACCUMULATE": "Verdict: leans positive but not strongly. Better to scale in over time than buy a full lot at once.",
        "HOLD":       "Verdict: not enough signal either way. Wait for the price to confirm direction before acting.",
        "REDUCE":     "Verdict: risks outweigh opportunity here. Trim existing positions; don't add.",
        "AVOID":      "Verdict: meaningful downside risk. Stay out until the picture changes.",
    }.get(verdict, "")

    return tech_sentence + " " + fund_sentence + " " + verdict_text
