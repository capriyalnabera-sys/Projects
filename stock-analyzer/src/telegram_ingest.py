"""Read messages from the user's existing Telegram research groups and extract
stock-related signals (ticker mentions, target prices, sentiment).

Read-only. Uses the user's own account via Telethon. Session file stays local.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat


TICKER_PATTERN = re.compile(r"\b([A-Z]{3,15})\b")
TARGET_PATTERN = re.compile(
    r"(?:target|TGT|tgt|TP|target price|tar)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([0-9]{2,6}(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
STOP_PATTERN = re.compile(
    r"(?:SL|stop\s*loss|sl)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([0-9]{2,6}(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

POSITIVE = {
    "buy", "accumulate", "bullish", "long", "breakout", "upside", "target",
    "rally", "strong", "outperform", "upgrade", "multibagger",
}
NEGATIVE = {
    "sell", "short", "bearish", "downside", "weak", "downgrade", "exit",
    "stoploss", "sl hit", "avoid", "underperform", "stuck", "risky",
}

NOISE_TICKERS = {
    # Action / status
    "BUY", "SELL", "HOLD", "TGT", "SL", "CMP", "ENTRY", "EXIT", "STOP",
    "LOSS", "TARGET", "BOOK", "BOOKED", "TRAIL", "TRAILING", "ADD", "AVG",
    # Indices and exchanges
    "NSE", "BSE", "MCX", "NCDEX", "NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY",
    "MIDCAP", "SMALLCAP", "ETF", "REIT", "INVIT",
    # Currency / pricing
    "INR", "RS", "USD", "EUR", "GBP", "JPY", "CMP",
    # Indicators / metrics
    "RSI", "MACD", "SMA", "EMA", "BB", "ADX", "ATR", "VWAP", "OBV",
    "EPS", "ROE", "ROCE", "ROA", "PE", "PB", "PEG", "CE", "PAT",
    "QOQ", "YOY", "MOM", "CAGR", "FY", "QFY", "FCF", "EBITDA", "EBIT",
    "PBT", "MTM", "OI", "GTT", "STT",
    # Time / date
    "AM", "PM", "EOD", "IST", "GMT", "UTC", "TODAY", "TMRW", "YDAY",
    # Generic
    "INDIA", "STOCK", "STOCKS", "EQUITY", "EQUITIES", "MARKET", "MARKETS",
    "TRADE", "TRADING", "INVEST", "INVESTING", "INVESTOR", "RESEARCH",
    "PRICE", "PRICES", "CHART", "VOLUME", "BREAKOUT", "BREAKDOWN",
    "SUPPORT", "RESISTANCE", "TREND", "RALLY", "CRASH", "GAP",
    "CALL", "PUT", "FUT", "FUTURES", "OPTION", "OPTIONS", "FNO",
    "INTRADAY", "BTST", "STBT", "POSITIONAL", "SWING", "DELIVERY",
    "PROFIT", "LOSS", "BOOK", "PARTIAL", "FULL",
    # Common acronyms
    "FII", "DII", "HNI", "QIP", "IPO", "FPO", "OFS", "RBI", "SEBI",
    "GDP", "CPI", "WPI", "GST", "ITC",  # ITC is also a ticker but very common context word
    "ATH", "ATL", "ALL", "ANY", "BO", "SH", "TH", "ND", "ST", "RD",
    # Bigrams that look like tickers
    "GOOD", "GREAT", "STRONG", "WEAK", "BAD", "SAFE", "RISKY", "BIG",
    "TOP", "BEST", "WORST", "NEW", "OLD", "FAST", "SLOW", "REAL",
    "NEWS", "ALERT", "BREAKING", "UPDATE", "FLASH",
}


@dataclass
class Mention:
    ticker: str
    text: str
    sentiment: float
    target: Optional[float]
    stop: Optional[float]
    when: datetime
    group: str
    msg_id: int = 0
    channel_id: int = 0
    has_pdf: bool = False


@dataclass
class TickerAggregate:
    ticker: str
    mentions: list[Mention] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.mentions)

    @property
    def avg_sentiment(self) -> float:
        if not self.mentions:
            return 0.0
        return sum(m.sentiment for m in self.mentions) / len(self.mentions)

    @property
    def quoted_targets(self) -> list[float]:
        return [m.target for m in self.mentions if m.target is not None]


def _sentiment(text: str) -> float:
    low = text.lower()
    pos = sum(1 for w in POSITIVE if w in low)
    neg = sum(1 for w in NEGATIVE if w in low)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / max(pos + neg, 1)


def _extract_tickers(
    text: str,
    allowlist: Optional[set[str]] = None,
    name_aliases: Optional[dict[str, str]] = None,
) -> set[str]:
    candidates = set(TICKER_PATTERN.findall(text)) - NOISE_TICKERS
    if name_aliases:
        low = text.lower()
        for phrase, ticker in name_aliases.items():
            if phrase in low:
                candidates.add(ticker)
    if allowlist is not None:
        return {t for t in candidates if t in allowlist}
    return candidates


def _parse_message(
    msg_text: str,
    when: datetime,
    group: str,
    allowlist: Optional[set[str]] = None,
    name_aliases: Optional[dict[str, str]] = None,
    msg_id: int = 0,
    channel_id: int = 0,
    has_pdf: bool = False,
) -> list[Mention]:
    if not msg_text:
        return []
    tickers = _extract_tickers(msg_text, allowlist, name_aliases)
    if not tickers:
        return []
    sent = _sentiment(msg_text)
    target_m = TARGET_PATTERN.search(msg_text)
    stop_m = STOP_PATTERN.search(msg_text)
    target = float(target_m.group(1)) if target_m else None
    stop = float(stop_m.group(1)) if stop_m else None
    return [
        Mention(ticker=t, text=msg_text[:300], sentiment=sent, target=target, stop=stop,
                when=when, group=group, msg_id=msg_id, channel_id=channel_id, has_pdf=has_pdf)
        for t in tickers
    ]


async def _list_dialogs(client: TelegramClient) -> list[tuple[int, str]]:
    out = []
    async for d in client.iter_dialogs():
        if isinstance(d.entity, (Channel, Chat)):
            out.append((d.id, d.name or str(d.id)))
    return out


async def _scan(
    client: TelegramClient,
    group_filter: Optional[Iterable[str]],
    days: int,
    allowlist: Optional[set[str]],
    name_aliases: Optional[dict[str, str]] = None,
    pdf_cache_dir: Optional[Path] = None,
    progress: Optional[callable] = None,
    download_new: bool = True,
) -> dict[str, TickerAggregate]:
    from .telegram_pdfs import ensure_downloaded, cached_text  # local to avoid circular at import time

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    aggregates: dict[str, TickerAggregate] = {}

    dialogs = await _list_dialogs(client)
    if group_filter:
        wanted = {g.lower() for g in group_filter}
        dialogs = [d for d in dialogs if d[1].lower() in wanted]

    pdfs_seen = pdfs_used = msgs_seen = 0

    for _id, name in dialogs:
        channel_dir = None
        if pdf_cache_dir is not None:
            channel_dir = pdf_cache_dir / f"{abs(_id)}"

        async for msg in client.iter_messages(_id, offset_date=None, limit=5000):
            if msg.date < cutoff:
                break
            msgs_seen += 1
            text = msg.message or ""
            pdf_text = ""

            if channel_dir is not None:
                from .telegram_pdfs import _pdf_filename  # noqa
                if _pdf_filename(msg):
                    pdfs_seen += 1
                    pdf_path = await ensure_downloaded(client, msg, channel_dir, download_new=download_new)
                    if pdf_path is not None:
                        pdfs_used += 1
                        pdf_text = cached_text(pdf_path)
                    if progress and pdfs_seen % 50 == 0:
                        progress(f"  scanned {msgs_seen} msgs, used {pdfs_used}/{pdfs_seen} PDFs")

            combined = (text + "\n\n" + pdf_text) if pdf_text else text
            mentions = _parse_message(
                combined, msg.date, name, allowlist, name_aliases,
                msg_id=getattr(msg, "id", 0),
                channel_id=abs(_id),
                has_pdf=bool(pdf_text),
            )
            for m in mentions:
                agg = aggregates.get(m.ticker)
                if agg is None:
                    agg = TickerAggregate(ticker=m.ticker)
                    aggregates[m.ticker] = agg
                agg.mentions.append(m)

    if progress:
        progress(f"  done: {msgs_seen} msgs, {pdfs_used}/{pdfs_seen} PDFs scanned")
    return aggregates


def scan_groups(
    api_id: int,
    api_hash: str,
    session_name: str,
    group_filter: Optional[Iterable[str]] = None,
    days: int = 7,
    tickers_of_interest: Optional[Iterable[str]] = None,
    name_aliases: Optional[dict[str, str]] = None,
    pdf_cache_dir: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
    download_new: bool = True,
) -> dict[str, TickerAggregate]:
    """Synchronous wrapper. First call prompts for phone + login code interactively.
    download_new=False reads only already-cached PDFs (fast path for the dashboard)."""
    allow = {t.upper() for t in tickers_of_interest} if tickers_of_interest else None

    async def _run():
        async with TelegramClient(session_name, api_id, api_hash) as client:
            return await _scan(
                client, group_filter, days, allow, name_aliases, pdf_cache_dir, progress,
                download_new=download_new,
            )

    return asyncio.run(_run())


def list_groups(api_id: int, api_hash: str, session_name: str) -> list[str]:
    async def _run():
        async with TelegramClient(session_name, api_id, api_hash) as client:
            return [name for _, name in await _list_dialogs(client)]

    return asyncio.run(_run())
