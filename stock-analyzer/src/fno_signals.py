"""F&O analytics + signal synthesis for index options.

Everything here is pure computation over the normalized chain from fno.py,
so it is fully testable offline (scripts/_smoke_fno.py). The only network
touch is the optional spot-history overlay (yfinance) and the VIX read
(regime cache first, yfinance fallback), both of which degrade to None.

What it computes:
  - PCR (OI + volume), total and near-ATM band
  - Max pain strike
  - OI walls → support/resistance levels with distances
  - ΔOI flow reading (put writing / call writing / straddle writing / unwinding)
  - ATM IV, IV skew (OTM put IV − OTM call IV), straddle price → expected move
  - Composite bias score [-3, +3] → BULLISH / BEARISH / RANGE-BOUND / NEUTRAL
  - Concrete strategy suggestions with strikes, sized off the chain itself

Not investment advice — heuristics over public exchange data.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from . import fno


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class FnoAnalysis:
    symbol: str
    label: str
    spot: float
    as_of: str
    expiry: str
    days_to_expiry: Optional[int]
    stale: bool
    source: str
    lot: int

    pcr_oi: Optional[float] = None
    pcr_oi_band: Optional[float] = None      # near-ATM ±5 strikes
    pcr_volume: Optional[float] = None
    max_pain: Optional[float] = None
    max_pain_distance_pct: Optional[float] = None

    supports: list[dict] = field(default_factory=list)     # [{strike, oi, distance_pct}]
    resistances: list[dict] = field(default_factory=list)

    atm_strike: Optional[float] = None
    atm_iv: Optional[float] = None
    iv_skew: Optional[float] = None
    straddle_price: Optional[float] = None
    expected_move_pct: Optional[float] = None
    expected_move_daily_pct: Optional[float] = None

    oi_flow: str = "no reading"              # human-readable ΔOI interpretation
    oi_flow_score: float = 0.0
    ce_oi_change: int = 0
    pe_oi_change: int = 0

    vix: Optional[float] = None
    spot_change_pct: Optional[float] = None  # day change of the underlying
    technical_score: Optional[float] = None  # from technical.analyze on index

    score: float = 0.0
    bias: str = "NEUTRAL"                    # BULLISH/BEARISH/RANGE-BOUND/NEUTRAL
    confidence: str = "low"                  # low/medium/high
    rationale: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    strategies: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Chain metrics (pure functions over normalized rows)
# ---------------------------------------------------------------------------

def _leg(row: dict, side: str) -> dict:
    return row.get(side) or {}


def pcr(rows: list[dict], use_volume: bool = False) -> Optional[float]:
    key = "volume" if use_volume else "oi"
    ce = sum((_leg(r, "ce").get(key) or 0) for r in rows)
    pe = sum((_leg(r, "pe").get(key) or 0) for r in rows)
    if ce <= 0:
        return None
    return round(pe / ce, 2)


def atm_strike(rows: list[dict], spot: float) -> Optional[float]:
    strikes = [r["strike"] for r in rows]
    if not strikes:
        return None
    return min(strikes, key=lambda k: abs(k - spot))


def band_rows(rows: list[dict], spot: float, step: float, n: int = 5) -> list[dict]:
    """Rows within ±n strike-steps of ATM — where the real positioning is."""
    atm = atm_strike(rows, spot)
    if atm is None or step <= 0:
        return rows
    lo, hi = atm - n * step, atm + n * step
    return [r for r in rows if lo <= r["strike"] <= hi]


def max_pain(rows: list[dict]) -> Optional[float]:
    """Strike minimizing total intrinsic payout to option buyers at expiry.
    Classic expiry-gravity level — price tends to drift toward it in the last
    sessions as writers defend their books."""
    strikes = [r["strike"] for r in rows]
    if not strikes:
        return None
    best_strike, best_pain = None, None
    for s in strikes:
        pain = 0.0
        for r in rows:
            k = r["strike"]
            ce_oi = _leg(r, "ce").get("oi") or 0
            pe_oi = _leg(r, "pe").get("oi") or 0
            pain += ce_oi * max(0.0, s - k)   # calls ITM when settle > strike
            pain += pe_oi * max(0.0, k - s)   # puts  ITM when settle < strike
        if best_pain is None or pain < best_pain:
            best_pain, best_strike = pain, s
    return best_strike


def oi_walls(rows: list[dict], spot: float, top_n: int = 3) -> tuple[list[dict], list[dict]]:
    """(supports, resistances): biggest PE OI at/below spot, CE OI at/above.
    Writers cluster where they expect price NOT to go — those strikes act as
    magnets/barriers until the OI unwinds."""
    puts = [(r["strike"], _leg(r, "pe").get("oi") or 0) for r in rows if r["strike"] <= spot]
    calls = [(r["strike"], _leg(r, "ce").get("oi") or 0) for r in rows if r["strike"] >= spot]
    puts.sort(key=lambda x: -x[1])
    calls.sort(key=lambda x: -x[1])

    def fmt(items):
        out = []
        for strike, oi in items[:top_n]:
            if oi <= 0:
                continue
            out.append({
                "strike": strike, "oi": oi,
                "distance_pct": round((strike / spot - 1) * 100, 2),
            })
        return out

    return fmt(puts), fmt(calls)


def atm_metrics(rows: list[dict], spot: float, step: float,
                dte: Optional[int]) -> dict:
    """ATM IV, straddle price, expected move; IV skew from OTM wings."""
    atm = atm_strike(rows, spot)
    out = {"atm_strike": atm, "atm_iv": None, "straddle_price": None,
           "expected_move_pct": None, "expected_move_daily_pct": None,
           "iv_skew": None}
    if atm is None:
        return out
    row = next((r for r in rows if r["strike"] == atm), None)
    if row is None:
        return out
    ce, pe = _leg(row, "ce"), _leg(row, "pe")

    ivs = [v for v in (ce.get("iv"), pe.get("iv")) if v]
    if ivs:
        out["atm_iv"] = round(sum(ivs) / len(ivs), 2)

    if ce.get("ltp") and pe.get("ltp"):
        straddle = ce["ltp"] + pe["ltp"]
        out["straddle_price"] = round(straddle, 2)
        # ATM straddle ≈ market's 1σ-ish expected move to expiry.
        out["expected_move_pct"] = round(straddle / spot * 100, 2)
        if dte and dte > 0:
            out["expected_move_daily_pct"] = round(straddle / spot * 100 / (dte ** 0.5), 2)

    # Skew: avg IV of OTM puts (2-4 steps below ATM) minus OTM calls (2-4 above).
    # Positive = downside protection bid up = fear; strongly negative = call chase.
    def wing_iv(side: str, direction: int) -> Optional[float]:
        vals = []
        for k in range(2, 5):
            target = atm + direction * k * step
            r = next((x for x in rows if x["strike"] == target), None)
            if r:
                iv = _leg(r, side).get("iv")
                if iv:
                    vals.append(iv)
        return sum(vals) / len(vals) if vals else None

    put_iv, call_iv = wing_iv("pe", -1), wing_iv("ce", +1)
    if put_iv is not None and call_iv is not None:
        out["iv_skew"] = round(put_iv - call_iv, 2)
    return out


def oi_flow(rows: list[dict], spot_change_pct: Optional[float]) -> tuple[str, float, int, int]:
    """Read the day's ΔOI: who is writing what, and what that implies.

    Index-option convention: fresh PE OI = put writers = floor being defended
    (bullish); fresh CE OI = call writers = ceiling (bearish). Unwinding is
    the corresponding side giving up. Price direction disambiguates.
    Returns (label, score in [-1.2, +1.2], ce_change, pe_change)."""
    ce_chg = sum((_leg(r, "ce").get("oi_change") or 0) for r in rows)
    pe_chg = sum((_leg(r, "pe").get("oi_change") or 0) for r in rows)
    total_oi = sum((_leg(r, "ce").get("oi") or 0) + (_leg(r, "pe").get("oi") or 0) for r in rows)
    if total_oi <= 0:
        return "no reading", 0.0, ce_chg, pe_chg

    # Materiality gate: ignore ΔOI noise under 0.5% of the book.
    threshold = max(1000, int(total_oi * 0.005))
    up = spot_change_pct is not None and spot_change_pct > 0.05
    down = spot_change_pct is not None and spot_change_pct < -0.05

    heavy_pe = pe_chg > threshold
    heavy_ce = ce_chg > threshold
    pe_unwind = pe_chg < -threshold
    ce_unwind = ce_chg < -threshold

    if heavy_pe and heavy_ce:
        if abs(pe_chg - ce_chg) < 0.3 * max(pe_chg, ce_chg):
            return "Heavy writing on BOTH sides — straddle/strangle sellers expect a range", 0.0, ce_chg, pe_chg
        if pe_chg > ce_chg:
            return "Put writing dominates call writing — dips likely bought", 0.6, ce_chg, pe_chg
        return "Call writing dominates put writing — rallies likely sold", -0.6, ce_chg, pe_chg
    if heavy_pe and not heavy_ce:
        s = 1.0 if up else 0.7
        return "Fresh put writing — support building below spot (bullish)", s, ce_chg, pe_chg
    if heavy_ce and not heavy_pe:
        s = -1.0 if down else -0.7
        return "Fresh call writing — resistance building above spot (bearish)", s, ce_chg, pe_chg
    if pe_unwind and down:
        return "Put writers bailing as price falls — support withdrawn (bearish)", -1.0, ce_chg, pe_chg
    if ce_unwind and up:
        return "Call writers covering as price rises — fuel for upside (bullish)", 1.0, ce_chg, pe_chg
    if pe_unwind:
        return "Put OI unwinding — support thinning", -0.4, ce_chg, pe_chg
    if ce_unwind:
        return "Call OI unwinding — ceiling thinning", 0.4, ce_chg, pe_chg
    return "No significant OI change — positioning unchanged", 0.0, ce_chg, pe_chg


# ---------------------------------------------------------------------------
# Signal synthesis
# ---------------------------------------------------------------------------

def _classify_iv(atm_iv: Optional[float], vix: Optional[float]) -> str:
    """'high' / 'normal' / 'low' — decides credit vs debit strategies."""
    ref = atm_iv if atm_iv is not None else vix
    if ref is None:
        return "normal"
    if ref >= 18:
        return "high"
    if ref <= 11:
        return "low"
    return "normal"


def synthesize(a: FnoAnalysis) -> None:
    """Fill score / bias / confidence / rationale on a partially-built analysis.
    Mutates in place. Weights sum so no single input can dominate."""
    score = 0.0
    r = a.rationale
    c = a.cautions

    # --- PCR (OI): conventional read mid-range, contrarian at extremes -----
    p = a.pcr_oi_band if a.pcr_oi_band is not None else a.pcr_oi
    if p is not None:
        if p >= 1.7:
            score += 0.2
            c.append(f"PCR {p:.2f} is extreme — crowded put writing, sharp unwinds hurt; contrarian risk")
        elif p >= 1.2:
            score += 0.6
            r.append(f"PCR {p:.2f} — put writers dominate, dips have support")
        elif p <= 0.5:
            score -= 0.2
            c.append(f"PCR {p:.2f} is extreme — max bearishness often precedes bounces; contrarian risk")
        elif p <= 0.8:
            score -= 0.6
            r.append(f"PCR {p:.2f} — call writers dominate, rallies get sold")
        else:
            r.append(f"PCR {p:.2f} — balanced positioning")

    # --- ΔOI flow ----------------------------------------------------------
    if a.oi_flow_score:
        score += a.oi_flow_score
    if a.oi_flow and a.oi_flow != "no reading":
        r.append(a.oi_flow)

    # --- Max pain gravity (only matters near expiry) ------------------------
    if a.max_pain_distance_pct is not None and a.days_to_expiry is not None:
        d = a.max_pain_distance_pct  # spot vs max pain, + = spot above
        if a.days_to_expiry <= 2 and abs(d) >= 0.4:
            pull = -0.4 if d > 0 else 0.4
            score += pull
            r.append(f"Max pain {a.max_pain:,.0f} is {abs(d):.1f}% {'below' if d > 0 else 'above'} spot with {a.days_to_expiry}d to expiry — expiry gravity {'down' if d > 0 else 'up'}")
        elif abs(d) >= 1.5:
            r.append(f"Max pain {a.max_pain:,.0f} ({d:+.1f}% vs spot) — relevant only into expiry")

    # --- Index technicals (halved so options data leads) --------------------
    if a.technical_score is not None:
        score += max(-0.75, min(0.75, a.technical_score * 0.5))
        r.append(f"Index technicals {a.technical_score:+.1f} (trend/momentum overlay)")

    # --- Volatility context --------------------------------------------------
    if a.vix is not None:
        if a.vix >= 20:
            c.append(f"India VIX {a.vix:.1f} — elevated; size down, expect ±1%+ days")
        elif a.vix <= 11:
            c.append(f"India VIX {a.vix:.1f} — complacent; cheap hedges, but breakouts can be violent")
    if a.iv_skew is not None:
        if a.iv_skew >= 3:
            c.append(f"IV skew +{a.iv_skew:.1f} — puts bid up, market paying for crash protection")
        elif a.iv_skew <= -2:
            c.append(f"IV skew {a.iv_skew:.1f} — calls richer than puts, chase behaviour")

    if a.stale:
        c.append("Chain data is STALE (exchange API unreachable) — treat signals as indicative only")
    if a.days_to_expiry is not None and a.days_to_expiry <= 1:
        c.append("Expiry within 1 day — gamma risk extreme, premiums decay by the hour")

    a.score = round(max(-3.0, min(3.0, score)), 2)

    # --- Bias + confidence ---------------------------------------------------
    range_evidence = "BOTH sides" in a.oi_flow
    if a.score >= 1.2:
        a.bias = "BULLISH"
    elif a.score <= -1.2:
        a.bias = "BEARISH"
    elif range_evidence and abs(a.score) < 0.8:
        a.bias = "RANGE-BOUND"
    else:
        a.bias = "NEUTRAL"

    strength = abs(a.score)
    agree = 0
    if p is not None and ((p >= 1.2 and a.score > 0) or (p <= 0.8 and a.score < 0)):
        agree += 1
    if a.oi_flow_score and (a.oi_flow_score > 0) == (a.score > 0):
        agree += 1
    if a.technical_score is not None and a.technical_score != 0 and (a.technical_score > 0) == (a.score > 0):
        agree += 1
    if strength >= 1.8 and agree >= 2 and not a.stale:
        a.confidence = "high"
    elif strength >= 1.0 or agree >= 2:
        a.confidence = "medium"
    else:
        a.confidence = "low"


def suggest_strategies(a: FnoAnalysis, step: float) -> list[dict]:
    """Concrete defined-risk structures from bias + IV state + OI walls.
    Strikes come from the chain itself (walls) so they're always tradeable."""
    out: list[dict] = []
    iv_state = _classify_iv(a.atm_iv, a.vix)
    atm = a.atm_strike or (round(a.spot / step) * step if step else a.spot)
    res = a.resistances[0]["strike"] if a.resistances else atm + 4 * step
    sup = a.supports[0]["strike"] if a.supports else atm - 4 * step
    lot = a.lot

    def s(name, legs, rationale, risk):
        return {"name": name, "legs": legs, "rationale": rationale,
                "risk": risk, "iv_state": iv_state, "lot": lot}

    if a.bias == "BULLISH":
        if iv_state == "high":
            out.append(s(
                "Bull Put Spread (credit)",
                [f"SELL {atm - step:,.0f} PE", f"BUY {sup - step:,.0f} PE"],
                f"IV is rich — sell it. Short put just below spot, hedge below the {sup:,.0f} support wall.",
                "Max loss = spread width − credit. Exit if spot closes below the short strike.",
            ))
        else:
            out.append(s(
                "Bull Call Spread (debit)",
                [f"BUY {atm:,.0f} CE", f"SELL {res:,.0f} CE"],
                f"IV is {iv_state} — buying is fair. Sell the {res:,.0f} CE wall to cut cost; that's where writers cap upside anyway.",
                "Max loss = net debit. Book at the resistance wall, don't wait for more.",
            ))
    elif a.bias == "BEARISH":
        if iv_state == "high":
            out.append(s(
                "Bear Call Spread (credit)",
                [f"SELL {atm + step:,.0f} CE", f"BUY {res + step:,.0f} CE"],
                f"IV is rich — sell it. Short call just above spot, hedge above the {res:,.0f} resistance wall.",
                "Max loss = spread width − credit. Exit if spot closes above the short strike.",
            ))
        else:
            out.append(s(
                "Bear Put Spread (debit)",
                [f"BUY {atm:,.0f} PE", f"SELL {sup:,.0f} PE"],
                f"IV is {iv_state} — buying is fair. Sell the {sup:,.0f} PE wall to cut cost; support sits there.",
                "Max loss = net debit. Book at the support wall.",
            ))
    elif a.bias == "RANGE-BOUND":
        out.append(s(
            "Iron Condor",
            [f"SELL {res:,.0f} CE", f"BUY {res + 2 * step:,.0f} CE",
             f"SELL {sup:,.0f} PE", f"BUY {sup - 2 * step:,.0f} PE"],
            f"Writers are boxing {sup:,.0f}–{res:,.0f}; collect premium inside the walls.",
            "Defined risk both sides. Exit the tested side if spot breaks a wall with OI unwinding.",
        ))
        if iv_state == "high" and a.days_to_expiry is not None and a.days_to_expiry <= 7:
            out.append(s(
                "Short Strangle (advanced)",
                [f"SELL {res:,.0f} CE", f"SELL {sup:,.0f} PE"],
                "High IV + short expiry + range evidence — maximum theta capture at the walls.",
                "UNDEFINED risk — needs margin & strict stops (exit at 2× credit). Not for small accounts.",
            ))
    else:  # NEUTRAL
        out.append(s(
            "No trade / wait",
            [],
            "Signals disagree or are weak — the edge isn't there. Flat is a position.",
            "Re-check after 10:00 AM when the day's OI picture settles, or post any pending event.",
        ))
        if iv_state == "low" and a.expected_move_pct:
            out.append(s(
                "Long Straddle (event play only)",
                [f"BUY {atm:,.0f} CE", f"BUY {atm:,.0f} PE"],
                f"IV is cheap; market prices only ±{a.expected_move_pct:.1f}% by expiry. Pays if a known event can beat that.",
                "Needs a move > straddle cost. Theta bleeds daily — only ahead of a catalyst.",
            ))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _spot_overlay(symbol: str) -> tuple[Optional[float], Optional[float], Optional[object]]:
    """(day_change_pct, technical_score, history_df) for the index spot via
    yfinance. All-None on failure — chain analytics still stand alone."""
    meta = fno.INDEX_META.get(symbol.upper())
    if not meta:
        return None, None, None
    try:
        import yfinance as yf
        h = yf.Ticker(meta["yf"]).history(period="1y", auto_adjust=False)
        if h is None or h.empty:
            return None, None, None
        h = h.dropna(subset=["Close"])
        if len(h) < 2:
            return None, None, None
        change_pct = float(h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100
        tech_score = None
        if len(h) >= 60:
            try:
                from . import technical
                tech_score = technical.analyze(h).score
            except Exception:
                pass
        return round(change_pct, 2), tech_score, h
    except Exception:
        return None, None, None


def _get_vix() -> Optional[float]:
    """India VIX — regime cache first (no network), yfinance fallback."""
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path("data/cache/regime.json")
        if p.exists():
            v = _json.loads(p.read_text(encoding="utf-8")).get("vix")
            if v:
                return float(v)
    except Exception:
        pass
    try:
        import yfinance as yf
        h = yf.Ticker("^INDIAVIX").history(period="5d", auto_adjust=False)
        vc = h["Close"].dropna()
        if len(vc):
            return round(float(vc.iloc[-1]), 2)
    except Exception:
        pass
    return None


def analyze_chain(chain: dict, cfg: Optional[dict] = None,
                  spot_change_pct: Optional[float] = None,
                  technical_score: Optional[float] = None,
                  vix: Optional[float] = None) -> FnoAnalysis:
    """Pure analysis of one normalized chain — no network. The overlay inputs
    (spot change / technicals / VIX) are optional enrichments."""
    sym = chain["symbol"]
    meta = fno.INDEX_META.get(sym, {})
    step = float(meta.get("step") or 50)
    spot = float(chain.get("spot") or 0)
    rows = chain.get("rows") or []
    expiry = chain.get("expiry") or ""
    dte = fno.days_to_expiry(expiry) if expiry else None

    a = FnoAnalysis(
        symbol=sym, label=meta.get("label", sym), spot=spot,
        as_of=chain.get("as_of") or "", expiry=expiry, days_to_expiry=dte,
        stale=bool(chain.get("stale")), source=chain.get("source") or "",
        lot=fno.lot_size(sym, cfg),
    )
    if not rows or spot <= 0:
        a.cautions.append("Option chain empty — no analysis possible")
        return a

    band = band_rows(rows, spot, step, n=5)

    a.pcr_oi = pcr(rows)
    a.pcr_oi_band = pcr(band)
    a.pcr_volume = pcr(rows, use_volume=True)
    a.max_pain = max_pain(rows)
    if a.max_pain:
        a.max_pain_distance_pct = round((spot / a.max_pain - 1) * 100, 2)
    a.supports, a.resistances = oi_walls(rows, spot)

    m = atm_metrics(rows, spot, step, dte)
    a.atm_strike = m["atm_strike"]
    a.atm_iv = m["atm_iv"]
    a.iv_skew = m["iv_skew"]
    a.straddle_price = m["straddle_price"]
    a.expected_move_pct = m["expected_move_pct"]
    a.expected_move_daily_pct = m["expected_move_daily_pct"]

    a.spot_change_pct = spot_change_pct
    a.technical_score = technical_score
    a.vix = vix

    a.oi_flow, a.oi_flow_score, a.ce_oi_change, a.pe_oi_change = oi_flow(band, spot_change_pct)

    synthesize(a)
    a.strategies = suggest_strategies(a, step)
    return a


def full_analysis(symbol: str, cfg: Optional[dict] = None,
                  expiry: Optional[str] = None, force: bool = False) -> Optional[FnoAnalysis]:
    """Fetch chain + spot overlay + VIX, run the full pipeline. None only when
    no chain (live or stale) is available at all — then the UI falls back to a
    spot-only card."""
    chain = fno.get_chain(symbol, expiry=expiry, force=force)
    change_pct, tech_score, _hist = _spot_overlay(symbol)
    if chain is None:
        return None
    # BSE payloads sometimes lack spot; borrow the yfinance close so strikes
    # can still be positioned. Without any spot the chain is unusable.
    if not chain.get("spot"):
        if _hist is not None and len(_hist):
            chain["spot"] = float(_hist["Close"].iloc[-1])
        else:
            return None
    return analyze_chain(chain, cfg, change_pct, tech_score, _get_vix())
