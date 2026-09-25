"""Local Flask UI for the analyzer.

Routes:
  /                       — recommendations home (curated lists)
  /screener?universe=X    — filter/sort table view of cached batch results
  /stock/<ticker>         — screener.in-style detail view with charts
  /analyze?tickers=...    — ad-hoc multi-ticker analysis (live)
  /api/refresh?universe=X — start batch refresh in background
  /api/status             — JSON, current refresh progress
  /api/chart/<ticker>     — JSON of price/SMA/RSI/MACD arrays for charting
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from . import batch, data, fundamentals, recommend, technical, universe
from .recommend import TelegramSignal


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


def _startup_prewarm():
    """Warm caches in a background thread so the first page request is snappy.
    Pre-warms: NSE session cookies, regime/VIX, accuracy cache, calibration."""
    try:
        from . import nse_quote, regime as regime_mod, accuracy
        nse_quote._get_session()           # NSE cookie warmup
        regime_mod.get_regime()            # cache regime + VIX
        accuracy.evaluate(Path("data/cache/snapshots"))  # accuracy cache hit
        from . import calibration
        calibration.compute(Path("data/cache/snapshots"))  # learned thresholds ready
        _prewarm_pages_async()             # hot pages memoized before first visit
    except Exception:
        pass


threading.Thread(target=_startup_prewarm, daemon=True).start()


def _inr_compact(n):
    if n is None:
        return "—"
    try:
        n = float(n)
        if n != n or n in (float("inf"), float("-inf")):  # NaN / inf guard
            return "—"
    except (TypeError, ValueError):
        return str(n)
    sign = "-" if n < 0 else ""
    v = abs(n)
    if v >= 1e7:  return f"{sign}₹{v / 1e7:.2f} Cr"
    if v >= 1e5:  return f"{sign}₹{v / 1e5:.2f} L"
    if v >= 1e3:  return f"{sign}₹{v / 1e3:.1f}k"
    return f"{sign}₹{v:.2f}"


def _inr_full(n, decimals=2):
    """Indian comma-separated number, e.g. 12,34,567.89."""
    if n is None:
        return "—"
    try:
        n = float(n)
        if n != n or n in (float("inf"), float("-inf")):  # NaN / inf guard
            return "—"
    except (TypeError, ValueError):
        return str(n)
    sign = "-" if n < 0 else ""
    v = abs(n)
    integer = int(v)
    decimal_part = f"{v:.{decimals}f}".split(".")[1] if decimals > 0 else ""
    s = str(integer)
    # Indian grouping: last 3 digits, then groups of 2
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        # group rest by 2 from the right
        chunks = []
        while len(rest) > 2:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            chunks.append(rest)
        grouped = ",".join(reversed(chunks)) + "," + last3
    return sign + "₹" + grouped + (("." + decimal_part) if decimal_part else "")


app.jinja_env.filters["inr_compact"] = _inr_compact
app.jinja_env.filters["inr_full"] = _inr_full


def _load_config() -> dict:
    p = Path("config.yaml")
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cache_root() -> Path:
    return Path(_load_config().get("cache", {}).get("dir", "data/cache"))


# ---------------------------------------------------------------------------
# In-memory request cache. The heavy per-page work is re-reading thousands of
# per-ticker JSON files (rows) and per-universe cached-counts on EVERY page
# load. Those only change when a batch refresh writes results, so a short-TTL
# memo makes repeat page loads near-instant. Explicitly cleared when a batch
# finishes so fresh verdicts appear immediately.
_MEMO_LOCK = threading.Lock()
_MEMO: dict[str, tuple[float, object]] = {}


def _memo_get(key: str, ttl_seconds: float, builder):
    now = time.time()
    with _MEMO_LOCK:
        hit = _MEMO.get(key)
        if hit is not None and (now - hit[0]) < ttl_seconds:
            return hit[1]
    val = builder()
    with _MEMO_LOCK:
        _MEMO[key] = (time.time(), val)
    return val


def _memo_clear() -> None:
    with _MEMO_LOCK:
        _MEMO.clear()


def _prewarm_pages_async() -> None:
    """After a batch finishes (memo just cleared), rebuild the hot pages in the
    background so the first human visitor gets the memoized ~50ms response
    instead of paying the ~6s cold render of the 1,900-row screener."""
    import requests as _rq
    for url in ("http://127.0.0.1:5000/screener", "http://127.0.0.1:5000/"):
        try:
            _rq.get(url, timeout=120)
        except Exception:
            continue


# Universe options shown in the dropdown. "alllisted" (full NSE+BSE) is last.
_UNIVERSE_MENU = ("all", "nifty50", "nifty100", "nifty500",
                  "midcap150", "smallcap250", "midsmall400", "alllisted")
_BIG_UNIVERSES = {"alllisted", "allnse", "allbse", "nsebse", "everylisted"}
_UNIVERSE_LABELS = {
    "all": "NIFTY ALL", "nifty50": "NIFTY 50", "nifty100": "NIFTY 100",
    "nifty500": "NIFTY 500", "midcap150": "MIDCAP 150",
    "smallcap250": "SMALLCAP 250", "midsmall400": "MIDSMALL 400",
    "alllisted": "NSE+BSE ALL",
}


def _spark_svg_fields(rows: list[dict]) -> None:
    """Precompute each row's sparkline polyline (points string + color) in
    Python. Doing this in Jinja was ~56k template-loop iterations per screener
    load (1,883 rows × 30 points) — the single biggest render cost (~6s).
    Python string-formatting does the same work in ~40ms. Mutates rows."""
    for r in rows:
        if "spark_points" in r:
            continue
        s = r.get("spark") or []
        pts = ""
        if len(s) >= 2:
            lo, hi = min(s), max(s)
            rng = (hi - lo) or 1
            step = 60 / (len(s) - 1)
            pts = " ".join(
                f"{i * step:.1f},{18 - ((v - lo) / rng) * 16:.1f}"
                for i, v in enumerate(s)
            )
        r["spark_points"] = pts
        score = r.get("combined_score") or 0
        r["spark_color"] = "#16a34a" if score > 0 else ("#ef4444" if score < 0 else "#9ca3af")


def _rows_for(name: str, tickers: list[str], cache_root: Path) -> list[dict]:
    """Memoized row loading + spark precompute — shared by home/screener/market."""
    def _build():
        rows = batch.read_universe(tickers, cache_root)
        _spark_svg_fields(rows)
        return rows
    # Rows only change when a batch writes results — and batch completion
    # clears this memo — so the TTL is just a safety net, not freshness.
    return _memo_get(f"rows:{name}", 600, _build)


def _resolve_display_tickers(name: str, cache_root: Path) -> list[str]:
    """Tickers to DISPLAY for a universe. For the big NSE+BSE universe this is
    the live set (proven-liquid subset) — never the full ~5,000, which would
    mean thousands of disk reads per page load and a meaningless wall of
    illiquid shells. Returns [] for the big universe before any full sweep
    has run (the dashboard then prompts the user to run one)."""
    if name.lower().replace("_", "") in _BIG_UNIVERSES:
        return universe.load_live_set(cache_root / "universe") or []
    return universe.get_universe(name, cache_dir=cache_root / "universe")


def _build_universes_meta(active_name: str, cache_root: Path) -> list[dict]:
    """Build the universe-selector metadata (name, total, cached, active).

    The cached-counts scan opens one JSON per ticker across every universe
    (~800+ file reads) — memoized for 60s since counts only move during a
    batch. The 'active' flag is applied per-request on a copy.

    For the big NSE+BSE universe we report the live-set size as 'cached'
    (a single cheap file read) instead of scanning ~5,000 names.
    """
    def _build() -> list[dict]:
        meta: list[dict] = []
        for u_name in _UNIVERSE_MENU:
            try:
                ut = universe.get_universe(u_name, cache_dir=cache_root / "universe")
                if u_name.lower().replace("_", "") in _BIG_UNIVERSES:
                    live = universe.load_live_set(cache_root / "universe") or []
                    cached = len(live)
                else:
                    cached = sum(1 for t in ut if batch.read_result(t, cache_root) is not None)
                meta.append({"name": u_name, "label": _UNIVERSE_LABELS.get(u_name, u_name.upper()),
                             "total": len(ut), "cached": cached,
                             "is_big": u_name.lower().replace("_", "") in _BIG_UNIVERSES})
            except Exception:
                continue
        return meta

    base = _memo_get("universes_meta", 600, _build)
    return [{**m, "active": m["name"] == active_name} for m in base]


def _build_aliases(tickers: list[str], fetched: dict[str, "data.StockData"]) -> dict[str, str]:
    suffixes = (" limited", " ltd", " ltd.", " industries", " corporation", " corp",
                " inc", " inc.", " co.", " company")
    skip = {"the", "of", "and"}
    out: dict[str, str] = {}
    for t in tickers:
        tk = t.upper()
        sd = fetched.get(tk)
        if sd is None:
            continue
        nm = (sd.info.get("longName") or sd.info.get("shortName") or sd.name or "").strip().lower()
        if not nm:
            continue
        candidates = {nm}
        for s in suffixes:
            if nm.endswith(s):
                candidates.add(nm[: -len(s)].strip())
        toks = [w for w in nm.split() if w not in skip]
        if len(toks) >= 2:
            candidates.add(" ".join(toks[:2]))
        for phrase in candidates:
            if len(phrase) >= 6 and " " in phrase:
                out[phrase] = tk
    return out


def _live_analyze(tickers: list[str], with_telegram: bool, telegram_days: int = 7):
    cfg = _load_config()
    cache_root = _cache_root()
    fetched: dict[str, data.StockData] = {}
    errors: list[tuple[str, str]] = []
    for t in tickers:
        try:
            fetched[t.upper()] = data.fetch(t)
        except Exception as e:
            errors.append((t, str(e)))

    tg_signals: dict[str, TelegramSignal] = {}
    if with_telegram:
        from . import telegram_ingest
        tcfg = cfg.get("telegram", {})
        if tcfg.get("api_id") and tcfg.get("api_hash"):
            try:
                aliases = _build_aliases(tickers, fetched)
                agg = telegram_ingest.scan_groups(
                    api_id=int(tcfg["api_id"]),
                    api_hash=tcfg["api_hash"],
                    session_name=tcfg.get("session_name", "stock_analyzer"),
                    group_filter=tcfg.get("groups") or None,
                    days=telegram_days,
                    tickers_of_interest=tickers,
                    name_aliases=aliases or None,
                    pdf_cache_dir=cache_root / "telegram_pdfs",
                )
                for t in tickers:
                    tk = t.upper()
                    if tk in agg:
                        a = agg[tk]
                        tg_signals[tk] = TelegramSignal(
                            mentions_7d=a.count, avg_sentiment=a.avg_sentiment,
                            quoted_targets=a.quoted_targets,
                        )
            except Exception as e:
                errors.append(("telegram", str(e)))

    results = []
    for t in tickers:
        tk = t.upper()
        sd = fetched.get(tk)
        if sd is None:
            continue
        try:
            tech = technical.analyze(sd.history)
            fund = fundamentals.analyze(
                sd.info, sd.sector,
                ticker=sd.ticker,
                screener_cache_dir=cache_root / "screener_in",
            )
            rec = recommend.recommend(
                tech, fund, cfg.get("recommendation", {}), sd.last_close, tg_signals.get(tk)
            )
            results.append({
                "ticker": tk, "name": sd.name, "yf_symbol": sd.yf_symbol,
                "sector": sd.sector or "—", "currency": sd.currency,
                "last_close": sd.last_close,
                "tech": tech, "fund": fund, "rec": rec,
            })
        except Exception as e:
            errors.append((tk, str(e)))
    return results, errors


# ----------------------------------------------------------------------------
# Routes


def _classify_pros_cons(rationale: list[str]) -> tuple[list[str], list[str]]:
    """Split rationale items into pros and cons by keyword scan."""
    POS = ("uptrend", "growth", "healthy", "strong", "cheap", "low leverage", "low d/e",
           "breakout", "oversold", "rsi healthy", "macd bullish", "low p/e", "low pe",
           "looks cheap", "earnings inflection")
    NEG = ("downtrend", "declining", "expensive", "weak", "loss-making", "high leverage",
           "overbought", "exhaustion", "blow-off", "negative", "macd bearish", "distress",
           "% growth ignored")
    pros, cons = [], []
    for item in rationale:
        low = item.lower()
        if any(p in low for p in POS):
            pros.append(item)
        elif any(n in low for n in NEG):
            cons.append(item)
        # else: skip neutral notes
    return pros, cons


@app.route("/")
def index():
    cache_root = _cache_root()
    name = request.args.get("universe", "nifty500")
    try:
        tickers = _resolve_display_tickers(name, cache_root)
    except ValueError:
        tickers = []
    rows = _rows_for(name, tickers, cache_root)
    status = batch.read_status(cache_root)

    universes_meta = _build_universes_meta(name, cache_root)

    # Universe-wide verdict distribution and stats
    verdict_counts = {"BUY": 0, "ACCUMULATE": 0, "HOLD": 0, "REDUCE": 0, "AVOID": 0}
    for r in rows:
        v = r.get("verdict", "HOLD")
        if v in verdict_counts:
            verdict_counts[v] += 1
    total_with_verdict = sum(verdict_counts.values()) or 1
    avg_score = round(sum(r.get("combined_score", 0) for r in rows) / max(len(rows), 1), 2)

    top_buys = sorted(
        [r for r in rows if r["verdict"] in ("BUY", "ACCUMULATE")],
        key=lambda r: -r["combined_score"],
    )[:6]
    top_avoids = sorted(
        [r for r in rows if r["verdict"] in ("REDUCE", "AVOID")],
        key=lambda r: r["combined_score"],
    )[:6]
    high_upside = sorted(
        [r for r in rows if r.get("upside_pct") is not None and r["combined_score"] > 0],
        key=lambda r: -(r["upside_pct"] or 0),
    )[:6]
    oversold = sorted(
        [r for r in rows if r["rsi_14"] < 40 and r["fundamental_score"] >= 0.3],
        key=lambda r: r["rsi_14"],
    )[:6]
    most_discussed = sorted(
        [r for r in rows if r["tg_mentions"] > 0],
        key=lambda r: -r["tg_mentions"],
    )[:6]

    from . import regime as regime_mod, fii_dii as fii_mod
    market_regime = _memo_get("regime", 120, regime_mod.get_regime)
    fii_signal = _memo_get("fii", 300, fii_mod.fetch)
    # For the big universe, show the TRUE listed total in the header even though
    # we only display/refresh the live set. Cheap len() over the cached list.
    if name.lower().replace("_", "") in _BIG_UNIVERSES:
        try:
            universe_total = len(universe.get_universe(name, cache_dir=cache_root / "universe"))
        except Exception:
            universe_total = len(tickers)
    else:
        universe_total = len(tickers)
    return render_template(
        "home.html",
        rows=rows, status=status, universes=universes_meta,
        universe_name=name,
        top_buys=top_buys, top_avoids=top_avoids,
        high_upside=high_upside, oversold=oversold,
        most_discussed=most_discussed,
        cached_count=len(rows), universe_total=universe_total,
        verdict_counts=verdict_counts, total_verdict=total_with_verdict,
        avg_score=avg_score,
        regime=market_regime,
        fii=fii_signal,
    )


@app.route("/screener")
@app.route("/dashboard")  # backward compat
def screener_page():
    cache_root = _cache_root()
    name = request.args.get("universe", "")
    if not name:
        # Default to the FULL NSE+BSE live set when one exists (user expects to
        # see every tradeable stock, ~1,900 names) — else the NIFTY union.
        has_live = bool(universe.load_live_set(cache_root / "universe"))
        name = "alllisted" if has_live else "all"
    try:
        tickers = _resolve_display_tickers(name, cache_root)
    except ValueError:
        return redirect(url_for("index"))
    status = batch.read_status(cache_root)

    def _render() -> str:
        rows = _rows_for(name, tickers, cache_root)
        counts = {"BUY": 0, "ACCUMULATE": 0, "HOLD": 0, "REDUCE": 0, "AVOID": 0}
        for r in rows:
            v = r.get("verdict", "HOLD")
            if v in counts:
                counts[v] += 1
        sectors = sorted({r.get("sector", "") for r in rows if r.get("sector")})
        universes_meta = _build_universes_meta(name, cache_root)
        return render_template(
            "screener.html",
            rows=rows,
            universe_name=name,
            universe_label=_UNIVERSE_LABELS.get(name, name.upper()),
            universe_total=len(tickers),
            cached_count=len(rows),
            counts=counts,
            sectors=sectors,
            status=status,
            universes=universes_meta,
        )

    # Rendering ~1,900 Jinja rows costs ~6s, so memoize the finished HTML per
    # universe. Skipped while a batch runs so the "refreshing X/Y" header stays
    # live; cleared when a batch completes (that's the only time rows change).
    if status.get("running"):
        return _render()
    return _memo_get(f"page:screener:{name}", 900, _render)


@app.route("/stock/<ticker>")
def stock_detail(ticker: str):
    from . import calibration
    cache_root = _cache_root()
    cached = batch.read_result(ticker, cache_root)
    if cached:
        pros, cons = _classify_pros_cons(cached.get("rationale", []))
        # Back-fill track_record + sector_track_record on cached results
        # written by older batches (before calibration shipped). Cheap disk
        # read — calibration.read_cached is a single file load.
        if not cached.get("track_record") or not cached.get("sector_track_record"):
            calib = calibration.read_cached()
            if calib:
                if not cached.get("track_record"):
                    cached["track_record"] = calibration.lookup_confidence_for_score(
                        calib, cached.get("combined_score") or 0
                    )
                if not cached.get("sector_track_record"):
                    cached["sector_track_record"] = calibration.sector_confidence(
                        calib, cached.get("sector")
                    )
        return render_template("stock.html", r=cached, live=False, pros=pros, cons=cons)
    # Fallback: live analyze (no Telegram, fast path)
    results, errors = _live_analyze([ticker], with_telegram=False)
    if not results:
        return render_template("stock.html", r=None, errors=errors, live=True)
    r = results[0]
    # Reshape live result into dict matching cached format
    live_dict = {
        "ticker": r["ticker"], "name": r["name"], "yf_symbol": r["yf_symbol"],
        "sector": r["sector"], "currency": r["currency"],
        "last_close": r["last_close"], "as_of": "live",
        "verdict": r["rec"].verdict, "combined_score": r["rec"].combined_score,
        "technical_score": r["rec"].technical_score,
        "fundamental_score": r["rec"].fundamental_score,
        "telegram_score": r["rec"].telegram_score,
        "trade_target": r["rec"].trade_target, "target_bull": r["rec"].target_bull,
        "fair_value": r["rec"].fair_value, "stop_loss": r["rec"].stop_loss,
        "horizon": r["rec"].horizon,
        "upside_pct": r["rec"].upside_pct, "downside_pct": r["rec"].downside_pct,
        "rsi_14": r["tech"].rsi_14, "sma_50": r["tech"].sma_50, "sma_200": r["tech"].sma_200,
        "high_52w": r["tech"].high_52w, "low_52w": r["tech"].low_52w,
        "atr_14": r["tech"].atr_14, "volume_ratio": r["tech"].volume_ratio,
        "trailing_pe": r["fund"].trailing_pe, "forward_pe": r["fund"].forward_pe,
        "roe": r["fund"].roe, "debt_to_equity": r["fund"].debt_to_equity,
        "earnings_growth": r["fund"].earnings_growth,
        "revenue_growth": r["fund"].revenue_growth,
        "fair_pe_target": r["fund"].fair_pe_target,
        "rationale": r["rec"].rationale, "entry_note": r["rec"].entry_note,
        "tg_mentions": 0, "tg_avg_sentiment": 0.0,
    }
    pros, cons = _classify_pros_cons(live_dict.get("rationale", []))
    return render_template("stock.html", r=live_dict, live=True, pros=pros, cons=cons)


# Journal section removed per user request (2026-07). The journal.py module and
# data/journal.json remain on disk (no data loss) — only the UI wiring is gone.
# /journal now redirects home in case of stale bookmarks.
@app.route("/journal")
def journal_page():
    return redirect(url_for("index"))


@app.route("/accuracy")
def accuracy_page():
    """Stale-while-revalidate. NEVER blocks on the ~50s yfinance bulk fetch.

    - Always reads from cache (even if stale), so render is sub-second.
    - If cache is stale OR ``?force=1``, kicks off a background rebuild.
    - Sets ``result['rebuilding']`` so the template can show a "recomputing,
      check back in ~1 min" banner.

    Prior to this change, every cache expiry (1h TTL) forced the next page
    load to wait 50s+ while the bulk yfinance fetch ran in the request
    handler. That's what made the page feel unusable.
    """
    from . import accuracy, calibration
    force = request.args.get("force") == "1"
    snap_dir = _cache_root() / "snapshots"
    cache_path = snap_dir / "_accuracy_cache.json"

    # Decide if a background rebuild is warranted
    is_stale = False
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        is_stale = age >= accuracy.ACCURACY_CACHE_TTL_SECONDS
    needs_rebuild = force or is_stale

    if needs_rebuild and _try_acquire_accuracy_rebuild():
        threading.Thread(target=_accuracy_rebuild_then_release, daemon=True).start()

    # Read cache as-is, regardless of staleness, so the page renders fast
    result = accuracy.evaluate(snap_dir, stale_ok=True)
    calib = calibration.compute(snap_dir, stale_ok=True)
    result["rebuilding"] = needs_rebuild or _accuracy_rebuild_lock.locked()
    takeaway, ordering = _accuracy_takeaway(result, calib)
    return render_template("accuracy.html", result=result, calibration=calib,
                           takeaway=takeaway, ordering=ordering)


def _accuracy_takeaway(result: dict, calib: dict) -> tuple[str, Optional[dict]]:
    """One plain-English sentence summarizing the whole page, plus a
    verdict-ordering health check (does BUY actually beat ACCUMULATE beat
    HOLD… in realized returns?). Pure formatting — no data fetches."""
    if not result.get("available"):
        return "", None
    parts: list[str] = []
    h = result.get("headline") or {}
    if h:
        parts.append(
            f"So far, {h.get('hit_rate_pct', 0):.0f}% of BUY/ACCUMULATE calls were "
            f"profitable after {h.get('horizon_days')} trading days "
            f"(avg {h.get('avg_return_pct', 0):+.1f}%, n={h.get('n_positive_calls')})."
        )
    floor = (calib or {}).get("learned_buy_min_score")
    if floor is not None:
        parts.append(f"Scores ≥ {floor:+.1f} have been the strongest zone.")

    # Ordering check at the longest horizon with data: avg returns should
    # descend from BUY → AVOID. Report which pairs invert.
    ordering: Optional[dict] = None
    horizons = result.get("horizons_days") or []
    by_v = result.get("by_verdict") or {}
    for hz in sorted(horizons, reverse=True):
        seq = []
        for v in ("BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID"):
            cell = (by_v.get(v) or {}).get(str(hz))
            if cell and cell.get("n", 0) >= 5:
                seq.append((v, cell["avg_return"]))
        if len(seq) >= 3:
            inversions = [
                f"{a}({ar:+.1f}%) < {b}({br:+.1f}%)"
                for (a, ar), (b, br) in zip(seq, seq[1:]) if ar < br
            ]
            ordering = {"horizon": hz, "ok": not inversions, "inversions": inversions}
            break
    return " ".join(parts), ordering


# Coalesce concurrent rebuilds — multiple page visits while a rebuild is
# already in flight should NOT each spawn another 50s yfinance fetch.
_accuracy_rebuild_lock = threading.Lock()


def _try_acquire_accuracy_rebuild() -> bool:
    """Non-blocking try-lock. Returns True if WE should run the rebuild;
    False if someone else already is."""
    return _accuracy_rebuild_lock.acquire(blocking=False)


def _accuracy_rebuild_then_release():
    try:
        from . import accuracy, calibration
        accuracy.evaluate(_cache_root() / "snapshots", force=True)
        calibration.compute(_cache_root() / "snapshots", force=True)
    except Exception:
        pass
    finally:
        try:
            _accuracy_rebuild_lock.release()
        except RuntimeError:
            pass


@app.route("/market")
def market():
    from . import market_pulse
    cache_root = _cache_root()
    name = request.args.get("universe", "nifty100")
    try:
        tickers = _resolve_display_tickers(name, cache_root)
    except ValueError:
        tickers = []
    rows = _rows_for(name, tickers, cache_root)
    # Index quotes hit yfinance — memoize briefly so repeat visits are instant
    # while intraday numbers stay reasonably fresh.
    indices = _memo_get("indices", 120, market_pulse.fetch_indices)
    agg = market_pulse.aggregate_universe(rows)
    heat = market_pulse.heatmap_rows(rows)
    universes_meta = _build_universes_meta(name, cache_root)
    return render_template(
        "market.html",
        indices=indices, agg=agg, heat=heat,
        universe_name=name, universes=universes_meta,
        cached_count=len(rows), universe_total=len(tickers),
    )


@app.route("/fno")
@app.route("/fno/<symbol>")
def fno_page(symbol: str = "NIFTY"):
    """F&O dashboard for index options — chain analytics, signals, strategies."""
    from . import fno as fno_mod, fno_signals
    sym = symbol.upper()
    if sym not in fno_mod.INDEX_META:
        return redirect(url_for("fno_page", symbol="NIFTY"))
    expiry = request.args.get("expiry") or None
    force = request.args.get("refresh") in ("1", "true")
    cfg = _load_config()

    def _build():
        analysis = fno_signals.full_analysis(sym, cfg, expiry=expiry, force=force)
        chain = fno_mod.get_chain(sym, expiry=expiry)
        return analysis, chain

    memo_key = f"fno:{sym}:{expiry or 'near'}"
    if force:
        analysis, chain = _build()
        with _MEMO_LOCK:
            _MEMO[memo_key] = (time.time(), (analysis, chain))
    else:
        analysis, chain = _memo_get(memo_key, 120, _build)

    chain_rows = _fno_display_rows(chain, analysis) if (chain and analysis) else []
    max_wall_oi = max(
        [s["oi"] for s in (analysis.supports if analysis else [])] +
        [s["oi"] for s in (analysis.resistances if analysis else [])] + [1]
    )
    return render_template(
        "fno.html",
        a=analysis, chain_rows=chain_rows, symbol=sym,
        symbols=[(s, fno_mod.INDEX_META[s]["label"]) for s in fno_mod.DISPLAY_ORDER],
        expiries=(chain or {}).get("expiries") or [], sel_expiry=expiry,
        max_wall_oi=max_wall_oi,
        fetch_log=fno_mod.get_fetch_log(sym) if analysis is None else [],
    )


def _fno_display_rows(chain: dict, analysis) -> list[dict]:
    """Chain rows ±8 strikes around ATM with per-side OI bar widths (percent
    of the window max) precomputed — keeps the template dumb."""
    rows = chain.get("rows") or []
    spot = chain.get("spot") or 0
    if not rows or not spot:
        return []
    atm = analysis.atm_strike
    step = 0.0
    from . import fno as fno_mod
    step = float(fno_mod.INDEX_META.get(chain["symbol"], {}).get("step") or 50)
    lo, hi = (atm or spot) - 8 * step, (atm or spot) + 8 * step
    window = [r for r in rows if lo <= r["strike"] <= hi]
    max_oi = max([max((r.get("ce") or {}).get("oi") or 0, (r.get("pe") or {}).get("oi") or 0)
                  for r in window] + [1])
    out = []
    for r in window:
        ce, pe = r.get("ce") or {}, r.get("pe") or {}
        out.append({
            "strike": r["strike"],
            "is_atm": atm is not None and r["strike"] == atm,
            "ce": ce, "pe": pe,
            "ce_bar": round((ce.get("oi") or 0) / max_oi * 100, 1),
            "pe_bar": round((pe.get("oi") or 0) / max_oi * 100, 1),
        })
    return out


@app.route("/api/fno/<symbol>")
def api_fno(symbol: str):
    """Full F&O analysis as JSON (signals, levels, strategies)."""
    from . import fno as fno_mod, fno_signals
    sym = symbol.upper()
    if sym not in fno_mod.INDEX_META:
        abort(404)
    a = fno_signals.full_analysis(sym, _load_config(),
                                  expiry=request.args.get("expiry") or None,
                                  force=request.args.get("refresh") in ("1", "true"))
    if a is None:
        return jsonify({"available": False,
                        "error": "option chain unavailable (exchange API unreachable and no cached copy)",
                        "attempts": fno_mod.get_fetch_log(sym)}), 503
    return jsonify({"available": True, **a.to_dict()})


@app.route("/api/fno/<symbol>/chain")
def api_fno_chain(symbol: str):
    """Raw normalized option chain as JSON."""
    from . import fno as fno_mod
    sym = symbol.upper()
    if sym not in fno_mod.INDEX_META:
        abort(404)
    chain = fno_mod.get_chain(sym, expiry=request.args.get("expiry") or None)
    if chain is None:
        return jsonify({"available": False}), 503
    return jsonify({"available": True, **chain})


@app.route("/api/intraday/<ticker>")
def api_intraday(ticker: str):
    """Live intraday signal: VWAP, ORB, gap, intraday RSI, volume."""
    from . import intraday
    s = intraday.intraday_signal(ticker)
    return jsonify({
        "available": s.available,
        "last_price": s.last_price,
        "open_price": s.open_price,
        "day_high": s.day_high,
        "day_low": s.day_low,
        "prev_close": s.prev_close,
        "day_change_pct": s.day_change_pct,
        "gap_pct": s.gap_pct,
        "vwap": s.vwap,
        "vs_vwap_pct": s.vs_vwap_pct,
        "or_high": s.or_high,
        "or_low": s.or_low,
        "orb_signal": s.orb_signal,
        "intraday_rsi": s.intraday_rsi,
        "volume_ratio": s.volume_ratio,
        "bias": s.bias,
        "notes": s.notes,
    })


@app.route("/api/short-term/<ticker>")
def api_short_term(ticker: str):
    """Short-term swing signal: 5/10/20 SMAs, Bollinger, Stochastic, ADX, RS vs NIFTY."""
    from . import intraday
    s = intraday.short_term_signal(ticker)
    return jsonify({
        "available": s.available,
        "sma_5": s.sma_5, "sma_10": s.sma_10, "sma_20": s.sma_20,
        "bb_upper": s.bb_upper, "bb_lower": s.bb_lower,
        "bb_pct_b": s.bb_pct_b, "bb_squeeze": s.bb_squeeze,
        "stoch_k": s.stoch_k, "stoch_d": s.stoch_d,
        "adx": s.adx, "plus_di": s.plus_di, "minus_di": s.minus_di,
        "breakout_10d": s.breakout_10d,
        "rs_5d_vs_nifty": s.rs_5d_vs_nifty,
        "rs_20d_vs_nifty": s.rs_20d_vs_nifty,
        "setup": s.setup,
        "notes": s.notes,
    })


@app.route("/reports/pdf/<int:channel_id>/<int:msg_id>.pdf")
def serve_telegram_pdf(channel_id: int, msg_id: int):
    """Serve a cached Telegram research-report PDF from the local cache.
    Linked from the Research mentions card on each stock detail page."""
    # Flask resolves relative paths against the app's root_path (src/), so
    # we need an absolute path here.
    pdf_path = (_cache_root() / "telegram_pdfs" / str(channel_id) / f"{msg_id}.pdf").resolve()
    if not pdf_path.exists():
        abort(404)
    return send_file(str(pdf_path), mimetype="application/pdf",
                     as_attachment=False, download_name=f"report_{msg_id}.pdf")


@app.route("/api/research/<ticker>")
def api_research(ticker: str):
    """Telegram research-report mentions for one ticker.
    Cached per-ticker on disk with a 30-min TTL so we don't re-scan on every
    page load. Acquires the process-wide Telegram lock if a fresh scan is
    needed — prevents 'database is locked' against a concurrent batch."""
    from . import telegram_ingest
    import time as _time
    cache_root = _cache_root()
    research_dir = cache_root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    cache_file = research_dir / f"{ticker.upper()}.json"
    # Long TTL (8h) since the batch refresh writes this file every time it runs,
    # which is way more frequent than 8h. Effectively the cache file is always fresh.
    ttl_seconds = 8 * 60 * 60

    if cache_file.exists() and (_time.time() - cache_file.stat().st_mtime) < ttl_seconds:
        try:
            cached_payload = json.loads(cache_file.read_text(encoding="utf-8"))
            _ensure_research_analysis(cached_payload)
            return jsonify(cached_payload)
        except Exception:
            pass

    cfg = _load_config()
    tcfg = cfg.get("telegram", {})
    if not tcfg.get("api_id") or not tcfg.get("api_hash"):
        return jsonify({"available": False, "reason": "Telegram not configured"})

    cached = batch.read_result(ticker, cache_root)
    company_name = cached.get("name") if cached else None
    aliases: dict[str, str] = {}
    if company_name:
        suffixes = (" limited", " ltd", " ltd.", " industries", " corporation", " corp")
        nm = company_name.strip().lower()
        candidates = {nm}
        for s in suffixes:
            if nm.endswith(s):
                candidates.add(nm[: -len(s)].strip())
        toks = [w for w in nm.split() if w not in {"the", "of", "and"}]
        if len(toks) >= 2:
            candidates.add(" ".join(toks[:2]))
        for phrase in candidates:
            if len(phrase) >= 6 and " " in phrase:
                aliases[phrase] = ticker.upper()

    # Lock: only one Telethon session at a time across this process.
    if not _telegram_lock.acquire(timeout=2):
        # Batch is hogging the session; fall back to last known data from batch cache.
        if cached and cached.get("tg_mentions"):
            payload = {
                "available": True,
                "mentions_count": cached.get("tg_mentions", 0),
                "avg_sentiment": cached.get("tg_avg_sentiment", 0.0),
                "quoted_targets": [],
                "mentions": [],
                "stale": True,
                "reason": "Live scan unavailable while batch is running. Showing last batch summary.",
            }
            return jsonify(payload)
        return jsonify({"available": False, "reason": "Telegram session busy. Try again in a minute."})

    try:
        agg = telegram_ingest.scan_groups(
            api_id=int(tcfg["api_id"]),
            api_hash=tcfg["api_hash"],
            session_name=tcfg.get("session_name", "stock_analyzer"),
            group_filter=tcfg.get("groups") or None,
            days=int(tcfg.get("scan_days", 14)),
            tickers_of_interest=[ticker],
            name_aliases=aliases or None,
            pdf_cache_dir=cache_root / "telegram_pdfs",
            download_new=False,
        )
    except Exception as e:
        _telegram_lock.release()
        return jsonify({"available": False, "reason": str(e)})
    finally:
        if _telegram_lock.locked():
            try:
                _telegram_lock.release()
            except RuntimeError:
                pass

    tk = ticker.upper()
    if tk not in agg or not agg[tk].mentions:
        payload = {"available": True, "mentions_count": 0, "mentions": []}
    else:
        a = agg[tk]
        mentions = sorted(a.mentions, key=lambda m: m.when, reverse=True)
        out_mentions = []
        for m in mentions[:25]:
            out_mentions.append({
                "group": m.group,
                "when": m.when.isoformat(timespec="minutes") if m.when else "",
                "text_excerpt": m.text[:280],
                "sentiment": round(m.sentiment, 2),
                "target": m.target,
                "stop": m.stop,
                "msg_id": m.msg_id,
                "channel_id": m.channel_id,
                "has_pdf": m.has_pdf,
            })
        payload = {
            "available": True,
            "mentions_count": a.count,
            "avg_sentiment": round(a.avg_sentiment, 2),
            "quoted_targets": a.quoted_targets,
            "mentions": out_mentions,
        }
        _ensure_research_analysis(payload)

    try:
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    return jsonify(payload)


def _ensure_research_analysis(payload: dict) -> None:
    """Add a structured ``analysis`` block to a Telegram-research payload in
    place, derived from the per-mention text. Idempotent: if analysis already
    exists we leave it alone, so cached payloads written by the batch are
    respected. Called from both the cached-read and fresh-scan paths."""
    if not isinstance(payload, dict) or "analysis" in payload:
        return
    mentions = payload.get("mentions") or []
    if not mentions:
        payload["analysis"] = {}
        return
    text_parts: list[str] = []
    for m in mentions:
        t = (m.get("text_excerpt") or "").strip()
        if t:
            text_parts.append(t)
    if not text_parts:
        payload["analysis"] = {}
        return
    try:
        from . import research_extract
        joined = " ".join(text_parts)
        payload["analysis"] = research_extract.analyze(joined, subject="research")
    except Exception:
        payload["analysis"] = {}


@app.route("/api/nse-filings/<ticker>")
def api_nse_filings(ticker: str):
    """Earnings call transcripts, concalls, investor presentations from NSE."""
    from . import nse_filings
    return jsonify(nse_filings.get_filings_with_text(ticker, max_extract=3))


@app.route("/api/calibration")
def api_calibration():
    """Self-calibration state — what the tool has learned from its own
    accuracy backtest. Used by the /accuracy page to show 'what the tool
    has learned' and by the stock detail page to show track-record chips."""
    from . import calibration
    return jsonify(calibration.compute(_cache_root() / "snapshots"))


