"""Offline smoke test for the batch speed-ups — no network needed.

Covers: no-price-data classification, the weekly no-data skip registry,
retrying only transient failures, accurate progress counts, and the bulk
history fetch's second pass for throttled chunks.
Run:  python scripts/_smoke_batch_nodata.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import batch, data  # noqa: E402
from src import exchange_prices  # noqa: E402

# Keep this test on the Yahoo path and away from the real price-file store.
exchange_prices.histories_for = lambda *a, **k: {}

batch.time.sleep = lambda s: None   # retry backoffs are 10s/25s — skip them
data.time.sleep = lambda s: None
REAL_BULK = data.bulk_fetch_histories


def main():
    root = Path(tempfile.mkdtemp(prefix="smoke_batch_"))
    try:
        # --- analyze_one classifies failures -------------------------------
        real_fetch = data.fetch

        def fetch_dead(t, **kw):
            raise data.NoPriceHistory("No price history")

        def fetch_flaky(t, **kw):
            raise ConnectionError("Too Many Requests")

        data.fetch = fetch_dead
        assert batch.analyze_one("DEADCO", {}, root) is batch.NO_DATA
        data.fetch = fetch_flaky
        assert batch.analyze_one("FLAKY", {}, root) is None
        data.fetch = real_fetch
        assert not batch.NO_DATA, "sentinel must be falsy so it is never written"
        print("analyze_one: no-data → NO_DATA, network error → None (retryable)")

        # --- run_batch: registry, retries, progress ------------------------
        calls = {}

        def fake_analyze(t, cfg, cache_root, **kw):
            calls[t] = calls.get(t, 0) + 1
            if t.startswith("DEAD"):
                return batch.NO_DATA
            if t == "FLAKY" and calls[t] == 1:
                return None                      # throttled once, then fine
            return {"ticker": t, "last_close": 100.0, "as_of": "2026-10-28T10:00:00+00:00",
                    "avg_daily_value_cr": 5.0}

        batch.analyze_one = fake_analyze
        data.bulk_fetch_histories = lambda tickers, period="2y": {}
        tickers = ["GOOD1", "GOOD2", "FLAKY", "DEAD1", "DEAD2", "DEAD3"]

        s1 = batch.run_batch(tickers, {}, root)
        assert s1["done"] == 6 and s1["total"] == 6, s1          # progress reaches total
        assert s1["ok"] == 3 and s1["no_data"] == 3 and s1["errors"] == 0, s1
        assert calls["FLAKY"] == 2, "transient failure must be retried"
        assert all(calls[d] == 1 for d in ("DEAD1", "DEAD2", "DEAD3")), \
            "no-data names must NOT be retried"
        reg = batch.load_no_data(root)
        assert set(reg) == {"DEAD1", "DEAD2", "DEAD3"}, reg
        print(f"run 1: done {s1['done']}/{s1['total']}, ok {s1['ok']}, no-data {s1['no_data']}, "
              f"FLAKY retried once, dead names tried once")

        calls.clear()
        s2 = batch.run_batch(tickers, {}, root)
        assert not any(t.startswith("DEAD") for t in calls), f"dead names re-tried: {calls}"
        assert s2["done"] == 6 and s2["no_data"] == 3, s2
        print(f"run 2: dead names skipped via registry (analyzed only {sorted(calls)})")

        # Expired entry (> 7 days old) is rechecked; recovered names leave the registry.
        reg["DEAD1"] = "2000-01-01"
        batch.save_no_data(root, reg)
        calls.clear()

        def recovered(t, cfg, cache_root, **kw):
            calls[t] = calls.get(t, 0) + 1
            if t == "DEAD1":
                return {"ticker": t, "last_close": 50.0, "as_of": "2026-10-28T10:00:00+00:00"}
            return fake_analyze(t, cfg, cache_root, **kw)

        batch.analyze_one = recovered
        batch.run_batch(tickers, {}, root)
        assert calls.get("DEAD1") == 1 and "DEAD1" not in batch.load_no_data(root)
        print("expired no-data entry rechecked; a name that has data again leaves the registry")

        # --- bulk fetch: throttled chunk retried, dropped names re-requested --
        import pandas as pd
        seen = []

        def chunk(tks, period):
            seen.append(list(tks))
            if len(seen) == 1:                   # first call "throttled": empty
                return {}
            if len(seen) == 2:                   # retry returns only some names
                return {t.upper(): pd.DataFrame({"Close": [1.0]}) for t in tks if t == "A"}
            return {t.upper(): pd.DataFrame({"Close": [1.0]}) for t in tks if not t.startswith("X")}

        data._bulk_fetch_chunk = chunk
        res = REAL_BULK(["A", "B", "XDEAD"], "2y")
        assert set(res) == {"A", "B"}, res
        assert seen[2] == ["B", "XDEAD"], f"second pass should re-request only missing names: {seen}"
        print("bulk fetch: empty chunk retried, dropped names re-requested, dead symbol absent")

        print("\nAll batch speed-up smoke checks passed.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
