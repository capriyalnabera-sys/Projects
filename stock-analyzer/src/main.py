from __future__ import annotations

import sys
from pathlib import Path

# Force UTF-8 on Windows consoles that default to cp1252 (would crash on ₹).
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from . import data, fundamentals, recommend, technical
from .recommend import TelegramSignal


console = Console()


def _load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _verdict_color(v: str) -> str:
    return {
        "BUY": "bold green",
        "ACCUMULATE": "green",
        "HOLD": "yellow",
        "REDUCE": "red",
        "AVOID": "bold red",
    }.get(v, "white")


def _fmt_money(x: float, currency: str = "INR") -> str:
    sym = "₹" if currency == "INR" else currency + " "
    return f"{sym}{x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def analyze_one_prefetched(ticker: str, cfg: dict, sd: "data.StockData | None", tg_signal: TelegramSignal | None = None):
    if sd is None:
        sd = data.fetch(ticker)
    tech = technical.analyze(sd.history)
    cache_root = Path(cfg.get("cache", {}).get("dir", "data/cache"))
    fund = fundamentals.analyze(
        sd.info, sd.sector,
        ticker=sd.ticker,
        screener_cache_dir=cache_root / "screener_in",
    )

    weights = cfg.get("recommendation", {})
    rec = recommend.recommend(tech, fund, weights, sd.last_close, tg_signal)

    header = f"[bold]{sd.name}[/]  ({sd.yf_symbol})"
    if sd.sector:
        header += f"  •  {sd.sector}"
    console.print(Panel(header, box=box.ROUNDED, padding=(0, 1)))

    summary = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    summary.add_column("k", style="dim")
    summary.add_column("v")
    summary.add_row("Verdict", f"[{_verdict_color(rec.verdict)}]{rec.verdict}[/]  (score {rec.combined_score:+.2f})")
    summary.add_row("Last close", _fmt_money(sd.last_close, sd.currency))
    if rec.trade_target is not None and rec.upside_pct is not None:
        summary.add_row("Trade target", f"{_fmt_money(rec.trade_target, sd.currency)}   {_fmt_pct(rec.upside_pct)}")
    if rec.target_bull is not None:
        summary.add_row("Bull target", _fmt_money(rec.target_bull, sd.currency))
    if rec.fair_value is not None:
        gap = (rec.fair_value / sd.last_close - 1) * 100
        summary.add_row("Fair value (info)", f"{_fmt_money(rec.fair_value, sd.currency)}   {_fmt_pct(gap)}")
    summary.add_row("Stop loss", f"{_fmt_money(rec.stop_loss, sd.currency)}   {_fmt_pct(rec.downside_pct)}")
    summary.add_row("Horizon", rec.horizon)
    console.print(summary)

    scores = Table(title="Score breakdown", box=box.SIMPLE, show_header=True, header_style="dim")
    scores.add_column("Layer")
    scores.add_column("Score", justify="right")
    scores.add_row("Technical", f"{rec.technical_score:+.2f}")
    scores.add_row("Fundamental", f"{rec.fundamental_score:+.2f}")
    scores.add_row("Telegram", f"{rec.telegram_score:+.2f}")
    console.print(scores)

    facts = Table(title="Key metrics", box=box.SIMPLE, show_header=False)
    facts.add_column("k", style="dim")
    facts.add_column("v")
    facts.add_row("RSI(14)", f"{tech.rsi_14:.1f}")
    facts.add_row("50/200 SMA", f"{tech.sma_50:,.2f} / {tech.sma_200:,.2f}" if tech.sma_200 else f"{tech.sma_50:,.2f} / n/a")
    facts.add_row("52w high / low", f"{tech.high_52w:,.2f}  ({tech.pct_from_52w_high:+.1f}%)  /  {tech.low_52w:,.2f}  ({tech.pct_from_52w_low:+.1f}%)")
    facts.add_row("ATR(14)", f"{tech.atr_14:,.2f}")
    facts.add_row("Volume vs 20d avg", f"{tech.volume_ratio:.2f}x")
    facts.add_row("Trailing PE / Forward PE", f"{_opt(fund.trailing_pe)} / {_opt(fund.forward_pe)}")
    facts.add_row("ROE", _pct(fund.roe))
    facts.add_row("Debt / Equity", _opt(fund.debt_to_equity))
    facts.add_row("Earnings growth (yoy)", _pct(fund.earnings_growth))
    facts.add_row("Revenue growth (yoy)", _pct(fund.revenue_growth))
    facts.add_row("Fair PE used", f"{fund.fair_pe_target:.1f}")
    console.print(facts)

    if rec.entry_note:
        console.print(Panel(f"[yellow]{rec.entry_note}[/]", title="Entry timing", box=box.ROUNDED))

    if rec.rationale:
        console.print(Panel("\n".join(f"• {r}" for r in rec.rationale), title="Rationale", box=box.ROUNDED))

    console.print()