@app.route("/filings/pdf/<ticker>/<path:filename>")
def serve_nse_filing(ticker: str, filename: str):
    """Serve a cached NSE filing PDF.

    Flask 3.x's ``send_file`` rejects relative paths — must be absolute. Our
    cache_root from config is ``data/cache`` (relative), so we resolve it to
    an absolute path before handing off.
    """
    safe = filename.replace("..", "").lstrip("/")
    pdf_path = (_cache_root() / "nse_filings" / ticker.upper() / safe).resolve()
    if not pdf_path.exists():
        abort(404)
    # Defence in depth: ensure the resolved path is still under the cache root
    # (blocks any ``..`` shenanigans that slipped past the surface check).
    cache_abs = _cache_root().resolve()
    try:
        pdf_path.relative_to(cache_abs)
    except ValueError:
        abort(403)
    return send_file(str(pdf_path), mimetype="application/pdf",
                     as_attachment=False, download_name=safe)


@app.route("/api/transcripts/<ticker>")
def api_transcripts(ticker: str):
    """Mentions of this ticker pulled from local meeting/call transcripts."""
    from . import transcripts as tmod
    # Build alias map from the cached batch result (e.g. 'borosil renewables' → BORORENEW)
    cache_root = _cache_root()
    cached = batch.read_result(ticker, cache_root)
    company_name = cached.get("name") if cached else None
    aliases: dict[str, str] = {}
    if company_name:
        suffixes = (" limited", " ltd", " ltd.", " industries", " corporation", " corp")
        nm = company_name.strip().lower()
        candidates = {nm}
        for s in suffixes:
            if nm.endswith(s):
                candidates.add(nm[: -len(s)].strip())
        toks = [w for w in nm.split() if w not in {"the", "of", "and"}]
        if len(toks) >= 2:
            candidates.add(" ".join(toks[:2]))
        for phrase in candidates:
            if len(phrase) >= 6 and " " in phrase:
                aliases[phrase] = ticker.upper()
    force = request.args.get("force") == "1"
    return jsonify(tmod.fetch_for_ticker(ticker, name_aliases=aliases or None, force=force))


