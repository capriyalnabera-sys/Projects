"""Batch analyzer: process a list of tickers, persist per-ticker JSON results
into a cache so the dashboard can render fast.

Each result file shape:
{
  "ticker": str, "name": str, "yf_symbol": str, "sector": str,
  "currency": str, "last_close": float, "as_of": iso8601 str,
  "verdict": str, "combined_score": float,
  "technical_score": float, "fundamental_score": float, "telegram_score": float,
  "trade_target": float|null, "target_bull": float|null, "fair_value": float|null,
  "stop_loss": float, "horizon": str, "upside_pct": float|null, "downside_pct": float,
  "rsi_14": float, "sma_50": float, "sma_200": float|null,
  "high_52w": float, "low_52w": float, "atr_14": float, "volume_ratio": float,
  "trailing_pe": float|null, "forward_pe": float|null, "roe": float|null,
  "debt_to_equity": float|null, "earnings_growth": float|null, "revenue_growth": float|null,
  "fair_pe_target": float, "rationale": [str], "entry_note": str|null,
  "tg_mentions": int, "tg_avg_sentiment": float
}
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Callable, Optional

from . import data, fundamentals, recommend, technical
from .recommend import TelegramSignal


def _serialize(ticker: str, sd, tech, fund, rec, tg: Optional[TelegramSignal] = None) -> dict:
    # Last ~30 daily closes for sparklines on recommendation cards.
    spark = []
    try:
        spark = [round(float(v), 2) for v in sd.history["Close"].tail(30).tolist()]
    except Exception:
        pass
    # Daily change %
    day_change = None
    try:
        closes = sd.history["Close"]
        if len(closes) >= 2:
            day_change = round((closes.iloc[-1] / closes.iloc[-2] - 1) * 100, 2)
    except Exception:
        pass
    return {
        "ticker": ticker,
        "name": sd.name,
        "yf_symbol": sd.yf_symbol,
        "sector": sd.sector or "",
        "industry": sd.industry or "",
        "currency": sd.currency,
        "last_close": sd.last_close,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": rec.verdict,
        "raw_verdict": rec.raw_verdict,
        "track_record": rec.track_record,
        "sector_track_record": rec.sector_track_record,
        "calibration_applied": rec.calibration_applied,
        "combined_score": rec.combined_score,
        "technical_score": rec.technical_score,
        "fundamental_score": rec.fundamental_score,
        "telegram_score": rec.telegram_score,
        "trade_target": rec.trade_target,
        "target_bull": rec.target_bull,
        "fair_value": rec.fair_value,
        "stop_loss": rec.stop_loss,
        "horizon": rec.horizon,
        "upside_pct": rec.upside_pct,
        "downside_pct": rec.downside_pct,
        "rsi_14": tech.rsi_14,
        "sma_50": tech.sma_50,
        "sma_200": tech.sma_200,
        "high_52w": tech.high_52w,
        "low_52w": tech.low_52w,
        "atr_14": tech.atr_14,
        "volume_ratio": tech.volume_ratio,
        "avg_daily_value_cr": tech.avg_daily_value_cr,
        "return_30d_pct": tech.return_30d_pct,
        "trailing_pe": fund.trailing_pe,
        "forward_pe": fund.forward_pe,
        "price_to_book": fund.price_to_book,
        "roe": fund.roe,
        "roce": fund.roce,
        "debt_to_equity": fund.debt_to_equity,
        "earnings_growth": fund.earnings_growth,
        "revenue_growth": fund.revenue_growth,
        "profit_margin": fund.profit_margin,
        "dividend_yield": fund.dividend_yield,
        "market_cap_cr": fund.market_cap_cr,
        "book_value": fund.book_value,
        "trailing_eps": fund.trailing_eps,
        "forward_eps": fund.forward_eps,
        "sales_growth_history": fund.sales_growth_history,
        "profit_growth_history": fund.profit_growth_history,
        "fair_pe_target": fund.fair_pe_target,
        "rationale": rec.rationale,
        "entry_note": rec.entry_note,
        "plain_summary": getattr(rec, "plain_summary", ""),
        "tg_mentions": tg.mentions_7d if tg else 0,
        "tg_avg_sentiment": tg.avg_sentiment if tg else 0.0,
        "spark": spark,
        "day_change_pct": day_change,
    }


# Default liquidity floor (₹cr/day) below which a name is a guaranteed HOLD —
# matches recommend.py's gate. Overridable via config recommendation.liquidity_floor_cr.
# Used to skip the expensive deep-analysis network calls on the full sweep.
LIQUIDITY_FLOOR_CR = 0.5


def _liquidity_floor(cfg: dict) -> float:
    return float((cfg or {}).get("recommendation", {}).get("liquidity_floor_cr", LIQUIDITY_FLOOR_CR))


def _illiquid_short_circuit(ticker: str, hist, tech, cfg: dict,
                            tg_signal: Optional[TelegramSignal], regime) -> dict:
    """Build a minimal HOLD result for a sub-liquidity-floor name WITHOUT the
    three network calls the full path makes (.info, screener.in scrape,
    earnings check). These names are HOLD no matter what their fundamentals
    say, so deep analysis is wasted work. Big win on the full NSE+BSE sweep
    where ~half the universe is illiquid BSE micro-caps."""
    from .fundamentals import FundamentalSnapshot
    yf_symbol = data.to_yf_symbol(ticker)
    # Empty fundamentals — not scored (recommend's liquidity gate forces HOLD).
    # notes MUST be [] not None — recommend.recommend iterates fund.notes.
    fund = FundamentalSnapshot(None, None, None, None, notes=[])
    sd = data.StockData(
        ticker=ticker.upper(), yf_symbol=yf_symbol, name=ticker.upper(),
        sector=None, industry=None, currency="INR", history=hist, info={},
    )
    rec = recommend.recommend(
        tech, fund, cfg.get("recommendation", {}), sd.last_close, tg_signal,
        regime=regime, earnings_days=None, prior_verdict=None, prior_score=None,
    )
    serialized = _serialize(ticker.upper(), sd, tech, fund, rec, tg_signal)
    serialized["earnings_in_days"] = None
    serialized["illiquid_skipped"] = True
    return serialized


# Bump when analysis logic changes, so every stock is re-analyzed once.
ANALYSIS_VERSION = "2026-11-01"


def input_key(history, regime: Optional[dict], cfg: Optional[dict]) -> Optional[str]:
    """Fingerprint of everything a verdict depends on that can change within a
    day: the latest price bar, the market regime, the recommendation settings,
    and the date (fundamentals caches and earnings proximity roll daily). Two
    runs with the same key would produce the same verdict, so the second one
    is skipped."""
    try:
        h = history.dropna(subset=["Close"])
        last_day = h.index[-1].date().isoformat()
        last_close = round(float(h["Close"].iloc[-1]), 2)
    except Exception:
        return None
    reg = regime or {}
    rec_cfg = json.dumps((cfg or {}).get("recommendation", {}), sort_keys=True, default=str)
    return "|".join([ANALYSIS_VERSION, date.today().isoformat(), last_day, str(last_close),
                     str(reg.get("state")), str(reg.get("hold_zone")), rec_cfg])


class _NoData:
    """Returned by analyze_one when Yahoo has no price history for a ticker."""
    def __bool__(self) -> bool:  # never mistaken for a real result
        return False


NO_DATA = _NoData()

# Tickers with no price data are skipped for this long before being rechecked.
NO_DATA_RECHECK_DAYS = 7


def _no_data_path(cache_root: Path) -> Path:
    # v2: the v1 registry could contain throttled names misread as "no data"
    # (yfinance hid the network error), so it is discarded rather than trusted.
    old = analysis_dir(cache_root) / "_no_data.json"
    if old.exists():
        try:
            old.unlink()
        except Exception:
            pass
    return analysis_dir(cache_root) / "_no_data_v2.json"


def load_no_data(cache_root: Path) -> dict[str, str]:
    """{TICKER: 'YYYY-MM-DD' last confirmed no-data}."""
    p = _no_data_path(cache_root)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_no_data(cache_root: Path, registry: dict[str, str]) -> None:
    try:
        _no_data_path(cache_root).write_text(json.dumps(registry), encoding="utf-8")
    except Exception:
        pass


def analyze_one(
    ticker: str,
    cfg: dict,
    cache_root: Path,
    tg_signal: Optional[TelegramSignal] = None,
    prefetched_history=None,
    regime: Optional[dict] = None,
    sector_stats: Optional[dict] = None,
) -> Optional[dict]:
    # Fast liquidity pre-check on the FREE prefetched history. A name below the
    # ₹1cr/day floor is a guaranteed HOLD, so short-circuit before the three
    # network calls (.info, screener.in, earnings) the full path makes.
    pre_tech = None
    if prefetched_history is not None and not getattr(prefetched_history, "empty", True):
        try:
            clean = prefetched_history.dropna(subset=["Close"])
            if not clean.empty:
                pre_tech = technical.analyze(clean)
                if (pre_tech.avg_daily_value_cr is not None
                        and pre_tech.avg_daily_value_cr < _liquidity_floor(cfg)):
                    return _illiquid_short_circuit(
                        ticker, clean, pre_tech, cfg, tg_signal, regime)
        except Exception:
            pre_tech = None

    try:
        sd = data.fetch(ticker, prefetched_history=prefetched_history)
    except data.NoPriceHistory:
        return NO_DATA
    except Exception:
        return None
    try:
        # Reuse the pre-check technical if we computed it (liquid name that
        # passed the floor) — same history, no need to recompute.
        tech = pre_tech if pre_tech is not None else technical.analyze(sd.history)
        fund = fundamentals.analyze(
            sd.info, sd.sector,
            ticker=sd.ticker,
            screener_cache_dir=cache_root / "screener_in",
            sector_stats=sector_stats,
            return_30d_pct=tech.return_30d_pct,
        )
        from . import earnings as earnings_mod
        is_pre, days_left = earnings_mod.is_pre_earnings(ticker)

        # Read PRIOR batch's verdict/score for persistence smoothing.
        # Prefer the RAW verdict (pre-overlay) if available so we compare
        # apples-to-apples — without this, regime downgrades in the prior
        # batch would leak into persistence on the next batch.
        prior = read_result(ticker, cache_root)
        prior_verdict = (prior or {}).get("raw_verdict") or (prior or {}).get("verdict")
        prior_score = (prior or {}).get("combined_score")

        rec = recommend.recommend(
            tech, fund, cfg.get("recommendation", {}), sd.last_close, tg_signal,
            regime=regime,
            earnings_days=days_left if is_pre else None,
            prior_verdict=prior_verdict,
            prior_score=prior_score,
            sector=sd.sector,
        )
        serialized = _serialize(ticker.upper(), sd, tech, fund, rec, tg_signal)
        serialized["earnings_in_days"] = days_left
        return serialized
    except Exception:
        return None


def analysis_dir(cache_root: Path) -> Path:
    d = cache_root / "analysis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(ticker: str, cache_root: Path) -> Path:
    safe = ticker.upper().replace("&", "_AMP_").replace("/", "_")
    return analysis_dir(cache_root) / f"{safe}.json"


def write_result(result: dict, cache_root: Path) -> None:
    cache_path(result["ticker"], cache_root).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


def read_result(ticker: str, cache_root: Path) -> Optional[dict]:
    p = cache_path(ticker, cache_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_universe(tickers: list[str], cache_root: Path) -> list[dict]:
    out: list[dict] = []
    for t in tickers:
        r = read_result(t, cache_root)
        if r:
            out.append(r)
    return out


# Default liquidity floor for the "live set" — matches recommend.py's HOLD gate.
# Callers pass the config value; this is only the fallback.
LIVE_SET_MIN_TURNOVER_CR = 0.5


def compute_live_set(tickers: list[str], cache_root: Path,
                     min_turnover_cr: float = LIVE_SET_MIN_TURNOVER_CR) -> list[str]:
    """From a just-swept universe, return the subset worth re-running every
    routine refresh: tickers that produced an analysis AND cleared the
    liquidity floor. Everything else (no data / delisted / dead shell /
    sub-floor turnover) is dropped so routine refreshes stay fast.
    """
    live: list[str] = []
    for t in tickers:
        r = read_result(t, cache_root)
        if not r:
            continue
        adv = r.get("avg_daily_value_cr")
        # Keep if it cleared the floor. If turnover is unknown but we DID get
        # an analysis with a real last_close, keep it too (benefit of doubt —
        # the next sweep re-checks).
        if adv is not None:
            if adv >= min_turnover_cr:
                live.append(t)
        elif r.get("last_close"):
            live.append(t)
    return live


def write_status(cache_root: Path, status: dict) -> None:
    (analysis_dir(cache_root) / "_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )


def read_status(cache_root: Path) -> dict:
    p = analysis_dir(cache_root) / "_status.json"
    if not p.exists():
        return {"running": False}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False}


def run_batch(
    tickers: list[str],
    cfg: dict,
    cache_root: Path,
    tg_signals: Optional[dict[str, TelegramSignal]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ttl_minutes: int = 0,           # 0 = always re-analyze
    max_workers: int = 8,           # retry-pass workers (cfg batch.analysis_workers sizes analysis)
    regime=None,                    # dict, or a Future resolving to one
    skip_unchanged: bool = True,    # skip stocks whose inputs haven't changed

) -> dict:
    """Run batch analysis in parallel. Skips tickers whose cache is fresh.
    Updates _status.json so /api/status can report progress.

    Parallel design: yfinance + screener.in calls are I/O-bound, so threads
    work well. Empirically 8 concurrent workers cut a NIFTY 500 batch from
    ~15 min to ~2-3 min without yfinance rate-limiting us.
    """
    started = time.time()
    total = len(tickers)
    from . import profiler as _profmod
    prof = _profmod.current()
    own_prof = prof is None
    if own_prof:
        prof = _profmod.Profiler()
        _profmod.install(prof)
    prof.meta.update({"tickers": len(tickers)})
    _t = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    write_status(cache_root, {
        "running": True, "total": total, "done": 0, "errors": 0,
        "started_at": started_at,
    })

    # First pass: figure out which tickers actually need work (TTL filter +
    # names confirmed to have no price data within the last week).
    no_data_reg = load_no_data(cache_root)
    recheck_cutoff = (datetime.now(timezone.utc).date()
                      - timedelta(days=NO_DATA_RECHECK_DAYS)).isoformat()
    to_process: list[str] = []
    skipped = 0
    skipped_no_data = 0
    for t in tickers:
        seen = no_data_reg.get(t.upper())
        if seen and seen >= recheck_cutoff:
            skipped += 1
            skipped_no_data += 1
            continue
        if ttl_minutes > 0:
            existing = read_result(t, cache_root)
            if existing:
                try:
                    age = time.time() - datetime.fromisoformat(existing["as_of"]).timestamp()
                    if age < ttl_minutes * 60:
                        skipped += 1
                        continue
                except Exception:
                    pass
        to_process.append(t)

    _t = prof.mark("check what needs refreshing", _t)
    prof.meta.update({"to_process": len(to_process), "skipped": skipped})
    done = skipped          # processed so far (drives the progress counter)
    ok = 0                  # produced a fresh analysis this run
    failed: list[str] = []  # transient failures — retried
    no_data_now: list[str] = []
    progress_lock = threading.Lock()
    counter = {"i": 0}

    # Bulk pre-fetch all histories in one yf.download call — way faster than
    # N per-ticker history HTTP roundtrips. The slice for each ticker is passed
    # into analyze_one so the per-ticker yfinance.history() call is skipped.
    write_status(cache_root, {
        "running": True, "total": total, "done": done, "errors": 0,
        "current": f"bulk-fetching {len(to_process)} histories",
        "started_at": started_at,
    })
    histories: dict = {}
    if to_process:
        # Exchange daily price files first — they cover the whole NSE/BSE
        # listing in one place. Yahoo only fills in what they don't cover.
        try:
            from . import exchange_prices
            histories = exchange_prices.histories_for(
                to_process, cfg,
                progress=lambda msg: write_status(cache_root, {
                    "running": True, "total": total, "done": done, "errors": 0,
                    "current": msg, "started_at": started_at,
                }))
        except Exception as e:
            print(f"[prices] exchange files unavailable: {type(e).__name__}: {e}", flush=True)
            histories = {}
        _t = prof.mark("price history: exchange files", _t)
        prof.meta["from_exchange_files"] = len(histories)
        rest = [t for t in to_process if t.upper() not in histories]
        prof.meta["from_yahoo"] = len(rest)
        if rest:
            write_status(cache_root, {
                "running": True, "total": total, "done": done, "errors": 0,
                "current": f"fetching {len(rest)} histories from Yahoo",
                "started_at": started_at,
            })
            histories.update(data.bulk_fetch_histories(rest, period="2y"))
        _t = prof.mark("price history: Yahoo bulk", _t)

    # ---- Skip stocks whose inputs haven't changed since their last analysis --
    # Prices now come from exchange files published once a day, so a repeat
    # refresh the same day would otherwise redo every stock on identical data.
    skipped_unchanged = 0
    if skip_unchanged and to_process:
        if hasattr(regime, "result"):
            try:
                regime = regime.result()
            except Exception:
                regime = None
        keep: list[str] = []
        for tk in to_process:
            h = histories.get(tk.upper())
            key = input_key(h, regime, cfg) if h is not None and not getattr(h, "empty", True) else None
            prev = read_result(tk, cache_root) if key else None
            if key and prev and prev.get("input_key") == key:
                skipped_unchanged += 1
                continue
            keep.append(tk)
        to_process = keep
        skipped += skipped_unchanged
        done += skipped_unchanged
    _t = prof.mark("skip unchanged stocks", _t)
    prof.meta.update({"skipped_unchanged": skipped_unchanged, "to_process": len(to_process)})

    # Company names from the exchange files, for rows Yahoo couldn't name.
    try:
        from . import exchange_prices as _ep
        _names = {"NSE": _ep.names("NSE"), "BSE": _ep.names("BSE")}
    except Exception:
        _names = {"NSE": {}, "BSE": {}}

    def _fill_name(result: dict) -> None:
        tk = (result.get("ticker") or "").upper()
        if result.get("name") and result["name"].upper() != tk:
            return
        n = (_names["BSE"].get(tk[:-3]) if tk.endswith(".BO")
             else _names["NSE"].get(tk.replace(".NS", "")))
        if n:
            result["name"] = n

    # Load PRIOR sector stats (computed from last batch's results). We use
    # last batch's distribution for relative scoring on this batch — slight lag
    # but avoids the chicken-and-egg of needing stats before analyzing anything.
    from . import sector_stats as ssmod
    sector_stats = ssmod.load_sector_stats(cache_root)

    # ---- Pipeline: per-server network prefetch overlapped with analysis -----
    # Liquid names need Yahoo .info, an earnings date and screener.in
    # fundamentals. Each server gets its own pool, capped at a polite
    # concurrency, so all servers work at once (previously each worker hit
    # them one after another). Analysis is CPU-bound pandas work that the GIL
    # serializes — measured: 1 thread 29 s, 4-8 threads ~56 s for the full
    # universe — so it runs on a small pool *alongside* the network: names
    # that need no network start immediately, and each liquid name is
    # analyzed the moment its own fetches finish.
    floor = _liquidity_floor(cfg)
    bcfg = (cfg or {}).get("batch", {}) or {}
    def _is_liquid(h) -> bool:
        try:
            tail = h.dropna(subset=["Close"]).tail(20)
            adv = float((tail["Close"] * tail["Volume"]).mean()) / 1e7
        except Exception:
            return True                  # unknown turnover: give it the full path
        return adv != adv or adv >= floor

    need_net: list[str] = []             # history in hand, liquid: needs fundamentals
    need_history: list[str] = []         # no history yet: check Yahoo first
    no_net: list[str] = []               # thin names: analyze right away
    for tk in to_process:
        h = histories.get(tk.upper())
        if h is None or getattr(h, "empty", True):
            need_history.append(tk)
        elif _is_liquid(h):
            need_net.append(tk)
        else:
            no_net.append(tk)
    # Analysis never waits on the network now, and the GIL makes extra threads
    # slower for this pandas work (measured: 1 thread 29 s, 4+ threads ~56 s).
    analysis_workers = max(1, int(bcfg.get("analysis_workers", 1)))
    no_history: set[str] = set()         # Yahoo confirmed: no price data
    prof.meta.update({"liquid_needing_fundamentals": len(need_net),
                      "needing_history_check": len(need_history),
                      "analysis_workers": analysis_workers})

    # Regime / research signals may still be computing in the background.
    # Resolve them once, on first use, inside an analysis worker — so the
    # network pools never wait on them.
    ctx = {"ready": False}
    ctx_lock = threading.Lock()

    def _context():
        nonlocal regime, tg_signals
        with ctx_lock:
            if not ctx["ready"]:
                t0 = time.perf_counter()
                if hasattr(regime, "result"):
                    try:
                        regime = regime.result()
                    except Exception:
                        regime = None
                if hasattr(tg_signals, "result"):
                    try:
                        tg_signals = tg_signals.result()
                    except Exception:
                        tg_signals = {}
                prof.add("wait: regime / research signals", time.perf_counter() - t0)
                ctx["ready"] = True
        return regime, tg_signals

    def _work(t: str):
        if t.upper() in no_history:
            return t, NO_DATA
        reg, tgs = _context()
        prefetched = histories.get(t.upper())
        result = analyze_one(
            t, cfg, cache_root,
            tg_signal=(tgs or {}).get(t.upper()),
            prefetched_history=prefetched,
            regime=reg,
            sector_stats=sector_stats,
        )
        if result:
            _fill_name(result)
            h = histories.get(t.upper())
            if h is not None and not getattr(h, "empty", True):
                result["input_key"] = input_key(h, reg, cfg)
            write_result(result, cache_root)
            fresh_results[t.upper()] = result
        return t, result

    def _status(current: str, running: bool = True) -> None:
        write_status(cache_root, {
            "running": running, "total": total, "done": done, "ok": ok,
            "errors": len(failed), "no_data": len(no_data_now) + skipped_no_data,
            "current": current, "started_at": started_at,
        })

    def _account(fut, tk: str) -> None:
        nonlocal done, ok
        try:
            _, result = fut.result()
        except Exception:
            result = None
        with progress_lock:
            counter["i"] += 1
            done += 1
            if result is NO_DATA:
                no_data_now.append(tk)
            elif result:
                ok += 1
            else:
                failed.append(tk)
            if progress_cb:
                progress_cb(counter["i"] + skipped, total, tk)
            if counter["i"] % 5 == 0 or counter["i"] == len(to_process):
                _status(tk)

    fresh_results: dict[str, dict] = {}  # this run's results, for the snapshot
    from .profiler import timed as profiler_timed
    PER_CALL_CEILING = 30                # generous seconds per queued network call
    analysis_futs: list = []
    sub_lock = threading.Lock()
    aex = ThreadPoolExecutor(max_workers=analysis_workers)

    def _submit(tk: str) -> None:
        with sub_lock:
            f = aex.submit(_work, tk)
            analysis_futs.append(f)
        f.add_done_callback(lambda fut, tk=tk: _account(fut, tk))

    for tk in no_net:
        _submit(tk)                      # no network needed: start now

    if need_net or need_history:
        import yfinance as _yf
        from . import earnings as _earn, screener_in as _screener
        yahoo_workers = int(bcfg.get("yahoo_workers", 8))
        screener_workers = int(bcfg.get("screener_workers", 6))
        scr_dir = cache_root / "screener_in"
        yex = ThreadPoolExecutor(max_workers=yahoo_workers)
        sex = ThreadPoolExecutor(max_workers=screener_workers)
        pf_lock = threading.Lock()
        # Jobs spawn follow-up jobs (history -> fundamentals), so completion is
        # tracked with an outstanding-job counter rather than executor shutdown.
        # It starts at 1 as a guard while the initial jobs are being queued.
        pf = {"outstanding": 1, "done": 0}
        all_done = threading.Event()
        remaining: dict[str, int] = {}

        def _finish() -> None:
            with pf_lock:
                pf["outstanding"] -= 1
                pf["done"] += 1
                n, zero = pf["done"], pf["outstanding"] == 0
            if zero:
                all_done.set()
            if n % 25 == 0:
                write_status(cache_root, {
                    "running": True, "total": total, "done": done, "ok": ok, "errors": len(failed),
                    "current": f"fetching from Yahoo + screener.in in parallel ({n} calls done), "
                               f"analyzing as data arrives",
                    "started_at": started_at,
                })

        def _spawn(ex, fn, *args) -> None:
            with pf_lock:
                pf["outstanding"] += 1

            def run():
                try:
                    fn(*args)
                except Exception:
                    pass
                finally:
                    _finish()
            ex.submit(run)

        def _part_done(tk: str) -> None:
            with pf_lock:
                remaining[tk] -= 1
                ready = remaining[tk] == 0
            if ready:
                _submit(tk)              # all of this name's data is in: analyze it

        def _yahoo_part(fn, tk: str) -> None:
            try:
                fn(tk)
            finally:
                _part_done(tk)

        def _screener_part(tk: str) -> None:
            try:
                _screener.fetch(tk, cache_dir=scr_dir, ttl_minutes=_screener.SCREENER_TTL_MINUTES)
            except Exception as e:
                print(f"[batch] screener prefetch {tk}: {type(e).__name__}: {e}", flush=True)
            finally:
                _part_done(tk)

        def _fundamentals(tk: str) -> None:
            nse = not tk.upper().endswith(".BO")
            with pf_lock:
                remaining[tk] = 3 if nse else 2
            _spawn(yex, _yahoo_part, data.fetch_info, tk)
            _spawn(yex, _yahoo_part, _earn.next_earnings_date, tk)
            if nse:
                _spawn(sex, _screener_part, tk)

        def _history_then_route(tk: str) -> None:
            # Dead listings stop here: no info / earnings / screener calls.
            try:
                with profiler_timed("net: yahoo history (per stock)"):
                    h = data.history_strict(_yf.Ticker(data.to_yf_symbol(tk)))
                h = h.dropna(subset=["Close"]) if h is not None else h
            except data.NoPriceHistory:
                no_history.add(tk.upper())
                _submit(tk)
                return
            except Exception:
                _submit(tk)              # transient: analysis retries via data.fetch
                return
            if h is None or h.empty:
                no_history.add(tk.upper())
                _submit(tk)
                return
            histories[tk.upper()] = h
            if _is_liquid(h):
                _fundamentals(tk)
            else:
                _submit(tk)

        for tk in need_net:
            _fundamentals(tk)
        for tk in need_history:
            _spawn(yex, _history_then_route, tk)
        _finish()                        # release the guard
        all_done.wait(timeout=PER_CALL_CEILING * max(pf["outstanding"] + pf["done"], 1))
        yex.shutdown(wait=False, cancel_futures=True)
        sex.shutdown(wait=False, cancel_futures=True)
    _t = prof.mark("fetch fundamentals (parallel per server, analysis overlapped)", _t)

    # Every name has been submitted; wait for the analysis that is still queued.
    # Hard cap so one hung call can never freeze the batch.
    PER_TICKER_TIMEOUT = 45
    with sub_lock:
        pending = list(analysis_futs)
    _, not_done = wait(pending, timeout=PER_TICKER_TIMEOUT * max(len(pending), 1) + 60)
    for f in not_done:
        f.cancel()
    aex.shutdown(wait=not not_done, cancel_futures=bool(not_done))

    _t = prof.mark("analyze stocks (remaining after network)", _t)

    # Retry pass for transient failures — also parallel.
    # Throttling windows last minutes, so short backoffs just get throttled again.
    backoffs = [20, 60]
    for round_idx, sleep_secs in enumerate(backoffs):
        if not failed:
            break
        time.sleep(sleep_secs)
        retry_list = list(failed)
        failed = []
        retry_counter = {"i": 0}

        def _retry(t: str):
            reg, tgs = _context()
            prefetched = histories.get(t.upper())
            result = analyze_one(
                t, cfg, cache_root,
                tg_signal=(tgs or {}).get(t.upper()),
                prefetched_history=prefetched,
                regime=reg,
                sector_stats=sector_stats,
            )
            if result:
                _fill_name(result)
                write_result(result, cache_root)
            return t, result

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_retry, t) for t in retry_list]
            for fut in as_completed(futs):
                try:
                    t, result = fut.result()
                except Exception:
                    continue
                with progress_lock:
                    retry_counter["i"] += 1
                    if result is NO_DATA:
                        no_data_now.append(t)
                    elif result:
                        ok += 1
                    else:
                        failed.append(t)
                    if retry_counter["i"] % 3 == 0 or retry_counter["i"] == len(retry_list):
                        _status(f"retry {round_idx+1}: {t} ({retry_counter['i']}/{len(retry_list)})")

    _t = prof.mark("retry failed stocks", _t)
    errors = len(failed)
    elapsed = time.time() - started

    # Remember confirmed no-data names (skip for a week); forget any that
    # produced data again.
    today_iso = datetime.now(timezone.utc).date().isoformat()
    for t in no_data_now:
        no_data_reg[t.upper()] = today_iso
    for t in to_process:
        if t not in no_data_now and read_result(t, cache_root):
            no_data_reg.pop(t.upper(), None)
    save_no_data(cache_root, no_data_reg)

    # Compute fresh sector stats from this batch's results so the NEXT batch
    # has up-to-date sector medians for relative scoring.
    if ok:                           # nothing re-analyzed → stats can't have changed
        try:
            fresh_stats = ssmod.compute_sector_stats(cache_root)
            ssmod.save_sector_stats(fresh_stats, cache_root)
        except Exception:
            pass

    _t = prof.mark("sector stats", _t)
    final = {
        "running": False, "total": total, "done": done, "ok": ok, "errors": errors,
        "no_data": len(no_data_now) + skipped_no_data,
        "unchanged": skipped_unchanged,
        "elapsed_sec": round(elapsed, 1),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "failed_tickers": failed[:50],  # store residue (capped) for diagnosis
    }
    write_status(cache_root, final)

    # Daily snapshot of verdicts for backtesting / accuracy tracking.
    try:
        snap_dir = cache_root / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).date().isoformat()
        snap_path = snap_dir / f"{today}.json"
        snap = {}
        if snap_path.exists():
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
            except Exception:
                snap = {}
        # Nothing re-analyzed and today's snapshot exists: it already stands.
        for t in (tickers if (ok or not snap) else []):
            r = fresh_results.get(t.upper()) or read_result(t, cache_root)
            if r:
                snap[t.upper()] = {
                    "verdict": r.get("verdict"),
                    # raw_verdict = pre-overlay, so calibration can separate
                    # "the model was wrong" from "a gate suppressed it".
                    "raw_verdict": r.get("raw_verdict"),
                    # sector is REQUIRED for per-sector calibration — without it
                    # accuracy.py buckets everything as "Unknown" and the sector
                    # track-record panel can never learn anything.
                    "sector": r.get("sector"),
                    "combined_score": r.get("combined_score"),
                    "last_close": r.get("last_close"),
                    "trade_target": r.get("trade_target"),
                    "stop_loss": r.get("stop_loss"),
                    "rsi_14": r.get("rsi_14"),
                }
        if ok or not snap_path.exists():
            snap_path.write_text(json.dumps(snap), encoding="utf-8")
    except Exception:
        pass
    prof.mark("daily snapshot", _t)
    if own_prof:
        _profmod.save(prof.report(), cache_root)
        _profmod.install(None)

    return final
