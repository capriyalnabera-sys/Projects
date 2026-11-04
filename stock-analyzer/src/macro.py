"""Macro backdrop → per-stock tilt.

Tracks the global/Indian macro factors that move Indian sectors in
predictable directions, and turns their recent trend into a small score
adjustment for each stock based on its sector/industry:

    crude oil (Brent)  — India imports ~85% of its oil: hurts OMCs, airlines,
                         paints, FMCG, fertilisers, cement; helps oil producers
    USD/INR            — a weaker rupee helps exporters (IT, pharma, textiles),
                         hurts importers (airlines, OMCs)
    US 10Y yield       — higher global rates pull foreign money out of India and
                         weigh on rate-sensitive sectors (banks, NBFCs, realty)
    US dollar index    — a strong dollar weighs on metals and EM flows
    copper             — global industrial demand; metals proxy
    gold               — risk-off gauge
    S&P 500            — global risk appetite; US tech spend for Indian IT
    FII flows (NSE)    — foreign money into Indian equities (banks most exposed)
    RBI policy (config)— optional manual input: macro.repo_trend cutting|hold|hiking

Each factor's move is normalised against a "meaningful move" size, so +1 means
"a clearly significant move up". A stock's macro score is the dot product of
those moves with its sector's sensitivities, clipped to ±1.5, and enters the
recommendation with a small weight (recommendation.macro_weight, default 0.25
→ at most ±0.375 on the combined score). Macro tilts a verdict; it never makes
one on its own.

Prices come from Yahoo Finance (one bulk request, cached for 3 hours). FII
flows come from NSE's FII/DII report (via fii_dii.py).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

CACHE_PATH = Path("data/cache/macro.json")
CACHE_TTL_SECONDS = 3 * 60 * 60
STALE_OK_SECONDS = 3 * 24 * 60 * 60   # use an old snapshot if a fetch fails
RETRY_AFTER_FAIL_SECONDS = 30 * 60    # don't re-hit an unreachable source every refresh
_last_fail = {"ts": 0.0}

# key: (Yahoo symbol, label, move unit, meaningful 1-month move, meaningful 3-month move)
# unit "pct" = % change; "abs" = change in percentage points (yields).
FACTORS = {
    "crude":  ("BZ=F",     "Brent crude",     "pct", 8.0,  15.0),
    "usdinr": ("INR=X",    "USD/INR",         "pct", 1.5,  3.0),
    "us10y":  ("^TNX",     "US 10Y yield",    "abs", 0.25, 0.5),
    "dxy":    ("DX-Y.NYB", "US dollar index", "pct", 2.0,  4.0),
    "copper": ("HG=F",     "Copper",          "pct", 5.0,  10.0),
    "gold":   ("GC=F",     "Gold",            "pct", 4.0,  8.0),
    "sp500":  ("^GSPC",    "S&P 500",         "pct", 4.0,  8.0),
}
SOURCES = {
    "prices": "Yahoo Finance (BZ=F, INR=X, ^TNX, DX-Y.NYB, HG=F, GC=F, ^GSPC)",
    "fii": "NSE FII/DII trading activity (nseindia.com/reports/fii-dii)",
    "rbi": "Manual setting macro.repo_trend in config.yaml (RBI policy announcements)",
}

# Market-wide tilt applied to every analysed stock (India is a net oil importer
# and foreign flows drive large caps).
MARKET_WIDE = {"sp500": 0.15, "fii": 0.15, "crude": -0.1, "gold": -0.05}

# (group label, industry keywords, sector fallbacks, sensitivities). First match
# wins, so more specific groups come first. Keywords match Yahoo's industry
# names case-insensitively ("Oil & Gas Refining & Marketing", "Airlines", …).
GROUPS = [
    ("Airlines", ["airline"], [], {"crude": -1.2, "usdinr": -0.6}),
    ("Oil refiners & marketers", ["refining", "oil & gas integrated"], [],
     {"crude": -1.0, "usdinr": -0.3}),
    ("Oil & gas producers", ["oil & gas e&p", "oil & gas drilling", "oil & gas equipment"], [],
     {"crude": 1.0}),
    ("Gas distribution", ["regulated gas"], [], {"crude": -0.4}),
    ("IT services & software", ["information technology", "software", "it services"],
     ["Technology"], {"usdinr": 1.0, "sp500": 0.5, "us10y": -0.2}),
    ("Pharma & healthcare", ["drug manufacturer", "pharma", "biotech"], ["Healthcare"],
     {"usdinr": 0.6}),
    ("Paints & chemicals", ["chemical"], [], {"crude": -0.6, "usdinr": 0.2}),
    ("Fertilisers & agri inputs", ["agricultural inputs", "fertili"], [], {"crude": -0.5}),
    ("Metals & mining", ["steel", "aluminum", "aluminium", "copper", "industrial metals",
                         "metals & mining", "coking coal", "thermal coal"], [],
     {"copper": 1.0, "dxy": -0.5, "usdinr": 0.3}),
    ("Cement & building materials", ["building materials", "cement"], [],
     {"crude": -0.5, "rates": -0.2}),
    ("Autos & auto parts", ["auto manufacturer", "auto parts", "recreational vehicle",
                            "farm & heavy"], [], {"crude": -0.4, "rates": -0.4}),
    ("Textiles & apparel", ["textile", "apparel"], [], {"usdinr": 0.5, "crude": -0.2}),
    ("Banks", ["bank"], [], {"rates": -0.3, "fii": 0.6}),
    ("NBFCs, insurers & capital markets", ["credit services", "capital markets", "insurance",
                                           "asset management", "mortgage", "financial"],
     ["Financial Services"], {"rates": -0.5, "fii": 0.4}),
    ("Real estate", ["real estate"], ["Real Estate"], {"rates": -0.7}),
    ("FMCG & consumer staples", ["household", "packaged foods", "personal products",
                                 "beverages", "confectioner", "tobacco", "food distribution"],
     ["Consumer Defensive"], {"crude": -0.4}),
    ("Power & utilities", ["utilities"], ["Utilities"], {"rates": -0.4}),
    ("Capital goods & infra", ["engineering & construction", "industrial machinery",
                               "electrical equipment", "infrastructure"],
     ["Industrials"], {"rates": -0.3}),
    ("Telecom & media", ["telecom"], ["Communication Services"], {"rates": -0.2}),
]
REPO_TREND = {"cutting": -1.0, "cut": -1.0, "easing": -1.0,
              "hold": 0.0, "neutral": 0.0, "pause": 0.0,
              "hiking": 1.0, "hike": 1.0, "tightening": 1.0}
MAX_STOCK_SCORE = 1.5


def _clip(x: float, lo: float = -2.0, hi: float = 2.0) -> float:
    return max(lo, min(hi, x))


def _factor_from_series(key: str, closes) -> Optional[dict]:
    sym, label, unit, thr1, thr3 = FACTORS[key]
    s = closes.dropna()
    if len(s) < 25:
        return None
    last = float(s.iloc[-1])
    ago1 = float(s.iloc[-22])
    ago3 = float(s.iloc[-64]) if len(s) >= 64 else float(s.iloc[0])
    if unit == "abs":
        ch1, ch3 = last - ago1, last - ago3
    else:
        if ago1 <= 0 or ago3 <= 0:
            return None
        ch1, ch3 = (last / ago1 - 1) * 100, (last / ago3 - 1) * 100
    move = _clip(0.5 * ch1 / thr1 + 0.5 * ch3 / thr3)
    if any(math.isnan(v) for v in (last, ch1, ch3, move)):
        return None
    return {"key": key, "symbol": sym, "label": label, "unit": unit,
            "last": round(last, 4), "change_1m": round(ch1, 2), "change_3m": round(ch3, 2),
            "move": round(move, 2), "trend": _trend_word(move)}


def _trend_word(move: float) -> str:
    if move >= 1.0:
        return "sharply up"
    if move >= 0.35:
        return "up"
    if move <= -1.0:
        return "sharply down"
    if move <= -0.35:
        return "down"
    return "flat"


def _fetch_prices() -> dict[str, dict]:
    import yfinance as yf
    syms = [v[0] for v in FACTORS.values()]
    df = yf.download(syms, period="6mo", interval="1d", progress=False,
                     auto_adjust=False, threads=True, group_by="column")
    out: dict[str, dict] = {}
    if df is None or df.empty:
        return out
    close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    for key, (sym, *_rest) in FACTORS.items():
        try:
            f = _factor_from_series(key, close[sym])
        except Exception:
            f = None
        if f:
            out[key] = f
    return out


def _fii_factor(fii: Optional[dict]) -> Optional[dict]:
    if not fii or fii.get("fii_net_cr") is None:
        return None
    net = float(fii.get("fii_net_cr") or 0)
    dii = float(fii.get("dii_net_cr") or 0)
    move = _clip(net / 3000.0, -1.0, 1.0)   # one day's flow: capped at ±1
    return {"key": "fii", "symbol": "NSE FII/DII", "label": "FII net flow (latest day)",
            "unit": "cr", "last": net, "change_1m": None, "change_3m": None,
            "dii_net_cr": dii, "as_of": fii.get("as_of"),
            "move": round(move, 2), "trend": _trend_word(move)}


def build_snapshot(prices: dict[str, dict], fii: Optional[dict] = None,
                   repo_trend: Optional[str] = None) -> dict:
    """Pure: factor dict → snapshot with the derived 'rates' factor."""
    factors = dict(prices)
    ff = _fii_factor(fii)
    if ff:
        factors["fii"] = ff
    repo = REPO_TREND.get(str(repo_trend or "").strip().lower()) if repo_trend else None
    us10y = factors.get("us10y", {}).get("move")
    if us10y is not None or repo is not None:
        parts = [(0.6, us10y), (0.4, repo)]
        used = [(w, v) for w, v in parts if v is not None]
        rates = sum(w * v for w, v in used) / sum(w for w, _ in used)
        factors["rates"] = {"key": "rates", "label": "Interest-rate pressure",
                            "move": round(rates, 2), "trend": _trend_word(rates),
                            "repo_trend": repo_trend if repo is not None else None,
                            "derived": True}
    return {"available": bool(prices), "factors": factors,
            "computed_at": datetime.now().isoformat(timespec="seconds"),
            "sources": SOURCES}


def snapshot(cfg: Optional[dict] = None, force: bool = False) -> dict:
    """Current macro snapshot. Cached for 3 h; a failed fetch falls back to a
    snapshot up to 3 days old, else {'available': False}."""
    mcfg = (cfg or {}).get("macro", {}) or {}
    if mcfg.get("enabled") is False:
        return {"available": False, "factors": {}, "disabled": True}
    cached = None
    if CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            age = time.time() - CACHE_PATH.stat().st_mtime
            if not force and age < CACHE_TTL_SECONDS and cached.get("repo_cfg") == mcfg.get("repo_trend"):
                return cached
        except Exception:
            cached = None
    if not force and time.time() - _last_fail["ts"] < RETRY_AFTER_FAIL_SECONDS:
        if cached:
            cached["stale"] = True
            return cached
        return {"available": False, "factors": {}, "reason": "macro data unavailable"}
    try:
        prices = _fetch_prices()
    except Exception:
        prices = {}
    fii = None
    if prices:
        try:
            from . import fii_dii
            fii = fii_dii.fetch()
        except Exception:
            pass
    if not prices:
        _last_fail["ts"] = time.time()
        if cached and time.time() - CACHE_PATH.stat().st_mtime < STALE_OK_SECONDS:
            cached["stale"] = True
            return cached
        return {"available": False, "factors": {}, "reason": "macro data unavailable"}
    snap = build_snapshot(prices, fii, mcfg.get("repo_trend"))
    snap["repo_cfg"] = mcfg.get("repo_trend")
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap), encoding="utf-8")
        tmp.replace(CACHE_PATH)
    except Exception:
        pass
    return snap


def group_for(sector: Optional[str], industry: Optional[str]) -> Optional[tuple]:
    ind = (industry or "").lower()
    sec = (sector or "").strip()
    if ind:
        for g in GROUPS:
            if any(k in ind for k in g[1]):
                return g
    if sec:
        for g in GROUPS:
            if sec in g[2]:
                return g
    return None


def stock_impact(snap: Optional[dict], sector: Optional[str],
                 industry: Optional[str]) -> dict:
    """{score, group, drivers:[(label, contribution, factor)], note}. score 0
    when there's no snapshot or the stock has no known sector."""
    out = {"score": 0.0, "group": None, "drivers": [], "note": None}
    if not snap or not snap.get("available") or not (sector or industry):
        return out
    factors = snap.get("factors") or {}
    g = group_for(sector, industry)
    sens = dict(MARKET_WIDE)
    if g:
        for k, v in g[3].items():
            sens[k] = sens.get(k, 0.0) + v
        out["group"] = g[0]
    contribs = []
    for k, w in sens.items():
        f = factors.get(k)
        if not f or f.get("move") is None:
            continue
        c = w * float(f["move"])
        if abs(c) >= 0.05:
            contribs.append((f.get("label", k), round(c, 2), f))
    score = _clip(sum(c for _, c, _ in contribs), -MAX_STOCK_SCORE, MAX_STOCK_SCORE)
    contribs.sort(key=lambda x: -abs(x[1]))
    out["score"] = round(score, 2)
    out["drivers"] = [{"label": lbl, "contribution": c, "trend": f.get("trend"),
                       "change_3m": f.get("change_3m"), "unit": f.get("unit")}
                      for lbl, c, f in contribs[:4]]
    if contribs and abs(score) >= 0.1:
        bits = []
        for lbl, c, f in contribs[:2]:
            ch = f.get("change_3m")
            unit = f.get("unit")
            if ch is None:
                move_txt = f.get("trend", "")
            elif unit == "abs":
                move_txt = f"{ch:+.2f} pts (3m)"
            else:
                move_txt = f"{ch:+.1f}% (3m)"
            bits.append(f"{lbl} {move_txt} → {'tailwind' if c > 0 else 'headwind'}")
        who = g[0] if g else "the market"
        out["note"] = f"Macro {score:+.2f} for {who}: " + "; ".join(bits)
    return out


def fingerprint(snap: Optional[dict]) -> str:
    """Short key of the factor moves, rounded so day-to-day noise doesn't
    force a re-analysis of every stock."""
    if not snap or not snap.get("available"):
        return "none"
    f = snap.get("factors") or {}
    return ",".join(f"{k}:{round(float(v.get('move') or 0) * 4) / 4:g}" for k, v in sorted(f.items()))


def sector_table(snap: Optional[dict]) -> list[dict]:
    """Every sector group's macro score, for the dashboard."""
    rows = []
    if not snap or not snap.get("available"):
        return rows
    for g in GROUPS:
        imp = stock_impact(snap, g[2][0] if g[2] else "x", g[1][0])
        rows.append({"group": g[0], "score": imp["score"], "drivers": imp["drivers"][:2]})
    rows.sort(key=lambda r: -r["score"])
    return rows