@app.route("/api/transcripts/invalidate", methods=["POST"])
def api_transcripts_invalidate():
    from . import transcripts as tmod
    n = tmod.invalidate_cache()
    return jsonify({"cleared": n})


@app.route("/api/position-size")
def api_position_size():
    """Given entry + stop, suggest qty using config's risk/account rule."""
    from . import position_sizer
    try:
        entry = float(request.args.get("entry", 0))
        stop = float(request.args.get("stop", 0))
    except ValueError:
        return jsonify({"error": "Invalid entry or stop"}), 400
    cfg = _load_config()
    account, risk_pct = position_sizer.get_config(cfg)
    result = position_sizer.suggest_qty(entry, stop, account, risk_pct)
    return jsonify(result)


@app.route("/api/news/<ticker>")
def api_news(ticker: str):
    """Recent news for a ticker. Yahoo first, MoneyControl supplements."""
    from . import news
    cache_root = _cache_root()
    cached = batch.read_result(ticker, cache_root)
    if cached:
        yf_symbol = cached.get("yf_symbol") or f"{ticker.upper()}.NS"
        company = cached.get("name") or ticker
    else:
        yf_symbol = f"{ticker.upper()}.NS"
        company = ticker
    items = news.fetch_news(
        yf_symbol=yf_symbol,
        ticker=ticker.upper(),
        company_name=company,
        cache_dir=cache_root / "news",
        ttl_minutes=30,
    )
    return jsonify({"ticker": ticker.upper(), "count": len(items), "items": items})


