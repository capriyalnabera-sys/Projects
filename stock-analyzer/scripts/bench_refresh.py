"""Benchmark a full-universe refresh offline, to find and measure bottlenecks.

Real: the analysis code, disk I/O, CPU, and a synthetic exchange price-file
store with every listed ticker × ~520 trading days.
Simulated: network calls, with realistic latency AND a per-server
concurrency cap (servers throttle heavy clients), so speed-ups can't come
from simply firing more requests — only from overlapping different servers
and avoiding wasted calls.

    python scripts/bench_refresh.py                 # cold + warm refresh
    python scripts/bench_refresh.py --download      # also first-time price-file download

Runs in a temp folder; never touches the real cache.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

# Simulated server behaviour: (latency seconds, max concurrent requests served)
SERVERS = {
    "yahoo": (0.8, 8),         # .info ~0.8s; calendar uses 0.5s below
    "screener": (1.0, 6),
    "screener_404": (0.4, 6),  # BSE .BO symbols: screener.in has no such page
    "nse_files": (0.6, 4),
    "bse_files": (0.6, 4),
}
CALENDAR_LATENCY = 0.5
_sems = {k: threading.BoundedSemaphore(v[1]) for k, v in SERVERS.items()}
_sems["yahoo_cal"] = _sems["yahoo"]
_net_calls = {k: 0 for k in list(SERVERS) + ["yahoo_cal"]}
_net_lock = threading.Lock()


def serve(server: str, latency: float | None = None) -> None:
    with _net_lock:
        _net_calls[server] += 1
    with _sems[server]:
        time.sleep(latency if latency is not None else SERVERS[server][0])


def build_store(store: Path, listed: list[str], liquid: set[str], days: list) -> None:
    rng = np.random.default_rng(7)
    nse = [t for t in listed if not t.endswith(".BO")]
    bse = [t[:-3] for t in listed if t.endswith(".BO")]
    for exch, syms in (("NSE", nse), ("BSE", bse)):
        d = store / exch
        d.mkdir(parents=True, exist_ok=True)
        n = len(syms)
        base = rng.uniform(20, 3000, n)
        liq = np.array([(s if exch == "NSE" else s + ".BO") in liquid for s in syms])
        vol = np.where(liq, rng.uniform(2e5, 5e6, n), rng.uniform(50, 2000, n)).round()
        close = base.copy()
        for day in days:
            prev = close.copy()
            close = prev * (1 + rng.normal(0, 0.012, n))
            df = pd.DataFrame({"sym": syms, "series": "EQ" if exch == "NSE" else "B",
                               "open": prev, "high": close * 1.01, "low": close * 0.99,
                               "close": close.round(2), "prev_close": prev.round(2), "volume": vol})
            with gzip.open(d / f"{day.isoformat()}.csv.gz", "wt", newline="") as f:
                df.to_csv(f, index=False)
        (d / "_names.json").write_text(json.dumps({s: f"{s} LTD" for s in syms}))


def install_fakes() -> None:
    import yfinance as yf
    from src import screener_in

    class FakeTicker:
        def __init__(self, sym): self.sym = sym

        @property
        def info(self):
            serve("yahoo")
            return {"longName": f"{self.sym} Limited", "sector": "Industrials",
                    "trailingPE": 22.0, "returnOnEquity": 0.16, "debtToEquity": 40.0,
                    "marketCap": 5e10, "currency": "INR"}

        @property
        def calendar(self):
            serve("yahoo_cal", CALENDAR_LATENCY)
            return {}

        def history(self, **kw):
            serve("yahoo")
            return pd.DataFrame()

    yf.Ticker = FakeTicker

    class R:
        def __init__(self, code): self.status_code, self.text = code, "<html></html>"

    def fake_get(url, headers=None, timeout=None):
        if ".BO/" in url:
            serve("screener_404")
            return R(404)
        serve("screener")
        return R(200)

    screener_in.requests.get = fake_get
    screener_in._parse_top_ratios = lambda soup: {"roce": 18.0, "market_cap_cr": 5000.0}
    screener_in._parse_growth_section = lambda soup, label: {}


def run(label: str, tickers: list[str]) -> dict:
    from src import batch, profiler, regime
    for k in _net_calls:
        _net_calls[k] = 0
    t0 = time.perf_counter()
    batch.run_batch(tickers, {}, Path("data/cache"), regime={"state": "neutral"})
    wall = time.perf_counter() - t0
    rep = profiler.load(Path("data/cache"))
    print(f"\n=== {label}: {wall:,.1f} s total ===")
    for s in rep.get("stages", []):
        bar = "█" * int(40 * s["seconds"] / max(wall, 0.01))
        print(f"  {s['stage']:<34} {s['seconds']:>7.1f} s  {bar}")
    print("  calls (summed across threads):")
    for k, c in rep.get("calls", {}).items():
        print(f"    {k:<34} {c['count']:>6} × {c['avg_ms']:>7.1f} ms = {c['seconds']:>8.1f} s")
    print("  network requests:", {k: v for k, v in _net_calls.items() if v})
    return {"label": label, "wall": wall, "report": rep, "requests": dict(_net_calls)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="also time the first-time price-file download")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tickers (quick runs)")
    args = ap.parse_args()

    listed = json.loads((ROOT / "data/cache/universe/_all_listed.json").read_text())
    live = json.loads((ROOT / "data/cache/universe/_live_set.json").read_text())
    live = set(live["tickers"] if isinstance(live, dict) else live)
    if args.limit:
        listed = listed[:args.limit]

    tmp = Path(tempfile.mkdtemp(prefix="bench_refresh_"))
    os.chdir(tmp)
    try:
        from src import exchange_prices as ep
        ep.STORE_DIR = tmp / "data/cache/prices"
        today = pd.Timestamp.now(tz="Asia/Kolkata").date()
        days = [today - timedelta(days=i) for i in range(ep.DEFAULT_CALENDAR_DAYS, 0, -1)
                if (today - timedelta(days=i)).weekday() < 5]
        print(f"Universe {len(listed)} tickers ({sum(t in live for t in listed)} liquid); "
              f"building synthetic store of {len(days)} trading days × 2 exchanges…", flush=True)
        t = time.perf_counter()
        build_store(ep.STORE_DIR, listed, live, days)
        print(f"  store built in {time.perf_counter() - t:.0f} s", flush=True)
        install_fakes()

        results = []
        if args.download:
            dl_dir = tmp / "dl"
            src_dir = ep.STORE_DIR

            class FileSession:
                def get(self, url, headers=None, timeout=None):
                    exch = "nse_files" if "nseindia" in url else "bse_files"
                    serve(exch)

                    class R:
                        status_code = 200
                        content = (b"TckrSymb,SctySrs,FinInstrmTp,FinInstrmNm,OpnPric,HghPric,LwPric,"
                                   b"ClsPric,PrvsClsgPric,TtlTradgVol\nABC,EQ,STK,ABC LTD,10,10,10,10,10,100\n")

                        def raise_for_status(self):
                            pass
                    return R()

            ep.STORE_DIR = dl_dir
            ep._session = lambda e: FileSession()
            t = time.perf_counter()
            ep.ensure_updated({})
            dl = time.perf_counter() - t
            print(f"\n=== first-time price-file download ({len(days)} days × 2 exchanges): {dl:,.1f} s ===")
            results.append({"label": "download", "wall": dl})
            ep.STORE_DIR = src_dir

        ep.ensure_updated = lambda *a, **k: []   # store is current for the refresh runs
        results.append(run("cold refresh (first of the day)", listed))
        results.append(run("warm refresh (same day again)", listed))
        # Next day: a new price file arrives (every stock has a new bar) and,
        # with .info TTLs staggered over 5-9 days, ~1/7 of info caches expire;
        # screener.in (3 days) and earnings (7 days / NSE calendar) still hold.
        # With the old 24 h TTLs everything expired, so the old code's next-day
        # refresh == its cold one.
        import zlib
        next_day = days[-1] + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        for exch in ("NSE", "BSE"):
            d = ep.STORE_DIR / exch
            last = sorted(d.glob("????-??-??.csv.gz"))[-1]
            df = pd.read_csv(last)
            df["prev_close"] = df["close"]
            df["close"] = (df["close"] * 1.004).round(2)
            with gzip.open(d / f"{next_day.isoformat()}.csv.gz", "wt", newline="") as f:
                df.to_csv(f, index=False)
        info_dir = Path("data/cache/yf_info")
        expired = [f for f in info_dir.glob("*.json") if zlib.crc32(f.stem.encode()) % 7 == 0]
        for f in expired:
            f.unlink()
        print(f"\n(next day: new price file {next_day}; {len(expired)} info caches expired)")
        ep.DEFAULT_CALENDAR_DAYS += 3
        results.append(run("next-day refresh (new prices, ~1/7 info expired)", listed))
        print("\nSUMMARY " + json.dumps({r["label"]: round(r["wall"], 1) for r in results}))
    finally:
        os.chdir(ROOT)
        shutil.rmtree(tmp, ignore_errors=True)
        os._exit(0)


if __name__ == "__main__":
    main()
