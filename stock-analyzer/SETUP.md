# Stock Analyzer 2.0 — Setup on a new machine

> 2.0 adds the F&O index-options module (`/fno` page, `fno` CLI command,
> `src/fno.py` + `src/fno_signals.py`). No new dependencies or credentials —
> the steps below are unchanged. See README.md for the feature overview.

Portable snapshot of the Indian-equity Stock Analyzer (NSE + BSE). Contains all
source code, the verdict-snapshot history that powers the self-calibration loop,
and the cached universe lists. It does **not** contain the big regenerable
caches (yfinance histories, downloaded PDFs) or any auth material.

## What's inside

```
src/                        - All Python code (~30 modules)
src/templates/              - Jinja2 templates for the web UI
scripts/                    - Helper / smoke-test scripts
data/transcripts/           - Local meeting-transcript drop folder + README
data/cache/snapshots/       - Daily verdict snapshots (powers /accuracy + calibration)
data/cache/calibration.json - Learned BUY threshold + per-sector confidence
data/cache/regime.json      - NIFTY regime + VIX cache
data/cache/sector_stats.json- Sector-relative percentile stats
data/cache/universe/        - Cached index lists + _all_listed + _live_set
config.example.yaml         - Template config — copy to config.yaml, add credentials
requirements.txt            - Python deps
run-web.bat / run.bat       - Launchers (web UI / CLI)
start_silent.vbs            - Silent background launcher (no console window)
SETUP.md                    - This file
PAID_API_OPTIONS.md         - Paid data-API comparison (not integrated; free stack today)
disclaimer.txt              - Risk disclaimer
```

> **NOT included** (intentionally — emailed auth material is risky):
> - `config.yaml` with your Telegram api_id / api_hash
> - `stock_analyzer.session` (live Telethon auth blob)
> - `.venv/`, and the multi-GB `data/cache/` download folders
>
> You recreate the first two on the new machine — step 3 below, ~2 minutes.

## Restore steps

1. Unzip into any folder. Open a terminal **in that folder**.

2. Create a fresh virtualenv:

   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Create `config.yaml` from the template:

   ```cmd
   copy config.example.yaml config.yaml
   ```

   Fill in `telegram.api_id` and `telegram.api_hash` from
   https://my.telegram.org (Apps section). On first launch Telethon asks for
   your phone number + login code once, then writes `stock_analyzer.session`.

4. Launch:

   ```cmd
   run-web.bat
   ```

   Opens `http://127.0.0.1:5000/`. First loads are slow while caches rebuild;
   after that pages are 15–50 ms.

5. Optional — recreate the scheduled refreshes (09:30 / 12:00 / 15:30 IST) via
   Windows Task Scheduler, each POSTing to
   `http://127.0.0.1:5000/api/refresh-all?ttl_minutes=15&telegram=0`.

## Key config knobs (`config.yaml`)

```yaml
recommendation:
  technical_weight: 0.50      # T and F each carry half the score
  fundamental_weight: 0.50
  telegram_weight: 0.0        # research-only; never scores
  liquidity_floor_cr: 0.5     # ₹50 lakh/day. Below this → forced HOLD +
                              # skipped from deep analysis on the full sweep
```

Changing `liquidity_floor_cr` needs a live-set rebuild afterwards:
`python scripts/_build_liveset_now.py`, then refresh the NSE+BSE universe.

## Universes

| Name | Size | Notes |
|---|---|---|
| nifty50 / 100 / 500 | 50–500 | Index constituents |
| midcap150, smallcap250, midsmall400 | — | Index constituents |
| all | ~800 | Union of all NIFTY indices |
| **alllisted** | **~5,000** | **Full NSE + BSE, ISIN-deduplicated** |

`alllisted` uses a **live-set** design: a *full sweep* analyses all ~5,000 names
(slow, ~30 min) then saves the subset that had data AND cleared the liquidity
floor to `data/cache/universe/_live_set.json` (~1,900 names). Routine refreshes
and every UI page use only the live set, so the tool stays fast. Trigger a full
sweep with the "Full sweep" button on the NSE+BSE tab, or
`/api/refresh?universe=alllisted&full=1`.

BSE-only names (ISIN not on NSE) carry a `.BO` suffix, e.g. `ANDHRAPET.BO`.

## Scoring model

Two layers, each clamped to [−3, +3], combined 50/50.

- **Technical** (`technical.py`) — trend vs 50/200 SMA, RSI-14, MACD crossover,
  volume surge, 52w position, 30-day momentum.
- **Fundamental** (`fundamentals.py` + `sector_params.py`) — ROE, earnings and
  revenue growth, D/E, P/E, profit margin, **scored against per-sector bands**
  (a 16% ROE is strong for metals, mediocre for IT; banks/utilities/realty skip
  D/E entirely), plus sector-relative percentile overlays and cross-sectional
  momentum.

Then noise gates in order: liquidity floor → data sufficiency (≥3 of 6
fundamentals) → confluence (BUY needs BOTH layers ≥ +0.5) → VIX-adaptive hold
zone → verdict persistence → NIFTY regime overlay → earnings blackout →
**learned calibration floor**.

## Self-calibration loop

The tool learns from its own accuracy:

1. `accuracy.evaluate()` replays every past verdict against realized returns at
   5/20/60-day horizons.
2. `calibration.compute()` walks score bands top-down to find the lowest band
   that still delivers buy-grade returns → the **learned BUY floor** — plus a
   per-sector confidence label.
3. Later batches demote BUY→HOLD below that floor, but **only once ≥30
   snapshots exist**. Below that it's informational only.

Current state is in `data/cache/calibration.json`.

## Surfaces

- `/` — Recommendations dashboard (curated lists, regime + FII banner)
- `/screener` — Full sortable/filterable grid; defaults to the NSE+BSE live set
- `/market` — Market pulse: NIFTY / VIX / FII-DII / regime
- `/stock/<TICKER>` — Verdict + track-record chips, NSE filings & earnings-call
  analysis, Telegram research, news, fundamentals, technical chart
- `/accuracy` — Hit-rate scorecard, plain-English takeaway, "What the tool has
  learned" calibration panel
- `/analyze` — Ad-hoc live analysis of any tickers

## Remote access (on the original machine)

- Server binds `0.0.0.0:5000` (override with `STOCK_ANALYZER_HOST`).
- **Tailscale** (works from anywhere, any network): install the app, sign in to
  the same account, browse to `http://<pc-tailscale-ip>:5000/`.
- **Home WiFi only**: `http://<pc-lan-ip>:5000/` — needs the "Stock Analyzer
  LAN" firewall rule (TCP 5000, Private profile).
- The app has **no login** — deliberately kept off the public internet.

## Performance notes

- In-memory memos for rows / universe counts / regime / FII / index quotes,
  cleared when a batch completes, then hot pages are pre-warmed in background.
- Sparkline SVG points precomputed in Python (was ~56k Jinja loop iterations).
- Illiquid names short-circuit before the 3 network calls (`.info`, screener.in,
  earnings) — ~7.7 s → 0.02 s each.
- `bulk_fetch_histories` chunks at 200 symbols.

## Notes

- Data sources are all free: yfinance, NSE direct APIs, screener.in scraping,
  Telegram via Telethon. See `PAID_API_OPTIONS.md` if you ever want to upgrade.
- The trade Journal was removed from the UI; `journal.py` and any existing
  `data/journal.json` remain on disk but are unwired.