@app.route("/api/chart/<ticker>")
def api_chart(ticker: str):
    """Return price + indicator arrays. Accepts ?period=1mo|3mo|6mo|1y|2y|5y|max.
    Always pulls 5y from yfinance so SMA200 has enough warm-up, then slices.
    For 2y/5y we downsample (every 2nd / every 5th day) so Chart.js stays snappy."""
    period_arg = request.args.get("period", "1y")
    # (tail_days, downsample_every)
    period_map = {
        "1mo": (22, 1),
        "3mo": (66, 1),
        "6mo": (132, 1),
        "1y":  (252, 1),
        "2y":  (504, 2),
        "5y":  (1260, 5),
    }
    tail_days, sample_every = period_map.get(period_arg, (252, 1))

    # Try the on-disk history cache first — instant if fresh (10-min TTL).
    cached_hist = data.read_cached_history(ticker, "5y")
    try:
        if cached_hist is not None:
            sd = data.fetch(ticker, period="5y", prefetched_history=cached_hist)
        else:
            sd = data.fetch(ticker, period="5y")
            # Persist for next request
            data.write_cached_history(ticker, sd.history, "5y")
    except Exception as e:
        return jsonify({
            "error": f"Price history unavailable for {ticker.upper()} ({e})",
            "ticker": ticker.upper(),
            "available": False,
        })

    full = sd.history.copy()
    close_full = full["Close"]

    # Indicators on the full series, then take last ~252 trading days for display.
    sma50 = close_full.rolling(50).mean()
    sma200 = close_full.rolling(200).mean()

    delta = close_full.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    ema12 = close_full.ewm(span=12, adjust=False).mean()
    ema26 = close_full.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    full["sma50"] = sma50
    full["sma200"] = sma200
    full["rsi"] = rsi
    full["macd"] = macd_line
    full["signal"] = signal_line
    full["macd_hist"] = macd_hist

    df = full.tail(tail_days)
    if sample_every > 1:
        df = df.iloc[::sample_every]

    def col(name):
        return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
                for v in df[name].tolist()]

    return jsonify({
        "ticker": sd.ticker,
        "name": sd.name,
        "currency": sd.currency,
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "close": col("Close"),
        "volume": col("Volume"),
        "sma50": col("sma50"),
        "sma200": col("sma200"),
        "rsi": col("rsi"),
        "macd": col("macd"),
        "signal": col("signal"),
        "macd_hist": col("macd_hist"),
    })