def _opt(x):
    return f"{x:.2f}" if x is not None else "n/a"


def _pct(x):
    return f"{x*100:.1f}%" if x is not None else "n/a"


@click.group()
def cli():
    """Indian-equity research/decision-support tool. Not investment advice."""


def _build_name_aliases(tickers, fetched: dict[str, "data.StockData"]) -> dict[str, str]:
    """Map normalized phrases (lowercase) to NSE ticker so report PDFs that use
    full company names get matched (e.g. 'borosil renewables' → BORORENEW)."""
    suffixes = (
        " limited", " ltd", " ltd.", " industries", " corporation", " corp",
        " inc", " inc.", " co.", " company",
    )
    skip_first_word_aliases = {"the", "of", "and"}
    aliases: dict[str, str] = {}
    for t in tickers:
        tk = t.upper()
        sd = fetched.get(tk)
        if sd is None:
            continue
        long_name = (sd.info.get("longName") or sd.info.get("shortName") or sd.name or "").strip()
        if not long_name:
            continue
        low = long_name.lower()
        candidates = {low}
        for s in suffixes:
            if low.endswith(s):
                candidates.add(low[: -len(s)].strip())
        # First two significant tokens (e.g. "ugro capital", "borosil renewables")
        tokens = [w for w in low.split() if w not in skip_first_word_aliases]
        if len(tokens) >= 2:
            candidates.add(" ".join(tokens[:2]))
        for phrase in candidates:
            if len(phrase) >= 6 and " " in phrase:
                aliases[phrase] = tk
    return aliases


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
@click.option("--with-telegram", is_flag=True, help="Fetch Telegram research-group signals (incl. PDF attachments)")
@click.option("--telegram-days", default=7, show_default=True)
@click.option("--no-pdfs", is_flag=True, help="Skip PDF download/parse on Telegram scan")
def analyze(tickers, config_path, with_telegram, telegram_days, no_pdfs):
    """Analyze one or more NSE tickers, e.g. RELIANCE TCS HFCL."""
    cfg = _load_config(Path(config_path))

    # Pre-fetch stock data so we can build name aliases before Telegram scan.
    fetched: dict[str, data.StockData] = {}
    for t in tickers:
        try:
            fetched[t.upper()] = data.fetch(t)
        except Exception as e:
            console.print(f"[red]Failed to fetch {t}: {e}[/]")

    tg_signals: dict[str, TelegramSignal] = {}
    if with_telegram:
        from . import telegram_ingest
        tcfg = cfg.get("telegram", {})
        if not tcfg.get("api_id") or not tcfg.get("api_hash"):
            console.print("[red]Telegram api_id/api_hash missing in config.yaml[/]")
            sys.exit(2)
        cache_root = Path(cfg.get("cache", {}).get("dir", "data/cache"))
        pdf_dir = None if no_pdfs else cache_root / "telegram_pdfs"
        aliases = _build_name_aliases(tickers, fetched)
        if aliases:
            console.print(f"[dim]Name aliases: {aliases}[/]")
        console.print(
            f"[dim]Scanning Telegram groups (last {telegram_days}d, "
            f"{'with' if pdf_dir else 'without'} PDF parsing)…[/]"
        )
        groups = tcfg.get("groups") or None
        agg = telegram_ingest.scan_groups(
            api_id=int(tcfg["api_id"]),
            api_hash=tcfg["api_hash"],
            session_name=tcfg.get("session_name", "stock_analyzer"),
            group_filter=groups,
            days=telegram_days,
            tickers_of_interest=tickers,
            name_aliases=aliases or None,
            pdf_cache_dir=pdf_dir,
            progress=lambda s: console.print(f"[dim]{s}[/]"),
        )
        for t in tickers:
            tk = t.upper()
            if tk in agg:
                a = agg[tk]
                tg_signals[tk] = TelegramSignal(
                    mentions_7d=a.count,
                    avg_sentiment=a.avg_sentiment,
                    quoted_targets=a.quoted_targets,
                )

    for t in tickers:
        try:
            analyze_one_prefetched(t, cfg, fetched.get(t.upper()), tg_signals.get(t.upper()))
        except Exception as e:
            console.print(f"[red]Failed for {t}: {e}[/]")


