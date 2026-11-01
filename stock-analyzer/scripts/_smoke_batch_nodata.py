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
# Keep the parallel fundamentals prefetch offline too — and record what it asks.
import threading  # noqa: E402
from src import earnings as _earnings, screener_in as _screener  # noqa: E402
PREFETCH = {"info": [], "earnings": [], "screener": []}
_pf_lock = threading.Lock()


def _rec(kind):
    def fn(t, **kw):
        with _pf_lock:
            PREFETCH[kind].append(t)
        return {} if kind != "earnings" else None
    return fn


data.fetch_info = _rec("info")
_earnings.next_earnings_date = _rec("earnings")
_screener.fetch = _rec("screener")

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

        # --- pipeline: per-server prefetch, overlap, resolved context -------
        import numpy as np
        import pandas as pd
        from concurrent.futures import ThreadPoolExecutor
        idx = pd.bdate_range(end="2026-10-30", periods=60)
        c = np.full(60, 100.0)

        def hist(vol):
            return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                                 "Adj Close": c, "Volume": np.full(60, vol)}, index=idx)

        liquid = ["LIQA", "LIQB", "LIQC.BO"]           # ₹10 Cr/day
        thin = ["THIN1", "THIN2"]                       # ₹0.0001 Cr/day
        hists = {t: hist(1_000_000) for t in liquid}
        hists.update({t: hist(1) for t in thin})
        exchange_prices.histories_for = lambda tickers, *a, **k: dict(hists)
        for k in PREFETCH:
            PREFETCH[k].clear()
        order, seen_regime = [], []
        side = ThreadPoolExecutor(max_workers=2)
        regime_future = side.submit(lambda: {"state": "risk_on"})
        tg_future = side.submit(lambda: {})

        def pipeline_analyze(t, cfg, cache_root, regime=None, **kw):
            seen_regime.append(regime)
            with _pf_lock:
                order.append((t, len(PREFETCH["info"]) + len(PREFETCH["earnings"])
                              + len(PREFETCH["screener"])))
            return {"ticker": t, "name": t, "last_close": 100.0,
                    "as_of": "2026-10-30T10:00:00+00:00"}

        batch.analyze_one = pipeline_analyze
        s3 = batch.run_batch(liquid + thin, {}, root, regime=regime_future, tg_signals=tg_future)
        side.shutdown()
        assert sorted(PREFETCH["info"]) == sorted(liquid), PREFETCH["info"]
        assert sorted(PREFETCH["earnings"]) == sorted(liquid), PREFETCH["earnings"]
        assert sorted(PREFETCH["screener"]) == ["LIQA", "LIQB"], \
            f"screener prefetch must cover NSE liquid names only: {PREFETCH['screener']}"
        assert all(r == {"state": "risk_on"} for r in seen_regime), \
            f"analysis must receive the resolved regime, got {seen_regime}"
        assert s3["ok"] == 5 and s3["done"] == 5, s3
        thin_first = [n for t, n in order if t in thin]
        assert thin_first and min(thin_first) < 8, \
            f"thin names should start before the network prefetch finishes: {order}"
        print(f"pipeline: Yahoo prefetch {len(PREFETCH['info'])}+{len(PREFETCH['earnings'])} calls, "
              f"screener.in {len(PREFETCH['screener'])} (BSE skipped), regime future resolved, "
              f"thin names analyzed alongside the network")

        # --- routing for names with no exchange history -------------------
        def fake_history(yt, **kw):
            sym = yt.ticker
            if sym.startswith("DEADH"):
                raise data.NoPriceHistory("No data found, symbol may be delisted")
            return hist(1_000_000) if sym.startswith("NEWLIQ") else hist(1)

        data.history_strict = fake_history
        exchange_prices.histories_for = lambda tickers, *a, **k: {}
        for k in PREFETCH:
            PREFETCH[k].clear()
        batch.analyze_one = pipeline_analyze
        s4 = batch.run_batch(["DEADH", "NEWLIQ", "NEWTHIN"], {}, root, regime={"state": "neutral"})
        assert PREFETCH["info"] == ["NEWLIQ"] and PREFETCH["earnings"] == ["NEWLIQ"], PREFETCH
        assert PREFETCH["screener"] == ["NEWLIQ"], PREFETCH
        assert s4["no_data"] >= 1 and s4["ok"] == 2, s4
        print("routing: dead listing stopped after one history check (0 follow-up calls); "
              "new liquid name got fundamentals; new thin name analyzed directly")

        print("\nAll batch speed-up smoke checks passed.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
