"""Offline smoke test for the F&O module — no network needed.

Builds raw NSE-shaped option-chain JSON for three market scenarios, runs the
full parse → analytics → signal pipeline, and asserts the outputs make sense.
Run:  python scripts/_smoke_fno.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import fno, fno_signals  # noqa: E402


SPOT = 25012.5
STEP = 50
EXPIRY = (datetime.now() + timedelta(days=5)).strftime("%d-%b-%Y")
FAR_EXPIRY = (datetime.now() + timedelta(days=33)).strftime("%d-%b-%Y")


def leg(oi, chg, vol, iv, ltp):
    return {"openInterest": oi, "changeinOpenInterest": chg,
            "totalTradedVolume": vol, "impliedVolatility": iv,
            "lastPrice": ltp, "bidprice": ltp * 0.99, "askPrice": ltp * 1.01}


def build_raw(scenario: str) -> dict:
    """Raw NSE option-chain-indices JSON, 25 strikes around ATM 25000."""
    atm = 25000
    data = []
    for i in range(-12, 13):
        k = atm + i * STEP
        dist = abs(i)
        # Premiums decay away from ATM; IV smiles upward at the wings.
        ce_ltp = max(2.0, 180 - i * 42) if i >= 0 else max(2.0, 180 + abs(i) * 45)
        pe_ltp = max(2.0, 180 + i * 42) if i <= 0 else max(2.0, 180 - i * 45)
        iv = 12.0 + 0.35 * dist

        base_ce_oi = 60_000 + 4_000 * dist
        base_pe_oi = 60_000 + 4_000 * dist
        ce_chg, pe_chg = 1_000, 1_000

        if scenario == "bullish":
            # Put wall at 24800, thin calls; fresh put writing across the board.
            if k <= atm:
                base_pe_oi = 190_000 if k == 24800 else 120_000
                pe_chg = 22_000
            if k >= atm:
                base_ce_oi = 70_000 if k != 25400 else 110_000
                ce_chg = -3_000
        elif scenario == "bearish":
            if k >= atm:
                base_ce_oi = 200_000 if k == 25200 else 130_000
                ce_chg = 24_000
            if k <= atm:
                base_pe_oi = 65_000 if k != 24600 else 100_000
                pe_chg = -4_000
        elif scenario == "range":
            if k == 24700:
                base_pe_oi = 210_000
            if k == 25300:
                base_ce_oi = 205_000
            ce_chg = 15_000 if k >= atm else 1_000
            pe_chg = 14_000 if k <= atm else 1_000

        data.append({
            "strikePrice": k, "expiryDate": EXPIRY,
            "CE": leg(base_ce_oi, ce_chg, base_ce_oi // 3, iv, round(ce_ltp, 1)),
            "PE": leg(base_pe_oi, pe_chg, base_pe_oi // 3, iv + (1.5 if scenario != "bullish" else -0.5), round(pe_ltp, 1)),
        })
    # A second expiry that must be filtered out by the parser.
    data.append({"strikePrice": atm, "expiryDate": FAR_EXPIRY,
                 "CE": leg(9_999_999, 0, 1, 14, 400), "PE": leg(9_999_999, 0, 1, 14, 400)})
    return {"records": {
        "expiryDates": [EXPIRY, FAR_EXPIRY],
        "underlyingValue": SPOT,
        "timestamp": datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
        "data": data,
    }}


def run_scenario(name, spot_change_pct, tech_score, vix):
    raw = build_raw(name)
    chain = fno.parse_nse_chain(raw, "NIFTY")
    assert chain is not None, "parse failed"
    assert chain["expiry"] == EXPIRY, "wrong expiry picked"
    assert len(chain["rows"]) == 25, f"expected 25 rows, got {len(chain['rows'])}"
    assert all(r["strike"] != 9_999_999 for r in chain["rows"])

    a = fno_signals.analyze_chain(chain, None, spot_change_pct, tech_score, vix)
    js = json.dumps(a.to_dict())  # must be JSON-serializable for the API
    assert len(js) > 500

    print(f"\n=== {name.upper()} (spot {SPOT}, day {spot_change_pct:+.1f}%) ===")
    print(f"  bias={a.bias} score={a.score:+.2f} conf={a.confidence}")
    print(f"  PCR(band)={a.pcr_oi_band} PCR(total)={a.pcr_oi} maxpain={a.max_pain}")
    print(f"  ATM {a.atm_strike} IV={a.atm_iv} straddle={a.straddle_price} "
          f"expmove={a.expected_move_pct}% skew={a.iv_skew}")
    print(f"  supports={[s['strike'] for s in a.supports]} "
          f"resistances={[s['strike'] for s in a.resistances]}")
    print(f"  flow: {a.oi_flow} (CE {a.ce_oi_change:+,} / PE {a.pe_oi_change:+,})")
    print(f"  strategies: {[s['name'] for s in a.strategies]}")
    for line in a.rationale:
        print(f"    • {line}")
    for line in a.cautions:
        print(f"    ! {line}")
    return a


def main():
    assert fno.days_to_expiry(EXPIRY) == 5
    assert fno.parse_expiry_date("30 Sep 2026") is not None  # BSE format
    assert fno.lot_size("NIFTY", {"fno": {"lot_sizes": {"NIFTY": 80}}}) == 80
    assert fno.lot_size("NIFTY") == fno.INDEX_META["NIFTY"]["lot"]

    bull = run_scenario("bullish", +0.6, 1.8, 13.5)
    assert bull.bias == "BULLISH", f"expected BULLISH, got {bull.bias}"
    assert bull.supports and bull.supports[0]["strike"] == 24800, "put wall wrong"
    assert any("Bull" in s["name"] for s in bull.strategies)

    bear = run_scenario("bearish", -0.7, -1.8, 17.0)
    assert bear.bias == "BEARISH", f"expected BEARISH, got {bear.bias}"
    assert bear.resistances and bear.resistances[0]["strike"] == 25200, "call wall wrong"
    assert any("Bear" in s["name"] for s in bear.strategies)

    rng = run_scenario("range", +0.02, 0.1, 12.0)
    assert rng.bias in ("RANGE-BOUND", "NEUTRAL"), f"got {rng.bias}"
    if rng.bias == "RANGE-BOUND":
        assert any("Condor" in s["name"] for s in rng.strategies)

    # Empty chain must not crash.
    empty = fno_signals.analyze_chain(
        {"symbol": "NIFTY", "spot": 0, "rows": [], "expiry": "", "as_of": ""})
    assert empty.bias == "NEUTRAL" and empty.cautions

    print("\nAll F&O smoke checks passed.")


if __name__ == "__main__":
    main()
