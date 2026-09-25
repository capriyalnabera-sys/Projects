# Paid data-API options for Stock Analyzer

You're staying **free for now** (yfinance + NSE/BSE direct + screener.in). This
file documents the paid options if you later want faster/cleaner data — mainly
to speed up the full NSE+BSE sweep and stop relying on flaky yfinance `.info` +
screener.in scraping.

## What the tool needs data for

| Need | Current free source | Reliability |
|---|---|---|
| OHLC price history (batch) | yfinance `bulk_fetch` | good, occasionally rate-limits |
| Live LTP | NSE direct quote API | very good |
| Fundamentals (PE, ROE, D/E, growth) | yfinance `.info` → screener.in scrape | patchy — the sweep bottleneck |
| Earnings dates | yfinance / NSE | ok |
| News / research | Yahoo + MoneyControl + Telegram | fine |

The **fundamentals** column is where a paid API helps most: one clean bulk call
instead of ~2,500 screener.in scrapes.

## Options (India-capable), cheapest → priciest

### 1. Broker APIs — you likely already have an account

| Provider | Cost | Gives you | Catch |
|---|---|---|---|
| **Upstox API** | Free with account | Real-time + historical OHLC, quotes | No fundamentals; OAuth token refresh daily |
| **Dhan API** | Free with account | OHLC, quotes, some fundamentals | Newer, smaller docs |
| **Angel One SmartAPI** | Free with account | OHLC, quotes | Rate limits |
| **Zerodha Kite Connect** | ₹2,000/mo | Rock-solid OHLC, quotes, instruments | Paid; still no deep fundamentals |

**Best fit:** if you hold a Zerodha/Upstox/Dhan account, wire its API for OHLC +
LTP (replaces yfinance history, faster + no rate-limit). Fundamentals still need
another source. Effort: ~half a day to add an adapter behind `data.py`.

### 2. Global data vendors — cover India via `.NS` / `.BO`

| Provider | Cost (approx) | Gives you | Notes |
|---|---|---|---|
| **EOD Historical Data (EODHD)** | ~$20-80/mo | Bulk EOD prices + **fundamentals** for NSE/BSE in ONE call | Best value for full-universe sweeps |
| **Financial Modeling Prep (FMP)** | ~$22-70/mo | Fundamentals, ratios, statements | India coverage decent, not exhaustive |
| **Alpha Vantage** | Free tier / $50+/mo | Prices + some fundamentals | Free tier too rate-limited for 5,000 names |
| **Twelve Data** | ~$30+/mo | Prices, some fundamentals | Good API ergonomics |

**Best fit for the 5,000-name sweep:** **EODHD** — its bulk fundamentals endpoint
would replace the screener.in scraping entirely and cut the sweep from ~35-45 min
to a few minutes. Effort: ~half a day for a `data.py` + `fundamentals.py` adapter.

### 3. What NOT to bother with

- **Tickertape / Trendlyne / screener.in** — no official public API (Tickertape
  you already know). screener.in scraping is what we already do.
- **NSE/BSE official paid feeds** — enterprise pricing, overkill for personal use.

## Recommendation if/when you go paid

1. **If you just want the sweep fast + reliable:** EODHD (~$20-40/mo tier) for
   bulk fundamentals + EOD prices. Single biggest win.
2. **If you want real-time + already use a broker:** wire your broker's free API
   (Upstox/Dhan/Kite) for OHLC/LTP, keep screener.in for fundamentals.
3. **Hybrid:** broker API for prices (free) + EODHD for fundamentals (paid) — the
   fastest, most reliable combination.

All three slot in behind the existing `data.py` / `fundamentals.py` interfaces —
no engine changes, just a new adapter and an API key in `config.yaml`. Ping me
when you want one wired in.

## Free optimizations already applied (no API needed)

- **Illiquid short-circuit** — sub-₹1cr/day names skip the 3 network calls
  (`.info` + screener + earnings). ~half the BSE universe → near-instant.
- **Chunked bulk fetch** — 5,000 names fetched in 200-symbol chunks.
- **Live-set** — routine refreshes only re-run proven-liquid names.
- Still available: parallelize the chunked history fetch, raise screener TTL.
