"""Side panels: wall properties, estimating rules, and the live report."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..model.types import Project, Wall
from ..model.units import format_ft_in
from ..quantities.catalog import CATALOG
from ..quantities.takeoff import Report
from . import theme


class WallPanel(QWidget):
    """Edit the selected wall. Every change re-runs the takeoff."""

    changed = Signal()
    delete_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._wall: Wall | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        box = QGroupBox("Selected wall")
        form = QFormLayout(box)

        self.label_edit = QLineEdit()
        self.assembly = QComboBox()
        for key, asm in CATALOG.items():
            self.assembly.addItem(asm.label, key)
        self.height = QDoubleSpinBox()
        self.height.setRange(0.5, 200.0)
        self.height.setSingleStep(0.5)
        self.height.setSuffix(" ft")
        self.readout = QLabel("no wall selected")
        self.readout.setWordWrap(True)
        self.readout.setFont(theme.mono(10))

        form.addRow("Label", self.label_edit)
        form.addRow("Assembly", self.assembly)
        form.addRow("Height", self.height)
        form.addRow(self.readout)

        self.delete_button = QPushButton("Delete wall")
        form.addRow(self.delete_button)
        layout.addWidget(box)
        layout.addStretch(1)

        self.label_edit.editingFinished.connect(self._push)
        self.assembly.currentIndexChanged.connect(self._push)
        self.height.valueChanged.connect(self._push)
        self.delete_button.clicked.connect(self._delete)
        self.set_wall(None)

    def set_wall(self, wall: Wall | None, report: Report | None = None) -> None:
        self._wall = wall
        self._loading = True
        enabled = wall is not None
        for w in (self.label_edit, self.assembly, self.height, self.delete_button):
            w.setEnabled(enabled)
        if wall is not None:
            self.label_edit.setText(wall.label)
            index = self.assembly.findData(wall.assembly_key)
            self.assembly.setCurrentIndex(max(0, index))
            self.height.setValue(wall.height_ft)
            self.readout.setText(self._describe(wall, report))
        else:
            self.label_edit.clear()
            self.readout.setText("no wall selected")
        self._loading = False

    def _describe(self, wall: Wall, report: Report | None) -> str:
        if report is None:
            return f"gross {format_ft_in(wall.centerline_length_ft)}"
        line = next((x for x in report.lines if x.wall_id == wall.id), None)
        if line is None:
            return f"gross {format_ft_in(wall.centerline_length_ft)}"
        correction = line.junction_correction_ft
        sign = "+" if correction >= 0 else "-"
        return (
            f"gross   {format_ft_in(line.gross_length_ft)}\n"
            f"adjust  {sign}{format_ft_in(abs(correction))}\n"
            f"net     {format_ft_in(line.net_length_ft)}\n"
            f"area    {line.net_area_sf:,.1f} sf\n"
            f"units   {line.units:,.0f}"
        )

    def _push(self) -> None:
        if self._loading or self._wall is None:
            return
        self._wall.label = self.label_edit.text()
        self._wall.assembly_key = self.assembly.currentData()
        self._wall.height_ft = self.height.value()
        self.changed.emit()

    def _delete(self) -> None:
        if self._wall is not None:
            self.delete_requested.emit(self._wall.id)


class RulesPanel(QWidget):
    """The estimating assumptions, visible and editable rather than buried."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        box = QGroupBox("Estimating rules")
        form = QFormLayout(box)

        self.waste = QDoubleSpinBox()
        self.waste.setRange(0.0, 50.0)
        self.waste.setSuffix(" %")
        self.waste.setSingleStep(1.0)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 200.0)
        self.threshold.setSuffix(" sf")
        self.threshold.setSingleStep(1.0)

        form.addRow("Waste factor", self.waste)
        form.addRow("Deduct openings over", self.threshold)

        note = QLabel(
            "5 to 10% waste is the usual allowance. Openings under the "
            "threshold are left in, because the material saved is offset by "
            "cutting and jamb labour."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.MUTED.name()};")
        form.addRow(note)

        layout.addWidget(box)
        layout.addStretch(1)

        self.waste.valueChanged.connect(self._push)
        self.threshold.valueChanged.connect(self._push)

    def set_project(self, project: Project) -> None:
        self._loading = True
        self.waste.setValue(project.settings.waste_factor * 100.0)
        self.threshold.setValue(project.settings.min_deduct_area_sf)
        self._loading = False

    def apply_to(self, project: Project) -> None:
        project.settings.waste_factor = self.waste.value() / 100.0
        project.settings.min_deduct_area_sf = self.threshold.value()

    def _push(self) -> None:
        if not self._loading:
            self.changed.emit()


class ReportPanel(QPlainTextEdit):
    """The takeoff, recomputed on every edit."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setFont(theme.mono(10))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setPlaceholderText("Draw a wall to see the takeoff.")

    def show_report(self, text: str) -> None:
        position = self.verticalScrollBar().value()
        self.setPlainText(text)
        self.verticalScrollBar().setValue(position)


class JunctionLegend(QWidget):
    """What the dots on the canvas mean."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        box = QGroupBox("Junctions")
        inner = QVBoxLayout(box)
        rows = [
            ("L", "L corner", "centerline self-corrects, no change"),
            ("T", "T intersection", "butting wall loses half the host"),
            ("X", "X crossing", "non-owner loses the full crossing"),
            ("multi", "multi-way", "flagged for review"),
        ]
        for key, name, detail in rows:
            color = theme.JUNCTION_COLORS[key].name()
            label = QLabel(
                f'<span style="color:{color};font-size:16px">&#9679;</span> '
                f"<b>{name}</b><br>"
                f"<span style='color:{theme.MUTED.name()}'>{detail}</span>"
            )
            label.setTextFormat(Qt.TextFormat.RichText)
            inner.addWidget(label)
        layout.addWidget(box)
        layout.addStretch(1)
