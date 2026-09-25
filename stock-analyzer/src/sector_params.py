"""Per-sector fundamental scoring parameters.

The base engine applied ONE set of absolute thresholds to every stock — ROE ≥20%
scored +1.0 whether it was a bank (where 15% is already strong and 20% rare) or
an FMCG (where 30%+ is normal and 15% is mediocre). PE <15 = "cheap" is right for
a commodity metal but wrong for an FMCG that structurally trades at 40-50×.

This module gives each broad sector its own bands so the fundamental score
reflects sector-appropriate expectations. yfinance's GICS-style sector names are
the keys; anything unlisted falls back to DEFAULT.

Each param set:
  roe:            (strong, healthy, ok, weak_below)   → +1.0 / +0.6 / +0.2 / −0.6
  pe:             (cheap_below, expensive_above, very_expensive_above)
                                                       → +0.5 / −0.2 / −0.6
  margin_good:    profit-margin threshold for +0.3
  score_leverage: False for sectors where debt is structural (banks, utilities,
                  realty) — D/E is not scored, matching how analysts read them.
"""
from __future__ import annotations

from typing import Optional


DEFAULT: dict = {
    "roe": (0.20, 0.15, 0.10, 0.05),
    "pe": (15, 40, 60),
    "margin_good": 0.15,
    "score_leverage": True,
}

# Tuned to how each sector actually trades on Indian exchanges.
SECTOR_PARAMS: dict[str, dict] = {
    # Banks/NBFCs: leverage IS the business; ROE 15%+ is strong; PE re-rates low.
    "Financial Services": {
        "roe": (0.18, 0.15, 0.12, 0.08), "pe": (12, 25, 35),
        "margin_good": 0.20, "score_leverage": False,
    },
    # IT services: asset-light, high ROE + margins are the norm, low debt.
    "Technology": {
        "roe": (0.25, 0.18, 0.12, 0.08), "pe": (18, 35, 50),
        "margin_good": 0.18, "score_leverage": True,
    },
    # FMCG: premium multiples are structural; very high ROE; thin-ish net margin.
    "Consumer Defensive": {
        "roe": (0.30, 0.20, 0.14, 0.08), "pe": (30, 55, 75),
        "margin_good": 0.12, "score_leverage": True,
    },
    # Pharma: R&D-heavy, richer PE tolerated, moderate margins.
    "Healthcare": {
        "roe": (0.20, 0.15, 0.10, 0.05), "pe": (25, 45, 65),
        "margin_good": 0.15, "score_leverage": True,
    },
    # Auto / discretionary retail: cyclical, thinner margins, moderate PE.
    "Consumer Cyclical": {
        "roe": (0.18, 0.13, 0.09, 0.04), "pe": (18, 35, 50),
        "margin_good": 0.10, "score_leverage": True,
    },
    # Metals / chemicals: deeply cyclical, low PE at the top of the cycle.
    "Basic Materials": {
        "roe": (0.16, 0.12, 0.08, 0.03), "pe": (10, 22, 32),
        "margin_good": 0.12, "score_leverage": True,
    },
    # Energy / oil & gas: capital-heavy, low PE, leverage common.
    "Energy": {
        "roe": (0.15, 0.11, 0.07, 0.03), "pe": (10, 20, 30),
        "margin_good": 0.10, "score_leverage": True,
    },
    # Capital goods / infra / engineering.
    "Industrials": {
        "roe": (0.18, 0.14, 0.10, 0.05), "pe": (18, 35, 50),
        "margin_good": 0.12, "score_leverage": True,
    },
    # Power / gas utilities: regulated returns, high structural leverage.
    "Utilities": {
        "roe": (0.14, 0.11, 0.08, 0.04), "pe": (12, 22, 32),
        "margin_good": 0.12, "score_leverage": False,
    },
    # Real estate: NAV/debt-driven, leverage structural.
    "Real Estate": {
        "roe": (0.14, 0.10, 0.07, 0.03), "pe": (14, 28, 40),
        "margin_good": 0.12, "score_leverage": False,
    },
    # Telecom / media.
    "Communication Services": {
        "roe": (0.16, 0.12, 0.08, 0.04), "pe": (16, 30, 45),
        "margin_good": 0.12, "score_leverage": True,
    },
}

# Sectors where debt is structural — kept as a derived set for the sector-relative
# overlay, so there's a single source of truth.
LEVERAGE_NATURAL_SECTORS = {
    s for s, p in SECTOR_PARAMS.items() if not p.get("score_leverage", True)
}


def get_params(sector: Optional[str]) -> dict:
    """Scoring bands for a sector, falling back to DEFAULT for unknown/None."""
    if not sector:
        return DEFAULT
    return SECTOR_PARAMS.get(sector, DEFAULT)
