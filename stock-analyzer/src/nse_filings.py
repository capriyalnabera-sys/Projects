"""NSE corporate filings — pull earnings call transcripts, concall recordings,
investor presentations directly from each company's NSE disclosure feed.

This is the authoritative source: companies file these as PDFs through NSE's
corporate disclosure system. We download, cache, and extract text so the
user gets the source material on the stock detail page.

Endpoint: https://www.nseindia.com/api/corporate-announcements?symbol=<SYM>
needs session cookies (handled by nse_quote._get_session()).

Cached two-layer:
  - filings list JSON per ticker (1h TTL — fresh enough)
  - downloaded PDFs + extracted text per attachment (forever — they don't change)
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from . import nse_quote


FILINGS_CACHE_DIR = Path("data/cache/nse_filings")
FILINGS_LIST_TTL_SECONDS = 60 * 60  # 1 hour
# Enriched payload (list + analysis) — same TTL so when new filings appear
# in the list, the enriched view rebuilds alongside it. PDFs themselves never
# change once published, so .txt + .analysis siblings stay valid forever.
FILINGS_ENRICHED_TTL_SECONDS = 60 * 60

# Subject-line keywords that mark a filing as "transcript-grade" — analyst calls,
# investor presentations, concall recordings. Skip routine board notices.
RELEVANT_KEYWORDS = (
    "transcript", "concall", "conference call", "earnings call",
    "investor presentation", "investor meet", "analyst meet",
    "analyst call", "audio recording", "earnings conference",
)


def _is_relevant(subject: str) -> bool:
    if not subject:
        return False
    low = subject.lower()
    return any(k in low for k in RELEVANT_KEYWORDS)


def _ticker_cache_dir(ticker: str) -> Path:
    d = FILINGS_CACHE_DIR / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _list_path(ticker: str) -> Path:
    return _ticker_cache_dir(ticker) / "_list.json"


def _safe_attachment_name(url: str, msg_id: str) -> str:
    """Map an attachment URL to a stable filename for local caching."""
    # Try to grab the trailing filename; fall back to msg_id
    m = re.search(r"/([^/?#]+\.pdf)(?:$|[?#])", url, re.IGNORECASE)
    if m:
        return m.group(1)
    return f"{msg_id}.pdf"


def fetch_filings(ticker: str, days_back: int = 365) -> dict:
    """Return relevant filings for a ticker. Cached as list JSON; PDFs
    downloaded on-demand by attachment view.
    Shape: {available, count, items: [{date, subject, desc, attachment_url, file}]}
    """
    tk = ticker.upper()
    list_file = _list_path(tk)
    if list_file.exists() and (time.time() - list_file.stat().st_mtime) < FILINGS_LIST_TTL_SECONDS:
        try:
            return json.loads(list_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    s = nse_quote._get_session()
    today = datetime.now().date()
    from_date = (today - timedelta(days=days_back)).strftime("%d-%m-%Y")
    to_date = today.strftime("%d-%m-%Y")
    url = "https://www.nseindia.com/api/corporate-announcements"
    params = {
        "index": "equities",
        "symbol": tk,
        "from_date": from_date,
        "to_date": to_date,
    }
    headers = {
        **nse_quote.HEADERS,
        "Referer": f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={tk}",
    }
    try:
        r = s.get(url, params=params, headers=headers, timeout=12)
        if r.status_code == 403:
            # Re-warm session and retry once
            nse_quote._session_warmed_at = 0
            s = nse_quote._get_session()
            r = s.get(url, params=params, headers=headers, timeout=12)
        if r.status_code != 200:
            return {"available": False, "reason": f"NSE returned HTTP {r.status_code}", "count": 0, "items": []}
        data = r.json()
    except Exception as e:
        return {"available": False, "reason": str(e), "count": 0, "items": []}

    if not isinstance(data, list):
        return {"available": False, "reason": "Unexpected response shape", "count": 0, "items": []}

    items: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        subject = entry.get("desc") or entry.get("subject") or ""
        if not _is_relevant(subject):
            continue
        attachment = (entry.get("attchmntFile") or "").strip()
        an_dt = entry.get("an_dt") or entry.get("sort_date") or entry.get("date") or ""
        items.append({
            # NSE returns dates like "29-May-2025 21:34:23" or "2025-05-29T..." —
            # try to land on the first 11 chars for D-Mon-YYYY, or 10 chars for ISO.
            "date": ((an_dt[:11] if (len(an_dt) > 4 and an_dt[2] == "-") else an_dt[:10]) if an_dt else "").strip(),
            "datetime": an_dt,
            "subject": subject.strip(),
            "long_desc": (entry.get("attchmntText") or "").strip()[:300],
            "attachment_url": attachment,
            "file": _safe_attachment_name(attachment, str(entry.get("id") or "")) if attachment else None,
        })

    # Newest first
    items.sort(key=lambda x: x["datetime"], reverse=True)
    payload = {
        "available": True,
        "ticker": tk,
        "count": len(items),
        "items": items[:30],   # cap to most recent 30 to keep page light
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        list_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass
    return payload


def download_filing(ticker: str, attachment_url: str, filename: str) -> Optional[Path]:
    """Download a filing PDF to local cache. Idempotent — skips if already on disk."""
    if not attachment_url or not filename:
        return None
    out = _ticker_cache_dir(ticker) / filename
    if out.exists() and out.stat().st_size > 0:
        return out
    s = nse_quote._get_session()
    try:
        r = s.get(attachment_url, headers={**nse_quote.HEADERS, "Referer": "https://www.nseindia.com/"}, timeout=30, stream=True)
        if r.status_code != 200:
            return None
        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
        if out.stat().st_size == 0:
            out.unlink(missing_ok=True)
            return None
        return out
    except Exception:
        return None


def extract_text(pdf_path: Path) -> str:
    """Extract text from a cached PDF. Caches the result as a .txt sibling
    so subsequent reads skip pypdf entirely."""
    if not pdf_path or not pdf_path.exists():
        return ""
    txt_path = pdf_path.with_suffix(".txt")
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
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
        text = "\n".join(parts)
        try:
            txt_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return text
    except Exception:
        return ""


def _analysis_cache_path(pdf_path: Path) -> Path:
    """Sibling .analysis.json next to each cached PDF — persisting the
    analyzer output so repeat visits skip the regex passes entirely."""
    return pdf_path.with_suffix(".analysis.json")


def _enrich_one(ticker: str, item: dict) -> dict:
    """Download + extract + analyze a single filing item, caching every
    stage. Returns the enriched item dict (safe to call concurrently)."""
    from . import research_extract

    out = dict(item)
    out["text_excerpt"] = ""
    out["local_path"] = None
    out["analysis"] = {}
    if not (item.get("attachment_url") and item.get("file")):
        return out
    pdf = download_filing(ticker, item["attachment_url"], item["file"])
    if not pdf:
        return out
    out["local_path"] = str(pdf.relative_to(FILINGS_CACHE_DIR.parent.parent))

    # Per-filing analysis cache — survives across page loads and never
    # invalidates (a published PDF is immutable).
    a_path = _analysis_cache_path(pdf)
    if a_path.exists():
        try:
            cached = json.loads(a_path.read_text(encoding="utf-8"))
            out["text_excerpt"] = cached.get("text_excerpt", "")
            out["analysis"] = cached.get("analysis", {})
            return out
        except Exception:
            pass  # fall through to re-extract

    text = extract_text(pdf)
    if not text:
        return out
    out["text_excerpt"] = text[:600].strip()
    out["analysis"] = research_extract.analyze(
        text, subject=item.get("subject", ""), ticker=ticker
    )
    try:
        a_path.write_text(
            json.dumps({"text_excerpt": out["text_excerpt"], "analysis": out["analysis"]}),
            encoding="utf-8",
        )
    except Exception:
        pass
    return out


def get_filings_with_text(ticker: str, max_extract: int = 3) -> dict:
    """Filings list + extracted text + structured analysis for the top N.

    Three-layer cache so the hot path is sub-100ms:
      1. ``_enriched.json`` per ticker — full payload incl. analysis (TTL 1h)
      2. ``<pdf>.analysis.json`` per filing — persisted analyzer output
      3. ``<pdf>.txt`` per filing — pypdf-extracted text

    Cold path parallelises PDF download + extract + analyze across the top-N
    items via a small thread pool, so the user waits on the slowest single
    NSE PDF download instead of the sum of three.
    """
    tk = ticker.upper()
    enriched_file = _ticker_cache_dir(tk) / "_enriched.json"

    # Hot path: fully-enriched cache fresh → instant return
    if (
        enriched_file.exists()
        and (time.time() - enriched_file.stat().st_mtime) < FILINGS_ENRICHED_TTL_SECONDS
    ):
        try:
            return json.loads(enriched_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    listing = fetch_filings(ticker)
    if not listing.get("available"):
        return listing
    items = listing.get("items") or []

    # Pick which items to enrich (top N most recent with attachments). The
    # rest stay un-analysed to keep the response light.
    to_enrich: list[dict] = []
    plain_tail: list[dict] = []
    for it in items:
        if len(to_enrich) < max_extract and it.get("attachment_url") and it.get("file"):
            to_enrich.append(it)
        else:
            plain = dict(it)
            plain["text_excerpt"] = ""
            plain["local_path"] = None
            plain["analysis"] = {}
            plain_tail.append(plain)

    # Parallel download + extract + analyze for the top N
    enriched_top: list[dict] = []
    if to_enrich:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(to_enrich))) as pool:
            futures = [pool.submit(_enrich_one, ticker, it) for it in to_enrich]
            # Preserve input order
            enriched_top = [f.result() for f in futures]

    enriched = enriched_top + plain_tail

    # Aggregate sentiment across analysed filings for the top-level tone badge
    agg_sentiment: list[float] = []
    agg_highlights = 0
    for it in enriched_top:
        a = it.get("analysis") or {}
        if a.get("highlight_count", 0) > 0:
            agg_sentiment.append(float(a.get("sentiment") or 0.0))
            agg_highlights += int(a.get("highlight_count") or 0)

    listing["items"] = enriched
    listing["aggregate"] = {
        "analysed_count": len(agg_sentiment),
        "avg_sentiment": (
            round(sum(agg_sentiment) / len(agg_sentiment), 2)
            if agg_sentiment else 0.0
        ),
        "total_highlights": agg_highlights,
    }

    # Persist the full enriched payload for the next visit
    try:
        enriched_file.write_text(json.dumps(listing), encoding="utf-8")
    except Exception:
        pass

    return listing