@app.route("/analyze")
def analyze():
    raw = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in raw.replace(",", " ").split() if t.strip()]
    if not tickers:
        return redirect(url_for("index"))
    use_tg = request.args.get("telegram", "0") == "1"
    days = int(request.args.get("days", "7") or 7)
    results, errors = _live_analyze(tickers, use_tg, days)
    return render_template(
        "result.html",
        results=results, errors=errors,
        tickers_str=" ".join(tickers), use_tg=use_tg, days=days,
    )


# ----------------------------------------------------------------------------
# Refresh API

_refresh_lock = threading.Lock()
_refresh_thread: Optional[threading.Thread] = None

# Process-wide lock for Telethon — its SQLite session file does not allow
# concurrent access. Both the batch refresh and /api/research touch it.
_telegram_lock = threading.Lock()


def _build_aliases_from_cache(tickers: list[str], cache_root: Path) -> dict[str, str]:
    """Build company-name → ticker aliases from already-cached batch results.
    Used so Telegram scans can match research reports that say 'Borosil Renewables'
    rather than 'BORORENEW'. Best-effort: tickers that have never been analyzed
    won't have aliases until the next refresh."""
    suffixes = (" limited", " ltd", " ltd.", " industries", " corporation", " corp",
                " inc", " inc.", " co.", " company")
    skip = {"the", "of", "and"}
    aliases: dict[str, str] = {}
    for t in tickers:
        cached = batch.read_result(t, cache_root)
        if not cached:
            continue
        nm = (cached.get("name") or "").strip().lower()
        if not nm:
            continue
        candidates = {nm}
        for s in suffixes:
            if nm.endswith(s):
                candidates.add(nm[: -len(s)].strip())
        toks = [w for w in nm.split() if w not in skip]
        if len(toks) >= 2:
            candidates.add(" ".join(toks[:2]))
        for phrase in candidates:
            if len(phrase) >= 6 and " " in phrase:
                aliases[phrase] = t.upper()
    return aliases


