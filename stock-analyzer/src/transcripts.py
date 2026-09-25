"""Extract stock mentions from meeting / call transcripts.

Drop transcript files into ``data/transcripts/`` and the tool will index them.
Supported formats:
  - ``.txt`` — plain text (whatever pasted from Otter, Notion, manual notes)
  - ``.vtt`` — WebVTT subtitles (Zoom / Google Meet exports)
  - ``.json`` — Fireflies / Otter JSON exports (auto-detects 'sentences' / 'transcript' shapes)
  - ``.md``  — markdown notes

For each file we extract every NSE-ticker-shaped token + any aliased company
names (e.g. "borosil renewables" → BORORENEW), pull the surrounding sentence
as context, and bag-of-words sentiment-score the snippet.

Stays informational only — does NOT feed verdict scoring. Surfaced as a
research card on the stock detail page alongside Telegram research and news.

Cached per-ticker as JSON in data/cache/transcripts/<TICKER>.json with a
12-hour TTL; the source files themselves can be edited freely.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


TRANSCRIPTS_DIR = Path("data/transcripts")
CACHE_DIR       = Path("data/cache/transcripts")
CACHE_TTL_SECONDS = 12 * 60 * 60  # transcripts don't change often, scan lazily


def _extract_text_from_file(p: Path) -> tuple[str, str, datetime]:
    """Return (text, title, mtime). Empty text on unsupported types or read failure."""
    suffix = p.suffix.lower()
    text = ""
    try:
        if suffix in (".txt", ".md"):
            text = p.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".vtt":
            # Strip VTT cue numbers, timestamps, and header line.
            raw = p.read_text(encoding="utf-8", errors="ignore")
            kept: list[str] = []
            for line in raw.splitlines():
                s = line.strip()
                if not s or s == "WEBVTT" or "-->" in s or s.isdigit():
                    continue
                if s.startswith("NOTE"):
                    continue
                kept.append(s)
            text = " ".join(kept)
        elif suffix == ".json":
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                d = None
            if isinstance(d, list):
                text = " ".join(_speaker_text(x) for x in d)
            elif isinstance(d, dict):
                # Fireflies: {"sentences": [{"text": ...}, ...]}
                if isinstance(d.get("sentences"), list):
                    text = " ".join(_speaker_text(x) for x in d["sentences"])
                elif isinstance(d.get("transcript"), list):
                    text = " ".join(_speaker_text(x) for x in d["transcript"])
                elif "text" in d:
                    text = str(d["text"])
    except Exception:
        text = ""
    title = p.stem.replace("_", " ").replace("-", " ")
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return text, title, mtime


def _speaker_text(x) -> str:
    """Extract the text field from a transcript entry shape, ignoring speaker."""
    if isinstance(x, dict):
        return str(x.get("text") or x.get("transcript") or "")
    return str(x)


def _split_sentences(text: str) -> list[str]:
    # Simple sentence splitter — fine for our snippet extraction needs
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 8]


def _list_transcript_files() -> list[Path]:
    if not TRANSCRIPTS_DIR.exists():
        return []
    out: list[Path] = []
    for ext in ("*.txt", "*.md", "*.vtt", "*.json"):
        out.extend(TRANSCRIPTS_DIR.rglob(ext))
    return sorted(out)


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines so each conversational block (e.g. one ticker's
    write-up in a morning call) becomes a single context window."""
    if not text:
        return []
    # treat 2+ newlines as a paragraph break; otherwise normalize single \n to space
    parts = re.split(r"\n\s*\n+", text)
    return [p.strip() for p in parts if p.strip()]


