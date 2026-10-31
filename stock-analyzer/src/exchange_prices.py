"""Price history from the exchanges' own daily price files ("bhavcopies").

NSE and BSE each publish one file per trading day listing every traded stock
with open/high/low/close, previous close and volume. Two years of those files
cover the whole listed universe in one place — no per-stock requests, no
Yahoo throttling, no "possibly delisted" gaps for thinly traded names.

Sources (tried in order per day):
  NSE  UDiFF CM bhavcopy (zip)          nsearchives.nseindia.com/content/cm/...
  NSE  sec_bhavdata_full (csv)          nsearchives.nseindia.com/products/content/...
  BSE  UDiFF CM bhavcopy (csv)          www.bseindia.com/download/BhavCopy/Equity/...

Store, one compact gzip CSV per exchange per trading day:
    data/cache/prices/NSE/2026-10-30.csv.gz   (sym, series, open, high, low,
                                               close, prev_close, volume)
    data/cache/prices/NSE/_names.json         {SYMBOL: company name}
    data/cache/prices/NSE/_missing.json       {date: "no file"} (holidays)

Corporate actions: raw exchange prices jump on split/bonus ex-dates. On an
ex-date the exchange's previous-close field carries the ADJUSTED price, so
prev_close[d] / close[d-1] gives the adjustment factor; every earlier bar is
scaled by it (volume inversely), like Yahoo's split-adjusted Close.

First run downloads ~2 years (~520 files per exchange, a few minutes, in the
background); afterwards one file per exchange per day. Everything degrades
to Yahoo: a missing, stale or unreachable store just means fewer histories
come from here.
"""
from __future__ import annotations

import gzip
import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests

