"""Diagnostic: scan the active group, show top tickers detected and check for
specific substrings (full company names) for the three test stocks."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

from src.telegram_ingest import _extract_tickers


async def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    tg = cfg["telegram"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with TelegramClient(tg["session_name"], int(tg["api_id"]), tg["api_hash"]) as client:
        target_id = None
        async for d in client.iter_dialogs():
            if isinstance(d.entity, (Channel, Chat)) and (d.name or "").lower() == "equity research reports":
                # Only the live one — we know it has recent messages
                if d.id == -1001165317194:
                    target_id = d.id
                    break

        if target_id is None:
            print("Active group not found.")
            return

        ticker_counts: Counter[str] = Counter()
        substring_hits = {"borosil": 0, "borenew": 0, "ugro": 0, "hfcl": 0}
        sample_with_ticker = None
        sample_no_ticker = None
        total = 0
        with_text = 0

        async for msg in client.iter_messages(target_id, limit=2000):
            if msg.date < cutoff:
                break
            total += 1
            text = msg.message or ""
            if not text:
                continue
            with_text += 1
            tickers = _extract_tickers(text)
            ticker_counts.update(tickers)
            low = text.lower()
            for k in substring_hits:
                if k in low:
                    substring_hits[k] += 1
            if tickers and sample_with_ticker is None:
                sample_with_ticker = text[:400]
            elif not tickers and sample_no_ticker is None and len(text) > 30:
                sample_no_ticker = text[:400]

        print(f"Total messages last 7d: {total}  |  with text: {with_text}")
        print(f"\nTop 25 ALLCAPS tokens detected (regex + noise filter):")
        for tk, n in ticker_counts.most_common(25):
            print(f"  {tk:<15} {n}")
        print(f"\nFull-name substring hits (case-insensitive):")
        for k, n in substring_hits.items():
            print(f"  '{k}': {n}")
        if sample_with_ticker:
            print(f"\n--- Sample message WITH ticker hit ---\n{sample_with_ticker}\n")
        if sample_no_ticker:
            print(f"--- Sample message WITHOUT ticker hit ---\n{sample_no_ticker}\n")


if __name__ == "__main__":
    asyncio.run(main())
