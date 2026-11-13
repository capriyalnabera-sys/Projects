"""Ind AS 116 Lease Accounting - Windows desktop application entry point.

Run:  python main.py                (uses the database in %LOCALAPPDATA%\\IndAS116LeaseApp)
      python main.py --db my.sqlite (use a specific database file)
      python main.py --demo         (load the demonstration leases on first start)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Ind AS 116 Lease Accounting")
    parser.add_argument("--db", help="Path to the SQLite database file")
    parser.add_argument("--demo", action="store_true", help="Load demonstration leases if the database is empty")
    args, qt_args = parser.parse_known_args()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from lease_app.db.database import Database, app_data_dir
    from lease_app.services import LeaseService
    from lease_app.ui.main_window import MainWindow

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("Ind AS 116 Lease Accounting")
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
    win = MainWindow(svc)
    win.show()
    if not svc.repo.lease_ids():
        QMessageBox.information(win, "Welcome",
                                "The database is empty.\n\nAdd leases in 'Lease Master' (or import the Excel template), "
                                "or load the demonstration leases from 'Settings > Load sample (demo) data'.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
