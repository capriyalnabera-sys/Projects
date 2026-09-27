"""Offline smoke test for the F&O tracking stack: history recording + dedup,
intraday shift analysis, signal-change alerts, and the backtest.
Run:  python scripts/_smoke_fno_track.py   (no network needed)
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _smoke_fno as fix  # noqa: E402  (chain fixture builder)
from src import fno, fno_signals, fno_history, fno_alerts, fno_accuracy  # noqa: E402

# Sandbox the on-disk state so the test never touches real history.
TMP = ROOT / "data" / "cache" / "fno" / "_smoke_tmp"
shutil.rmtree(TMP, ignore_errors=True)
fno_history.HISTORY_DIR = TMP / "history"
fno_alerts.STATE_PATH = TMP / "alert_state.json"
fno_alerts.ALERTS_PATH = TMP / "alerts.json"


def analysis_for(scenario, spot_change, tech, vix, as_of):
    chain = fno.parse_nse_chain(fix.build_raw(scenario), "NIFTY")
    chain["as_of"] = as_of
    return fno_signals.analyze_chain(chain, None, spot_change, tech, vix)


def main():
    # --- history recording + as_of dedup --------------------------------
    a1 = analysis_for("range", 0.0, 0.1, 12.0, "26-Sep-2026 09:30:00")
    assert fno_history.maybe_record(a1) is True
    assert fno_history.maybe_record(a1) is False, "same as_of must dedup"
    a2 = analysis_for("bullish", 0.6, 1.8, 13.0, "26-Sep-2026 11:00:00")
    assert fno_history.maybe_record(a2) is True
    a3 = analysis_for("bullish", 0.9, 1.9, 12.5, "26-Sep-2026 14:30:00")
    assert fno_history.maybe_record(a3) is True
    recs = fno_history.intraday("NIFTY")
    assert len(recs) == 3, recs
    print(f"history: 3 snapshots recorded, dedup works")

    # --- intraday shifts -------------------------------------------------
    shifts = fno_history.intraday_shifts(recs)
    assert shifts["available"] and shifts["count"] == 3
    texts = " | ".join(c["text"] for c in shifts["changes"])
    assert "PCR" in texts, texts                      # range→bullish moves PCR up
    assert "Signal flipped" in texts, texts           # RANGE-BOUND → BULLISH
    assert len(shifts["series"]["spot"]) == 3
    pts = fno_history.spark_points(shifts["series"]["pcr"])
    assert pts.count(",") == 3 and " " in pts
    print(f"shifts: {len(shifts['changes'])} readings — {texts[:90]}…")

    # --- alerts: first sight no alert, flip alerts, repeat silent --------
    assert fno_alerts.check_and_notify(a1) is None, "first observation must not alert"
    al = fno_alerts.check_and_notify(a2)
    assert al and al["from"] == "RANGE-BOUND" and al["to"] == "BULLISH", al
    assert fno_alerts.check_and_notify(a3) is None, "unchanged bias must not re-alert"
    assert fno_alerts.recent_alerts()[0]["to"] == "BULLISH"
    print(f"alerts: fired on flip {al['from']} → {al['to']}, silent otherwise")

    # --- backtest with synthetic closes ----------------------------------
    # Three past days: bullish (market rose → hit), bearish (rose → miss),
    # range with expiry inside the series (stayed inside ±1.44% → hit).
    days = ["2026-09-01", "2026-09-02", "2026-09-03"]
    scen = ["bullish", "bearish", "range"]
    for day, sc in zip(days, scen):
        a = analysis_for(sc, 0.5 if sc == "bullish" else -0.6 if sc == "bearish" else 0.0,
                         1.8 if sc == "bullish" else -1.8 if sc == "bearish" else 0.1,
                         13.0, f"{day} 15:30:00")
        a.expiry = "04-Sep-2026"
        rec = fno_history._to_record(a)
        rec["ts"] = f"{day}T15:30:00+05:30"
        p = fno_history._day_path("NIFTY", day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(__import__("json").dumps({"records": [rec]}))
    spot = fix.SPOT
    closes = {
        "2026-09-01": spot, "2026-09-02": spot * 1.004,   # +0.4% after day 1
        "2026-09-03": spot * 1.009, "2026-09-04": spot * 1.006,
        "2026-09-05": spot * 1.010, "2026-09-08": spot * 1.012,
    }
    t = fno_accuracy.evaluate("NIFTY", closes={k: round(v, 2) for k, v in closes.items()})
    d = t["directional"]
    assert d["n"] == 2 and d["hit_rate_1d"] == 50.0, d      # bull hit, bear miss
    assert t["range"]["n"] == 1 and t["range"]["hit_rate"] == 100.0, t["range"]
    outcomes = {o["day"]: o["outcome"] for o in t["recent"]}
    assert outcomes["2026-09-01"] == "hit" and outcomes["2026-09-02"] == "miss"
    assert outcomes["2026-09-03"] == "hit"
    print(f"backtest: directional 1/2 hit (as constructed), range 1/1 held; "
          f"avg signed move {d['avg_signed_move_1d_pct']:+.2f}%")

    # --- market-hours helper ---------------------------------------------
    from datetime import datetime
    ist = fno_history.IST
    assert fno_history.is_market_hours(datetime(2026, 9, 25, 10, 0, tzinfo=ist))
    assert not fno_history.is_market_hours(datetime(2026, 9, 25, 16, 0, tzinfo=ist))
    assert not fno_history.is_market_hours(datetime(2026, 9, 27, 10, 0, tzinfo=ist))  # Sunday
    print("market-hours gate correct (weekday 09:15–15:35 IST)")

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nAll F&O tracking smoke checks passed.")


if __name__ == "__main__":
    main()
