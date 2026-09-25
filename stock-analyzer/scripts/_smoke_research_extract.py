"""One-off smoke test for research_extract on real cached HFCL filings.
Run via:  .venv\\Scripts\\python.exe scripts\\_smoke_research_extract.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import research_extract  # noqa: E402

samples = [
    ROOT / "data/cache/nse_filings/HFCL/AHMED_30052025173945_HFCL_STX_Investor_Call_Transcript_30052025.txt",
    ROOT / "data/cache/nse_filings/HFCL/AHMED_30042026140823_HFCL_STX_IP_30042026.txt",
]

for p in samples:
    if not p.exists():
        print(f"MISSING {p}")
        continue
    txt = p.read_text(encoding="utf-8", errors="ignore")
    r = research_extract.analyze(
        txt,
        subject="Analysts/Institutional Investor Meet/Con. Call Updates",
        ticker="HFCL",
    )
    print("=" * 78)
    print(p.name, "len=", len(txt))
    print("doc_type=", r["doc_type"], " sentiment=", r["sentiment"],
          " highlights=", r["highlight_count"])
    print("\nSUMMARY:")
    print(" ", r["summary"][:560])
    print(f"\nKEY METRICS ({len(r['key_metrics'])}):")
    for m in r["key_metrics"][:6]:
        print(f"  - {m['label']:11s} {m['value']:14s} | {m['sentence'][:130]}")
    print(f"\nGUIDANCE ({len(r['guidance'])}):")
    for g in r["guidance"][:5]:
        print(f"  - [{g['horizon']:18s}] {g['value']:14s} | {g['sentence'][:140]}")
    print(f"\nCAPEX ({len(r['capex_strategic'])}):")
    for c in r["capex_strategic"][:3]:
        print(f"  - {c[:170]}")
    print(f"\nRISKS ({len(r['risks'])}):")
    for x in r["risks"][:3]:
        print(f"  - {x[:170]}")
    print(f"\nPOSITIVES ({len(r['positives'])}):")
    for x in r["positives"][:3]:
        print(f"  - {x[:170]}")
    print(f"\nQUOTED TARGETS ({len(r['quoted_targets'])}):")
    for t in r["quoted_targets"][:3]:
        print(f"  - ₹{t['price']} {t['horizon']} | {t['sentence'][:140]}")
    print()