def _refresh_worker(name: str, ttl_minutes: int, with_telegram: bool = True,
                    full_sweep: bool = False):
    cache_root = _cache_root()
    cfg = _load_config()
    try:
        tickers = universe.get_universe(name, cache_dir=cache_root / "universe")
    except ValueError:
        return

    # Big NSE+BSE universe: use the live set for routine refreshes so we don't
    # re-sweep ~5,500 names (incl. thousands of illiquid/no-data shells) every
    # time. A "full sweep" re-runs the entire universe and rebuilds the live set.
    is_big = name.lower().replace("_", "") in ("alllisted", "allnse", "allbse", "nsebse", "everylisted")
    full_universe = list(tickers)
    if is_big and not full_sweep:
        live = universe.load_live_set(cache_root / "universe")
        if live:
            tickers = live  # fast path — only the proven-liquid subset

    # Resolve NIFTY regime once per batch
    from . import regime as regime_mod
    regime = regime_mod.get_regime()

    tg_signals: dict[str, TelegramSignal] = {}
    if with_telegram:
        tcfg = cfg.get("telegram", {})
        if tcfg.get("api_id") and tcfg.get("api_hash"):
            try:
                from . import telegram_ingest
                aliases = _build_aliases_from_cache(tickers, cache_root)
                agg = telegram_ingest.scan_groups(
                    api_id=int(tcfg["api_id"]),
                    api_hash=tcfg["api_hash"],
                    session_name=tcfg.get("session_name", "stock_analyzer"),
                    group_filter=tcfg.get("groups") or None,
                    days=int(tcfg.get("scan_days", 7)),
                    tickers_of_interest=tickers,
                    name_aliases=aliases or None,
                    pdf_cache_dir=cache_root / "telegram_pdfs",
                    download_new=False,  # Fast path: parse only cached PDFs (no network).
                )
                for tk, a in agg.items():
                    tg_signals[tk] = TelegramSignal(
                        mentions_7d=a.count,
                        avg_sentiment=a.avg_sentiment,
                        quoted_targets=a.quoted_targets,
                    )
            except Exception:
                # Telegram is optional — bail to plain batch if anything goes wrong
                # (session locked by another process, network issue, etc.)
                tg_signals = {}

    batch.run_batch(tickers, cfg, cache_root, tg_signals=tg_signals, ttl_minutes=ttl_minutes, regime=regime)
    # Fresh verdicts just landed — drop memoized rows/counts so pages show them,
    # then rebuild the hot pages in the background so no visitor eats the cold render.
    _memo_clear()
    threading.Thread(target=_prewarm_pages_async, daemon=True).start()
    # Precompute accuracy in background so /accuracy is instant on next visit.
    threading.Thread(target=_precompute_accuracy_async, daemon=True).start()
    # Recompute self-calibration from the fresh accuracy data — feeds the
    # learned BUY-threshold and per-sector confidence chips into the NEXT batch.
    threading.Thread(target=_recompute_calibration_async, daemon=True).start()


