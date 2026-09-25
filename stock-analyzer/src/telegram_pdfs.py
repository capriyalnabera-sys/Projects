"""Download PDF attachments from Telegram messages and extract text.

Cached on disk by message id under cache_dir/<msg_id>.pdf and .txt so that
re-running the analyzer is fast and doesn't re-download.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    DocumentAttributeFilename,
    MessageMediaDocument,
)


def _pdf_filename(msg) -> Optional[str]:
    media = getattr(msg, "media", None)
    if not isinstance(media, MessageMediaDocument):
        return None
    doc = media.document
    if doc is None:
        return None
    mime = (getattr(doc, "mime_type", "") or "").lower()
    fname: Optional[str] = None
    for attr in (doc.attributes or []):
        if isinstance(attr, DocumentAttributeFilename):
            fname = attr.file_name
            break
    if "pdf" in mime:
        return fname or f"{msg.id}.pdf"
    if fname and fname.lower().endswith(".pdf"):
        return fname
    return None


async def ensure_downloaded(
    client: TelegramClient, msg, cache_dir: Path, download_new: bool = True
) -> Optional[Path]:
    """If download_new=False, return path only if PDF is already cached (skip network).
    Used by the dashboard batch path so it never blocks on Telegram downloads —
    only the dedicated 'warm cache' run downloads new PDFs."""
    if _pdf_filename(msg) is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{msg.id}.pdf"
    if out.exists() and out.stat().st_size > 0:
        return out
    if not download_new:
        return None
    for attempt in range(2):
        try:
            await client.download_media(msg, file=str(out))
            break
        except FloodWaitError as e:
            await asyncio.sleep(min(e.seconds + 1, 30))
        except Exception:
            return None
    return out if (out.exists() and out.stat().st_size > 0) else None


def extract_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        parts: list[str] = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(t)
        return "\n".join(parts)
    except Exception:
        return ""


def cached_text(pdf_path: Path) -> str:
    """Return cached extracted text if present; else extract, write cache, return."""
    txt_path = pdf_path.with_suffix(".txt")
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    text = extract_text(pdf_path)
    try:
        txt_path.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return text