def scan_all(
    name_aliases: Optional[dict[str, str]] = None,
    allowlist: Optional[set[str]] = None,
) -> dict[str, list[dict]]:
    """Walk transcripts dir, extract per-ticker mention objects.

    For each paragraph that mentions a ticker, the per-ticker block contains
    the tight sentence as ``snippet`` AND the whole paragraph as
    ``paragraph`` so downstream analysis (target, guidance, capex) can use
    the wider context — a sentence like "Target ₹150 over 12 months" doesn't
    have the ticker in it, but lives in the same paragraph as the header.
    """
    from .telegram_ingest import TICKER_PATTERN, NOISE_TICKERS, _sentiment

    out: dict[str, list[dict]] = defaultdict(list)
    files = _list_transcript_files()
    for p in files:
        text, title, mtime = _extract_text_from_file(p)
        if not text:
            continue

        for paragraph in _split_paragraphs(text):
            para_low = paragraph.lower()
            # Find all tickers in this paragraph
            tickers_in_para: set[str] = set(
                TICKER_PATTERN.findall(paragraph)
            ) - NOISE_TICKERS
            if name_aliases:
                for phrase, tk in name_aliases.items():
                    if phrase in para_low:
                        tickers_in_para.add(tk)
            if allowlist is not None:
                tickers_in_para = {t for t in tickers_in_para if t in allowlist}
            if not tickers_in_para:
                continue

            sentences = _split_sentences(paragraph)
            # Pick the tightest sentence per ticker as the display snippet
            for tk in tickers_in_para:
                snippet = ""
                for sentence in sentences:
                    if tk in sentence or (
                        name_aliases
                        and any(
                            phrase in sentence.lower() and tk == alias_tk
                            for phrase, alias_tk in name_aliases.items()
                        )
                    ):
                        snippet = sentence
                        break
                if not snippet and sentences:
                    snippet = sentences[0]
                sent = round(_sentiment(paragraph), 2)
                out[tk].append({
                    "title": title,
                    "file": p.name,
                    "when": mtime.isoformat(timespec="minutes"),
                    "snippet": snippet[:400],
                    "paragraph": paragraph[:1600],
                    "sentiment": sent,
                })

    return dict(out)


def fetch_for_ticker(
    ticker: str,
    name_aliases: Optional[dict[str, str]] = None,
    force: bool = False,
) -> dict:
    """Return cached or freshly-scanned mentions for one ticker.
    Shape: {available, mentions_count, avg_sentiment, mentions: [...]}"""
    tk = ticker.upper()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{tk}.json"
    if not force and cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SECONDS:
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Re-scan everything (cheap — transcripts are local files)
    by_ticker = scan_all(name_aliases=name_aliases, allowlist={tk})
    mentions = by_ticker.get(tk, [])
    # Newest first
    mentions.sort(key=lambda m: m["when"], reverse=True)
    avg_sent = round(sum(m["sentiment"] for m in mentions) / len(mentions), 2) if mentions else 0.0

    # Run the structured analyzer over all snippets that mention this ticker so the
    # UI can surface what the transcripts ACTUALLY said about it (target, guidance,
    # capex, risks) instead of just a list of raw snippets.
    analysis: dict = {}
    if mentions:
        try:
            from . import research_extract
            # Prefer the wider paragraph-level context for analysis (carries
            # target prices, capex notes etc. that a sentence-level snippet
            # would lose). Fall back to snippet when no paragraph is stored.
            seen_para: set[str] = set()
            ctx_parts: list[str] = []
            for m in mentions:
                p = (m.get("paragraph") or m.get("snippet") or "").strip()
                if not p or p in seen_para:
                    continue
                seen_para.add(p)
                ctx_parts.append(p)
            joined = "\n\n".join(ctx_parts)
            analysis = research_extract.analyze(joined, subject="transcript", ticker=tk)
        except Exception:
            analysis = {}

    payload = {
        "available": True,
        "mentions_count": len(mentions),
        "avg_sentiment": avg_sent,
        "transcript_files_scanned": len(_list_transcript_files()),
        "mentions": mentions[:25],
        "analysis": analysis,
    }
    try:
        cache_file.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass
    return payload


def invalidate_cache() -> int:
    """Wipe cached results — call this if user adds new transcript files."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except Exception:
            pass
    return n
