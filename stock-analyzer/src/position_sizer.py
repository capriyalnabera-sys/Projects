"""Position sizing helper — given account size, risk-per-trade %, and stop
distance, suggest qty. Implements the 1% rule (default) — never risk more
than 1% of account on a single trade.

Reads account_size and risk_per_trade_pct from config.yaml under
'position_sizing'. Sensible defaults if unset.
"""
from __future__ import annotations

from typing import Optional


DEFAULT_ACCOUNT_SIZE = 1_000_000  # ₹10 lakh starting assumption
DEFAULT_RISK_PCT = 1.0            # 1% of account at risk per trade


def suggest_qty(
    entry_price: float,
    stop_loss: Optional[float],
    account_size: float = DEFAULT_ACCOUNT_SIZE,
    risk_pct: float = DEFAULT_RISK_PCT,
) -> dict:
    """Compute suggested position size given account/risk parameters.
    Returns dict with qty, risk_amount, position_value, capital_pct, plus
    a structured explanation string.
    """
    if not entry_price or entry_price <= 0:
        return {"qty": 0, "reason": "Need a positive entry price."}
    if not stop_loss or stop_loss <= 0:
        return {"qty": 0, "reason": "Need a stop loss to compute size."}
    if stop_loss >= entry_price:
        return {"qty": 0, "reason": "Stop must be below entry for a long position."}

    risk_per_share = entry_price - stop_loss
    risk_budget = account_size * (risk_pct / 100.0)
    qty = int(risk_budget // risk_per_share)
    if qty <= 0:
        return {"qty": 0, "reason": "Stop distance too wide for the configured risk budget."}

    position_value = qty * entry_price
    actual_risk = qty * risk_per_share
    capital_pct = position_value / account_size * 100

    return {
        "qty": qty,
        "risk_per_share": round(risk_per_share, 2),
        "risk_amount": round(actual_risk, 2),
        "position_value": round(position_value, 2),
        "capital_pct": round(capital_pct, 1),
        "account_size": account_size,
        "risk_pct": risk_pct,
        "explanation": (
            f"At ₹{entry_price:.2f} entry with stop ₹{stop_loss:.2f}, you risk "
            f"₹{risk_per_share:.2f}/share. Buying {qty} shares puts ₹{position_value:,.0f} "
            f"({capital_pct:.1f}% of capital) at risk of ₹{actual_risk:,.0f} "
            f"({risk_pct}% of ₹{account_size:,.0f} account)."
        ),
    }


def get_config(cfg: dict) -> tuple[float, float]:
    """Pull (account_size, risk_pct) from config dict, with defaults."""
    ps = cfg.get("position_sizing") or {}
    return (
        float(ps.get("account_size", DEFAULT_ACCOUNT_SIZE)),
        float(ps.get("risk_per_trade_pct", DEFAULT_RISK_PCT)),
    )
