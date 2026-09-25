"""Pull meaningful, fundamentals-relevant insights out of long research text.

Designed for three sources:
  - NSE earnings call transcripts / investor presentations (long PDFs)
  - Telegram research-group PDFs (broker / boutique reports)
  - Locally-dropped transcripts (morning calls, internal notes)

The output is structured so the UI can render it as readable sections instead of
a raw 600-char excerpt. Pure pattern-matching — no LLM call, runs in milliseconds.

Typical shape returned by ``analyze``::

    {
      "doc_type": "concall" | "presentation" | "research" | "transcript",
      "summary":  "...",                # 2-3 plain-English lines
      "key_metrics":      [{label, value, sentence}],
      "guidance":         [{sentence, horizon, value}],
      "capex_strategic":  [str],
      "risks":            [str],
      "positives":        [str],
      "quoted_targets":   [{price, horizon}],   # for research reports
      "sentiment":        float,        # -1.0 to +1.0
      "highlight_count":  int,          # total signal-bearing sentences
    }
"""
from __future__ import annotations

import re
from typing import Optional


# ---------- text normalization ----------

def _normalize(text: str) -> str:
    """Undo the typical mangling pypdf does to multi-column PDFs."""
    if not text:
        return ""
    # de-hyphenate end-of-line breaks: "expan-\nsion" -> "expansion"
    text = re.sub(r"-\n\s*", "", text)
    # collapse repeated whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    # strip page numbers like "Page 4 of 19" on their own line
    text = re.sub(r"(?im)^\s*page\s+\d+\s+of\s+\d+\s*$", "", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    # split on .?! followed by whitespace, treating newlines as soft separators too
    flat = re.sub(r"\s*\n\s*", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z₹0-9])", flat)
    out: list[str] = []
    for p in parts:
        s = p.strip()
        # ignore boilerplate-tiny or boilerplate-huge fragments
        if 20 <= len(s) <= 600:
            out.append(s)
    return out


# ---------- regex / keyword banks ----------

