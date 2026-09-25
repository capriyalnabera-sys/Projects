"""Show the SAME fundamentals score differently by sector (bank vs IT vs FMCG)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import fundamentals, sector_params  # noqa: E402

# Identical company metrics — only the sector differs.
info = {
    "returnOnEquity": 0.16,     # 16% ROE
    "trailingPE": 30.0,         # PE 30
    "forwardPE": 28.0,
    "debtToEquity": 1.5,        # D/E 1.5
    "earningsGrowth": 0.12,
    "revenueGrowth": 0.14,
    "profitMargins": 0.13,      # 13% net margin
    "priceToBook": 3.0,
}

print("Same metrics (ROE 16%, PE 30, D/E 1.5, margin 13%) scored per sector:\n")
print(f"{'Sector':24s} {'params(roe/pe/lev)':28s} {'score':>6s}")
for sector in ["Financial Services", "Technology", "Consumer Defensive",
               "Basic Materials", "Healthcare", None]:
    p = sector_params.get_params(sector)
    fund = fundamentals.analyze(info, sector, ticker=None)
    lev = "no" if not p["score_leverage"] else "yes"
    ptxt = f"roe{p['roe'][0]:.0%}/pe<{p['pe'][0]}/lev:{lev}"
    print(f"{str(sector):24s} {ptxt:28s} {fund.score:+6.2f}")

print("\nKey notes per sector:")
for sector in ["Financial Services", "Consumer Defensive"]:
    fund = fundamentals.analyze(info, sector, ticker=None)
    print(f"\n  {sector}:")
    for n in fund.notes[:6]:
        print(f"    - {n}")
