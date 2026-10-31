"""Offline smoke test for the exchange daily-price-file source — no network.

Generates price files in the real NSE UDiFF (zip), NSE sec_bhavdata_full
and BSE UDiFF layouts, serves them through a fake HTTP layer, and checks
download/fallback/holiday/blocked handling, split adjustment, series
preference, staleness, and the batch's Yahoo hand-off.
Run:  python scripts/_smoke_exchange_prices.py
"""
import io
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import batch, data, exchange_prices as ep, technical  # noqa: E402

ep.time.sleep = lambda s: None
batch.time.sleep = lambda s: None

UDIFF_COLS = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
              "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
              "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
              "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")

TODAY = datetime.now(ep.IST).date()
WINDOW = 70
DAYS = [TODAY - timedelta(days=i) for i in range(WINDOW, -1, -1)
        if (TODAY - timedelta(days=i)).weekday() < 5 and TODAY - timedelta(days=i) < TODAY]
HOLIDAY = DAYS[len(DAYS) // 2]          # both NSE files 404 → holiday
FULL_ONLY = DAYS[5]                     # UDiFF 404 → sec_bhavdata_full fallback
FLAKY = DAYS[8]                         # transient 500 on the first attempt
SPLIT_DAY = DAYS[30]                    # SPLITCO 1:5 split ex-date
NEW_FROM = DAYS[-8]                     # NEWCO lists late (< MIN_ROWS bars)
TRADING = [d for d in DAYS if d != HOLIDAY]


def px(sym, i):
    base = {"RELIANCE": 2800.0, "THINCO": 41.0, "SPLITCO": 1000.0, "NEWCO": 120.0,
            "ABCLTD": 77.0}[sym]
    return round(base * (1 + 0.002 * ((i * 7) % 11 - 5)), 2)


def raw_close(sym, d):
    i = TRADING.index(d)
    c = px(sym, i)
    if sym == "SPLITCO" and d >= SPLIT_DAY:
        c = round(c / 5, 2)
    return c


def raw_prev(sym, d):
    i = TRADING.index(d)
    if i == 0:
        return raw_close(sym, d)
    prev = raw_close(sym, TRADING[i - 1])
    if sym == "SPLITCO" and d == SPLIT_DAY:
        prev = round(prev / 5, 2)       # exchange shows the ADJUSTED previous close
    return prev


def nse_rows(d):
    syms = [("RELIANCE", "EQ", 9_000_000, "RELIANCE INDUSTRIES LTD"),
            ("THINCO", "BE", 1_200, "THIN COMPANY LIMITED"),
            ("SPLITCO", "EQ", 300_000, "SPLIT CO LTD")]
    if d >= NEW_FROM:
        syms.append(("NEWCO", "EQ", 50_000, "NEW CO LTD"))
    out = []
    for s, ser, vol, nm in syms:
        c, pc = raw_close(s, d), raw_prev(s, d)
        out.append((s, ser, c, pc, vol, nm))
    # A second, thinner line for RELIANCE in another series — must lose.
    out.append(("RELIANCE", "BL", round(raw_close("RELIANCE", d) * 1.5, 2),
                raw_prev("RELIANCE", d), 10, "RELIANCE INDUSTRIES LTD"))
    return out


def udiff_csv(d, rows, exch="NSE"):
    lines = [UDIFF_COLS]
    for s, ser, c, pc, vol, nm in rows:
        lines.append(f"{d:%Y-%m-%d},{d:%Y-%m-%d},CM,{exch},STK,1,INE000000000,{s},{ser},,,,,{nm},"
                     f"{c},{c*1.01:.2f},{c*0.99:.2f},{c},{c},{pc},,{c},,,{vol},{vol*c:.0f},10,F1,1,,,,,")
    # A non-stock row (index/bond) that must be filtered out.
    lines.append(f"{d:%Y-%m-%d},{d:%Y-%m-%d},CM,{exch},IDX,9,,NIFTYIDX,,,,,,Index,1,1,1,1,1,1,,1,,,0,0,0,F1,1,,,,,")
    return "\n".join(lines).encode()


def zipped(name, payload):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, payload)
    return b.getvalue()


def full_csv(d, rows):
    lines = ["SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
             "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"]
    for s, ser, c, pc, vol, nm in rows:
        lines.append(f"{s}, {ser}, {d:%d-%b-%Y}, {pc}, {c}, {c*1.01:.2f}, {c*0.99:.2f}, {c}, {c}, {c}, "
                     f"{vol}, 1, 1, 1, 50")
    return "\n".join(lines).encode()


class Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


flaky_hits = {"n": 0}
BLOCK = {"on": False}


class FakeSession:
    def get(self, url, headers=None, timeout=None):
        if BLOCK["on"] and "nseindia" in url:
            return Resp(403)
        for d in DAYS:
            ymd, dmy = d.strftime("%Y%m%d"), d.strftime("%d%m%Y")
            if f"NSE_CM_0_0_0_{ymd}" in url:
                if d in (HOLIDAY, FULL_ONLY):
                    return Resp(404)
                if d == FLAKY and flaky_hits["n"] == 0:
                    flaky_hits["n"] += 1
                    return Resp(500)
                return Resp(200, zipped(f"BhavCopy_{ymd}.csv", udiff_csv(d, nse_rows(d))))
            if f"sec_bhavdata_full_{dmy}" in url:
                return Resp(404) if d == HOLIDAY else Resp(200, full_csv(d, nse_rows(d)))
            if f"BSE_CM_0_0_0_{ymd}" in url:
                if d == HOLIDAY:
                    return Resp(200, b"<!DOCTYPE html><html>File not found</html>")
                rows = [("ABCLTD", "B", raw_close("ABCLTD", d), raw_prev("ABCLTD", d), 8_000, "ABC LIMITED")]
                return Resp(200, udiff_csv(d, rows, "BSE"))
        return Resp(404)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_prices_"))
    ep.STORE_DIR = tmp / "prices"
    ep._session = lambda exch: FakeSession()
    cfg = {"prices": {"history_calendar_days": WINDOW}}
    try:
        # --- download: fallback, holiday, transient error -------------------
        r = ep.ensure_updated(cfg)
        nse = next(x for x in r if x["exchange"] == "NSE")
        stored = set(ep.stored_days("NSE"))
        assert HOLIDAY.isoformat() not in stored
        assert FULL_ONLY.isoformat() in stored, "sec_bhavdata_full fallback not used"
        assert FLAKY.isoformat() not in stored and nse["errors"] == 1
        missing = json.loads((ep.STORE_DIR / "NSE" / "_missing.json").read_text())
        assert HOLIDAY.isoformat() in missing and FLAKY.isoformat() not in missing
        print(f"download: {len(stored)} NSE days; holiday marked, sec_bhavdata_full fallback used, "
              f"transient error left for retry")
        bse_days = ep.stored_days("BSE")
        assert HOLIDAY.isoformat() not in bse_days, "BSE HTML 'not found' page must count as no file"
        r2 = ep.ensure_updated(cfg)
        assert FLAKY.isoformat() in ep.stored_days("NSE"), "retry should fetch the flaky day"
        assert next(x for x in r2 if x["exchange"] == "NSE")["wanted"] == 1
        assert ep.ensure_updated(cfg)[0]["wanted"] == 0, "current store must be a no-op"
        print(f"rerun: only the failed day re-requested, then no-op; BSE {len(bse_days)} days")

        # --- parsing: series preference + non-stock filter + names ----------
        day_file = pd.read_csv(ep.STORE_DIR / "NSE" / f"{TRADING[-1].isoformat()}.csv.gz")
        rel = day_file[day_file["sym"] == "RELIANCE"]
        assert len(rel) == 1 and rel["series"].iloc[0] == "EQ", rel
        assert "NIFTYIDX" not in set(day_file["sym"]), "index row must be filtered"
        assert ep.names("NSE")["RELIANCE"] == "RELIANCE INDUSTRIES LTD"
        print("parse: EQ line preferred over thinner series, index rows dropped, names captured")

        # --- histories: coverage, split adjustment --------------------------
        h = ep.histories_for(["RELIANCE", "THINCO", "SPLITCO", "NEWCO", "ABCLTD.BO", "UNKNOWN"],
                             cfg, update_first=False)
        assert set(h) == {"RELIANCE", "THINCO", "SPLITCO", "ABCLTD.BO"}, sorted(h)
        s = h["SPLITCO"]["Close"]
        worst = s.pct_change().abs().max()
        assert worst < 0.05, f"split not adjusted (worst daily move {worst:.0%})"
        assert abs(s.iloc[-1] - raw_close("SPLITCO", TRADING[-1])) < 0.01, "latest close must be raw"
        assert abs(s.iloc[0] - raw_close("SPLITCO", TRADING[0]) / 5) < 0.01, "pre-split prices /5"
        v = h["SPLITCO"]["Volume"]
        assert v.iloc[0] == 300_000 * 5, "pre-split volume ×5"
        t = technical.analyze(h["THINCO"])
        assert t.avg_daily_value_cr is not None and t.avg_daily_value_cr < 0.5
        print(f"histories: 4/6 covered (NEWCO too new, UNKNOWN absent); split adjusted "
              f"(worst daily move {worst:.1%}); thin stock analyzable")

        # --- staleness ----------------------------------------------------
        stale_dir = tmp / "stale"
        (stale_dir / "NSE").mkdir(parents=True)
        old = TODAY - timedelta(days=12)
        shutil.copy(ep.STORE_DIR / "NSE" / f"{TRADING[-1].isoformat()}.csv.gz",
                    stale_dir / "NSE" / f"{old.isoformat()}.csv.gz")
        real_dir, ep.STORE_DIR = ep.STORE_DIR, stale_dir
        assert ep.histories_for(["RELIANCE"], cfg, update_first=False) == {}
        assert ep.summary()[0]["stale"] is True
        ep.STORE_DIR = real_dir
        print("staleness: a store >6 days old is ignored (Yahoo used) and flagged in the summary")

        # --- blocked ----------------------------------------------------------
        blk = tmp / "blocked"
        ep.STORE_DIR = blk
        BLOCK["on"] = True
        rb = ep.update("NSE", WINDOW)
        assert rb["blocked"] and rb["ok"] == 0
        assert rb["wanted"] - rb["missing"] - rb["ok"] > 0
        BLOCK["on"] = False
        ep.STORE_DIR = real_dir
        print("blocked: HTTP 403 stops the download instead of hammering the exchange")

        # --- unreachable exchange: give up fast, then cool down -------------
        calls = {"n": 0}

        class DeadSession:
            def get(self, url, headers=None, timeout=None):
                calls["n"] += 1
                raise TimeoutError("read timed out")

        dead = tmp / "dead"
        ep.STORE_DIR = dead
        ep._session = lambda exch: DeadSession()
        rd = ep.ensure_updated({"prices": {"history_calendar_days": WINDOW, "bse_files": False}})
        assert rd[0]["gave_up"], rd
        assert calls["n"] <= ep.GIVE_UP_AFTER + 6, f"kept hammering: {calls['n']} requests"
        before = calls["n"]
        assert ep.ensure_updated({"prices": {"history_calendar_days": WINDOW, "bse_files": False}}) == []
        assert calls["n"] == before, "cooldown must skip the retry"
        ep.STORE_DIR = real_dir
        ep._session = lambda exch: FakeSession()
        print(f"unreachable: gave up after {before} requests (of {rd[0]['wanted']} files), "
              f"then skipped retries during the cooldown")

        # --- batch integration: Yahoo only for uncovered tickers -------------
        asked_yahoo, seen = [], {}

        def fake_bulk(tickers, period="2y"):
            asked_yahoo.extend(tickers)
            return {}

        def fake_analyze(t, cfg_, cache_root, prefetched_history=None, **kw):
            seen[t] = None if prefetched_history is None else len(prefetched_history)
            return {"ticker": t, "name": t, "last_close": 1.0,
                    "as_of": "2026-10-30T10:00:00+00:00"}

        data.bulk_fetch_histories = fake_bulk
        batch.analyze_one = fake_analyze
        root = tmp / "cache"
        batch.run_batch(["RELIANCE", "SPLITCO", "ABCLTD.BO", "NEWCO", "UNKNOWN"], cfg, root)
        assert sorted(asked_yahoo) == ["NEWCO", "UNKNOWN"], asked_yahoo
        assert seen["RELIANCE"] and seen["ABCLTD.BO"] and seen["NEWCO"] is None
        rel_row = batch.read_result("RELIANCE", root)
        assert rel_row["name"] == "RELIANCE INDUSTRIES LTD", rel_row["name"]
        assert batch.read_result("ABCLTD.BO", root)["name"] == "ABC LIMITED"
        print(f"batch: exchange files fed {sum(1 for v in seen.values() if v)} of 5; Yahoo asked only "
              f"for {sorted(asked_yahoo)}; company names filled from the files")

        print("\nAll exchange price-file smoke checks passed.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
