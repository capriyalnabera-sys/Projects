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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    max_workers: int = 16,          # parallelism for yfinance/screener fetches
    regime: Optional[dict] = None,
) -> dict:
    """Run batch analysis in parallel. Skips tickers whose cache is fresh.
    Updates _status.json so /api/status can report progress.

    Parallel design: yfinance + screener.in calls are I/O-bound, so threads
    work well. Empirically 8 concurrent workers cut a NIFTY 500 batch from
    ~15 min to ~2-3 min without yfinance rate-limiting us.
    """
    started = time.time()
    total = len(tickers)
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
    histories = data.bulk_fetch_histories(to_process, period="2y") if to_process else {}

    # Load PRIOR sector stats (computed from last batch's results). We use
    # last batch's distribution for relative scoring on this batch — slight lag
    # but avoids the chicken-and-egg of needing stats before analyzing anything.
    from . import sector_stats as ssmod
    sector_stats = ssmod.load_sector_stats(cache_root)

    def _work(t: str):
        prefetched = histories.get(t.upper())
        result = analyze_one(
            t, cfg, cache_root,
            tg_signal=(tg_signals or {}).get(t.upper()),
            prefetched_history=prefetched,
            regime=regime,
            sector_stats=sector_stats,
        )
        if result:
            write_result(result, cache_root)
        return t, result

    def _status(current: str, running: bool = True) -> None:
        write_status(cache_root, {
            "running": running, "total": total, "done": done, "ok": ok,
            "errors": len(failed), "no_data": len(no_data_now) + skipped_no_data,
            "current": current, "started_at": started_at,
        })

    # Per-task hard timeout — a single hung yfinance call used to freeze the
    # whole batch for hours. 45s is plenty for any one ticker's analysis.
    PER_TICKER_TIMEOUT = 45
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_to_ticker = {ex.submit(_work, t): t for t in to_process}
        try:
            for fut in as_completed(fut_to_ticker, timeout=PER_TICKER_TIMEOUT * len(to_process) + 60):
                t_assigned = fut_to_ticker[fut]
                try:
                    t, result = fut.result(timeout=PER_TICKER_TIMEOUT)
                except Exception:
                    t, result = t_assigned, None
                with progress_lock:
                    counter["i"] += 1
                    done += 1
                    if result is NO_DATA:
                        no_data_now.append(t_assigned)
                    elif result:
                        ok += 1
                    else:
                        failed.append(t_assigned)
                    if progress_cb:
                        progress_cb(counter["i"] + skipped, total, t_assigned)
                    if counter["i"] % 5 == 0 or counter["i"] == len(to_process):
                        _status(t_assigned)
        except Exception:
            # Overall as_completed timeout — cancel anything still pending
            # and let what we have be the result. Better than hanging forever.
            for f in fut_to_ticker:
                if not f.done():
                    f.cancel()

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
            prefetched = histories.get(t.upper())
            result = analyze_one(
                t, cfg, cache_root,
                tg_signal=(tg_signals or {}).get(t.upper()),
                prefetched_history=prefetched,
                regime=regime,
                sector_stats=sector_stats,
            )
            if result:
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
    try:
        fresh_stats = ssmod.compute_sector_stats(cache_root)
        ssmod.save_sector_stats(fresh_stats, cache_root)
    except Exception:
        pass

    final = {
        "running": False, "total": total, "done": done, "ok": ok, "errors": errors,
        "no_data": len(no_data_now) + skipped_no_data,
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
        for t in tickers:
            r = read_result(t, cache_root)
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
        snap_path.write_text(json.dumps(snap), encoding="utf-8")
    except Exception:
        pass

    return final