INR_AMOUNT = re.compile(
    r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)\s*"
    r"(crore|cr\b|crores|lakh|lakhs|million|mn\b|billion|bn\b)?",
    re.IGNORECASE,
)
PERCENT = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")
HORIZON = re.compile(
    r"\b("
    r"FY\s*'?\d{2,4}"
    r"|Q[1-4]\s*(?:FY)?\s*'?\d{2,4}"
    r"|H[12]\s*(?:FY)?\s*'?\d{2,4}"
    r"|next\s+(?:year|quarter|few\s+years?|\d+\s+(?:years?|quarters?|months?))"
    r"|by\s+\d{4}"
    r"|in\s+\d{4}"
    r"|over\s+the\s+next\s+\d+\s+(?:years?|quarters?|months?)"
    r"|over\s+the\s+next\s+(?:few\s+)?years?"
    r"|coming\s+(?:quarters?|years?)"
    r")",
    re.IGNORECASE,
)
TARGET_PRICE = re.compile(
    r"(?:target|tp|price\s+target)\s*(?:price)?\s*(?:of|at|:)?\s*"
    r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
RATING = re.compile(
    r"\b(BUY|SELL|HOLD|ACCUMULATE|REDUCE|ADD|OUTPERFORM|UNDERPERFORM|NEUTRAL|OVERWEIGHT|UNDERWEIGHT)\b"
)

GUIDANCE_VERBS = (
    "expect", "expects", "expecting", "guide", "guiding", "guidance",
    "target", "targeting", "plan to", "plans to", "aim to", "aiming",
    "project", "projecting", "anticipate", "anticipating", "forecast",
    "forecasting", "intend", "looking to", "should reach", "should achieve",
    "should deliver", "to grow", "to deliver", "to reach", "estimate",
    "estimates", "estimating", "see", "we see",
)
CAPEX_KEYS = (
    "capex", "capital expenditure", "capital outlay",
    "investment of", "investing in", "invested in",
    "new plant", "new factory", "new facility", "new line",
    "expanding our", "expanding capacity", "expanding the",
    "commission", "commissioning", "setting up", "set up a",
    "greenfield", "brownfield", "added capacity", "additional capacity",
    "capacity addition", "capacity expansion", "doubling capacity",
    "ramping up", "ramp-up",
)

# Bio / governance / boilerplate giveaways — skip these sentences entirely
# when classifying risks/capex (they're director credentials, not risk
# disclosures, even if they contain "risk management" or "investment banking").
BIO_BOILERPLATE = (
    "independent director", "executive director", "non-executive director",
    "chartered accountant", "company secretary",
    "decades of experience", "decades experience",
    "years of experience", "advocate and solicitor",
    "expertise in", "specializes in", "has held", "previously held",
    "hand over the call", "handover the call", "over to", "moderator",
    "good morning, ladies", "good afternoon, ladies", "thank you, and",
    "before we begin", "safe harbor", "forward-looking statements",
)
RISK_KEYS = (
    "risk", "risks", "headwind", "headwinds", "challenge", "challenging",
    "decline", "declined", "declining", "weak", "weakness",
    "slowdown", "slowing", "concern", "concerns", "pressure",
    "margin pressure", "muted", "subdued", "compress", "compression",
    "delay", "delayed", "postpone", "regulatory", "litigation",
    "deteriorat", "downgrade", "miss",
)
POSITIVE_KEYS = (
    "strong", "robust", "record", "all-time high", "all time high",
    "outperform", "exceed", "exceeded", "ahead of plan", "ahead of schedule",
    "best ever", "highest ever", "improvement", "improved", "improving",
    "accelerate", "accelerating", "tailwind", "tailwinds", "expansion",
    "growth", "grew", "growing", "robust demand", "strong demand",
    "healthy", "encouraging", "momentum",
)
NEGATIVE_KEYS = (
    "loss", "losses", "fell", "missed", "below estimate", "below estimates",
    "disappoint", "deteriorat", "shortfall", "lower than expected",
)

METRIC_LABEL_HINTS = (
    ("revenue", ("revenue", "topline", "top-line", "sales", "turnover", "net sales")),
    ("ebitda",  ("ebitda", "operating profit")),
    ("pat",     ("pat", "profit after tax", "net profit", "bottom-line", "bottomline")),
    ("margin",  ("margin", "ebitda margin", "operating margin", "gross margin", "pat margin")),
    ("order_book", ("order book", "orderbook", "order backlog")),
    ("debt",    ("debt", "net debt", "borrowings")),
    ("roe",     ("roe", "return on equity")),
    ("roce",    ("roce", "return on capital")),
)


# ---------- classification helpers ----------

def _lower_has_any(s_low: str, keys: tuple[str, ...]) -> bool:
    return any(k in s_low for k in keys)


def _detect_doc_type(text: str, subject: str = "") -> str:
    """Best-effort guess: concall transcript, investor presentation, or research report."""
    blob = (subject + " " + text[:2000]).lower()
    if any(k in blob for k in ("conference call", "earnings call", "concall", "transcript of")):
        return "concall"
    if any(k in blob for k in ("investor presentation", "investor meet", "analyst meet")):
        return "presentation"
    if any(k in blob for k in ("target price", "rating:", "we recommend", "initiate", "reiterate")):
        return "research"
    return "transcript"


def _detect_metric_label(s_low: str) -> Optional[str]:
    for label, hints in METRIC_LABEL_HINTS:
        if any(h in s_low for h in hints):
            return label
    return None


def _extract_metric_pairs(sentence: str) -> list[dict]:
    """Proximity-aware metric extraction. For each number found, look in a
    short window around it (≈60 chars before, 30 after) for the label
    keyword. Avoids the failure where a paragraph like::

        "Tanker asset prices & order book * Coal inventories elevated 19%"

    would yank "19%" out and label it "order_book" just because the keyword
    appears somewhere in the same flattened bullet-blob.

    Each returned dict carries a tight ``context`` slice of nearby words so
    the UI doesn't have to display the whole stitched sentence.
    """
    pairs: list[dict] = []
    used_spans: list[tuple[int, int]] = []

    def _ctx(start: int, end: int) -> str:
        a = max(0, start - 70)
        b = min(len(sentence), end + 70)
        chunk = sentence[a:b]
        # add ellipsis if we truncated
        if a > 0: chunk = "…" + chunk
        if b < len(sentence): chunk = chunk + "…"
        return chunk.strip()

    for m in INR_AMOUNT.finditer(sentence):
        start, end = m.span()
        window_low = sentence[max(0, start - 70):end + 30].lower()
        label = _detect_metric_label(window_low)
        if not label:
            continue
        unit = (m.group(2) or "").strip()
        value = f"₹{m.group(1)}" + (f" {unit}" if unit else "")
        pairs.append({"label": label, "value": value, "context": _ctx(start, end)})
        used_spans.append((start, end))

    for m in PERCENT.finditer(sentence):
        start, end = m.span()
        # Skip if this % is part of an INR-driven match (e.g. "10-12%" near an amount)
        if any(s - 4 <= start <= e + 4 for s, e in used_spans):
            continue
        window_low = sentence[max(0, start - 70):end + 30].lower()
        label = _detect_metric_label(window_low)
        if not label:
            continue
        value = f"{m.group(1)}%"
        pairs.append({"label": label, "value": value, "context": _ctx(start, end)})

    return pairs


def _sentiment(text: str) -> float:
    """Naive bag-of-words sentiment in [-1, +1]."""
    low = text.lower()
    pos = sum(1 for w in POSITIVE_KEYS if w in low)
    neg_bank = RISK_KEYS + NEGATIVE_KEYS
    neg = sum(1 for w in neg_bank if w in low)
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 2)


