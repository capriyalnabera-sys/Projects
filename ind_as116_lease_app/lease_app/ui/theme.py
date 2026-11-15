"""Force a light (white) theme regardless of the Windows dark / light mode setting."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

TEXT = QColor("#1f2937")
WHITE = QColor("#ffffff")


def apply_light_theme(app):
    try:  # Qt 6.8+: tell Qt to ignore the Windows dark colour scheme
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        pass
    app.setStyle("Fusion")             # Fusion honours our palette on every Windows version
    pal = QPalette()
    roles = {
        QPalette.Window: WHITE, QPalette.WindowText: TEXT, QPalette.Base: WHITE,
        QPalette.AlternateBase: QColor("#f8fafc"), QPalette.Text: TEXT, QPalette.Button: QColor("#f3f4f6"),
        QPalette.ButtonText: TEXT, QPalette.BrightText: QColor("#c00000"), QPalette.ToolTipBase: WHITE,
        QPalette.ToolTipText: TEXT, QPalette.PlaceholderText: QColor("#9ca3af"),
        QPalette.Highlight: QColor("#2E75B6"), QPalette.HighlightedText: WHITE,
        QPalette.Link: QColor("#1F4E78"), QPalette.Light: WHITE, QPalette.Midlight: QColor("#e5e7eb"),
        QPalette.Mid: QColor("#c7ccd3"), QPalette.Dark: QColor("#9ca3af"), QPalette.Shadow: QColor("#6b7280"),
    }
    for group in (QPalette.Active, QPalette.Inactive):
        for role, color in roles.items():
            pal.setColor(group, role, color)
    for role, color in roles.items():
        pal.setColor(QPalette.Disabled, role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#9ca3af"))
    app.setPalette(pal)
    # dialogs and message boxes are top-level windows: give them the white background too
    app.setStyleSheet("QDialog, QMessageBox { background: #ffffff; } "
                      "QMessageBox QLabel { color: #1f2937; } "
                      "QToolTip { background: #ffffff; color: #1f2937; border: 1px solid #c7ccd3; }")
