"""Ind AS 116 Lease Accounting - Windows desktop application entry point.

Run:  python main.py                (uses the database in %LOCALAPPDATA%\\IndAS116LeaseApp)
      python main.py --db my.sqlite (use a specific database file)
      python main.py --demo         (load the demonstration leases on first start)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or later is required. Please install Python 3.12 (64-bit) from python.org.")

# make the lease_app package importable whatever folder the program is started from
sys.path.insert(0, str(Path(__file__).resolve().parent))


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") if sys.platform.startswith("win") else None
    p = Path(base) / "IndAS116LeaseApp" if base else Path.home() / ".local" / "share" / "IndAS116LeaseApp"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = Path(__file__).resolve().parent
    return p


def report_error(title: str, exc_text: str):
    """Write the error to startup_error.log and show it in a message box (or the console)."""
    log = log_dir() / "startup_error.log"
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} {title}\n{exc_text}\n")
    except OSError:
        pass
    msg = f"{title}\n\n{exc_text.strip().splitlines()[-1]}\n\nFull details saved to:\n{log}"
    print(msg, file=sys.stderr)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv[:1])
        box = QMessageBox(QMessageBox.Critical, "Ind AS 116 Lease Accounting", msg)
        box.setDetailedText(exc_text)
        box.exec()
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    """Errors inside the running application: show and log them instead of failing silently."""
    report_error("Unexpected error", "".join(traceback.format_exception(exc_type, exc, tb)))


def run():
    parser = argparse.ArgumentParser(description="Ind AS 116 Lease Accounting")
    parser.add_argument("--db", help="Path to the SQLite database file")
    parser.add_argument("--demo", action="store_true", help="Load demonstration leases if the database is empty")
    parser.add_argument("--self-test", action="store_true",
                        help="Start with a temporary demo database, generate April 2027 journals, open every screen, "
                             "write self_test.log and exit (used to verify the built .exe)")
    args, qt_args = parser.parse_known_args()

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as exc:
        raise SystemExit(
            f"The PySide6 package is not installed ({exc}).\n"
            "Start the program with run_from_source.bat - it installs everything automatically.") from exc

    from lease_app.db.database import Database, app_data_dir
    from lease_app.services import LeaseService
    from lease_app.ui.main_window import MainWindow

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("Ind AS 116 Lease Accounting")
    if args.self_test:
        import tempfile
        db_path = Path(tempfile.mkdtemp()) / "self_test.sqlite"
        args.demo = True
    else:
        db_path = Path(args.db) if args.db else app_data_dir() / "lease_accounting.sqlite"
    db = Database(db_path)
    try:
        db.auto_backup_if_due()
    except Exception as exc:  # never block start-up because of a backup problem
        print("Auto-backup failed:", exc)
    svc = LeaseService(db)
    if args.demo and not svc.repo.lease_ids():
        from lease_app.sample_data import load_sample_data
        load_sample_data(svc.repo)
    sys.excepthook = _excepthook
    win = MainWindow(svc)
    win.show()
    if args.self_test:
        return self_test(app, win, svc)
    if not svc.repo.lease_ids():
        QMessageBox.information(win, "Welcome",
                                "The database is empty.\n\nAdd leases in 'Lease Master' (or import the Excel template), "
                                "or load the demonstration leases from 'Settings > Load sample (demo) data'.")
    return app.exec()


def self_test(app, win, svc) -> int:
    """Exercise the engine and every screen; result written to self_test.log (exit code 0 = pass)."""
    from datetime import date
    from lease_app.ui.main_window import SECTIONS
    lines_out = []
    try:
        lines = svc.generate_month(date(2027, 4, 1))
        dr = sum(l.debit for l in lines)
        cr = sum(l.credit for l in lines)
        lines_out.append(f"April 2027 journals: {len(lines)} lines, debit {dr}, credit {cr}")
        if dr != cr or not lines:
            raise RuntimeError("journals not balanced")
        for name, _ in SECTIONS:
            win.goto(name)
            app.processEvents()
            lines_out.append(f"screen ok: {name}")
        lines_out.append("SELF-TEST PASSED")
        code = 0
    except Exception:
        lines_out.append(traceback.format_exc())
        lines_out.append("SELF-TEST FAILED")
        code = 1
    (log_dir() / "self_test.log").write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print("\n".join(lines_out))
    win.close()
    return code


def main():
    try:
        code = run()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            report_error("The application could not start", str(exc.code))
        raise
    except Exception:
        report_error("The application could not start", traceback.format_exc())
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