# ---------- public extractor ----------

def analyze(text: str, subject: str = "", ticker: Optional[str] = None) -> dict:
    """Return structured insights from a research / transcript text blob.

    ``subject`` is the filing subject line (or report title), used to bias
    doc-type detection. ``ticker`` is currently unused but kept on the API
    so callers can pass it through for future per-ticker filtering.
    """
    if not text or len(text) < 200:
        return {
            "doc_type": "transcript",
            "summary": "",
            "key_metrics": [],
            "guidance": [],
            "capex_strategic": [],
            "risks": [],
            "positives": [],
            "quoted_targets": [],
            "sentiment": 0.0,
            "highlight_count": 0,
        }

    norm = _normalize(text)
    sentences = _split_sentences(norm)
    doc_type = _detect_doc_type(norm, subject)

    key_metrics: list[dict] = []
    guidance: list[dict] = []
    capex_strategic: list[str] = []
    risks: list[str] = []
    positives: list[str] = []
    quoted_targets: list[dict] = []

    seen_metric_signatures: set[str] = set()

    for sent in sentences:
        low = sent.lower()
        is_bio = _lower_has_any(low, BIO_BOILERPLATE)

        # 1) broker / report targets
        m = TARGET_PRICE.search(sent)
        if m and not is_bio:
            horizon_m = HORIZON.search(sent)
            quoted_targets.append({
                "price": m.group(1).replace(",", ""),
                "horizon": (horizon_m.group(1) if horizon_m else ""),
                "sentence": sent[:280],
            })

        # 2) forward guidance — needs a forward verb AND (a number or a horizon)
        has_horizon = bool(HORIZON.search(sent))
        has_number = bool(INR_AMOUNT.search(sent) or PERCENT.search(sent))
        has_guidance_verb = _lower_has_any(low, GUIDANCE_VERBS)
        if has_guidance_verb and (has_horizon or has_number) and not is_bio:
            horizon_m = HORIZON.search(sent)
            inr_m = INR_AMOUNT.search(sent)
            pct_m = PERCENT.search(sent)
            value = ""
            if inr_m:
                unit = (inr_m.group(2) or "").strip()
                value = f"₹{inr_m.group(1)}" + (f" {unit}" if unit else "")
            elif pct_m:
                value = f"{pct_m.group(1)}%"
            guidance.append({
                "sentence": sent[:320],
                "horizon": (horizon_m.group(1) if horizon_m else ""),
                "value": value,
            })

        # 3) capex / strategic plans — require both a capex keyword AND either
        #    a rupee amount OR a horizon to filter out generic sector talk.
        if _lower_has_any(low, CAPEX_KEYS) and not is_bio:
            if INR_AMOUNT.search(sent) or HORIZON.search(sent) or "capex" in low:
                capex_strategic.append(sent[:320])

        # 4) risks / negatives flagged — skip director bios that merely
        #    mention "risk management" as a domain of expertise.
        if (_lower_has_any(low, RISK_KEYS) or _lower_has_any(low, NEGATIVE_KEYS)) and not is_bio:
            risks.append(sent[:320])

        # 5) positives / wins
        elif _lower_has_any(low, POSITIVE_KEYS) and (has_number or "growth" in low) and not is_bio:
            positives.append(sent[:320])

        # 6) key metrics — proximity-aware: pair each number with the label
        # keyword that's actually near it, not just somewhere in the sentence.
        for pair in _extract_metric_pairs(sent):
            sig = f"{pair['label']}:{pair['value']}"
            if sig in seen_metric_signatures:
                continue
            seen_metric_signatures.add(sig)
            key_metrics.append({
                "label": pair["label"],
                "value": pair["value"],
                # Use the tight local window as the displayed context. Falls
                # back to a sentence slice if context is empty.
                "sentence": (pair.get("context") or sent)[:240],
            })

    # de-dupe text-only lists while preserving order, cap each list
    def _uniq(lst: list[str], cap: int) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in lst:
            key = s[:120].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= cap:
                break
        return out

    capex_strategic = _uniq(capex_strategic, 4)
    risks = _uniq(risks, 4)
    positives = _uniq(positives, 4)
    key_metrics = key_metrics[:8]
    guidance = guidance[:5]

    # 2-3 line summary: pick highest-signal sentences (numbers + forward verbs + positives)
    scored: list[tuple[float, str]] = []
    for sent in sentences[:120]:  # cap scan to first chunk to stay fast
        low = sent.lower()
        score = 0.0
        if INR_AMOUNT.search(sent): score += 1.5
        if PERCENT.search(sent):    score += 1.0
        if HORIZON.search(sent):    score += 0.8
        if _lower_has_any(low, GUIDANCE_VERBS): score += 1.2
        if _lower_has_any(low, POSITIVE_KEYS):  score += 0.5
        if _lower_has_any(low, RISK_KEYS):      score += 0.3
        if _detect_metric_label(low):           score += 0.7
        if score > 0:
            scored.append((score, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    summary_sentences: list[str] = []
    seen_summary: set[str] = set()
    for _, s in scored:
        key = s[:80].lower()
        if key in seen_summary:
            continue
        seen_summary.add(key)
        summary_sentences.append(s)
        if len(summary_sentences) >= 3:
            break
    summary = " ".join(summary_sentences)[:600]

    sentiment = _sentiment(norm[:8000])  # cap to first 8KB for speed

    highlight_count = (
        len(key_metrics) + len(guidance) + len(capex_strategic)
        + len(risks) + len(positives) + len(quoted_targets)
    )

    return {
        "doc_type": doc_type,
        "summary": summary,
        "key_metrics": key_metrics,
        "guidance": guidance,
        "capex_strategic": capex_strategic,
        "risks": risks,
        "positives": positives,
        "quoted_targets": quoted_targets,
        "sentiment": sentiment,
        "highlight_count": highlight_count,
    }
