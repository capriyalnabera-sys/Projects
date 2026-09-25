"""Smoke test: build the full NSE+BSE universe and report composition."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import universe  # noqa: E402

cache_dir = ROOT / "data/cache/universe"

nse = universe._fetch_nse_all(cache_dir)
bse = universe._fetch_bse_all(cache_dir)
print(f"NSE equities (EQ+BE): {len(nse)}")
print(f"BSE active equities:  {len(bse)}")

allt = universe.get_all_listed(cache_dir)
bo = [t for t in allt if t.endswith(".BO")]
ns = [t for t in allt if not t.endswith(".BO")]
print(f"\nUnion total:    {len(allt)}")
print(f"  NSE-line:     {len(ns)}")
print(f"  BSE-only(.BO):{len(bo)}")
print(f"\nSample NSE: {ns[:8]}")
print(f"Sample BSE-only: {bo[:8]}")

# sanity: no plain symbol collides with a .BO of the same base
ns_set = set(ns)
collisions = [t for t in bo if t[:-3] in ns_set]
print(f"\nBase-symbol overlaps NSE has (expected, dual-list handled by ISIN): {len(collisions)} (these are still distinct tickers)")
