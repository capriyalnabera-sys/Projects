"""Verify the live-set mechanism end-to-end against the EXISTING cache,
without waiting for a 25-min full sweep.

1. compute_live_set over a mix of cached-liquid NSE names + fake BSE shells
   → should keep only the liquid ones.
2. save → load round-trip.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import batch, universe  # noqa: E402

cache_root = ROOT / "data/cache"
cache_dir = cache_root / "universe"

# Grab some tickers that ARE cached from the last NIFTY batch
nifty = universe.get_universe("nifty100", cache_dir=cache_dir)
cached = [t for t in nifty if batch.read_result(t, cache_root)][:20]
print(f"Sample cached NIFTY tickers: {len(cached)}")

# Add fake BSE-only shells that have no cache at all
fakes = ["NONEXIST1.BO", "NONEXIST2.BO", "DEADSHELL.BO"]
test_universe = cached + fakes

live = batch.compute_live_set(test_universe, cache_root)
print(f"\ncompute_live_set({len(test_universe)} in) -> {len(live)} live")
print(f"  fakes excluded? {not any(f in live for f in fakes)}")

# Show turnover of a few to confirm the floor is applied
print("\n  liquidity check (avg_daily_value_cr) on first 5 cached:")
for t in cached[:5]:
    r = batch.read_result(t, cache_root)
    adv = r.get("avg_daily_value_cr") if r else None
    kept = "KEPT" if t in live else "dropped"
    print(f"    {t:14s} adv={adv} -> {kept}")

# Round-trip
universe.save_live_set(live, cache_dir)
reloaded = universe.load_live_set(cache_dir)
print(f"\nsave/load round-trip: saved {len(live)} -> loaded {len(reloaded) if reloaded else 0}")
print(f"  match? {set(live) == set(reloaded or [])}")

# Clean up — restore empty so we don't leave a stale partial live-set
universe.save_live_set([], cache_dir)
print("\n(reset live-set to empty so a real full sweep rebuilds it cleanly)")
