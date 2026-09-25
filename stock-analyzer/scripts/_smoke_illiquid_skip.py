"""Verify the illiquid short-circuit: illiquid name returns HOLD without
the .info/screener/earnings network calls; liquid name still gets full analysis."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import batch, data  # noqa: E402
import yaml  # noqa: E402

cache_root = ROOT / "data/cache"
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

# Illiquid BSE name (adv ~0.008 cr) vs a liquid NSE name
illiquid = "ANSALAPI.BO"
liquid = "RELIANCE"

hist = data.bulk_fetch_histories([illiquid, liquid], period="6mo")

for tk in (illiquid, liquid):
    h = hist.get(tk.upper())
    if h is None:
        print(f"{tk}: no history")
        continue
    t0 = time.time()
    res = batch.analyze_one(tk, cfg, cache_root, prefetched_history=h)
    dt = time.time() - t0
    if res:
        print(f"{tk:14s} verdict={res.get('verdict'):5s} "
              f"adv_cr={res.get('avg_daily_value_cr'):.4f} "
              f"illiquid_skipped={res.get('illiquid_skipped', False)} "
              f"took={dt:.2f}s "
              f"(fund_populated: pe={res.get('trailing_pe')}, roe={res.get('roe')})")
    else:
        print(f"{tk}: no result")
