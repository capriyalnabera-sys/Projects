"""Regression checks for the Nov-2026 audit fixes and the results index.

    python scripts/_smoke_audit_fixes.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    if not cond:
        failures.append(name)


def main():
    from src import batch, fundamentals, recommend, technical, universe, fno_signals

    # --- results index -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rows = [{"ticker": f"T{i}", "verdict": "HOLD", "combined_score": i / 10} for i in range(50)]
        for r in rows:
            batch.write_result(r, root)
        batch.write_result({"ticker": "JUNK", "name": "no verdict"}, root)
        tks = [r["ticker"] for r in rows] + ["JUNK", "MISSING"]
        got = batch.read_universe(tks, root)
        check("index: rows in order, junk/missing skipped", [r["ticker"] for r in got] == tks[:50])
        check("index file written", (root / "analysis" / "_index.pkl").exists())
        time.sleep(0.01)
        batch.write_result({"ticker": "T3", "verdict": "BUY", "combined_score": 2.0}, root)
        check("index: changed file picked up", batch.read_results(["T3"], root)["T3"]["verdict"] == "BUY")
        got[0]["spark_points"] = "x"
        check("index: returned rows are copies", "spark_points" not in batch.read_results(["T0"], root)["T0"])
        batch.cache_path("T4", root).unlink()
        check("index: deleted file disappears", "T4" not in batch.read_results(["T4"], root))
        check("compact JSON", "\n" not in batch.cache_path("T1", root).read_text())

    # --- D/E and dividend units -------------------------------------------
    f = fundamentals.analyze({"debtToEquity": 35.2, "dividendYield": 0.45, "trailingPE": 20,
                              "returnOnEquity": 0.2, "profitMargins": 0.1}, "Industrials")
    check("Yahoo D/E percent → ratio", abs(f.debt_to_equity - 0.352) < 1e-9)
    check("Yahoo dividend yield percent → fraction", abs(f.dividend_yield - 0.0045) < 1e-9)
    f2 = fundamentals.analyze({"debtToEquity": 2.9, "trailingPE": 20, "returnOnEquity": 0.2,
                               "profitMargins": 0.1}, "Industrials")
    check("tiny Yahoo D/E (2.9%) is low leverage", any("Low leverage" in n for n in f2.notes))

    # --- targets only on positive verdicts --------------------------------
    hist = pd.DataFrame({"Open": np.linspace(100, 104, 300), "High": np.linspace(101, 105, 300),
                         "Low": np.linspace(99, 103, 300), "Close": np.linspace(100, 104, 300),
                         "Volume": np.full(300, 1e6)},
                        index=pd.date_range("2025-08-01", periods=300, freq="B"))
    tech = technical.analyze(hist)
    fs = fundamentals.FundamentalSnapshot(None, None, None, None, notes=[])
    rec = recommend.recommend(tech, fs, {}, 104.0)
    check("HOLD carries no trade target/upside",
          rec.verdict != "HOLD" or (rec.trade_target is None and rec.upside_pct is None))

    # --- universe: NSE list loss keeps the last good list -----------------
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "_all_listed.json").write_text(json.dumps(["RELIANCE", "TCS", "ABC.BO"]))
        (d / "_bse_equity_all.json").write_text(json.dumps([{"scrip_id": "RELIANCE", "isin": "X"}]))
        old = time.time() - 30 * 86400
        os.utime(d / "_bse_equity_all.json", (old, old))
        import requests
        real_get = requests.get
        requests.get = lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("blocked"))
        from src import exchange_prices as ep
        real_recent = ep.recent_symbols
        ep.recent_symbols = lambda *a, **k: set()
        try:
            out = universe.get_all_listed(d)
        finally:
            requests.get = real_get
            ep.recent_symbols = real_recent
        check("NSE unreachable → previous list kept, not a BSE-only one",
              out == ["RELIANCE", "TCS", "ABC.BO"])
        check("stale BSE cache used when refetch fails",
              universe._fetch_bse_all(d) == [{"scrip_id": "RELIANCE", "isin": "X"}])

    # --- F&O spreads never collapse to one strike ------------------------
    a = fno_signals.FnoAnalysis.__new__(fno_signals.FnoAnalysis)
    a.atm_iv, a.vix, a.atm_strike, a.spot, a.lot, a.days_to_expiry = 12.0, 13.0, 25000, 25000, 75, 2
    a.resistances = [{"strike": 25000, "oi": 9}, {"strike": 25300, "oi": 5}]
    a.supports = [{"strike": 25000, "oi": 9}, {"strike": 24700, "oi": 5}]
    ok = True
    for bias in ("BULLISH", "BEARISH", "RANGE-BOUND"):
        a.bias = bias
        for s in fno_signals.suggest_strategies(a, 50):
            strikes = [leg.split()[1] for leg in s["legs"]]
            if len(strikes) == 2 and strikes[0] == strikes[1]:
                ok = False
    check("spreads have two distinct strikes when walls sit at ATM", ok)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("exception")
    print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED: {failures}", flush=True)
    os._exit(1 if failures else 0)
