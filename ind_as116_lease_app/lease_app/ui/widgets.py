"""Reusable Qt widgets: table model, register entry form, helpers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QRegularExpression, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableView, QVBoxLayout, QWidget)

from ..db.repository import ValidationError
from ..engine.decimal_utils import D, fmt_inr
from ..registers import Register, parse_date

BLANK_DATE = QDate(1900, 1, 1)


def fmt_value(v, ftype=None):
    if v is None or v == "":
        return ""
    if isinstance(v, Decimal) or ftype == "money":
        return fmt_inr(v)
    if ftype == "decimal":
        try:
            dv = D(v)
            return fmt_inr(dv) if abs(dv) >= 1000 else f"{dv.normalize():f}"
        except ValueError:
            return str(v)
    if isinstance(v, date) or ftype == "date":
        d = v if isinstance(v, date) else parse_date(v)
        return d.strftime("%d-%m-%Y") if d else ""
    return str(v)


class DictTableModel(QAbstractTableModel):
    """columns = list of (key, label, ftype)."""

    def __init__(self, columns, rows=None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows = rows or []
        self.highlight = None   # callable(row) -> QColor | None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _, ftype = self.columns[index.column()]
        v = row.get(key)
        if role == Qt.DisplayRole:
            return fmt_value(v, ftype)
        if role == Qt.UserRole:          # sort key
            if "_sort_" + key in row:
                return row["_sort_" + key]
            if ftype in ("money", "decimal") or isinstance(v, Decimal):
                try:
                    return float(D(v))
                except ValueError:
                    return 0.0
            if isinstance(v, date):
                return v.isoformat()
            return "" if v is None else str(v)
        if role == Qt.TextAlignmentRole and (ftype in ("money", "decimal", "int") or isinstance(v, Decimal)):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.BackgroundRole and self.highlight:
            return self.highlight(row)
        if role == Qt.FontRole and row.get("_bold"):
            f = QFont()
            f.setBold(True)
            return f
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section][1]
        return None


class SearchableTable(QWidget):
    def __init__(self, columns, parent=None, search=True):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit(placeholderText="Search...")
        self.search.setClearButtonEnabled(True)
        if search:
            lay.addWidget(self.search)
        self.model = DictTableModel(columns)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setSortRole(Qt.UserRole)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.view)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

    def set_rows(self, rows):
        self.proxy.sort(-1)                       # keep natural (chronological) order until user sorts
        self.view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.model.set_rows(rows)
        self.view.resizeColumnsToContents()
        for i in range(self.model.columnCount()):
            if self.view.columnWidth(i) > 320:
                self.view.setColumnWidth(i, 320)

    def selected_row(self):
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        return self.model.rows[self.proxy.mapToSource(idx[0]).row()]

    def visible_rows(self):
        return [self.model.rows[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]


class DateField(QDateEdit):
    def __init__(self, optional=True):
        super().__init__()
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd-MM-yyyy")
        self.optional = optional
        self.setMinimumDate(BLANK_DATE)
        self.setSpecialValueText(" ")
        self.setDate(BLANK_DATE if optional else QDate.currentDate())

    def value(self):
        d = self.date()
        if d == BLANK_DATE:
            return None
        return date(d.year(), d.month(), d.day())

    def set_value(self, v):
        d = parse_date(v) if v else None
        self.setDate(QDate(d.year, d.month, d.day) if d else BLANK_DATE)


class RecordDialog(QDialog):
    """Auto-generated add / edit form for a register."""

    def __init__(self, repo, reg: Register, record=None, parent=None, preset=None):
        super().__init__(parent)
        self.repo, self.reg, self.record = repo, reg, record
        self.saved_key = None
        self.setWindowTitle(("Edit " if record else "Add ") + reg.title)
        self.resize(640, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setLabelAlignment(Qt.AlignRight)
        self.widgets = {}
        values = dict(record or {})
        for k, v in (preset or {}).items():
            values.setdefault(k, v)
        num_re = QRegularExpressionValidator(QRegularExpression(r"^-?[0-9,]*\.?[0-9]*$"))
        int_re = QRegularExpressionValidator(QRegularExpression(r"^-?[0-9]*$"))
        for f in reg.fields:
            v = values.get(f.key)
            if v is None and not record:
                v = f.default
            if f.ftype == "date":
                w = DateField(optional=True)
                w.set_value(v)
            elif f.ftype in ("choice", "lease"):
                w = QComboBox()
                items = list(f.choices) if f.ftype == "choice" else [""] + repo.lease_ids()
                w.addItems(items)
                if v is not None and str(v) in items:
                    w.setCurrentText(str(v))
            elif f.ftype == "longtext":
                w = QPlainTextEdit()
                w.setFixedHeight(56)
                w.setPlainText("" if v is None else str(v))
            else:
                w = QLineEdit("" if v is None else str(v))
                if f.ftype == "decimal":
                    w.setValidator(num_re)
                elif f.ftype == "int":
                    w.setValidator(int_re)
            if f.readonly and not (f.key == reg.key and not record):
                w.setEnabled(False)
            if f.help:
                w.setToolTip(f.help)
            label = QLabel(f.label + (" *" if f.required else ""))
            if f.required:
                label.setStyleSheet("font-weight:600")
            form.addRow(label, w)
            self.widgets[f.key] = w
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        note = QLabel("* mandatory.  Hover over a field for guidance.")
        note.setStyleSheet("color:#666")
        outer.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.on_save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def values(self):
        out = {}
        for k, w in self.widgets.items():
            if isinstance(w, DateField):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText() or None
            elif isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText() or None
            else:
                out[k] = w.text() or None
        return out

    def on_save(self):
        raw = self.values()
        reason = ""
        if self.record:
            reason, ok = QInputDialog.getText(self, "Reason for change",
                                              "Enter the reason for this change (kept in the audit trail):")
            if not ok:
                return
            if not reason.strip():
                QMessageBox.warning(self, "Reason required", "A change reason is required to edit a record.")
                return
        try:
            self.saved_key = self.repo.save(self.reg, raw, reason,
                                            original_key=self.record[self.reg.key] if self.record else None)
        except ValidationError as e:
            QMessageBox.warning(self, "Please correct the following", "\n".join("• " + m for m in e.errors))
            return
        self.accept()


def button(text, slot=None, primary=False, tip=""):
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def hbox(*widgets, stretch=True):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if x is None:
            lay.addStretch(1)
        elif isinstance(x, str):
            lay.addWidget(QLabel(x))
        else:
            lay.addWidget(x)
    if stretch and None not in widgets:
        lay.addStretch(1)
    return w


def kpi_card(title, value, sub=""):
    f = QFrame()
    f.setObjectName("kpi")
    lay = QVBoxLayout(f)
    t = QLabel(title)
    t.setObjectName("kpiTitle")
    v = QLabel(value)
    v.setObjectName("kpiValue")
    lay.addWidget(t)
    lay.addWidget(v)
    if sub:
        s = QLabel(sub)
        s.setObjectName("kpiSub")
        lay.addWidget(s)
    return f


def save_file_dialog(parent, title, default_name, filt="Excel files (*.xlsx)"):
    path, _ = QFileDialog.getSaveFileName(parent, title, default_name, filt)
    return path


def open_file_dialog(parent, title, filt="Excel files (*.xlsx *.xls)"):
    path, _ = QFileDialog.getOpenFileName(parent, title, "", filt)
    return path


def confirm(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def error(parent, title, text):
    QMessageBox.critical(parent, title, text)


def html_table(headers, rows, money_cols=()):
    h = "".join(f"<th>{x}</th>" for x in headers)
    body = ""
    for r in rows:
        cells = ""
        for i, x in enumerate(r):
            align = ' align="right"' if (i in money_cols or isinstance(x, Decimal)) else ""
            cells += f"<td{align}>{fmt_value(x)}</td>"
        body += f"<tr>{cells}</tr>"
    return f'<table cellspacing="0" cellpadding="4" border="1" style="border-collapse:collapse">' \
           f'<tr style="background:#1F4E78;color:white">{h}</tr>{body}</table>'
