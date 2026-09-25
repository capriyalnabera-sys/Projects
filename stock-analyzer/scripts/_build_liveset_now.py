"""Build the live-set directly from the analyzed files on disk — robust against
the status-file scramble. Reads the full NSE+BSE universe, keeps names that
have an analysis result AND cleared the ₹1cr/day liquidity floor."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import batch, universe  # noqa: E402

cache_root = ROOT / "data/cache"
cache_dir = cache_root / "universe"

full = universe.get_all_listed(cache_dir)
print(f"Full universe: {len(full)}")

analyzed = sum(1 for t in full if batch.read_result(t, cache_root))
print(f"Analyzed (have a result on disk): {analyzed}")

live = batch.compute_live_set(full, cache_root)
print(f"Live set (had data + cleared ₹1cr floor): {len(live)}")

# Composition
bo_live = [t for t in live if t.endswith(".BO")]
print(f"  NSE-line live: {len(live) - len(bo_live)}")
print(f"  BSE-only live: {len(bo_live)}")

universe.save_live_set(live, cache_dir)
print("\nsaved -> data/cache/universe/_live_set.json")
reloaded = universe.load_live_set(cache_dir)
print(f"reload check: {len(reloaded or [])} tickers")
