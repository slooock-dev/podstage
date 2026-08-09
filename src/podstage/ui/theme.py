"""Design tokens + stylesheet for the podstage window.

Direction: precision & density (a power-user server tool) — dark, borders-only
depth, one accent, monospace for data. Spacing on a 4px grid, radius system
6/8px, four-level contrast hierarchy.
"""

from pathlib import Path

from PyQt6.QtCore import QPointF, QStandardPaths, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPolygonF
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


# -- stepper arrows ---------------------------------------------------------
# Styling a widget through a stylesheet drops Qt's own rendering of its
# sub-controls, so spin boxes and combos need their arrows supplied here. Qt
# cannot draw a triangle from a stylesheet: the CSS border trick that works in
# browsers comes out as a small filled rectangle (verified). So the arrows are
# painted to real files in the cache dir at startup and the stylesheet points
# at those, which keeps the theme self-contained without committing binary
# assets and lets the colour follow the palette above.
_ARROW_W, _ARROW_H = 9, 5


def _draw_arrow(path: Path, colour: str, *, down: bool) -> None:
    pix = QPixmap(_ARROW_W, _ARROW_H)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    if down:
        points = [(0, 0), (_ARROW_W, 0), (_ARROW_W / 2, _ARROW_H)]
    else:
        points = [(0, _ARROW_H), (_ARROW_W, _ARROW_H), (_ARROW_W / 2, 0)]
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.end()
    pix.save(str(path), "PNG")


def arrow_icons() -> dict[str, str]:
    """``{name: path}`` for the stepper arrows, (re)drawn on each start.

    Needs a QApplication, so this runs from the window rather than at import.
    """
    cache = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation) or "/tmp") / "arrows"
    cache.mkdir(parents=True, exist_ok=True)
    icons = {}
    for name, colour, down in (("up", SECONDARY, False), ("down", SECONDARY, True),
                               ("up-off", FAINT, False), ("down-off", FAINT, True)):
        target = cache / f"{name}.png"
        _draw_arrow(target, colour, down=down)
        icons[name] = target.as_posix()
    return icons


def qss() -> str:
    """The stylesheet with the freshly drawn arrow paths filled in.

    A read-only or full cache dir costs the arrows, not the window: Qt draws
    nothing for a missing image, which is exactly the state this replaced.
    """
    try:
        icons = arrow_icons()
    except OSError:
        return QSS
    return QSS + f"""
QSpinBox::up-arrow {{ image: url("{icons['up']}"); }}
QSpinBox::down-arrow, QComboBox::down-arrow {{ image: url("{icons['down']}"); }}
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {{
    image: url("{icons['up-off']}");
}}
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off,
QComboBox::down-arrow:disabled {{ image: url("{icons['down-off']}"); }}
"""


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
/* Sub-heading INSIDE a card (the doctor check groups): brighter than the
   muted detail text it sits above, but without the card kicker's uppercase
   letter-spacing, so it never competes with the card title. */
QLabel[groupTitle="true"] {{ color: {FG}; font-size: 11px; font-weight: 600; }}
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
/* Neutral: a fact about a path this install does not take. Muted on
   purpose, so "cannot run here" never reads as a green all-clear. */
QLabel[status="info"] {{ color: {FAINT}; }}

/* -- controls ----------------------------------------------------------- */
QPushButton {{
    background: #22262c; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 14px; color: {FG};
}}
QPushButton:hover {{ background: #2e343c; border-color: #3c434c; }}
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
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: #3c434c; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
/* Sub-controls of spin boxes and combos. Styling a widget through a
   stylesheet at all makes Qt drop the NATIVE rendering of its sub-controls,
   so without explicit rules the steppers are bare boxes with no arrows. The
   buttons are styled here; the arrow images come from qss(), which paints
   them at startup (see the stepper-arrow section above). */
QComboBox::drop-down {{ border: none; width: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; background: transparent; border: none;
    width: 16px; margin-right: 2px;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: rgba(255,255,255,0.06); border-radius: 3px;
}}
/* The arrow images themselves are appended by qss(): they are painted at
   startup, because a stylesheet cannot draw a triangle (see _draw_arrow). */
QSpinBox::up-arrow, QSpinBox::down-arrow, QComboBox::down-arrow {{
    width: 9px; height: 5px;
}}
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
