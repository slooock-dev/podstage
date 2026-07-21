"""Design tokens + stylesheet for the podstage window.

Direction: precision & density (a power-user server tool) — dark, borders-only
depth, one accent, monospace for data. Spacing on a 4px grid, radius system
6/8px, four-level contrast hierarchy.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

# -- palette ----------------------------------------------------------------
BG = "#141619"        # window
SURFACE = "#1a1d21"   # cards
SUNKEN = "#101214"    # log wells
BORDER = "#282c32"
FG = "#e8eaed"
SECONDARY = "#aab0ba"
MUTED = "#7f858f"
FAINT = "#565c66"
ACCENT = "#3d7eff"
OK = "#3fb968"
WARN = "#d9a53f"
ERR = "#e05263"

MONO = "'JetBrains Mono', 'Fira Code', monospace"


def repolish(w: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    w.style().unpolish(w)
    w.style().polish(w)


QSS = f"""
QWidget {{ background: {BG}; color: {FG}; font-size: 12px; }}
QLabel {{ background: transparent; }}
QRadioButton, QCheckBox {{ background: transparent; }}

/* -- sidebar ------------------------------------------------------------ */
QFrame#sidebar {{ border: none; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 14px; font-weight: 600; letter-spacing: -0.2px; padding: 4px; }}
QListWidget#nav {{ border: none; outline: none; font-size: 12px; }}
QListWidget#nav::item {{ padding: 7px 10px; border-radius: 6px; margin: 1px 0; color: {SECONDARY}; }}
QListWidget#nav::item:hover {{ background: rgba(255,255,255,0.04); }}
QListWidget#nav::item:selected {{ background: rgba(61,126,255,0.14); color: {FG}; }}
QLabel#globalState {{ color: {MUTED}; font-family: {MONO}; font-size: 11px; padding: 4px; }}
QLabel#globalState[state="running"] {{ color: {OK}; }}

/* -- cards -------------------------------------------------------------- */
QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame[card="true"] > QWidget {{ background: transparent; }}
QLabel[cardTitle="true"] {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#pageTitle {{ font-size: 16px; font-weight: 600; letter-spacing: -0.3px; }}

/* -- text roles --------------------------------------------------------- */
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[secondary="true"] {{ color: {SECONDARY}; }}
QLabel[mono="true"] {{ font-family: {MONO}; }}
QLabel#sessionState {{ font-size: 15px; font-weight: 600; }}
QLabel#sessionState[state="running"] {{ color: {OK}; }}
QLabel#sessionState[state="stopped"] {{ color: {MUTED}; }}
QLabel#sessionState[state="busy"] {{ color: {WARN}; }}
QLabel#sessionState[state="error"] {{ color: {ERR}; }}
QLabel[status="ok"] {{ color: {OK}; }}
QLabel[status="warn"] {{ color: {WARN}; }}
QLabel[status="fail"] {{ color: {ERR}; }}

/* -- controls ----------------------------------------------------------- */
QPushButton {{
    background: #22262c; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 14px; color: {FG};
}}
QPushButton:hover {{ background: #2a2f36; }}
QPushButton:pressed {{ background: #1e2227; }}
QPushButton:disabled {{ background: #1c1f24; color: {FAINT}; border-color: #22262c; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #5a91ff; }}
QPushButton[primary="true"]:disabled {{ background: #26354f; border-color: #26354f; color: {FAINT}; }}
QPushButton[danger="true"] {{ background: transparent; border-color: #53333a; color: {ERR}; }}
QPushButton[danger="true"]:hover {{ background: rgba(224,82,99,0.12); }}
QPushButton[danger="true"]:disabled {{ background: transparent; border-color: #2c2529; color: {FAINT}; }}

QComboBox, QSpinBox, QLineEdit {{
    background: #1e2227; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 4px 8px; color: {FG}; selection-background-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
    selection-background-color: rgba(61,126,255,0.2); color: {FG}; outline: none;
}}

QProgressBar {{
    background: #1e2227; border: 1px solid {BORDER}; border-radius: 5px;
    max-height: 10px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

/* -- tables ------------------------------------------------------------- */
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: transparent; outline: none;
    alternate-background-color: rgba(255,255,255,0.02);
}}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:selected {{ background: rgba(61,126,255,0.16); color: {FG}; }}
QHeaderView::section {{
    background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 8px; color: {MUTED}; font-size: 11px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

/* -- log wells ---------------------------------------------------------- */
QPlainTextEdit {{
    background: {SUNKEN}; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: {MONO}; font-size: 11px; color: {SECONDARY};
    selection-background-color: {ACCENT};
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #33383f; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #40464e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #33383f; border-radius: 4px; min-width: 24px; }}

QDialog {{ background: {BG}; }}
QMessageBox {{ background: {BG}; }}
QRadioButton, QCheckBox {{ color: {FG}; spacing: 6px; }}
QToolTip {{ background: {SURFACE}; color: {FG}; border: 1px solid {BORDER}; padding: 4px; }}
"""
