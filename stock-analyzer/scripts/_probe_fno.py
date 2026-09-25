"""Probe v2: NSE's NEWER F&O endpoints (option-chain-v3, underlying-information,
quote-derivative) with option-chain page warmup."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import nse_quote  # noqa: E402

s = nse_quote._get_session()
OC_HEADERS = {**nse_quote.HEADERS, "Referer": "https://www.nseindia.com/option-chain"}

# Warm the option-chain page itself (sets additional cookies some APIs demand)
try:
    r = s.get("https://www.nseindia.com/option-chain", headers=nse_quote.HEADERS, timeout=15)
    print("warmup /option-chain:", r.status_code)
except Exception as e:
    print("warmup ERR", e)

# 1. Universe of F&O underlyings
print("\n=== underlying-information ===")
try:
    r = s.get("https://www.nseindia.com/api/underlying-information", headers=OC_HEADERS, timeout=15)
    print("HTTP", r.status_code)
    if r.status_code == 200:
        d = r.json()
        data = d.get("data", d)
        idx = data.get("IndexList") or []
        und = data.get("UnderlyingList") or []
        print("indices:", len(idx), "| stocks:", len(und))
        if idx: print("  idx sample:", idx[:3])
        if und: print("  stock sample:", und[:3])
except Exception as e:
    print("ERR", e)

# 2. Expiry list for a symbol
print("\n=== option-chain-contract-info NIFTY ===")
try:
    r = s.get("https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY",
              headers=OC_HEADERS, timeout=15)
    print("HTTP", r.status_code)
    if r.status_code == 200:
        print(json.dumps(r.json(), indent=1)[:500])
except Exception as e:
    print("ERR", e)

# 3. v3 chain (indices)
print("\n=== option-chain-v3 NIFTY ===")
try:
    # try without expiry first; then with one if we learn the format
    r = s.get("https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY",
              headers=OC_HEADERS, timeout=15)
    print("no-expiry HTTP", r.status_code, "len", len(r.text))
    if r.status_code == 200 and r.text.strip():
        d = r.json()
        rec = d.get("records", d)
        print(" keys:", list(d.keys())[:8])
        data = rec.get("data") if isinstance(rec, dict) else None
        if data:
            print(" strike rows:", len(data))
            print(" sample keys:", list(data[0].keys()))
except Exception as e:
    print("ERR", e)

# 4. quote-derivative for lot size
print("\n=== quote-derivative RELIANCE ===")
try:
    r = s.get("https://www.nseindia.com/api/quote-derivative?symbol=RELIANCE",
              headers=OC_HEADERS, timeout=15)
    print("HTTP", r.status_code)
    if r.status_code == 200:
        d = r.json()
        stocks = d.get("stocks") or []
        print("contracts:", len(stocks))
        if stocks:
            meta = stocks[0].get("metadata", {})
            mdob = stocks[0].get("marketDeptOrderBook", {})
            print(" sample metadata:", {k: meta.get(k) for k in ("instrumentType","expiryDate","optionType","strikePrice")})
            print(" lot (marketLot):", d.get("info", {}).get("marketLot") or mdob.get("marketLot") or meta.get("marketLot"))
            print(" info keys:", list((d.get("info") or {}).keys()))
except Exception as e:
    print("ERR", e)
