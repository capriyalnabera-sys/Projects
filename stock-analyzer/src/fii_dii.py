"""Daily FII/DII flow signal — overlays the regime.

NSE publishes net buy/sell of FIIs and DIIs daily. Heavy persistent selling
by FIIs is a strong macro headwind even when the index hasn't broken its
200SMA yet. Heavy buying is a tailwind across most names.

We don't gate verdicts on this alone — it's auxiliary information surfaced
on the home page next to the regime banner. The trader can read both.

Cached for 4 hours.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import nse_quote


CACHE_PATH = Path("data/cache/fii_dii.json")
CACHE_TTL_SECONDS = 4 * 60 * 60


def fetch() -> dict:
    """Return the latest FII/DII net flow data.
    Shape: {fii_net_cr, dii_net_cr, signal, reason, as_of}
    signal ∈ {'tailwind', 'headwind', 'neutral', 'unknown'}.
    """
    if CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                d = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                d["computed_age_seconds"] = int(age)
                return d
            except Exception:
                pass

    payload = {"signal": "unknown", "reason": "Data unavailable", "as_of": ""}
    try:
        # NSE's React API: returns array of objects with category/buyValue/sellValue/netValue
        sess = nse_quote._get_session()
        r = sess.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={**nse_quote.HEADERS, "Referer": "https://www.nseindia.com/reports/fii-dii"},
            timeout=10,
        )
        if r.status_code == 200:
            arr = r.json()
            fii = next((x for x in arr if "FII" in (x.get("category") or "") or "FPI" in (x.get("category") or "")), None)
            dii = next((x for x in arr if "DII" in (x.get("category") or "")), None)
            fii_net = float((fii or {}).get("netValue") or 0)
            dii_net = float((dii or {}).get("netValue") or 0)
            as_of = (fii or dii or {}).get("date") or ""

            # Heuristic: ₹2000cr daily net is meaningful; either layer can dominate
            if fii_net >= 2000:
                signal, reason = "tailwind", f"FII net buying ₹{fii_net:,.0f} cr — strong inflow"
            elif fii_net <= -2000 and dii_net < 1000:
                signal, reason = "headwind", f"FII net selling ₹{abs(fii_net):,.0f} cr without DII support"
            elif fii_net <= -2000:
                signal, reason = "neutral", f"FII selling ₹{abs(fii_net):,.0f} cr but DII absorbing ₹{dii_net:,.0f} cr"
            elif dii_net >= 2000 and fii_net > -500:
                signal, reason = "tailwind", f"DII net buying ₹{dii_net:,.0f} cr"
            else:
                signal = "neutral"
                reason = f"FII ₹{fii_net:+,.0f} cr · DII ₹{dii_net:+,.0f} cr (within normal range)"

            payload = {
                "signal": signal,
                "reason": reason,
                "fii_net_cr": round(fii_net, 0),
                "dii_net_cr": round(dii_net, 0),
                "as_of": as_of,
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            }
    except Exception as e:
        payload["reason"] = f"Fetch failed: {e}"

    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    return payload
