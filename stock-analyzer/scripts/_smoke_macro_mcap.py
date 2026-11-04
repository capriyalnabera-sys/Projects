"""Offline checks: macro factor maths, sector tilt, recommend integration,
input-key fingerprint, and the market-cap universe filter.

    python scripts/_smoke_macro_mcap.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta
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
    from src import macro, recommend, batch, mcap
    from src.technical import TechnicalSnapshot  # noqa: F401
    from src.fundamentals import FundamentalSnapshot

    # --- factor maths ------------------------------------------------------
    idx = pd.date_range("2026-05-01", periods=120, freq="B")
    crude = pd.Series(np.linspace(100, 80, 120), index=idx)        # -20% → sharply down
    f = macro._factor_from_series("crude", crude)
    check("crude falling 20% over 6m → negative move", f["move"] < -0.5 and f["trend"].endswith("down"))
    tnx = pd.Series(np.linspace(4.0, 4.6, 120), index=idx)          # +0.6 pts
    f2 = macro._factor_from_series("us10y", tnx)
    check("yield up 0.6 pts → positive move (abs units)", f2["move"] > 0.5 and f2["unit"] == "abs")

    prices = {"crude": f, "us10y": f2,
              "usdinr": {"key": "usdinr", "label": "USD/INR", "unit": "pct", "move": 1.0,
                         "change_3m": 3.0, "trend": "sharply up"}}
    snap = macro.build_snapshot(prices, fii={"fii_net_cr": -3000, "dii_net_cr": 2500},
                                repo_trend="cutting")
    check("rates factor derived from US10Y + RBI", "rates" in snap["factors"])
    check("FII factor parsed", snap["factors"]["fii"]["move"] == -1.0)

    paints = macro.stock_impact(snap, "Basic Materials", "Specialty Chemicals")
    airline = macro.stock_impact(snap, "Industrials", "Airlines")
    it = macro.stock_impact(snap, "Technology", "Information Technology Services")
    upstream = macro.stock_impact(snap, "Energy", "Oil & Gas E&P")
    check("falling crude is a tailwind for paints/chemicals", paints["score"] > 0)
    check("airlines mapped and crude tailwind", airline["group"] == "Airlines" and airline["score"] > 0)
    check("weak rupee helps IT", it["score"] > 0 and it["group"].startswith("IT"))
    check("falling crude hurts oil producers", upstream["score"] < 0)
    check("sector fallback (Healthcare)", macro.group_for("Healthcare", "")[0].startswith("Pharma"))
    check("no sector → no tilt", macro.stock_impact(snap, None, None)["score"] == 0)
    check("score clipped", all(abs(macro.stock_impact(snap, g[2][0] if g[2] else "x", g[1][0])["score"])
                               <= macro.MAX_STOCK_SCORE for g in macro.GROUPS))
    check("note explains drivers", "tailwind" in (paints["note"] or ""))
    check("sector table sorted", [r["score"] for r in macro.sector_table(snap)] ==
          sorted([r["score"] for r in macro.sector_table(snap)], reverse=True))

    # --- recommend integration --------------------------------------------
    hist = pd.DataFrame({"Open": np.linspace(100, 130, 300), "High": np.linspace(101, 131, 300),
                         "Low": np.linspace(99, 129, 300), "Close": np.linspace(100, 130, 300),
                         "Volume": np.full(300, 1e6)},
                        index=pd.date_range("2025-08-01", periods=300, freq="B"))
    from src import technical
    tech = technical.analyze(hist)
    fund = FundamentalSnapshot(0.5, 20.0, 0.18, 30.0, notes=[])
    base = recommend.recommend(tech, fund, {}, 130.0)
    with_m = recommend.recommend(tech, fund, {}, 130.0, macro=snap,
                                 sector="Basic Materials", industry="Specialty Chemicals")
    delta = with_m.combined_score - base.combined_score
    check("macro adds weighted tilt to combined score",
          abs(delta - paints["score"] * 0.25) < 1e-6 and with_m.macro_score == paints["score"])
    check("[M] rationale line", any(x.startswith("[M] Macro +") for x in with_m.rationale))
    off = recommend.recommend(tech, fund, {"macro_weight": 0}, 130.0, macro=snap,
                              sector="Basic Materials", industry="Specialty Chemicals")
    check("macro_weight 0 disables tilt", abs(off.combined_score - base.combined_score) < 1e-9)

    # --- fingerprint feeds skip-unchanged ---------------------------------
    k1 = batch.input_key(hist, {"state": "neutral"}, {}, snap)
    snap2 = macro.build_snapshot({**prices, "crude": {**f, "move": 1.5}}, None, "cutting")
    k2 = batch.input_key(hist, {"state": "neutral"}, {}, snap2)
    check("macro change invalidates input key", k1 != k2)
    check("same macro → same key", k1 == batch.input_key(hist, {"state": "neutral"}, {}, snap))

    # --- market-cap filter -------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        from src import data
        data.INFO_CACHE_DIR = root / "yf_info"
        data.INFO_CACHE_DIR.mkdir()
        # BIGCO: info cached on disk (no network); MIDCO: from a past analysis;
        # SMALL: fetched; NOINFO: Yahoo has nothing.
        (data.INFO_CACHE_DIR / "BIGCO.json").write_text(json.dumps({"sharesOutstanding": 1e9}))
        batch.write_result({"ticker": "MIDCO", "market_cap_cr": 800.0, "last_close": 100.0}, root)
        calls = []

        def fake_fetch_info(tk):
            calls.append(tk)
            (data.INFO_CACHE_DIR / f"{tk}.json").write_text("{}")   # Yahoo answered
            return {"SMALL": {"marketCap": 2e9, "currentPrice": 20.0}, "NOINFO": {}}.get(tk, {})
        data.fetch_info = fake_fetch_info
        closes = {"BIGCO": 50.0, "MIDCO": 110.0, "SMALL": 20.0, "NOINFO": 5.0, "IDX": 10.0}
        tks = ["BIGCO", "MIDCO", "SMALL", "NOINFO", "IDX"]
        reg = mcap.update(tks, closes, root)
        check("disk-known share counts need no network", "BIGCO" not in calls and "MIDCO" not in calls)
        keep, stats = mcap.eligible(tks, reg, closes, 500, always={"IDX"})
        # BIGCO 1e9×50/1e7 = 5000 cr ✓ ; MIDCO 8e7 sh ×110 = 880 cr ✓ ; SMALL 1e8×20 = 200 cr ✗
        check("≥₹500 cr kept, below dropped, index member kept",
              keep == ["BIGCO", "MIDCO", "IDX"] and stats["below_min"] == 1 and stats["unknown"] == 1)
        calls.clear()
        mcap.update(tks, closes, root)
        check("second update makes no network calls (cached)", calls == [])
        reg = mcap.load(root)
        reg["SMALL"]["checked"] = (date.today() - timedelta(days=31)).isoformat()
        mcap.save(root, reg)
        calls.clear()
        mcap.update(tks, closes, root)
        check("share counts re-fetched after 30 days", calls == ["SMALL"])
        check("min cap from config", mcap.min_cap_cr({"universe": {"min_market_cap_cr": 1000}}) == 1000)

        from src import universe
        universe.save_mcap_universe(keep, stats, root / "universe")
        check("ALL UNIVERSE returns the market-cap list",
              universe.get_universe("alllisted", cache_dir=root / "universe") == keep)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("exception")
    print("\nALL PASS" if not failures else f"\n{len(failures)} FAILED: {failures}", flush=True)
    os._exit(1 if failures else 0)
