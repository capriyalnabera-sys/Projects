"""Build a sanitized, portable ZIP of the Stock Analyzer project.

Deliberately EXCLUDES:
  - config.yaml            (contains Telegram api_id / api_hash)
  - *.session              (live Telethon auth blob)
  - .venv/, __pycache__/   (regenerable, machine-specific)
  - the multi-GB download caches (telegram_pdfs, nse_filings, yf_*, analysis,
    screener_in, news, earnings, research, transcripts-cache)

Keeps the small, meaningful state: source, snapshots (self-calibration
history), universe lists, learned calibration, sample transcripts, docs.

Usage:  .venv\\Scripts\\python.exe scripts\\_package.py
Prints the output path, size, and a security assertion.
"""
from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / f"stock_analyzer_{date.today().isoformat()}.zip"

# Never ship these, no matter where they appear.
FORBIDDEN_PARTS = (".venv", "__pycache__", ".git")
FORBIDDEN_NAMES = {"config.yaml"}
FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".session", ".session-journal", ".zip", ".log")

ROOT_FILES = [
    "config.example.yaml", "requirements.txt", "run-web.bat", "run.bat",
    "start_silent.vbs", "disclaimer.txt", ".gitignore",
    "SETUP.md", "PAID_API_OPTIONS.md",
]

# (source dir, glob, recursive)
TREES = [
    ("src", "**/*.py", True),
    ("src/templates", "*.html", False),
    ("scripts", "*.py", False),
    ("data/transcripts", "*", False),
    ("data/cache/snapshots", "*.json", False),
    ("data/cache/universe", "*", False),
]

SMALL_CACHE_FILES = [
    "data/cache/calibration.json",
    "data/cache/regime.json",
    "data/cache/sector_stats.json",
    "data/cache/fii_dii.json",
    "data/journal.json",
]


def is_safe(p: Path) -> bool:
    if any(part in FORBIDDEN_PARTS for part in p.parts):
        return False
    if p.name in FORBIDDEN_NAMES:
        return False
    if p.suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    return True


def main() -> int:
    added: list[str] = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(path: Path) -> None:
            if not path.is_file() or not is_safe(path):
                return
            rel = path.relative_to(ROOT).as_posix()
            z.write(path, rel)
            added.append(rel)

        for name in ROOT_FILES:
            add(ROOT / name)

        for sub, pattern, recursive in TREES:
            base = ROOT / sub
            if not base.exists():
                continue
            it = base.rglob(pattern) if recursive else base.glob(pattern)
            for p in it:
                add(p)

        for rel in SMALL_CACHE_FILES:
            add(ROOT / rel)

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"ZIP:   {OUT}")
    print(f"Size:  {size_mb:.2f} MB")
    print(f"Files: {len(added)}")

    # Hard assertion — refuse to hand over a package containing secrets.
    leaks = [
        r for r in added
        if "config.yaml" in r or ".session" in r or ".venv" in r or "__pycache__" in r
    ]
    print("\n=== SECURITY CHECK ===")
    if leaks:
        print("  FAILED — package contains sensitive/unwanted files:")
        for r in leaks:
            print("   ", r)
        return 1
    print("  PASSED — no credentials, sessions, venv, or bytecode in package.")

    print("\nTop-level contents:")
    tops = sorted({r.split("/")[0] for r in added})
    for t in tops:
        n = sum(1 for r in added if r.split("/")[0] == t)
        print(f"  {t:28s} {n:4d} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
