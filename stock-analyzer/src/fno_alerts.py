"""Signal-change alerts for the F&O module.

The tracking loop (web.py) hands each fresh analysis to check_and_notify().
When a symbol's bias flips (e.g. NEUTRAL → BULLISH), the transition is
appended to a rolling alerts log that the /fno page shows, and — if enabled
in config.yaml (fno.alerts.telegram: true) and Telegram credentials exist —
a message is sent to the user's own Saved Messages.

State and log live on disk so restarts don't re-fire old transitions:
    data/cache/fno/alert_state.json   {"NIFTY": {"bias": "...", "score": ...}}
    data/cache/fno/alerts.json        {"alerts": [newest ... oldest]}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .fno_history import now_ist

STATE_PATH = Path("data/cache/fno/alert_state.json")
ALERTS_PATH = Path("data/cache/fno/alerts.json")
MAX_ALERTS = 200


def _read_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p: Path, obj) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")
    except Exception:
        pass


def recent_alerts(limit: int = 10) -> list[dict]:
    return (_read_json(ALERTS_PATH, {}).get("alerts") or [])[:limit]


def check_and_notify(a, cfg: Optional[dict] = None, telegram_lock=None) -> Optional[dict]:
    """Record a bias transition if one happened. Returns the alert dict when a
    new alert fired, else None. Never raises."""
    try:
        if a is None or a.stale:
            return None
        state = _read_json(STATE_PATH, {})
        prev = state.get(a.symbol) or {}
        prev_bias = prev.get("bias")

        state[a.symbol] = {"bias": a.bias, "score": a.score,
                           "ts": now_ist().isoformat(timespec="seconds")}
        _write_json(STATE_PATH, state)

        # First observation ever, or unchanged bias → nothing to announce.
        if prev_bias is None or prev_bias == a.bias:
            return None

        alert = {
            "ts": now_ist().isoformat(timespec="seconds"),
            "symbol": a.symbol,
            "label": a.label,
            "from": prev_bias,
            "to": a.bias,
            "score": a.score,
            "confidence": a.confidence,
            "spot": a.spot,
            "reason": a.rationale[0] if a.rationale else a.oi_flow,
        }
        log = _read_json(ALERTS_PATH, {})
        alerts = log.get("alerts") or []
        alerts.insert(0, alert)
        _write_json(ALERTS_PATH, {"alerts": alerts[:MAX_ALERTS]})

        _maybe_telegram(alert, cfg, telegram_lock)
        return alert
    except Exception:
        return None


def _maybe_telegram(alert: dict, cfg: Optional[dict], telegram_lock) -> None:
    """Best-effort DM to the user's own Telegram Saved Messages. Opt-in via
    config (fno.alerts.telegram: true) and requires the same api_id/api_hash
    the research-ingest feature uses. Failures are swallowed — an alert must
    never break the tracking loop."""
    try:
        cfg = cfg or {}
        if not ((cfg.get("fno") or {}).get("alerts") or {}).get("telegram"):
            return
        tcfg = cfg.get("telegram") or {}
        if not tcfg.get("api_id") or not tcfg.get("api_hash"):
            return
        if telegram_lock is not None and not telegram_lock.acquire(timeout=3):
            return  # a batch scan holds the session file; skip, don't block
        try:
            from telethon.sync import TelegramClient
            text = (f"F&O signal change: {alert['label']}\n"
                    f"{alert['from']} → {alert['to']}  "
                    f"(score {alert['score']:+.2f}, {alert['confidence']} confidence)\n"
                    f"Spot {alert['spot']:,.2f}\n"
                    f"{alert['reason']}")
            with TelegramClient(tcfg.get("session_name", "stock_analyzer"),
                                int(tcfg["api_id"]), tcfg["api_hash"]) as client:
                client.send_message("me", text)
        finally:
            if telegram_lock is not None:
                try:
                    telegram_lock.release()
                except RuntimeError:
                    pass
    except Exception:
        pass
