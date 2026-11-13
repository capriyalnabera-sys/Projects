"""Main application window with left-hand navigation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from ..services import LeaseService
from . import pages

STYLE = """
QWidget { font-family: 'Segoe UI', Arial; font-size: 10pt; color: #1f2937; }
QMainWindow, QStackedWidget > QWidget { background: #ffffff; }
#nav { background: #1F4E78; border: none; color: white; font-size: 10.5pt; padding-top: 6px; }
#nav::item { padding: 9px 14px; color: #e5edf5; }
#nav::item:selected { background: #2E75B6; color: white; border-left: 4px solid #FFC000; }
#nav::item:hover { background: #2a5f8f; }
#brand { background: #17375E; color: white; font-size: 12pt; font-weight: 600; padding: 14px; }
#pageTitle { font-size: 16pt; font-weight: 600; color: #1F4E78; padding: 4px 0; }
#pageSub { color: #555; padding-bottom: 6px; }
QPushButton { background: #f3f4f6; border: 1px solid #c7ccd3; border-radius: 4px; padding: 6px 12px; }
QPushButton:hover { background: #e5e7eb; }
QPushButton[primary="true"] { background: #2E75B6; color: white; border: 1px solid #1F4E78; }
QPushButton[primary="true"]:hover { background: #1F4E78; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit { border: 1px solid #c7ccd3; border-radius: 3px; padding: 4px; background: white; }
QTableView { gridline-color: #e5e7eb; selection-background-color: #DDEBF7; selection-color: #000; alternate-background-color: #f8fafc; }
QHeaderView::section { background: #DDEBF7; padding: 5px; border: none; border-right: 1px solid #c7d7ea; font-weight: 600; }
QTabBar::tab { padding: 7px 14px; }
QTabBar::tab:selected { background: #DDEBF7; }
#kpi { background: #f8fafc; border: 1px solid #dbe3ec; border-radius: 6px; }
#kpiTitle { color: #555; }
#kpiValue { font-size: 15pt; font-weight: 600; color: #1F4E78; }
#kpiSub { color: #777; font-size: 9pt; }
#totals { font-weight: 600; padding: 6px; background: #f3f4f6; }
QGroupBox { font-weight: 600; border: 1px solid #dbe3ec; border-radius: 4px; margin-top: 10px; padding-top: 10px; }
"""

SECTIONS = [
    ("Dashboard", pages.DashboardPage),
    ("Lease Master", pages.LeaseMasterPage),
    ("Rent Escalation", pages.EscalationPage),
    ("Payment Schedule", pages.PaymentSchedulePage),
    ("Lease Calculations", pages.CalculationsPage),
    ("Modifications", pages.ModificationPage),
    ("Terminations", pages.TerminationPage),
    ("Security Deposits", pages.DepositPage),
    ("Monthly Accounting", pages.MonthlyAccountingPage),
    ("GL Reconciliation", pages.GLReconPage),
    ("Reports", pages.ReportsPage),
    ("Settings", pages.SettingsPage),
    ("Backup and Restore", pages.BackupPage),
]


class MainWindow(QMainWindow):
    def __init__(self, svc: LeaseService):
        super().__init__()
        self.svc = svc
        self.setWindowTitle("Ind AS 116 Lease Accounting")
        self.resize(1400, 860)
        self.setStyleSheet(STYLE)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        left = QWidget()
        left.setFixedWidth(220)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        brand = QLabel("Ind AS 116\nLease Accounting")
        brand.setObjectName("brand")
        ll.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        ll.addWidget(self.nav, 1)
        lay.addWidget(left)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.pages = []
        for name, cls in SECTIONS:
            self.nav.addItem(name)
            page = cls(self)
            page.layout().setContentsMargins(18, 12, 18, 12)
            self.pages.append(page)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.show_page)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Database: {svc.db.path}    User: {svc.db.user}    Offline desktop mode")
        self.nav.setCurrentRow(0)

    def show_page(self, i):
        self.stack.setCurrentIndex(i)
        self.pages[i].refresh()

    def goto(self, name):
        for i, (n, _) in enumerate(SECTIONS):
            if n == name:
                self.nav.setCurrentRow(i)
                return self.pages[i]