STORE_DIR = Path("data/cache/prices")
IST = timezone(timedelta(hours=5, minutes=30))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SOURCES = {
    "NSE": {
        "urls": [
            "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
            "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv",
        ],
        "headers": {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"},
        "warmup": "https://www.nseindia.com/",
    },
    "BSE": {
        "urls": [
            "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV",
        ],
        "headers": {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.bseindia.com/"},
        "warmup": "https://www.bseindia.com/",
    },
}

DEFAULT_CALENDAR_DAYS = 760      # ≈ 2 years + buffer → ~520 trading days
STALE_AFTER_DAYS = 6             # store older than this → don't trust it
MIN_ROWS = 20                    # fewer bars than this → let Yahoo try
GIVE_UP_AFTER = 10               # consecutive failures with nothing saved → stop
RETRY_COOLDOWN_MIN = 60          # after giving up, wait this long before retrying
SERIES_RANK = {"EQ": 0, "BE": 1, "BZ": 2, "SM": 3, "ST": 4, "SZ": 5}

_lock = threading.Lock()
_progress: dict = {"msg": ""}


# ---------------------------------------------------------------------------
# Parsing — pure, tolerant of the three file layouts.
# ---------------------------------------------------------------------------

def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def parse_bhav(content: bytes) -> pd.DataFrame:
    """Raw file bytes (zip or csv) → one row per symbol:
    sym, series, open, high, low, close, prev_close, volume, name."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            content = z.read(member)
    df = pd.read_csv(io.BytesIO(content), dtype=str, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    cols = {c.upper(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n.upper() in cols:
                return df[cols[n.upper()]]
        return pd.Series([None] * len(df), index=df.index)

    if "TCKRSYMB" in cols:                       # UDiFF (NSE + BSE, since 2024)
        if "FININSTRMTP" in cols:
            df = df[df[cols["FININSTRMTP"]].astype(str).str.strip().str.upper() == "STK"]
        out = pd.DataFrame({
            "sym": col("TckrSymb"), "series": col("SctySrs"),
            "open": col("OpnPric"), "high": col("HghPric"), "low": col("LwPric"),
            "close": col("ClsPric"), "prev_close": col("PrvsClsgPric"),
            "volume": col("TtlTradgVol"), "name": col("FinInstrmNm"),
        })
    elif "CLOSE_PRICE" in cols:                  # NSE sec_bhavdata_full
        out = pd.DataFrame({
            "sym": col("SYMBOL"), "series": col("SERIES"),
            "open": col("OPEN_PRICE"), "high": col("HIGH_PRICE"), "low": col("LOW_PRICE"),
            "close": col("CLOSE_PRICE"), "prev_close": col("PREV_CLOSE"),
            "volume": col("TTL_TRD_QNTY"), "name": None,
        })
    elif "TOTTRDQTY" in cols:                    # legacy NSE cm bhavcopy
        out = pd.DataFrame({
            "sym": col("SYMBOL"), "series": col("SERIES"),
            "open": col("OPEN"), "high": col("HIGH"), "low": col("LOW"),
            "close": col("CLOSE"), "prev_close": col("PREVCLOSE"),
            "volume": col("TOTTRDQTY"), "name": None,
        })
    else:
        raise ValueError(f"unrecognized price-file layout: {list(df.columns)[:8]}")

    out["sym"] = out["sym"].astype(str).str.strip().str.upper()
    out["series"] = out["series"].fillna("").astype(str).str.strip().str.upper()
    for c in ("open", "high", "low", "close", "prev_close", "volume"):
        out[c] = _num(out[c])
    out = out[(out["close"] > 0) & out["sym"].ne("") & out["sym"].ne("NAN")]
    # One row per symbol: prefer the main equity series, then the busiest line.
    out = out.assign(_rank=out["series"].map(SERIES_RANK).fillna(9))
    out = out.sort_values(["sym", "_rank", "volume"], ascending=[True, True, False])
    out = out.drop_duplicates("sym", keep="first").drop(columns="_rank")
    return out.reset_index(drop=True)


def build_history(g: pd.DataFrame) -> pd.DataFrame:
    """One symbol's daily rows (date, open..volume, prev_close) → split/bonus-
    adjusted OHLCV frame shaped like a yfinance history."""
    g = g.sort_values("date").drop_duplicates("date", keep="last")
    close = g["close"].to_numpy(dtype=float)
    prev = g["prev_close"].to_numpy(dtype=float)
    factor = [1.0] * len(g)
    for i in range(1, len(g)):
        pc, c_prev = prev[i], close[i - 1]
        if pc and pc > 0 and c_prev > 0:
            f = pc / c_prev
            # Only real corporate actions: ignore tiny drifts, reject absurd values.
            if abs(f - 1) > 0.03 and 0.02 < f < 50:
                factor[i] = f
    # Bars before an ex-date are scaled by the product of all later factors.
    mult = [1.0] * len(g)
    running = 1.0
    for i in range(len(g) - 1, -1, -1):
        mult[i] = running
        running *= factor[i]
    m = pd.Series(mult, index=g.index)
    hist = pd.DataFrame({
        "Open": g["open"].fillna(g["close"]) * m,
        "High": g["high"].fillna(g["close"]) * m,
        "Low": g["low"].fillna(g["close"]) * m,
        "Close": g["close"] * m,
        "Volume": (g["volume"].fillna(0) / m).round(),
    })
    hist["Adj Close"] = hist["Close"]
    hist.index = pd.DatetimeIndex(pd.to_datetime(g["date"]), name="Date")
    return hist[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _dir(exch: str) -> Path:
    d = STORE_DIR / exch
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def stored_days(exch: str) -> list[str]:
    d = STORE_DIR / exch
    if not d.exists():
        return []
    return sorted(p.name[:10] for p in d.glob("????-??-??.csv.gz"))


def _save_day(exch: str, day: str, df: pd.DataFrame) -> None:
    d = _dir(exch)
    cols = ["sym", "series", "open", "high", "low", "close", "prev_close", "volume"]
    tmp = d / f".{day}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        df[cols].to_csv(f, index=False)
    tmp.replace(d / f"{day}.csv.gz")
    names = df.dropna(subset=["name"])
    if not names.empty:
        p = d / "_names.json"
        cur = _read_json(p)
        cur.update({s: str(n).strip() for s, n in zip(names["sym"], names["name"]) if str(n).strip()})
        p.write_text(json.dumps(cur), encoding="utf-8")


def names(exch: str) -> dict[str, str]:
    return _read_json(STORE_DIR / exch / "_names.json")


def summary() -> list[dict]:
    """[{exchange, days, first, last, stale}] for the UI. Cheap: directory listing."""
    out = []
    today = datetime.now(IST).date()
    for exch in SOURCES:
        days = stored_days(exch)
        if not days:
            continue
        last = date.fromisoformat(days[-1])
        out.append({"exchange": exch, "days": len(days), "first": days[0], "last": days[-1],
                    "stale": (today - last).days > STALE_AFTER_DAYS})
    return out


def progress_message() -> str:
    return _progress.get("msg", "")


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

class _Blocked(Exception):
    pass


def _http_get(session: requests.Session, url: str, headers: dict) -> Optional[bytes]:
    """bytes on success, None when the file doesn't exist (404). Raises
    _Blocked on 401/403 and other exceptions on transient failures."""
    r = session.get(url, headers=headers, timeout=25)
    if r.status_code == 404:
        return None
    if r.status_code in (401, 403):
        raise _Blocked(f"HTTP {r.status_code}")
    r.raise_for_status()
    if not r.content or r.content.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        return None  # BSE serves an HTML "not found" page with HTTP 200
    return r.content


def _fetch_day(exch: str, day: date, session: requests.Session) -> tuple[str, Optional[pd.DataFrame]]:
    """('ok', df) | ('missing', None) | raises on transient/blocked."""
    src = SOURCES[exch]
    for tpl in src["urls"]:
        url = tpl.format(ymd=day.strftime("%Y%m%d"), dmy=day.strftime("%d%m%Y"))
        content = _http_get(session, url, src["headers"])
        if content is None:
            continue
        df = parse_bhav(content)
        if not df.empty:
            return "ok", df
    return "missing", None


def _session(exch: str) -> requests.Session:
    s = requests.Session()
    try:
        s.get(SOURCES[exch]["warmup"], headers=SOURCES[exch]["headers"], timeout=10)
    except Exception:
        pass
    return s


def update(exch: str, calendar_days: int = DEFAULT_CALENDAR_DAYS,
           progress: Optional[Callable[[str], None]] = None, workers: int = 3) -> dict:
    """Download every missing trading day in the window. Idempotent; safe to
    call often (no-op when current). Returns counts for logging."""
    today = datetime.now(IST).date()
    have = set(stored_days(exch))
    missing_path = _dir(exch) / "_missing.json"
    known_missing = _read_json(missing_path)
    wanted = []
    for i in range(calendar_days, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        if d.weekday() >= 5 or iso in have or iso in known_missing:
            continue
        wanted.append(d)
    result = {"exchange": exch, "wanted": len(wanted), "ok": 0, "missing": 0,
              "errors": 0, "blocked": False, "gave_up": False}
    if not wanted:
        return result

    session = _session(exch)
    stop = threading.Event()
    done = {"n": 0}
    streak = {"fail": 0}
    lock = threading.Lock()

    def work(d: date) -> None:
        if stop.is_set():
            return
        iso = d.isoformat()
        try:
            status, df = _fetch_day(exch, d, session)
            if status == "ok":
                _save_day(exch, iso, df)
                with lock:
                    result["ok"] += 1
                    streak["fail"] = 0
            elif d < today:
                # No file for a past weekday = exchange holiday. Today's file
                # may simply not be published yet (~6-7 pm IST), so not today.
                with lock:
                    known_missing[iso] = "no file"
                    result["missing"] += 1
        except _Blocked:
            with lock:
                result["blocked"] = True
            stop.set()
        except Exception:
            with lock:
                result["errors"] += 1
                streak["fail"] += 1
                # Unreachable / timing-out exchange: stop instead of spending
                # minutes per file on ~500 files.
                if streak["fail"] >= GIVE_UP_AFTER and result["ok"] == 0:
                    result["gave_up"] = True
                    stop.set()
        finally:
            with lock:
                done["n"] += 1
                msg = f"{exch} price files {done['n']}/{len(wanted)}"
                _progress["msg"] = msg
            if progress and (done["n"] % 10 == 0 or done["n"] == len(wanted)):
                progress(f"downloading {msg}")
            time.sleep(0.25)  # be polite to the exchange servers

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, wanted))

    try:
        missing_path.write_text(json.dumps(known_missing), encoding="utf-8")
    except Exception:
        pass
    _prune(exch, calendar_days)
    _progress["msg"] = ""
    return result


def _prune(exch: str, calendar_days: int) -> None:
    cutoff = (datetime.now(IST).date() - timedelta(days=calendar_days + 30)).isoformat()
    for p in (STORE_DIR / exch).glob("????-??-??.csv.gz"):
        if p.name[:10] < cutoff:
            try:
                p.unlink()
            except Exception:
                pass


def _settings(cfg: Optional[dict]) -> dict:
    p = ((cfg or {}).get("prices") or {})
    return {
        "NSE": bool(p.get("nse_files", True)),
        "BSE": bool(p.get("bse_files", True)),
        "calendar_days": int(p.get("history_calendar_days", DEFAULT_CALENDAR_DAYS)),
    }


def ensure_updated(cfg: Optional[dict] = None, exchanges: Optional[list[str]] = None,
                   progress: Optional[Callable[[str], None]] = None) -> list[dict]:
    """Bring the enabled exchanges' stores up to date. If another thread is
    already updating, wait for it (reporting its progress) instead of
    downloading twice."""
    st = _settings(cfg)
    targets = [e for e in (exchanges or list(SOURCES)) if st.get(e)]
    while not _lock.acquire(timeout=2):
        if progress and _progress.get("msg"):
            progress(f"downloading {_progress['msg']}")
    try:
        results = []
        for exch in targets:
            attempt_path = _dir(exch) / "_last_attempt.json"
            last = _read_json(attempt_path)
            if last.get("failed") and time.time() - last.get("ts", 0) < RETRY_COOLDOWN_MIN * 60:
                continue  # exchange was unreachable recently — use what's stored
            try:
                r = update(exch, st["calendar_days"], progress)
                results.append(r)
                failed = r["blocked"] or r["gave_up"]
                try:
                    attempt_path.write_text(json.dumps({"ts": time.time(), "failed": failed}),
                                            encoding="utf-8")
                except Exception:
                    pass
                if r["wanted"]:
                    print(f"[prices] {exch}: +{r['ok']} days, {r['missing']} holidays, "
                          f"{r['errors']} errors"
                          f"{' — BLOCKED by exchange' if r['blocked'] else ''}"
                          f"{' — unreachable, gave up (retry in 1 h)' if r['gave_up'] else ''}",
                          flush=True)
            except Exception as e:
                print(f"[prices] {exch} update failed: {type(e).__name__}: {e}", flush=True)
        return results
    finally:
        _lock.release()


# ---------------------------------------------------------------------------
# Histories for the batch
# ---------------------------------------------------------------------------

def _load_frames(exch: str, syms: set[str], calendar_days: int) -> pd.DataFrame:
    cutoff = (datetime.now(IST).date() - timedelta(days=calendar_days)).isoformat()
    parts = []
    for day in stored_days(exch):
        if day < cutoff:
            continue
        try:
            df = pd.read_csv(STORE_DIR / exch / f"{day}.csv.gz",
                             dtype={"sym": str, "series": str})
        except Exception:
            continue
        df = df[df["sym"].isin(syms)]
        if not df.empty:
            df["date"] = day
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def histories_for(tickers: list[str], cfg: Optional[dict] = None,
                  progress: Optional[Callable[[str], None]] = None,
                  update_first: bool = True) -> dict[str, pd.DataFrame]:
    """{TICKER: adjusted daily history} for every ticker the exchange files
    cover. NSE tickers are plain symbols (RELIANCE); BSE-only are SYMBOL.BO.
    Tickers not covered (or a stale store) are simply absent — the caller
    fetches those from Yahoo."""
    st = _settings(cfg)
    want: dict[str, dict[str, str]] = {"NSE": {}, "BSE": {}}
    for t in tickers:
        u = t.upper().strip()
        if u.endswith(".BO"):
            want["BSE"][u[:-3]] = u
        elif u.endswith(".NS"):
            want["NSE"][u[:-3]] = t.upper()
        elif "." not in u and not u.startswith("^"):
            want["NSE"][u] = u
    needed = [e for e, m in want.items() if m and st.get(e)]
    if not needed:
        return {}
    if update_first:
        ensure_updated(cfg, needed, progress)

    out: dict[str, pd.DataFrame] = {}
    today = datetime.now(IST).date()
    for exch in needed:
        days = stored_days(exch)
        if not days:
            continue
        if (today - date.fromisoformat(days[-1])).days > STALE_AFTER_DAYS:
            print(f"[prices] {exch} store is stale (last file {days[-1]}) — using Yahoo instead",
                  flush=True)
            continue
        if progress:
            progress(f"assembling {exch} price history")
        frames = _load_frames(exch, set(want[exch]), st["calendar_days"])
        if frames.empty:
            continue
        for sym, g in frames.groupby("sym", sort=False):
            if len(g) < MIN_ROWS:
                continue
            try:
                out[want[exch][sym]] = build_history(g)
            except Exception:
                continue
    return out


def company_name(ticker: str) -> Optional[str]:
    u = ticker.upper()
    if u.endswith(".BO"):
        return names("BSE").get(u[:-3])
    return names("NSE").get(u.replace(".NS", ""))
