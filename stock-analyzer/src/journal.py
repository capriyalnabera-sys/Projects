"""Personal trade journal — log entries, track open positions live, archive closed
trades. Stored at data/journal.json (gitignored)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yfinance as yf

from . import data as data_mod

JOURNAL_PATH = Path("data/journal.json")


def _load() -> dict:
    if not JOURNAL_PATH.exists():
        return {"trades": []}
    try:
        return json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"trades": []}


def _save(d: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")


def add_trade(
    ticker: str, qty: int, entry_price: float, entry_date: str,
    stop_loss: Optional[float] = None, target: Optional[float] = None,
    notes: str = "", cache_root: Optional[Path] = None,
) -> dict:
    d = _load()
    verdict_at_entry = None
    score_at_entry = None
    if cache_root is not None:
        from . import batch
        cached = batch.read_result(ticker, cache_root)
        if cached:
            verdict_at_entry = cached.get("verdict")
            score_at_entry = cached.get("combined_score")
    trade = {
        "id": uuid.uuid4().hex[:8],
        "ticker": ticker.upper(),
        "qty": int(qty),
        "entry_price": float(entry_price),
        "entry_date": entry_date,
        "stop_loss": float(stop_loss) if stop_loss is not None else None,
        "target": float(target) if target is not None else None,
        "exit_price": None,
        "exit_date": None,
        "status": "open",
        "notes": notes or "",
        "verdict_at_entry": verdict_at_entry,
        "score_at_entry": score_at_entry,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    d["trades"].append(trade)
    _save(d)
    return trade


def close_trade(trade_id: str, exit_price: float, exit_date: str) -> Optional[dict]:
    d = _load()
    for t in d["trades"]:
        if t["id"] == trade_id and t["status"] == "open":
            t["exit_price"] = float(exit_price)
            t["exit_date"] = exit_date
            t["status"] = "closed"
            _save(d)
            return t
    return None


def delete_trade(trade_id: str) -> bool:
    d = _load()
    n = len(d["trades"])
    d["trades"] = [t for t in d["trades"] if t["id"] != trade_id]
    if len(d["trades"]) != n:
        _save(d)
        return True
    return False


def list_trades_with_live(cache_root: Optional[Path] = None) -> list[dict]:
    d = _load()
    trades = list(d["trades"])
    open_tickers = sorted({t["ticker"] for t in trades if t["status"] == "open"})

    live: dict[str, float] = {}
    live_as_of: dict[str, str] = {}

    # PRIMARY: NSE direct quote API — most accurate (exchange-of-record).
    # Real-time during market hours; previous close after-hours.
    if open_tickers:
        try:
            from . import nse_quote
            quotes = nse_quote.fetch_quotes(open_tickers)
            for tk, q in quotes.items():
                live[tk] = float(q["ltp"])
                # Prefer NSE's own timestamp (e.g. "13-May-2026 12:35:00") if present
                live_as_of[tk] = q.get("as_of") or datetime.now().isoformat(timespec="minutes")
        except Exception:
            pass

    # SECONDARY: moneycontrol price API (when we have an sccode for the ticker).
    missing = [t for t in open_tickers if t not in live]
    if missing:
        try:
            from . import moneycontrol
            for tk in missing:
                q = moneycontrol.fetch_quote(tk)
                if q and q.get("ltp"):
                    live[tk] = float(q["ltp"])
                    live_as_of[tk] = q.get("as_of") or datetime.now().isoformat(timespec="minutes")
        except Exception:
            pass

    # TERTIARY: yfinance bulk fetch for whatever's still missing.
    missing = [t for t in open_tickers if t not in live]
    if missing:
        try:
            histories = data_mod.bulk_fetch_histories(missing, period="5d")
            now_iso = datetime.now().isoformat(timespec="minutes")
            for tk, df in histories.items():
                if df is None or df.empty:
                    continue
                closes = df["Close"].dropna() if hasattr(df, "columns") else None
                if closes is not None and len(closes) > 0:
                    live[tk] = float(closes.iloc[-1])
                    live_as_of[tk] = now_iso
        except Exception:
            pass

    # FINAL FALLBACK: batch cache for anything truly unreachable.
    if cache_root is not None:
        from . import batch as batch_mod
        for tk in open_tickers:
            if tk in live:
                continue
            cached = batch_mod.read_result(tk, cache_root)
            if cached and cached.get("last_close") is not None:
                lc = cached["last_close"]
                if isinstance(lc, (int, float)) and lc == lc:
                    live[tk] = float(lc)
                    live_as_of[tk] = cached.get("as_of", "")

    out: list[dict] = []
    today = date.today()
    for t in trades:
        e = dict(t)
        # Ensure consistent shape for the template (Jinja's `is not none` doesn't
        # catch missing keys — they become Undefined and explode on .format).
        e["current_price"] = None
        e["pnl_per_share"] = None
        e["pnl_pct"] = None
        e["pnl_total"] = None
        e["alert"] = None
        try:
            entry_d = date.fromisoformat(t["entry_date"])
            e["days_held"] = max(0, (today - entry_d).days)
        except Exception:
            e["days_held"] = 0

        if t["status"] == "open" and t["ticker"] in live:
            ltp = live[t["ticker"]]
            e["current_price"] = ltp
            e["ltp_as_of"] = live_as_of.get(t["ticker"], "")
            e["pnl_per_share"] = ltp - t["entry_price"]
            e["pnl_pct"] = (ltp / t["entry_price"] - 1) * 100
            e["pnl_total"] = e["pnl_per_share"] * t["qty"]
            if t.get("stop_loss") and ltp <= t["stop_loss"]:
                e["alert"] = "Stop hit"
            elif t.get("target") and ltp >= t["target"]:
                e["alert"] = "Target hit"
        elif t["status"] == "closed" and t.get("exit_price") is not None:
            e["pnl_per_share"] = t["exit_price"] - t["entry_price"]
            e["pnl_pct"] = (t["exit_price"] / t["entry_price"] - 1) * 100
            e["pnl_total"] = e["pnl_per_share"] * t["qty"]

        # Did the verdict at entry match what the price has done since?
        e["verdict_accuracy"] = _verdict_accuracy(t.get("verdict_at_entry"), e["pnl_pct"])
        out.append(e)
    # Open first, then closed; within each, newest first
    out.sort(key=lambda x: (0 if x["status"] == "open" else 1, x.get("created_at", "")), reverse=False)
    out.sort(key=lambda x: (0 if x["status"] == "open" else 1))
    return out


def _verdict_accuracy(verdict: Optional[str], pnl_pct: Optional[float]) -> dict:
    """Was the verdict at entry directionally correct vs current price action?
    Returns a dict with status (machine), label (human), color (pos/neg/neutral).
    """
    if pnl_pct is None:
        return {"status": "pending", "label": "Pending LTP", "color": "neutral"}
    if not verdict:
        return {"status": "no_verdict", "label": "No verdict at entry", "color": "neutral"}
    v = verdict.upper()
    if v in ("BUY", "ACCUMULATE"):
        if pnl_pct > 1.0:
            return {"status": "correct", "label": "On track", "color": "pos"}
        if pnl_pct > -2.0:
            return {"status": "early", "label": "Too early to tell", "color": "neutral"}
        return {"status": "wrong", "label": "Wrong so far", "color": "neg"}
    if v == "HOLD":
        if abs(pnl_pct) < 3.0:
            return {"status": "correct", "label": "Flat as expected", "color": "neutral"}
        if pnl_pct > 0:
            return {"status": "outperformed", "label": "Up despite HOLD", "color": "pos"}
        return {"status": "underperformed", "label": "Down despite HOLD", "color": "neg"}
    if v in ("REDUCE", "AVOID"):
        if pnl_pct < -1.0:
            return {"status": "correct", "label": "Fell as predicted", "color": "pos"}
        if pnl_pct < 2.0:
            return {"status": "early", "label": "Verdict pending", "color": "neutral"}
        return {"status": "wrong", "label": f"Up despite {v}", "color": "neg"}
    return {"status": "neutral", "label": "—", "color": "neutral"}


def summary(trades: list[dict]) -> dict:
    open_pnl = sum((t.get("pnl_total") or 0) for t in trades if t["status"] == "open")
    closed_pnl = sum((t.get("pnl_total") or 0) for t in trades if t["status"] == "closed")
    n_open = sum(1 for t in trades if t["status"] == "open")
    n_closed = sum(1 for t in trades if t["status"] == "closed")
    n_winners = sum(1 for t in trades if t["status"] == "closed" and (t.get("pnl_total") or 0) > 0)
    win_rate = (n_winners / n_closed * 100) if n_closed > 0 else None

    # Verdict accuracy across all trades with a determinable outcome
    evaluable = [t for t in trades
                 if t.get("verdict_at_entry") and (t.get("verdict_accuracy") or {}).get("status") not in (None, "pending", "no_verdict")]
    n_eval = len(evaluable)
    n_correct = sum(1 for t in evaluable
                    if (t.get("verdict_accuracy") or {}).get("status") == "correct")
    n_wrong = sum(1 for t in evaluable
                  if (t.get("verdict_accuracy") or {}).get("status") == "wrong")
    verdict_hit_rate = (n_correct / n_eval * 100) if n_eval > 0 else None
    return {
        "open_count": n_open, "closed_count": n_closed,
        "open_pnl": round(open_pnl, 2), "closed_pnl": round(closed_pnl, 2),
        "total_pnl": round(open_pnl + closed_pnl, 2),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "verdict_hit_rate": round(verdict_hit_rate, 1) if verdict_hit_rate is not None else None,
        "verdict_correct": n_correct,
        "verdict_wrong": n_wrong,
        "verdict_evaluable": n_eval,
    }
