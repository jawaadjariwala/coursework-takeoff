"""One place for colour and pen choices, so the canvas reads as one drawing."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# Paper, not a dark IDE. Estimators work from printed and scanned drawings and
# the app sits next to them all day.
PAPER = QColor("#F7F5F1")
GRID = QColor("#E3DED6")
GRID_MAJOR = QColor("#D2CABE")
INK = QColor("#2A2724")
MUTED = QColor("#8A8178")

# Assemblies are distinguished by hue, with block warm and veneer red, which
# is roughly how they read on a real drawing.
ASSEMBLY_COLORS = {
    "cmu6": QColor("#6E8CA0"),
    "cmu8": QColor("#4A6C8A"),
    "cmu12": QColor("#2F4D67"),
    "brick4": QColor("#A6563C"),
}
ASSEMBLY_FALLBACK = QColor("#5B6770")

SELECTED = QColor("#C8841A")
PREVIEW = QColor("#1A7F6B")

# Junction markers. The colours carry meaning: green is a corner that needed
# nothing, amber moved material, red wants a human.
JUNCTION_COLORS = {
    "L": QColor("#3E8E6F"),
    "T": QColor("#C8841A"),
    "X": QColor("#B4503C"),
    "multi": QColor("#8E3EA8"),
}

OPENING = QColor("#FFFFFF")
OPENING_EDGE = QColor("#6B625A")

CALIBRATION = QColor("#1A7F6B")


def mono(size: int = 11) -> QFont:
    f = QFont("Menlo")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(size)
    return f


def ui_font(size: int = 12, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f
