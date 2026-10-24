"""Offline smoke test for the Opportunities scanners — no network needed.
Run:  python scripts/_smoke_opportunities.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import opportunities as opp  # noqa: E402


def row(ticker, **kw):
    """Baseline liquid, healthy stock that matches NO scanner by default."""
    base = dict(
        ticker=ticker, name=f"{ticker} Ltd", sector="Industrials",
        last_close=500.0, day_change_pct=0.5, verdict="HOLD", raw_verdict="HOLD",
        combined_score=0.2, technical_score=0.2, fundamental_score=0.5,
        telegram_score=0.0, trade_target=550.0, stop_loss=460.0,
        upside_pct=10.0, downside_pct=-8.0, rsi_14=52.0, sma_50=490.0,
        sma_200=470.0, high_52w=600.0, low_52w=380.0, atr_14=10.0,
        volume_ratio=1.0, avg_daily_value_cr=12.0, return_30d_pct=2.0,
        trailing_pe=28.0, forward_pe=24.0, price_to_book=4.0, roe=0.12,
        roce=0.13, debt_to_equity=0.8, earnings_growth=0.05, revenue_growth=0.06,
        profit_margin=0.08, dividend_yield=0.01, market_cap_cr=4000.0,
        tg_mentions=0, tg_avg_sentiment=0.0, track_record=None, rationale=[],
    )
    base.update(kw)
    return base


ROWS = [
    # One engineered hit per scanner -------------------------------------
    row("BRKOUT", market_cap_cr=5000, last_close=990, high_52w=1000, volume_ratio=2.2,
        sma_200=900, sma_50=950, rsi_14=65, day_change_pct=2.0, verdict="BUY",
        upside_pct=10, downside_pct=-5, avg_daily_value_cr=20, low_52w=700,
        trade_target=1089, stop_loss=940),
    row("PULLBK", sma_50=500, sma_200=450, last_close=505, high_52w=600, rsi_14=42,
        return_30d_pct=-5, volume_ratio=0.8, day_change_pct=-1.0, verdict="ACCUMULATE",
        upside_pct=12, downside_pct=-5, avg_daily_value_cr=15, combined_score=1.4,
        trade_target=565, stop_loss=480),
    row("WASHOT", market_cap_cr=3000, rsi_14=28, roe=0.22, roce=0.20, debt_to_equity=0.3,
        fundamental_score=1.5, profit_margin=0.12, earnings_growth=0.05,
        return_30d_pct=-15, high_52w=1000, last_close=780, low_52w=600,
        day_change_pct=-2.0, verdict="HOLD", raw_verdict="HOLD", upside_pct=20,
        downside_pct=-8, avg_daily_value_cr=12, sma_50=820, sma_200=850,
        trade_target=936, stop_loss=718, dividend_yield=0.015),
    row("COMPND", tg_mentions=0, revenue_growth=0.15, earnings_growth=0.20, roce=0.25,
        debt_to_equity=0.2, trailing_pe=20, market_cap_cr=8000, rsi_14=50,
        upside_pct=25, downside_pct=-10, sma_200=400, last_close=450, verdict="BUY",
        avg_daily_value_cr=6, high_52w=500, trade_target=562, stop_loss=405),
    row("YIELDR", dividend_yield=0.035, trailing_pe=12, price_to_book=2.0, roce=0.18,
        debt_to_equity=0.3, profit_margin=0.10, earnings_growth=0.02, sma_200=300,
        last_close=310, high_52w=400, rsi_14=48, verdict="HOLD", upside_pct=10,
        downside_pct=-6, avg_daily_value_cr=10, trade_target=341, stop_loss=291),
    row("BUZZED", market_cap_cr=6000, tg_mentions=5, tg_avg_sentiment=0.6,
        telegram_score=1.5, return_30d_pct=3.0, verdict="BUY", combined_score=1.6,
        fundamental_score=0.5, sma_50=200, last_close=210, rsi_14=60,
        upside_pct=16, downside_pct=-7, avg_daily_value_cr=15, sma_200=190,
        trade_target=244, stop_loss=195),
    # Noise that must match nothing ---------------------------------------
    row("AVOIDX", verdict="AVOID", raw_verdict="AVOID", combined_score=-2.5),
    row("ILLIQD", avg_daily_value_cr=0.3, verdict="BUY", combined_score=2.0),
    {"ticker": "NULLSX", "name": "Nulls Ltd"},  # nulls everywhere — must not crash
]


def ids_with(result, ticker):
    return [s["id"] for s in result["scanners"]
            if any(c["ticker"] == ticker for c in s["candidates"])]


def main():
    # --- neutral regime: each engineered row hits its scanner -------------
    r = opp.scan(ROWS, regime={"state": "neutral"}, fno_bias="NEUTRAL")
    assert r["has_rows"] and r["total_candidates"] >= 6, r["total_candidates"]
    expect = {"BRKOUT": "fresh_highs_breakout", "PULLBK": "leader_pullback",
              "WASHOT": "quality_washout", "COMPND": "forgotten_compounder",
              "YIELDR": "paid_to_wait", "BUZZED": "quiet_accumulation"}
    for t, sid in expect.items():
        hits = ids_with(r, t)
        assert sid in hits, f"{t} missed {sid} (got {hits})"
    for t in ("AVOIDX", "ILLIQD", "NULLSX"):
        assert not ids_with(r, t), f"{t} should match nothing"
    print("neutral: all 6 engineered setups matched; noise/null rows excluded")

    # --- scores + top strip -----------------------------------------------
    scores = [c["opp_score"] for c in r["top"]]
    assert all(0 <= s <= 100 for s in scores)
    assert scores == sorted(scores, reverse=True), "top not sorted"
    assert all(c["band"] in ("Prime", "Strong", "Decent") for c in r["top"])
    tickers_in_top = [c["ticker"] for c in r["top"]]
    assert len(tickers_in_top) == len(set(tickers_in_top)), "top strip must dedupe"
    buz = next(c for c in r["top"] if c["ticker"] == "BUZZED")
    assert buz["reasons"] and buz["rr"] and buz["setup_title"]
    print(f"scores: top strip {scores} — sorted, deduped, banded")

    # --- regime behavior ---------------------------------------------------
    ro = opp.scan(ROWS, regime={"state": "risk_off"})
    assert ro["scanners"][0]["id"] == "quality_washout", "risk_off must lead defensive"
    washot_ro = ids_with(ro, "WASHOT")
    assert "quality_washout" not in washot_ro, "mcap 3000 < 5000 risk_off floor must drop it"
    assert "fresh_highs_breakout" in ids_with(ro, "BRKOUT"), "BRKOUT meets tightened risk_off gates"
    rn = opp.scan(ROWS, regime={"state": "risk_on"})
    assert rn["scanners"][0]["id"] == "fresh_highs_breakout", "risk_on must lead procyclical"
    # Regime multiplier: BRKOUT (procyclical-only) scores lower in risk_off than risk_on.
    def score_of(res, t):
        for c in res["top"]:
            if c["ticker"] == t:
                return c["opp_score"]
        return None
    s_off, s_on = score_of(ro, "BRKOUT"), score_of(rn, "BRKOUT")
    assert s_off is not None and s_on is not None and s_off < s_on, (s_off, s_on)
    print(f"regime: card order flips; BRKOUT score {s_off} (risk_off) < {s_on} (risk_on)")

    # --- empty input --------------------------------------------------------
    empty = opp.scan([], regime=None)
    assert not empty["has_rows"] and empty["total_candidates"] == 0
    assert opp.nifty_fno_bias() is None or isinstance(opp.nifty_fno_bias(), str)
    print("empty input + fno-bias accessor safe")

    print("\nAll Opportunities smoke checks passed.")


if __name__ == "__main__":
    main()
