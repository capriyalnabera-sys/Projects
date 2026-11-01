"""Offline smoke test for the "Refresh all" call reductions — no network.

Covers: skip-unchanged fingerprint (+ force), .info repricing and staggered
TTL, NSE event-calendar earnings with Yahoo fallback, accuracy using local
exchange histories, the consolidated price panel and its incremental update,
the publish-time gate for today's file, the Telegram scan cache, and the
refresh-all worker running to completion (it used to crash with NameError).
Run:  python scripts/_smoke_refresh_calls.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_refresh_calls_"))
os.chdir(TMP)                     # every relative cache path lands in the temp dir

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

from src import batch, data, earnings, exchange_prices as ep  # noqa: E402

batch.time.sleep = lambda s: None


def hist(close=100.0, days=60, end="2026-10-30", vol=1_000_000):
    idx = pd.bdate_range(end=end, periods=days)
    c = np.full(days, close)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                         "Adj Close": c, "Volume": np.full(days, vol)}, index=idx)


def check_skip_unchanged():
    root = TMP / "cache_skip"
    hists = {"AAA": hist(100.0, vol=1), "BBB": hist(200.0, vol=1)}   # thin: no network path
    ep.histories_for = lambda tickers, *a, **k: dict(hists)
    calls = []

    def fake_analyze(t, cfg, cache_root, **kw):
        calls.append(t)
        return {"ticker": t, "name": t, "last_close": 1.0, "as_of": "2026-10-30T10:00:00+00:00"}

    batch.analyze_one = fake_analyze
    reg = {"state": "neutral", "hold_zone": 0.8}
    s1 = batch.run_batch(["AAA", "BBB"], {}, root, regime=reg)
    assert sorted(calls) == ["AAA", "BBB"] and s1["ok"] == 2, (calls, s1)
    calls.clear()
    s2 = batch.run_batch(["AAA", "BBB"], {}, root, regime=reg)
    assert calls == [] and s2["unchanged"] == 2 and s2["done"] == 2, (calls, s2)
    snap = TMP / root / "snapshots"
    hists["BBB"] = hist(205.0, vol=1)                                   # new price bar
    calls.clear()
    batch.run_batch(["AAA", "BBB"], {}, root, regime=reg)
    assert calls == ["BBB"], calls
    calls.clear()
    batch.run_batch(["AAA", "BBB"], {}, root, regime={"state": "risk_off", "hold_zone": 1.2})
    assert sorted(calls) == ["AAA", "BBB"], "a regime change must re-analyze"
    calls.clear()
    batch.run_batch(["AAA", "BBB"], {}, root, regime={"state": "risk_off", "hold_zone": 1.2},
                    skip_unchanged=False)
    assert sorted(calls) == ["AAA", "BBB"], "force must re-analyze everything"
    assert any(snap.glob("*.json")), "snapshot must exist"
    print("skip-unchanged: same-day repeat analyzed 0/2; a new price bar re-ran only that "
          "stock; a regime change and force re-ran all")


def check_reprice_and_ttl():
    info = {"currentPrice": 100.0, "trailingPE": 20.0, "forwardPE": 18.0, "priceToBook": 3.0,
            "marketCap": 1e10, "dividendYield": 2.0, "returnOnEquity": 0.15}
    r = data.reprice_info(info, 110.0)
    assert abs(r["trailingPE"] - 22.0) < 1e-9 and abs(r["priceToBook"] - 3.3) < 1e-9
    assert abs(r["marketCap"] - 1.1e10) < 1 and abs(r["dividendYield"] - 2.0 / 1.1) < 1e-9
    assert r["returnOnEquity"] == 0.15 and info["trailingPE"] == 20.0, "must not mutate the cache"
    assert data.reprice_info(info, 1000.0)["trailingPE"] == 20.0, "implausible 10× jump ignored"
    ttls = {data._info_ttl(f"T{i}") // 86400 for i in range(400)}
    assert ttls == {5, 6, 7, 8, 9}, ttls
    print("info: ratios rescaled to today's price (P/E 20→22, yield inverse), cache untouched; "
          "TTL spread over 5-9 days")


def check_nse_calendar():
    future = (date.today() + timedelta(days=3)).strftime("%d-%b-%Y")
    later = (date.today() + timedelta(days=20)).strftime("%d-%b-%Y")
    past = (date.today() - timedelta(days=2)).strftime("%d-%b-%Y")
    payload = [
        {"symbol": "RELIANCE", "purpose": "Financial Results", "date": later},
        {"symbol": "RELIANCE", "purpose": "Financial Results/Dividend", "date": future},
        {"symbol": "TCS", "purpose": "Fund Raising", "date": future},           # not results
        {"symbol": "INFY", "purpose": "Financial Results", "date": past},         # passed
    ]
    m = earnings.parse_nse_event_calendar(payload)
    assert m == {"RELIANCE": (date.today() + timedelta(days=3)).isoformat()}, m

    yahoo_calls = []
    import yfinance as yf

    class FakeYT:
        def __init__(self, s): self.s = s

        @property
        def calendar(self):
            yahoo_calls.append(self.s)
            return {}
    yf.Ticker = FakeYT

    from src import nse_quote

    class Resp:
        def __init__(self, code, body): self.status_code, self._b = code, body

        @property
        def text(self): return json.dumps(self._b)

        def json(self): return self._b

    hits = {"n": 0}

    class Sess:
        def get(self, url, headers=None, timeout=None):
            hits["n"] += 1
            return Resp(200, payload)
    nse_quote._get_session = lambda: Sess()
    earnings.EARNINGS_CACHE_DIR = TMP / "earn_ok"
    days = earnings.days_until_earnings("RELIANCE")
    assert days == 3 and earnings.next_earnings_date("TCS") is None
    out = []
    ths = [threading.Thread(target=lambda: out.append(earnings.next_earnings_date("INFY")))
           for _ in range(8)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert hits["n"] == 1, f"calendar must be fetched once, got {hits['n']}"
    assert yahoo_calls == [], "NSE names must not hit Yahoo when the calendar works"
    earnings.next_earnings_date("ABC.BO")
    assert yahoo_calls == ["ABC.BO"], "BSE-only names still use Yahoo"

    class Down:
        def get(self, url, headers=None, timeout=None):
            raise ConnectionError("down")
    nse_quote._get_session = lambda: Down()
    earnings.EARNINGS_CACHE_DIR = TMP / "earn_down"
    yahoo_calls.clear()
    earnings.next_earnings_date("WIPRO")
    assert yahoo_calls == ["WIPRO.NS"], f"fallback to Yahoo when NSE is down: {yahoo_calls}"
    print("earnings: one NSE calendar call served 10 lookups (results only, past dates dropped); "
          "BSE-only and NSE-down fall back to Yahoo")


def check_accuracy_local():
    from src import accuracy
    ep.histories_for = lambda tickers, *a, **k: {"AAA": hist()}
    asked = []
    data.bulk_fetch_histories = lambda tickers, period="2y": asked.extend(tickers) or {}
    root = TMP / "cache_acc"
    batch.save_no_data(root, {"DEAD.BO": date.today().isoformat()})
    out = accuracy._histories_for_accuracy(["AAA", "BBB", "DEAD.BO"], "200d", root)
    assert set(out) == {"AAA"} and asked == ["BBB"], (sorted(out), asked)
    print("accuracy: local exchange history used; Yahoo asked only for the uncovered stock, "
          "never for a known no-data one")


def write_day(store, exch, day, rows):
    import gzip
    d = store / exch
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["sym", "series", "open", "high", "low", "close",
                                     "prev_close", "volume"])
    with gzip.open(d / f"{day}.csv.gz", "wt", newline="") as f:
        df.to_csv(f, index=False)


def check_panel_and_gate():
    import importlib
    importlib.reload(ep)          # earlier checks replaced histories_for
    store = TMP / "prices"
    ep.STORE_DIR = store
    today = datetime.now(ep.IST).date()
    days = [today - timedelta(days=i) for i in range(12, 0, -1) if (today - timedelta(days=i)).weekday() < 5]
    for i, d in enumerate(days[:-1]):
        write_day(store, "NSE", d.isoformat(), [["AAA", "EQ", 10, 10, 10, 10 + i, 10 + i - 1, 100],
                                                ["BBB", "EQ", 20, 20, 20, 20 + i, 20 + i - 1, 100]])
    direct = ep._read_days("NSE", ep.stored_days("NSE"), {"AAA"})
    via = ep._load_frames("NSE", {"AAA"}, 30)
    pd.testing.assert_frame_equal(
        direct.sort_values("date").reset_index(drop=True)[["sym", "close", "date"]],
        via.sort_values("date").reset_index(drop=True)[["sym", "close", "date"]])
    assert (store / "NSE" / "_panel.pkl").exists()
    reads = {"n": 0}
    real_read_days = ep._read_days

    def counting(exch, ds, syms):
        reads["n"] += len(ds)
        return real_read_days(exch, ds, syms)
    ep._read_days = counting
    ep._load_frames("NSE", {"AAA"}, 30)
    assert reads["n"] == 0, "unchanged store must be served from the panel alone"
    write_day(store, "NSE", days[-1].isoformat(), [["AAA", "EQ", 10, 10, 10, 99, 98, 100]])
    f = ep._load_frames("NSE", {"AAA"}, 30)
    assert reads["n"] == 1, f"a new day must read just that file, read {reads['n']}"
    assert f.sort_values("date")["close"].iloc[-1] == 99
    ep._read_days = real_read_days
    print(f"panel: matches the day files; unchanged store read 0 day files; a new day read 1 "
          f"(was {len(days)} every refresh)")

    # Publish-time gate: on a weekday, today's file is only requested after 18:30 IST.
    asked = []

    class Sess:
        def get(self, url, headers=None, timeout=None):
            asked.append(url)

            class R:
                status_code = 404
                content = b""
            return R()

    class FixedDT(datetime):
        moment = None

        @classmethod
        def now(cls, tz=None):
            return cls.moment
    real_dt = ep.datetime
    ep.datetime = FixedDT
    ep._session = lambda e: Sess()
    ep.STORE_DIR = TMP / "gate"
    friday = date(2026, 10, 30)
    FixedDT.moment = real_dt(2026, 10, 30, 11, 0, tzinfo=ep.IST)
    ep.update("NSE", calendar_days=0)
    assert not any(friday.strftime("%Y%m%d") in u for u in asked), "requested before publication"
    FixedDT.moment = real_dt(2026, 10, 30, 19, 0, tzinfo=ep.IST)
    ep.update("NSE", calendar_days=0)
    assert any(friday.strftime("%Y%m%d") in u for u in asked), "must request after 18:30"
    ep.datetime = real_dt
    print("publish gate: today's file not requested at 11:00 IST, requested at 19:00 IST")


def check_web_paths():
    import src.web as web
    from src.recommend import TelegramSignal
    root = TMP / "cache_web"
    root.mkdir(parents=True, exist_ok=True)
    scans = {"n": 0}

    def scan():
        scans["n"] += 1
        return {"AAA": TelegramSignal(3, 0.5, [120.0]), "BBB": TelegramSignal(1, 0.1, [])}
    cfg = {"telegram": {"scan_days": 14}}
    a = web._cached_research_scan(root, cfg, ["AAA", "BBB"], scan)
    b = web._cached_research_scan(root, cfg, ["AAA"], scan)
    assert scans["n"] == 1 and b["AAA"].mentions_7d == 3 and set(b) == {"AAA"}, (scans, b)
    web._cached_research_scan(root, {"telegram": {"scan_days": 7}}, ["AAA"], scan)
    assert scans["n"] == 2, "different look-back must rescan"
    web._cached_research_scan(root, cfg, ["AAA", "CCC"], scan)
    assert scans["n"] == 3, "new stocks must rescan"
    empty = {"n": 0}
    web._cached_research_scan(TMP / "cache_web2", cfg, ["X"], lambda: empty.__setitem__("n", empty["n"] + 1) or {})
    web._cached_research_scan(TMP / "cache_web2", cfg, ["X"], lambda: empty.__setitem__("n", empty["n"] + 1) or {})
    assert empty["n"] == 2, "an empty (failed/unconfigured) scan must not be cached"
    print("telegram: repeat scan within the hour reused (subset too); new look-back or new "
          "stocks rescan; empty results never cached")

    # The refresh-all worker used to raise NameError after the batch.
    ran = {"after": None}
    web.batch.run_batch = lambda *a, **k: {"ok": 0, "done": 3}
    web._after_refresh = lambda result: ran.__setitem__("after", result)
    web._refresh_all_worker(0, False)
    assert ran["after"] == {"ok": 0, "done": 3}, ran
    web._refresh_worker("nifty50", 0, False, False, True)
    print("refresh-all: runs to completion and reaches the post-refresh step (no NameError)")


def check_after_refresh():
    import importlib
    import src.web as web
    importlib.reload(web)
    started = []
    web._memo_clear = lambda: started.append("memo")
    web._prewarm_pages_async = lambda: started.append("prewarm")
    web._learn_from_snapshots = lambda: started.append("learn")
    # (src.web's own startup thread may also call the prewarm stub on reload,
    # so only memo/learn — which come solely from _after_refresh — are exact.)
    web._after_refresh({"ok": 0})
    assert "memo" not in started and "learn" not in started, "nothing changed → nothing to redo"
    web._after_refresh({"ok": 5})
    import time
    time.sleep(0.3)
    assert started.count("memo") == 1 and started.count("learn") == 1, started
    assert "prewarm" in started, started
    print("post-refresh: skipped entirely when 0 stocks changed; otherwise memo + prewarm + "
          "one sequential accuracy→calibration thread")


def main():
    try:
        check_skip_unchanged()
        check_reprice_and_ttl()
        check_nse_calendar()
        check_accuracy_local()
        check_panel_and_gate()
        check_web_paths()
        check_after_refresh()
        print("\nAll refresh call-reduction smoke checks passed.")
        code = 0
    except Exception:
        import traceback
        traceback.print_exc()
        code = 1
    finally:
        os.chdir(ROOT)
        shutil.rmtree(TMP, ignore_errors=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # background threads started by src.web need no graceful shutdown


if __name__ == "__main__":
    main()