@cli.command()
@click.argument("symbols", nargs=-1)
@click.option("--config", "config_path", default="config.yaml", show_default=True)
@click.option("--expiry", default=None, help="Specific expiry (e.g. 30-Sep-2026); default = nearest")
@click.option("--refresh", is_flag=True, help="Bypass the 3-min chain cache")
def fno(symbols, config_path, expiry, refresh):
    """F&O analysis for index options: NIFTY BANKNIFTY SENSEX FINNIFTY MIDCPNIFTY.

    No symbols = NIFTY BANKNIFTY SENSEX."""
    from . import fno as fno_mod, fno_signals
    cfg = _load_config(Path(config_path))
    targets = [s.upper() for s in symbols] or ["NIFTY", "BANKNIFTY", "SENSEX"]

    for sym in targets:
        if sym not in fno_mod.INDEX_META:
            console.print(f"[red]{sym}: unknown index (choose from {', '.join(fno_mod.INDEX_META)})[/]")
            continue
        console.print(f"[dim]Fetching {sym} option chain…[/]")
        a = fno_signals.full_analysis(sym, cfg, expiry=expiry, force=refresh)
        if a is None:
            console.print(f"[red]{sym}: option chain unavailable (exchange API unreachable, no cache)[/]")
            for line in fno_mod.get_fetch_log(sym):
                console.print(f"  [dim]{line}[/]")
            console.print()
            continue

        bias_color = {"BULLISH": "bold green", "BEARISH": "bold red",
                      "RANGE-BOUND": "magenta", "NEUTRAL": "yellow"}.get(a.bias, "white")
        header = f"[bold]{a.label}[/]  spot {a.spot:,.2f}"
        if a.spot_change_pct is not None:
            header += f"  ({a.spot_change_pct:+.2f}%)"
        header += f"  •  expiry {a.expiry}"
        if a.days_to_expiry is not None:
            header += f" ({a.days_to_expiry}d)"
        if a.stale:
            header += "  [yellow]\\[STALE][/]"
        console.print(Panel(header, box=box.ROUNDED, padding=(0, 1)))

        t = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        t.add_column("k", style="dim")
        t.add_column("v")
        t.add_row("Signal", f"[{bias_color}]{a.bias}[/]  (score {a.score:+.2f}, {a.confidence} confidence)")
        t.add_row("PCR", f"{a.pcr_oi_band} near-ATM  /  {a.pcr_oi} total  /  {a.pcr_volume} volume")
        if a.max_pain:
            t.add_row("Max pain", f"{a.max_pain:,.0f}  (spot {a.max_pain_distance_pct:+.2f}% vs pain)")
        if a.atm_iv is not None:
            skew = f"  skew {a.iv_skew:+.1f}" if a.iv_skew is not None else ""
            t.add_row("ATM IV", f"{a.atm_iv}%{skew}")
        if a.expected_move_pct is not None:
            t.add_row("Expected move", f"±{a.expected_move_pct}% by expiry  (straddle ₹{a.straddle_price:,.0f})")
        if a.vix is not None:
            t.add_row("India VIX", f"{a.vix}")
        if a.supports:
            t.add_row("Support", "  ".join(f"{w['strike']:,.0f} ({w['oi']/1e5:.0f}L)" for w in a.supports))
        if a.resistances:
            t.add_row("Resistance", "  ".join(f"{w['strike']:,.0f} ({w['oi']/1e5:.0f}L)" for w in a.resistances))
        t.add_row("OI flow", a.oi_flow)
        t.add_row("Lot size", str(a.lot))
        console.print(t)

        if a.rationale:
            console.print(Panel("\n".join(f"• {r}" for r in a.rationale), title="Rationale", box=box.ROUNDED))
        if a.cautions:
            console.print(Panel("\n".join(f"[yellow]! {w}[/]" for w in a.cautions), title="Cautions", box=box.ROUNDED))
        for st in a.strategies:
            legs = "   ".join(st["legs"]) if st["legs"] else "—"
            console.print(Panel(f"[bold]{legs}[/]\n{st['rationale']}\n[dim]{st['risk']}[/]",
                                title=f"{st['name']} (IV {st['iv_state']})", box=box.ROUNDED))
        console.print()


@cli.command("list-groups")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def list_groups_cmd(config_path):
    """List Telegram groups/channels you're a member of (so you can pick which to scan)."""
    from . import telegram_ingest
    cfg = _load_config(Path(config_path))
    tcfg = cfg.get("telegram", {})
    if not tcfg.get("api_id") or not tcfg.get("api_hash"):
        console.print("[red]Telegram api_id/api_hash missing in config.yaml[/]")
        sys.exit(2)
    names = telegram_ingest.list_groups(
        api_id=int(tcfg["api_id"]),
        api_hash=tcfg["api_hash"],
        session_name=tcfg.get("session_name", "stock_analyzer"),
    )
    for n in sorted(names):
        console.print(f"• {n}")


if __name__ == "__main__":
    cli()
