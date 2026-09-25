"""Self-calibration layer — closes the feedback loop from accuracy → verdicts.

Reads the walk-forward backtest results that ``accuracy.evaluate()`` already
computes and turns the observational stats into actionable adjustments:

  * **Learned BUY threshold** — the lowest score band where BUY+ACCUMULATE
    verdicts historically delivered positive expected returns. Verdicts below
    this band get demoted to HOLD with a "calibration: below learned floor"
    reason.

  * **Sector confidence multipliers** — for sectors where the tool has been
    consistently wrong (hit rate < 40% over ≥10 samples), the verdict carries
    a "low historical hit rate in this sector" note. We do NOT auto-suppress
    those verdicts — they're flagged so the user sees the caveat.

  * **Per-verdict track record** — at any given score, how often has the tool
    been right? Surfaced next to the verdict on the stock detail page so the
    user knows whether to trust *this* call.

Persists to ``data/cache/calibration.json``. Read by ``recommend.py`` for the
soft override, by the web layer for UI rendering. Recomputed automatically
after every batch refresh.

Data-sufficiency gate: until ≥30 snapshots are collected, calibration is
*informational only* — no thresholds are auto-applied. This stops the tool
from chasing tiny samples and turning every quirk of recent market action
into a permanent rule.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


CALIBRATION_PATH = Path("data/cache/calibration.json")
CALIBRATION_TTL_SECONDS = 6 * 60 * 60  # 6h; recomputed eagerly after each batch

# Minimum samples to trust a band / sector reading
MIN_BAND_SAMPLES = 5
MIN_SECTOR_SAMPLES = 10

# Sufficiency: only apply auto-overrides once we have at least this many snapshots
APPLY_OVERRIDES_MIN_SNAPSHOTS = 30

# Lowest score a BUY can ever carry — recommend.py uses
# ``buy_threshold = max(1.5, hold_zone + 0.7)``. A learned floor below this can
# never bind, which we surface instead of implying active filtering.
MIN_BUY_THRESHOLD = 1.5


def _band_to_score_range(label: str) -> tuple[float, float]:
    """Map accuracy.py's score-bin labels to (lo, hi) score ranges."""
    if label == "≥+2":      return (2.0, 99.0)
    if label == "+1 to +2": return (1.0, 2.0)
    if label == "0 to +1":  return (0.0, 1.0)
    if label == "-1 to 0":  return (-1.0, 0.0)
    if label == "≤-1":      return (-99.0, -1.0)
    return (-99.0, 99.0)


