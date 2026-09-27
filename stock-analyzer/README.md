# Stock Analyzer 2.0

Indian-equity research & decision-support tool (NSE + BSE) with a web UI and
CLI. Version 2.0 adds a complete **F&O analysis module for index options**
(NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY).

> Output is heuristic and may be wrong, stale, or based on incomplete data.
> Not SEBI-registered. Not investment advice. See `disclaimer.txt`.

## What it does

**Equities (v1, carried forward)**
- Multi-layer recommendations: technicals (RSI/MACD/SMA/ATR/momentum) +
  fundamentals (PE/ROE/growth/debt, screener.in enrichment) + optional
  Telegram research-group signals, blended into BUY→AVOID verdicts.
- Universe screener (NIFTY 50 → full NSE+BSE), market pulse dashboard,
  sector-relative stats, market-regime overlay (NIFTY 200SMA/ADX + India VIX).
- Self-calibration loop: daily verdict snapshots → accuracy tracking →
  learned thresholds.
- Trade journal, position sizer, earnings/filings/news/transcripts per stock.

**F&O — new in 2.0** (`/fno` in the web UI, `python -m src.main fno` in the CLI)
- Live option chains from the exchanges themselves: NSE API for NIFTY /
  BANKNIFTY / FINNIFTY / MIDCPNIFTY, BSE API (best-effort) for SENSEX.
  Disk-cached with stale-fallback when APIs throttle.
- Chain analytics: PCR (OI + volume, total and near-ATM), max pain, OI walls
  → concrete support/resistance strikes, ΔOI flow reading (put/call writing,
  unwinding, straddle-seller detection), ATM IV, IV skew, straddle-implied
  expected move (total and per-day).
- Signal synthesis: composite score in [-3, +3] → **BULLISH / BEARISH /
  RANGE-BOUND / NEUTRAL** with confidence, cross-checked against index
  technicals and India VIX, with explicit rationale and cautions.
- Strategy suggestions with actual strikes from the chain (bull/bear spreads,
  iron condor, straddle/strangle) picked by bias × IV regime, each with a
  defined-risk note and current lot size.
- **Background tracker** (while the app runs, market hours): snapshots each
  tracked index every few minutes into `data/cache/fno/history/`, powering —
  - *Intraday tracker*: sparklines + shift readings (PCR drift, OI-wall moves,
    max-pain drift, IV moves, intraday bias flips) since open.
  - *Signal-change alerts*: every bias flip lands in an on-page feed
    (`/api/fno/alerts`); optionally also DM'd to your own Telegram Saved
    Messages (`fno.alerts.telegram: true` in config.yaml).
  - *Signal track record*: end-of-day signals are backtested against the
    index's actual next-1d/3d moves (directional) and expected-move ranges
    (range-bound) — the options-side analog of the equity Accuracy page.
  Tracked symbols/interval configurable via `fno.track_symbols` /
  `fno.track_interval_minutes`.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\activate
cp config.example.yaml config.yaml               # optional: Telegram creds, lot overrides

# Web UI (http://localhost:5000)
.venv/bin/python -m flask --app src.web run

# CLI
.venv/bin/python -m src.main analyze RELIANCE TCS
.venv/bin/python -m src.main fno                 # NIFTY + BANKNIFTY + SENSEX
.venv/bin/python -m src.main fno BANKNIFTY --expiry 30-Sep-2026
```

Windows launchers: `run-web.bat` (web), `run.bat` (CLI),
`start_silent.vbs` (background). Full setup notes: `SETUP.md`.

## F&O module layout

| File | Role |
|---|---|
| `src/fno.py` | Data layer — NSE/BSE chain fetch, session warmup, normalization, disk cache |
| `src/fno_signals.py` | Pure analytics + signal synthesis + strategy suggestions |
| `src/templates/fno.html` | Web dashboard (walls, flow, chain table, strategies) |
| `scripts/_smoke_fno.py` | Offline smoke test — synthetic chains, no network needed |

API endpoints: `/api/fno/<symbol>` (full analysis JSON),
`/api/fno/<symbol>/chain` (normalized chain JSON).

Lot sizes change by exchange notice — update `fno.lot_sizes` in `config.yaml`
rather than editing code.

## Notes on data sources

Everything runs on free public endpoints (NSE/BSE exchange APIs, Yahoo
Finance, screener.in). NSE throttles aggressively by IP: the F&O layer warms
cookies like a browser, caches chains for 3 minutes, and serves a flagged
stale copy (up to 36h) when blocked. SENSEX depends on BSE's less stable API
and degrades to a spot-only view when it's down. Paid alternatives are
compared in `PAID_API_OPTIONS.md`.
