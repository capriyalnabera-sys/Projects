"""One-off probe: for given group names, count messages in last 7d and last 30d."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat


async def main(names: list[str], cfg_path: Path):
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    tg = cfg["telegram"]
    wanted = {n.lower() for n in names}

    async with TelegramClient(tg["session_name"], int(tg["api_id"]), tg["api_hash"]) as client:
        matched: list[tuple[int, str]] = []
        async for d in client.iter_dialogs():
            if isinstance(d.entity, (Channel, Chat)):
                nm = d.name or ""
                if nm.lower() in wanted:
                    matched.append((d.id, nm))

        if not matched:
            print("No groups matched.")
            return

        cutoff_7 = datetime.now(timezone.utc) - timedelta(days=7)
        cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)

        print(f"{'Group':<55} {'7d':>6} {'30d':>6}  {'Last msg':>20}")
        print("-" * 95)
        for _id, nm in matched:
            n7 = n30 = 0
            last_seen = None
            async for msg in client.iter_messages(_id, limit=2000):
                if last_seen is None:
                    last_seen = msg.date
                if msg.date >= cutoff_7:
                    n7 += 1
                if msg.date >= cutoff_30:
                    n30 += 1
                else:
                    break
            last_str = last_seen.astimezone().strftime("%Y-%m-%d %H:%M") if last_seen else "—"
            print(f"{nm[:55]:<55} {n7:>6} {n30:>6}  {last_str:>20}  (id={_id})")


if __name__ == "__main__":
    cfg = Path("config.yaml")
    names = [
        "Equity Research Reports",
        "Financial News and Knowledge",
        "Financial Newspapers (Business Standard, Mint, WallStreel Journal)",
    ]
    asyncio.run(main(names, cfg))