def compute(snap_dir: Optional[Path] = None, force: bool = False, stale_ok: bool = False) -> dict:
    """Read the cached accuracy result + derive learned thresholds.

    Cheap call — ``accuracy.evaluate`` itself is disk-cached for 1h, so this
    runs in milliseconds when nothing has changed. Use ``force=True`` to
    bypass the calibration disk cache (e.g. after a fresh batch).
    ``stale_ok=True`` returns whatever's on disk regardless of TTL — paired
    with stale-while-revalidate at the /accuracy route.
    """
    if not force and CALIBRATION_PATH.exists():
        age = time.time() - CALIBRATION_PATH.stat().st_mtime
        if stale_ok or age < CALIBRATION_TTL_SECONDS:
            try:
                return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

    from . import accuracy
    snap_dir = snap_dir or Path("data/cache/snapshots")
    acc = accuracy.evaluate(snap_dir, stale_ok=stale_ok)
    if not acc.get("available"):
        result = {
            "available": False,
            "reason": acc.get("reason", "Accuracy data unavailable"),
            "computed_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save(result)
        return result

    n_snapshots = acc.get("snapshot_count", 0)
    horizons = acc.get("horizons_days") or [5, 20, 60]

    # Pick the LONGEST horizon that ACTUALLY has data. Snapshots taken in the
    # last 60 days won't have 60d outcomes yet, so falling back to 20d (then
    # 5d) is right rather than reporting zero samples. We pick the horizon
    # that maximises total samples observed across score bands.
    score_calib = acc.get("score_calibration") or {}
    def _samples_at(h: int) -> int:
        total = 0
        for band in ("≥+2", "+1 to +2", "0 to +1", "-1 to 0", "≤-1"):
            cell = (score_calib.get(band) or {}).get(str(h))
            if cell:
                total += cell.get("n", 0)
        return total

    target_horizon = str(max(horizons))  # default to longest
    for h in sorted(horizons, reverse=True):
        if _samples_at(h) >= MIN_BAND_SAMPLES:
            target_horizon = str(h)
            break

    # ---- score-band thresholds -------------------------------------------
    band_summary: list[dict] = []
    # Per-band labels (informational only) — every band gets a guidance tag.
    for band_label in ("≥+2", "+1 to +2", "0 to +1", "-1 to 0", "≤-1"):
        cell = (score_calib.get(band_label) or {}).get(target_horizon)
        if not cell or cell.get("n", 0) < MIN_BAND_SAMPLES:
            band_summary.append({
                "band": band_label,
                "n": (cell or {}).get("n", 0),
                "avg_return": (cell or {}).get("avg_return"),
                "hit_rate": (cell or {}).get("hit_rate"),
                "verdict_guidance": "insufficient sample",
            })
            continue
        avg = cell["avg_return"]
        hit = cell["hit_rate"]
        if avg >= 1.0 and hit >= 50.0:
            guidance = "buy-grade"
        elif avg >= 0.0 and hit >= 50.0:
            guidance = "accumulate-grade"
        elif avg <= -2.0 and hit <= 40.0:
            guidance = "avoid-grade"
        else:
            guidance = "neutral / no edge"
        band_summary.append({
            "band": band_label,
            "n": cell["n"],
            "avg_return": avg,
            "hit_rate": hit,
            "verdict_guidance": guidance,
        })

    # Learned BUY floor — walk TOP-DOWN, descending the floor while each band
    # remains buy-grade. The first non-buy-grade band stops the walk, and that
    # boundary becomes the floor.
    learned_buy_min: Optional[float] = None
    stopped_early = False
    for band_label in ("≥+2", "+1 to +2", "0 to +1", "-1 to 0", "≤-1"):
        cell = (score_calib.get(band_label) or {}).get(target_horizon)
        if not cell or cell.get("n", 0) < MIN_BAND_SAMPLES:
            stopped_early = True      # tiny sample = treat as a break
            break
        avg = cell["avg_return"]
        hit = cell["hit_rate"]
        if avg >= 1.0 and hit >= 50.0:
            lo, _ = _band_to_score_range(band_label)
            learned_buy_min = lo
        else:
            stopped_early = True
            break

    # Degenerate case: EVERY band came back buy-grade, so the walk ran to the
    # bottom and "learned" a floor of -99 — i.e. no filter at all. That isn't a
    # floor, it's the absence of one: in this window even low-scoring names went
    # up (typically a broad rally), so the score has no discriminating power at
    # this horizon. Report that honestly instead of advertising a no-op gate.
    no_discrimination = (not stopped_early) and learned_buy_min is not None
    if no_discrimination:
        learned_buy_min = None

    # ---- sector calibration ----------------------------------------------
    sector_calib: dict[str, dict] = {}
    sector_block = acc.get("by_sector") or {}
    for sec, by_v in sector_block.items():
        # Take the longest-horizon BUY+ACCUMULATE combined stats
        positive_n = 0
        positive_returns_sum = 0.0
        positive_hits = 0
        for v in ("BUY", "ACCUMULATE"):
            cell = (by_v.get(v) or {}).get(target_horizon)
            if not cell:
                continue
            n = cell.get("n") or 0
            positive_n += n
            positive_returns_sum += (cell.get("avg_return") or 0) * n
            positive_hits += int((cell.get("hit_rate") or 0) / 100 * n)
        if positive_n < MIN_SECTOR_SAMPLES:
            continue
        avg_ret = positive_returns_sum / positive_n
        hit_rate = positive_hits / positive_n * 100
        if hit_rate < 40 and avg_ret < 0:
            confidence = "low"          # surfaced as warning chip
            note = f"hit rate {hit_rate:.0f}% / avg {avg_ret:+.1f}% — tool has struggled here"
        elif hit_rate >= 65 and avg_ret >= 2.0:
            confidence = "high"
            note = f"hit rate {hit_rate:.0f}% / avg {avg_ret:+.1f}% — strong track record"
        else:
            confidence = "moderate"
            note = f"hit rate {hit_rate:.0f}% / avg {avg_ret:+.1f}%"
        sector_calib[sec] = {
            "n": positive_n,
            "avg_return": round(avg_ret, 2),
            "hit_rate": round(hit_rate, 1),
            "confidence": confidence,
            "note": note,
        }

    # ---- decide whether to apply auto-overrides --------------------------
    data_sufficient = n_snapshots >= APPLY_OVERRIDES_MIN_SNAPSHOTS
    apply_buy_floor = (learned_buy_min is not None) and data_sufficient

    # Headline summary text — what has the tool learned?
    lessons: list[str] = []
    if no_discrimination:
        lessons.append(
            f"No usable BUY floor at the {target_horizon}d horizon: EVERY score band "
            f"was profitable, so the score isn't separating winners from losers in "
            f"this window (typically a broad market rally lifting everything). "
            f"No verdicts are being filtered — treat the score as low-signal here "
            f"until a flat or falling stretch tests it."
        )
    elif apply_buy_floor:
        # A BUY already requires score >= max(1.5, hold_zone + 0.7). If the
        # learned floor sits below that, it can never actually fire — say so
        # rather than implying verdicts are being filtered.
        if learned_buy_min < MIN_BUY_THRESHOLD:
            lessons.append(
                f"Learned floor is raw-score {learned_buy_min:.1f}, which is BELOW the "
                f"{MIN_BUY_THRESHOLD:.1f} a BUY already needs — so it is not filtering "
                f"anything today. Bands down to {learned_buy_min:.1f} were profitable at "
                f"the {target_horizon}d horizon, meaning the score is only weakly "
                f"separating winners from losers in this window."
            )
        else:
            lessons.append(
                f"BUYs only validated above raw-score {learned_buy_min:.1f} — "
                f"verdicts below this band get demoted to HOLD."
            )
    elif learned_buy_min is not None:
        lessons.append(
            f"Provisional BUY floor at raw-score {learned_buy_min:.1f}, but "
            f"only {n_snapshots} snapshots — need ≥{APPLY_OVERRIDES_MIN_SNAPSHOTS} "
            f"before auto-applying."
        )
    # ---- inversion check: is the score even ordered correctly? -------------
    # The whole premise is "higher score → better return". If a LOWER band
    # outperforms the top band by a wide margin, the model is not just weak,
    # it's mis-ordered — the most important thing calibration can report.
    ranked = [
        (b["band"], b["avg_return"])
        for b in band_summary
        if b.get("n", 0) >= MIN_BAND_SAMPLES and b.get("avg_return") is not None
    ]
    inverted_note = None
    if len(ranked) >= 2:
        top_band, top_ret = ranked[0]
        best_band, best_ret = max(ranked[1:], key=lambda x: x[1])
        if best_ret > top_ret + 1.0:
            inverted_note = (
                f"Score ordering is INVERTED at {target_horizon}d: the "
                f"'{best_band}' band returned {best_ret:+.1f}% vs only "
                f"{top_ret:+.1f}% for the top '{top_band}' band. Higher scores "
                f"did NOT produce better outcomes in this window, so treat the "
                f"score as unreliable for ranking until this corrects."
            )
    if inverted_note:
        lessons.append(inverted_note)

    if sector_calib:
        low_sectors = [s for s, v in sector_calib.items() if v["confidence"] == "low"]
        high_sectors = [s for s, v in sector_calib.items() if v["confidence"] == "high"]
        if low_sectors:
            lessons.append(
                f"Sectors with weak track record: {', '.join(low_sectors[:5])}"
                f"{' …' if len(low_sectors) > 5 else ''}."
            )
        if high_sectors:
            lessons.append(
                f"Strong track record sectors: {', '.join(high_sectors[:5])}"
                f"{' …' if len(high_sectors) > 5 else ''}."
            )
    if not lessons:
        lessons.append(
            f"Still gathering data ({n_snapshots} snapshots). The tool will start "
            f"applying calibration once it has ≥{APPLY_OVERRIDES_MIN_SNAPSHOTS}."
        )

    result = {
        "available": True,
        "n_snapshots": n_snapshots,
        "target_horizon_days": int(target_horizon),
        "score_bands": band_summary,
        "sectors": sector_calib,
        "learned_buy_min_score": learned_buy_min,
        "no_discrimination": no_discrimination,
        "score_inverted": bool(inverted_note),
        "data_sufficient": data_sufficient,
        "apply_buy_floor": apply_buy_floor,
        "lessons": lessons,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(result)
    return result


def _save(result: dict) -> None:
    try:
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass


def read_cached() -> Optional[dict]:
    """Cheap read for hot paths — returns None if no calibration on disk yet."""
    if not CALIBRATION_PATH.exists():
        return None
    try:
        return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def lookup_confidence_for_score(calib: dict, score: float) -> Optional[dict]:
    """Given a current verdict's combined score, find the matching score-band
    statistics so the UI can show 'historical hit rate at this score band'.

    Returns ``None`` if no calibration is available or the band has too few
    samples to be meaningful.
    """
    if not calib or not calib.get("available"):
        return None
    for band in calib.get("score_bands") or []:
        lo, hi = _band_to_score_range(band["band"])
        if lo <= score < hi:
            n = band.get("n") or 0
            if n < MIN_BAND_SAMPLES:
                return None
            return {
                "band": band["band"],
                "n": n,
                "avg_return": band.get("avg_return"),
                "hit_rate": band.get("hit_rate"),
                "guidance": band.get("verdict_guidance"),
                "horizon_days": calib.get("target_horizon_days"),
            }
    return None


def sector_confidence(calib: dict, sector: Optional[str]) -> Optional[dict]:
    """Return the historical track record block for a sector, if available."""
    if not calib or not calib.get("available") or not sector:
        return None
    return (calib.get("sectors") or {}).get(sector)