def _precompute_accuracy_async():
    """Compute accuracy result in a background thread so /accuracy is instant."""
    try:
        from . import accuracy
        accuracy.evaluate(_cache_root() / "snapshots", force=True)
    except Exception:
        pass


def _recompute_calibration_async():
    """Re-derive learned BUY threshold + per-sector confidence from the freshly-
    computed accuracy data. Runs after _precompute_accuracy_async populates the
    accuracy cache, so this call is cheap (just reads + aggregates)."""
    try:
        from . import calibration
        calibration.compute(_cache_root() / "snapshots", force=True)
    except Exception:
        pass


def _refresh_all_worker(ttl_minutes: int, with_telegram: bool):
    """Refresh every unique ticker across every configured universe.
    Telegram scan runs once for the combined set, then a single batch."""
    cache_root = _cache_root()
    cfg = _load_config()
    all_universes = ("nifty50", "nifty100", "nifty500", "midcap150", "smallcap250", "midsmall400")
    seen: set[str] = set()
    tickers: list[str] = []
    for u in all_universes:
        try:
            for t in universe.get_universe(u, cache_dir=cache_root / "universe"):
                tk = t.upper()
                if tk not in seen:
                    seen.add(tk)
                    tickers.append(t)
        except Exception:
            continue
    from . import regime as regime_mod
    regime = regime_mod.get_regime()

    tg_signals: dict[str, TelegramSignal] = {}
    if with_telegram:
        tcfg = cfg.get("telegram", {})
        if tcfg.get("api_id") and tcfg.get("api_hash") and _telegram_lock.acquire(timeout=5):
            try:
                from . import telegram_ingest
                aliases = _build_aliases_from_cache(tickers, cache_root)
                agg = telegram_ingest.scan_groups(
                    api_id=int(tcfg["api_id"]),
                    api_hash=tcfg["api_hash"],
                    session_name=tcfg.get("session_name", "stock_analyzer"),
                    group_filter=tcfg.get("groups") or None,
                    days=int(tcfg.get("scan_days", 14)),
                    tickers_of_interest=tickers,
                    name_aliases=aliases or None,
                    pdf_cache_dir=cache_root / "telegram_pdfs",
                    download_new=False,
                )
                for tk, a in agg.items():
                    tg_signals[tk] = TelegramSignal(
                        mentions_7d=a.count,
                        avg_sentiment=a.avg_sentiment,
                        quoted_targets=a.quoted_targets,
                    )
                # Persist per-ticker research so /api/research can read from disk
                # without needing a live Telegram session — kills the 'database
                # is locked' errors that occur when batch + research API contend.
                _persist_research_per_ticker(agg, cache_root)
            except Exception:
                tg_signals = {}
            finally:
                try:
                    _telegram_lock.release()
                except RuntimeError:
                    pass

    batch.run_batch(tickers, cfg, cache_root, tg_signals=tg_signals, ttl_minutes=ttl_minutes, regime=regime)

    # After a FULL sweep of the big universe, rebuild the live set so future
    # routine refreshes only re-run the names that had data + cleared the
    # liquidity floor.
    if is_big and full_sweep:
        try:
            floor = batch._liquidity_floor(cfg)
            live = batch.compute_live_set(full_universe, cache_root, min_turnover_cr=floor)
            if live:
                universe.save_live_set(live, cache_root / "universe")
        except Exception:
            pass

    # Fresh verdicts just landed — drop memoized rows/counts so pages show them,
    # then rebuild the hot pages in the background so no visitor eats the cold render.
    _memo_clear()
    threading.Thread(target=_prewarm_pages_async, daemon=True).start()
    # Precompute accuracy in background so /accuracy is instant on next visit.
    threading.Thread(target=_precompute_accuracy_async, daemon=True).start()
    # Recompute self-calibration from the fresh accuracy data — feeds the
    # learned BUY-threshold and per-sector confidence chips into the NEXT batch.
    threading.Thread(target=_recompute_calibration_async, daemon=True).start()


