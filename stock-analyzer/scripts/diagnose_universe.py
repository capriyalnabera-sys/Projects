"""Why are listed stocks missing from the analysis? Run on the PC that runs
the app (it needs internet access to Yahoo Finance).

    python scripts/diagnose_universe.py        (or double-click diagnose-universe.bat)

Prints, and saves to diagnose_report.txt:
  1. Coverage: listed vs analyzed, split NSE / BSE-only, liquid vs thin.
  2. The last batch run's outcome counts.
  3. A live test of a sample of MISSING stocks, fetched one at a time from
     Yahoo, with the exact reason each one fails (or succeeds).
  4. A bulk-download test of the same sample.
Takes about a minute. Read-only: changes nothing in the cache.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

LINES: list[str] = []


def out(s: str = "") -> None:
    print(s, flush=True)
    LINES.append(s)


def spread(items: list, n: int) -> list:
    """n items evenly spaced through the list (not just the first n)."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def main() -> None:
    from src import batch, data, universe

    cache = Path("data/cache")
    listed = universe.load_all_listed_cached(cache / "universe")
    live = set(universe.load_live_set(cache / "universe") or [])
    rows = {t: batch.read_result(t, cache) for t in listed}
    analyzed = [t for t, r in rows.items() if r]
    missing = [t for t, r in rows.items() if not r]
    thin = [t for t in analyzed if (rows[t].get("avg_daily_value_cr") or 0) < 0.5]

    def nse(ts): return [t for t in ts if not t.endswith(".BO")]
    def bse(ts): return [t for t in ts if t.endswith(".BO")]

    out("=" * 64)
    out("STOCK ANALYZER — UNIVERSE DIAGNOSTIC")
    out("=" * 64)
    out(f"Listed          : {len(listed):>5}   (NSE {len(nse(listed))}, BSE-only {len(bse(listed))})")
    out(f"Analyzed        : {len(analyzed):>5}   (NSE {len(nse(analyzed))}, BSE-only {len(bse(analyzed))})")
    out(f"  of which thin : {len(thin):>5}   (below Rs 0.5 Cr/day)")
    out(f"Missing         : {len(missing):>5}   (NSE {len(nse(missing))}, BSE-only {len(bse(missing))})")
    out(f"Live set        : {len(live):>5}")
    reg = batch.load_no_data(cache)
    out(f"No-data registry: {len(reg):>5}   (skipped for a week)")

    st = batch.read_status(cache)
    out("")
    out("Last batch run:")
    for k in ("total", "done", "ok", "no_data", "errors", "elapsed_sec", "finished_at"):
        if k in st:
            out(f"  {k:<12}: {st[k]}")
    if st.get("failed_tickers"):
        out(f"  failed (sample): {', '.join(st['failed_tickers'][:15])}")

    import yfinance as yf
    out("")
    out(f"yfinance version: {yf.__version__}")
    sample = spread(nse(missing), 12) + spread(bse(missing), 4)
    if not sample:
        out("\nNothing is missing — every listed stock has an analysis.")
        return

    out("")
    out(f"Live test: fetching {len(sample)} missing stocks one at a time from Yahoo")
    out("-" * 64)
    tally: dict[str, int] = {}
    for t in sample:
        sym = data.to_yf_symbol(t)
        try:
            h = data.history_strict(yf.Ticker(sym))
            h = h.dropna(subset=["Close"]) if h is not None else h
            if h is None or h.empty:
                verdict, detail = "NO DATA", "empty response"
            else:
                last20 = h.tail(20)
                adv = float((last20["Close"] * last20["Volume"]).mean()) / 1e7
                verdict = "OK"
                detail = f"{len(h)} days, last close {h['Close'].iloc[-1]:,.2f}, ~Rs {adv:.2f} Cr/day"
        except data.NoPriceHistory as e:
            verdict, detail = "NO DATA", str(e).split(":", 1)[-1].strip()[:70]
        except Exception as e:
            name = type(e).__name__
            verdict = "THROTTLED" if "RateLimit" in name or "Too Many" in str(e) else "ERROR"
            detail = f"{name}: {str(e)[:60]}"
        tally[verdict] = tally.get(verdict, 0) + 1
        out(f"  {sym:<20} {verdict:<10} {detail}")
        time.sleep(1.5)

    out("-" * 64)
    out("Result: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))

    out("")
    nse_sample = [data.to_yf_symbol(t) for t in spread(nse(missing), 12)]
    if nse_sample:
        try:
            df = yf.download(nse_sample, period="2y", group_by="ticker",
                             progress=False, auto_adjust=False, threads=True, timeout=60)
            got = 0
            for s in nse_sample:
                try:
                    sub = df[s] if len(nse_sample) > 1 else df
                    if not sub.dropna(how="all").empty:
                        got += 1
                except Exception:
                    pass
            out(f"Bulk download test: {got}/{len(nse_sample)} of the NSE sample returned data")
        except Exception as e:
            out(f"Bulk download test: failed — {type(e).__name__}: {str(e)[:80]}")

    out("")
    out("What this means:")
    if tally.get("OK"):
        out("  OK rows: Yahoo HAS data for stocks the sweep missed -> the sweep was")
        out("  throttled or failing. Run Full sweep again; it now retries these.")
    if tally.get("THROTTLED") or tally.get("ERROR"):
        out("  THROTTLED/ERROR rows: Yahoo is limiting or refusing requests right now.")
    if tally.get("NO DATA") and not tally.get("OK"):
        out("  NO DATA rows: Yahoo genuinely has no prices for these listings.")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            Path("diagnose_report.txt").write_text("\n".join(LINES), encoding="utf-8")
            print(f"\nSaved {Path('diagnose_report.txt').resolve()}")
        except Exception:
            pass
        os._exit(0)
