"""Recent stock-wise news from Yahoo Finance (via yfinance) and MoneyControl.

Returns a normalized list of {title, publisher, url, published_at, summary, source}.
Cached per ticker as JSON in cache_dir with a TTL (news is time-sensitive,
default 30 min).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _cache_path(ticker: str, cache_dir: Path) -> Path:
    return cache_dir / f"{ticker.upper()}.json"


def _is_fresh(p: Path, ttl_minutes: int) -> bool:
    if not p.exists():
        return False
    return (time.time() - p.stat().st_mtime) < ttl_minutes * 60


def _to_iso(value) -> str:
    """Normalize various time formats to ISO string."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="minutes")
        except Exception:
            return ""
    if isinstance(value, str):
        return value
    return ""


def fetch_yahoo(yf_symbol: str, max_items: int = 10) -> list[dict]:
    """Pull news via yfinance Ticker.news. Handles both old flat format and new
    nested 'content' structure since yfinance changed the schema mid-2024."""
    try:
        import yfinance as yf
        items = yf.Ticker(yf_symbol).news or []
    except Exception:
        return []

    out: list[dict] = []
    for it in items[:max_items]:
        # Newer yfinance: {"content": {"title", "provider", "canonicalUrl", "pubDate", "summary"}, ...}
        # Older: flat {"title", "publisher", "link", "providerPublishTime", ...}
        content = it.get("content") if isinstance(it.get("content"), dict) else None
        title = (content or it).get("title") or it.get("title", "")
        if not title:
            continue
        if content:
            publisher = ((content.get("provider") or {}).get("displayName")) or ""
            url = ((content.get("canonicalUrl") or {}).get("url")
                   or (content.get("clickThroughUrl") or {}).get("url")
                   or "")
            published = content.get("pubDate") or content.get("displayTime")
            summary = content.get("summary") or ""
        else:
            publisher = it.get("publisher", "")
            url = it.get("link", "")
            published = it.get("providerPublishTime")
            summary = it.get("summary", "")
        if not url:
            continue
        out.append({
            "title": title.strip(),
            "publisher": (publisher or "Yahoo").strip(),
            "url": url,
            "published_at": _to_iso(published),
            "summary": (summary or "").strip()[:280],
            "source": "yahoo",
        })
    return out


def _slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def fetch_moneycontrol(company_name: str, max_items: int = 8) -> list[dict]:
    """Best-effort scrape of MoneyControl's tag/news page for the company.

    MoneyControl uses /news/tags/<slug>.html for many companies; otherwise we
    fall back to the search page. Quietly returns [] on any failure.
    """
    if not company_name:
        return []
    # Drop common corporate suffixes
    cleaned = re.sub(r"\b(limited|ltd\.?|industries|corporation|corp\.?|inc\.?|company|co\.?)\b",
                     "", company_name, flags=re.IGNORECASE).strip()
    slug = _slugify(cleaned)
    if not slug:
        return []

    out: list[dict] = []
    candidates = [
        f"https://www.moneycontrol.com/news/tags/{slug}.html",
        f"https://www.moneycontrol.com/news/tags/{slug.replace('-', '')}.html",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
        except Exception:
            continue
        if r.status_code != 200 or not r.text:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        # MoneyControl tag pages use <li class="clearfix"> with an <a> for headline
        # and a <span class="article_schedule"> for date.
        for li in soup.select("li.clearfix")[:max_items * 2]:
            a = li.find("a")
            if not a:
                continue
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or not href.startswith("http"):
                continue
            date_el = li.select_one(".article_schedule, span.fl, span.gL_10")
            published = date_el.get_text(" ", strip=True) if date_el else ""
            out.append({
                "title": title,
                "publisher": "MoneyControl",
                "url": href,
                "published_at": published,
                "summary": "",
                "source": "moneycontrol",
            })
            if len(out) >= max_items:
                break
        if out:
            break
    return out


def fetch_news(
    yf_symbol: str,
    ticker: str,
    company_name: str = "",
    cache_dir: Optional[Path] = None,
    ttl_minutes: int = 30,
    max_items: int = 10,
) -> list[dict]:
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = _cache_path(ticker, cache_dir)
        if _is_fresh(cache, ttl_minutes):
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                pass

    items = fetch_yahoo(yf_symbol, max_items=max_items)
    # Yahoo can be sparse for Indian stocks — supplement from MoneyControl.
    if len(items) < 5 and company_name:
        items.extend(fetch_moneycontrol(company_name, max_items=max_items - len(items)))

    # Dedupe by normalized title prefix
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        key = re.sub(r"\W+", " ", it.get("title", "").lower())[:90].strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(it)
    deduped = deduped[:max_items]

    if cache_dir is not None:
        try:
            _cache_path(ticker, cache_dir).write_text(
                json.dumps(deduped), encoding="utf-8"
            )
        except Exception:
            pass
    return deduped
