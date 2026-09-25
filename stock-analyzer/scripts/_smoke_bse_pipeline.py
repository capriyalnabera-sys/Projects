"""Confirm a BSE-only .BO ticker flows through the full analysis pipeline."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import batch, universe, data  # noqa: E402
import yaml  # noqa: E402

cache_root = ROOT / "data/cache"
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) if (ROOT / "config.yaml").exists() else {}

allt = universe.get_all_listed(cache_root / "universe")
bo = [t for t in allt if t.endswith(".BO")]

# Pre-fetch a chunk to find ones yfinance actually has data for
sample = bo[:40]
print(f"Testing yfinance resolution on {len(sample)} BSE-only names...")
hist = data.bulk_fetch_histories(sample, period="6mo")
resolved = [t for t in sample if t.upper() in hist]
print(f"  resolved with data: {len(resolved)} / {len(sample)}")
print(f"  e.g. {resolved[:6]}")

# Run the full analyze_one on the first 3 resolved
print("\nFull pipeline on first 3 resolved BSE-only names:")
for t in resolved[:3]:
    try:
        res = batch.analyze_one(t, cfg, cache_root, prefetched_history=hist.get(t.upper()))
        if res:
            print(f"  {t:16s} verdict={res.get('verdict'):11s} "
                  f"score={res.get('combined_score'):+.2f} "
                  f"close={res.get('last_close')} "
                  f"adv_cr={res.get('avg_daily_value_cr')}")
        else:
            print(f"  {t:16s} -> no result")
    except Exception as e:
        print(f"  {t:16s} -> ERR {e}")
