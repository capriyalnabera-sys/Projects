"""Fallback fundamentals scraper for screener.in.

Fills in fields that yfinance often returns as None for Indian stocks:
ROE, ROCE, trailing P/E, debt/equity, sales/profit growth.

Caches per ticker as JSON in cache_dir with TTL.
"""
from __future__ import annotations

import json
import re
import time
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


def _to_float(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.strip()
    # Drop currency / suffix labels but keep the leading number.
    t = t.replace("₹", "").replace(",", "").replace("%", "")
    t = re.sub(r"\b(Cr\.?|L|Lac|Crores?|Lakhs?)\b", "", t, flags=re.IGNORECASE).strip()
    m = re.match(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_top_ratios(soup: BeautifulSoup) -> dict:
    out: dict = {}
    ul = soup.find(id="top-ratios")
    if ul is None:
        return out
    for li in ul.find_all("li"):
        name_el = li.find("span", class_="name")
        num_el = li.find("span", class_="number") or li.find("span", class_="value")
        if not name_el or not num_el:
            continue
        name = name_el.get_text(strip=True).lower()
        val = _to_float(num_el.get_text(" ", strip=True))
        if val is None:
            continue
        if "stock p/e" in name or name == "p/e":
            out["trailing_pe"] = val
        elif "roe" in name:
            out["roe"] = val / 100  # screener uses %, our format uses decimal
        elif "roce" in name:
            out["roce"] = val / 100
        elif "market cap" in name:
            out["market_cap_cr"] = val
        elif "debt to equity" in name or name == "debt/equity":
            out["debt_to_equity"] = val
        elif "dividend yield" in name:
            out["dividend_yield"] = val / 100
        elif "book value" in name:
            out["book_value"] = val
        elif "current price" in name:
            out["current_price"] = val
        elif "face value" in name:
            out["face_value"] = val
    return out


def _parse_growth_section(soup: BeautifulSoup, section_text: str) -> dict[str, float]:
    """Extract %-values from a 'Compounded Sales Growth' / 'Compounded Profit Growth'
    style table (rows: 10 Years, 5 Years, 3 Years, TTM)."""
    out: dict[str, float] = {}
    target = section_text.lower()
    for table in soup.find_all("table", class_=re.compile("ranges-table")):
        head = table.find(["th", "h2"])
        title = (head.get_text(" ", strip=True).lower() if head else "")
        if target not in title:
            continue
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) != 2:
                continue
            label = cells[0].get_text(" ", strip=True).lower()
            val = _to_float(cells[1].get_text(" ", strip=True))
            if val is None:
                continue
            if "10 year" in label:
                out["10y"] = val / 100
            elif "5 year" in label:
                out["5y"] = val / 100
            elif "3 year" in label:
                out["3y"] = val / 100
            elif "ttm" in label:
                out["ttm"] = val / 100
    return out


def fetch(ticker: str, cache_dir: Optional[Path] = None, ttl_minutes: int = 60) -> dict:
    """Return a dict of fundamental fields scraped from screener.in.

    Tries /consolidated/ first (preferred for groups with subsidiaries) then standalone.
    Returns {} if both fail.
    """
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache = _cache_path(ticker, cache_dir)
        if _is_fresh(cache, ttl_minutes):
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                pass

    out: dict = {}
    for path in (f"/company/{ticker.upper()}/consolidated/", f"/company/{ticker.upper()}/"):
        try:
            r = requests.get("https://www.screener.in" + path, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            ratios = _parse_top_ratios(soup)
            if not ratios:
                continue
            out.update(ratios)
            sales_growth = _parse_growth_section(soup, "compounded sales growth")
            profit_growth = _parse_growth_section(soup, "compounded profit growth")
            if sales_growth:
                # Prefer TTM, then 3y, then 5y as "current" revenue growth signal.
                for k in ("ttm", "3y", "5y", "10y"):
                    if k in sales_growth:
                        out["revenue_growth"] = sales_growth[k]
                        break
                out["sales_growth_history"] = sales_growth
            if profit_growth:
                for k in ("ttm", "3y", "5y", "10y"):
                    if k in profit_growth:
                        out["earnings_growth"] = profit_growth[k]
                        break
                out["profit_growth_history"] = profit_growth
            break
        except Exception:
            continue

    if cache_dir is not None and out:
        try:
            _cache_path(ticker, cache_dir).write_text(json.dumps(out), encoding="utf-8")
        except Exception:
            pass
    return out