def _persist_research_per_ticker(agg, cache_root: Path) -> None:
    """Write per-ticker research JSON files so /api/research can serve them
    without re-opening the Telegram session."""
    research_dir = cache_root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    for tk, a in agg.items():
        try:
            mentions = sorted(a.mentions, key=lambda m: m.when, reverse=True)
            payload = {
                "available": True,
                "mentions_count": a.count,
                "avg_sentiment": round(a.avg_sentiment, 2),
                "quoted_targets": a.quoted_targets,
                "mentions": [
                    {
                        "group": m.group,
                        "when": m.when.isoformat(timespec="minutes") if m.when else "",
                        "text_excerpt": m.text[:280],
                        "sentiment": round(m.sentiment, 2),
                        "target": m.target,
                        "stop": m.stop,
                        "msg_id": m.msg_id,
                        "channel_id": m.channel_id,
                        "has_pdf": m.has_pdf,
                    }
                    for m in mentions[:25]
                ],
            }
            _ensure_research_analysis(payload)
            (research_dir / f"{tk}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except Exception:
            continue


@app.route("/api/refresh", methods=["GET", "POST"])
def api_refresh():
    global _refresh_thread
    name = request.args.get("universe", "nifty500")
    ttl = int(request.args.get("ttl_minutes", "0") or 0)
    use_tg = request.args.get("telegram", "1") == "1"
    # full=1 forces a complete sweep of a big universe (all ~5,500 names) and
    # rebuilds the live set. Without it, the big universe refreshes only its
    # proven-liquid live subset.
    full_sweep = request.args.get("full", "0") == "1"
    with _refresh_lock:
        if _refresh_thread and _refresh_thread.is_alive():
            return jsonify({"started": False, "reason": "refresh already running"}), 409
        _refresh_thread = threading.Thread(
            target=_refresh_worker, args=(name, ttl, use_tg, full_sweep), daemon=True
        )
        _refresh_thread.start()
    return jsonify({"started": True, "universe": name, "ttl_minutes": ttl,
                    "telegram": use_tg, "full_sweep": full_sweep})


@app.route("/api/refresh-all", methods=["GET", "POST"])
def api_refresh_all():
    """Refresh deduplicated tickers across every universe — typically ~700-800 stocks.
    Cache is per-ticker so a stock in multiple universes only gets analyzed once."""
    global _refresh_thread
    ttl = int(request.args.get("ttl_minutes", "0") or 0)
    use_tg = request.args.get("telegram", "1") == "1"
    with _refresh_lock:
        if _refresh_thread and _refresh_thread.is_alive():
            return jsonify({"started": False, "reason": "refresh already running"}), 409
        _refresh_thread = threading.Thread(
            target=_refresh_all_worker, args=(ttl, use_tg), daemon=True
        )
        _refresh_thread.start()
    return jsonify({"started": True, "scope": "all-universes", "ttl_minutes": ttl, "telegram": use_tg})


@app.route("/api/status")
def api_status():
    return jsonify(batch.read_status(_cache_root()))


def _first_run_autobuild():
    """Fresh installs ship universe lists but no analyzed verdicts, so every
    page reads '0 stocks cached'. Kick a NIFTY 50 batch automatically — the
    header shows live progress and bigger universes stay one click away."""
    global _refresh_thread
    try:
        analysis = _cache_root() / "analysis"
        # _status.json and other _-prefixed bookkeeping files don't count as
        # cached verdicts — only real per-ticker rows do.
        if analysis.exists() and any(f.name[:1] != "_" for f in analysis.glob("*.json")):
            return
        with _refresh_lock:
            if _refresh_thread and _refresh_thread.is_alive():
                return
            _refresh_thread = threading.Thread(
                target=_refresh_worker, args=("nifty50", 0, True, False), daemon=True
            )
            _refresh_thread.start()
        print("[startup] Analysis cache is empty (first run) — building NIFTY 50 "
              "automatically (~2 min). Use Refresh all on the home page for the "
              "full universe.", flush=True)
    except Exception:
        pass


# Started at the bottom of the module so every function it needs is defined.
threading.Thread(target=_first_run_autobuild, daemon=True).start()


if __name__ == "__main__":
    import os
    # Bind all interfaces so phones/tablets on the same home WiFi can reach the
    # tool at http://<PC-LAN-IP>:5000/. Localhost (127.0.0.1) still works too.
    # Access is gated by the Windows Firewall rule (Private networks only) — the
    # app itself has no auth, so keep it on trusted home networks.
    host = os.environ.get("STOCK_ANALYZER_HOST", "0.0.0.0")
    app.run(host=host, port=5000, debug=False, threaded=True)
