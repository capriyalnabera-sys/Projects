from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Sectors where high D/E is structural (lending, leasing, property dev, regulated
# utilities). Single source of truth lives in sector_params (score_leverage=False).
from .sector_params import LEVERAGE_NATURAL_SECTORS  # noqa: E402,F401


@dataclass
class FundamentalSnapshot:
    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    price_to_book: Optional[float]
    roe: Optional[float]
    roce: Optional[float] = None
    debt_to_equity: Optional[float] = None
    earnings_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    market_cap_cr: Optional[float] = None  # Indian crore from screener
    book_value: Optional[float] = None
    forward_eps: Optional[float] = None
    trailing_eps: Optional[float] = None
    sales_growth_history: Optional[dict] = None   # {"10y":0.16,"5y":..,"3y":..,"ttm":..}
    profit_growth_history: Optional[dict] = None
    fair_pe_target: float = 22.0
    score: float = 0.0
    notes: list[str] = None


def _g(info: dict, key: str) -> Optional[float]:
    v = info.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def analyze(
    info: dict,
    sector: Optional[str],
    ticker: Optional[str] = None,
    screener_cache_dir: Optional[Path] = None,
    sector_stats: Optional[dict] = None,
    return_30d_pct: Optional[float] = None,
) -> FundamentalSnapshot:
    pe = _g(info, "trailingPE")
    fpe = _g(info, "forwardPE")
    pb = _g(info, "priceToBook")
    roe = _g(info, "returnOnEquity")
    de = _g(info, "debtToEquity")
    eg = _g(info, "earningsGrowth")
    rg = _g(info, "revenueGrowth")
    pm = _g(info, "profitMargins")
    dy = _g(info, "dividendYield")
    mcap = _g(info, "marketCap")
    feps = _g(info, "forwardEps")
    teps = _g(info, "trailingEps")

    # Fallback: if any key field is missing from yfinance, scrape screener.in.
    fallback_used = False
    sc: dict = {}
    if ticker:
        try:
            from . import screener_in
            # screener.in fundamentals update on quarterly results, not intraday —
            # a 24h cache is plenty and saves a network call on every batch.
            sc = screener_in.fetch(ticker, cache_dir=screener_cache_dir, ttl_minutes=24 * 60) or {}
        except Exception:
            sc = {}
        if sc:
            fallback_used = True
            if pe is None and sc.get("trailing_pe") is not None:
                pe = sc["trailing_pe"]
            if roe is None and sc.get("roe") is not None:
                roe = sc["roe"]
            if de is None and sc.get("debt_to_equity") is not None:
                de = sc["debt_to_equity"]
            if eg is None and sc.get("earnings_growth") is not None:
                eg = sc["earnings_growth"]
            if rg is None and sc.get("revenue_growth") is not None:
                rg = sc["revenue_growth"]
            if dy is None and sc.get("dividend_yield") is not None:
                dy = sc["dividend_yield"]

    # Always pull these richer screener fields if available — purely informational.
    roce = sc.get("roce") if sc else None
    book_value = sc.get("book_value") if sc else None
    market_cap_cr = sc.get("market_cap_cr") if sc else None
    sales_growth_history = sc.get("sales_growth_history") if sc else None
    profit_growth_history = sc.get("profit_growth_history") if sc else None

    score = 0.0
    notes: list[str] = []

    # Sector-specific scoring bands — a bank's "strong ROE" differs from an
    # FMCG's, an FMCG's "cheap PE" differs from a metal's. See sector_params.py.
    from . import sector_params as spmod
    params = spmod.get_params(sector)
    roe_strong, roe_healthy, roe_ok, roe_weak = params["roe"]
    pe_cheap, pe_expensive, pe_very_expensive = params["pe"]
    margin_good = params["margin_good"]
    score_leverage = params["score_leverage"]

    if roe is not None:
        if roe >= roe_strong:
            score += 1.0
            notes.append(f"Strong ROE {roe*100:.0f}% (top-tier for {sector or 'sector'})")
        elif roe >= roe_healthy:
            score += 0.6
            notes.append(f"Healthy ROE {roe*100:.0f}%")
        elif roe >= roe_ok:
            score += 0.2
        elif roe < roe_weak:
            score -= 0.6
            notes.append(f"Weak ROE {roe*100:.0f}% (below par for {sector or 'sector'})")

    # Quality gate: % growth is unreliable when company is loss-making
    # (e.g. -₹100 → -₹50 is "+50% growth" but still bleeding).
    eg_for_scoring = eg
    if eg is not None and roe is not None and roe < 0:
        notes.append(f"EG {eg*100:.0f}% but loss-making (ROE {roe*100:.0f}%) — % growth ignored")
        eg_for_scoring = None

    if eg_for_scoring is not None:
        if eg_for_scoring >= 0.25:
            score += 0.8
            notes.append(f"Earnings growth {eg_for_scoring*100:.0f}%")
        elif eg_for_scoring >= 0.10:
            score += 0.4
        elif eg_for_scoring < 0:
            score -= 0.8
            notes.append(f"Earnings declining {eg_for_scoring*100:.0f}%")

    if rg is not None:
        if rg >= 0.20:
            score += 0.6
            notes.append(f"Revenue growth {rg*100:.0f}%")
        elif rg >= 0.10:
            score += 0.3
        elif rg < 0:
            score -= 0.5
            notes.append(f"Revenue declining {rg*100:.0f}%")

    if de is not None:
        # yfinance reports debt/equity as a ratio scaled differently for some tickers;
        # we treat values > 5 as already in % form and divide.
        de_norm = de / 100 if de > 5 else de
        if not score_leverage:
            notes.append(f"D/E {de_norm:.2f} — leverage is structural for {sector}, not scored")
        else:
            if de_norm <= 0.3:
                score += 0.4
                notes.append(f"Low leverage D/E {de_norm:.2f}")
            elif de_norm <= 1.0:
                score += 0.1
            elif de_norm > 2.0:
                score -= 0.6
                notes.append(f"High leverage D/E {de_norm:.2f}")
            elif de_norm > 1.0:
                score -= 0.2

    pe_for_valuation = pe
    # If trailing PE is much higher than forward PE, earnings just inflected — score on forward.
    if pe is not None and pe > 0 and fpe is not None and fpe > 0 and pe > 3 * fpe:
        pe_for_valuation = fpe
        notes.append(f"Earnings inflection: trailing PE {pe:.0f} → forward PE {fpe:.0f} (using forward)")

    if pe_for_valuation is not None and pe_for_valuation > 0:
        if pe_for_valuation < pe_cheap:
            score += 0.5
            notes.append(f"PE {pe_for_valuation:.1f} — cheap for {sector or 'sector'}")
        elif pe_for_valuation > pe_very_expensive:
            score -= 0.6
            notes.append(f"PE {pe_for_valuation:.1f} — expensive for {sector or 'sector'}")
        elif pe_for_valuation > pe_expensive:
            score -= 0.2
    elif pe is not None and pe < 0:
        score -= 0.4
        notes.append("Negative earnings (loss-making)")

    if pm is not None:
        if pm >= margin_good:
            score += 0.3
        elif pm < 0:
            score -= 0.4
            notes.append(f"Negative profit margin {pm*100:.0f}%")

    if fallback_used:
        notes.append("(fundamentals filled from screener.in fallback)")

    # ---- Sector-relative overlay -------------------------------------------
    # Compare to sector medians instead of absolute thresholds. ROE 18% is
    # great in Utilities, weak in IT. This nudges score based on sector context.
    if sector_stats and sector and sector in sector_stats:
        from . import sector_stats as ssmod
        sector_data = sector_stats[sector]

        # For "higher is better" metrics
        for metric, value, label in (
            ("roe", roe, "ROE"),
            ("revenue_growth", rg, "revenue growth"),
            ("earnings_growth", eg_for_scoring, "EPS growth"),
            ("profit_margin", pm, "profit margin"),
        ):
            bucket = ssmod.percentile_bucket(value, sector_data.get(metric))
            if bucket == "top":
                score += 0.3
                notes.append(f"{label} in TOP quartile of {sector}")
            elif bucket == "bottom":
                score -= 0.3
                notes.append(f"{label} in BOTTOM quartile of {sector}")

        # For "lower is better" metrics (PE, leverage), inverted
        for metric, value, label, skip_if_sector_leveraged in (
            ("trailing_pe", pe_for_valuation, "P/E", False),
            ("debt_to_equity", de, "D/E", True),
        ):
            if skip_if_sector_leveraged and sector in LEVERAGE_NATURAL_SECTORS:
                continue
            bucket = ssmod.percentile_bucket(value, sector_data.get(metric))
            if bucket == "bottom":
                score += 0.3
                notes.append(f"{label} in BOTTOM quartile of {sector} (cheap/clean)")
            elif bucket == "top":
                score -= 0.3
                notes.append(f"{label} in TOP quartile of {sector} (expensive/leveraged)")

        # Cross-sectional momentum: did this stock lead or lag its sector?
        # In a sector rally, even mediocre stocks ride up — only relative
        # outperformers get the bonus. Captures true alpha vs index-following.
        mom_bucket = ssmod.percentile_bucket(return_30d_pct, sector_data.get("return_30d_pct"))
        if mom_bucket == "top":
            score += 0.5
            notes.append(f"30d return in TOP quartile of {sector} (relative strength leader)")
        elif mom_bucket == "bottom":
            score -= 0.5
            notes.append(f"30d return in BOTTOM quartile of {sector} (relative weakness)")

    score = max(-3.0, min(3.0, score))

    fair_pe_target = _fair_pe(sector, eg_for_scoring)

    return FundamentalSnapshot(
        trailing_pe=pe,
        forward_pe=fpe,
        price_to_book=pb,
        roe=roe,
        roce=roce,
        debt_to_equity=de,
        earnings_growth=eg,
        revenue_growth=rg,
        profit_margin=pm,
        dividend_yield=dy,
        market_cap=mcap,
        market_cap_cr=market_cap_cr,
        book_value=book_value,
        forward_eps=feps,
        trailing_eps=teps,
        sales_growth_history=sales_growth_history,
        profit_growth_history=profit_growth_history,
        fair_pe_target=fair_pe_target,
        score=score,
        notes=notes,
    )


def _fair_pe(sector: Optional[str], earnings_growth: Optional[float]) -> float:
    base = {
        "Financial Services": 18,
        "Technology": 28,
        "Industrials": 22,
        "Consumer Cyclical": 24,
        "Consumer Defensive": 32,
        "Communication Services": 20,
        "Healthcare": 30,
        "Energy": 14,
        "Basic Materials": 18,
        "Utilities": 16,
        "Real Estate": 20,
    }.get(sector or "", 22)

    if earnings_growth is not None:
        if earnings_growth >= 0.30:
            base *= 1.25
        elif earnings_growth >= 0.15:
            base *= 1.10
        elif earnings_growth < 0:
            base *= 0.75
    return base
