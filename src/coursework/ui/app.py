"""Main window: toolbar, canvas, panels, and the edit-to-report loop.

Every edit runs the full takeoff again. That sounds wasteful and is not: the
solver handles a 220 wall plan in about 7 ms, so recomputing on each change is
cheaper than inventing a dependency graph, and it means the report on screen
is never stale.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from ..demo import demo_project
from ..model.types import Project, Wall
from ..model.units import UnitParseError, format_ft_in, parse_ft_in
from ..quantities import render, takeoff
from ..quantities.catalog import DEFAULT_ASSEMBLY
from ..store import sqlite_store
from .canvas import DEFAULT_PX_PER_FT, Mode, PlanView
from .panels import JunctionLegend, ReportPanel, RulesPanel, WallPanel

DEFAULT_WALL_HEIGHT = 10.0


class MainWindow(QMainWindow):
    def __init__(self, path: str | None = None, *, demo_plan: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("Coursework")
        self.resize(1680, 980)

        self.project = Project()
        self.path: Path | None = None
        self._report = None

        self.view = PlanView()
        self.setCentralWidget(self.view)

        self.wall_panel = WallPanel()
        self.rules_panel = RulesPanel()
        self.legend = JunctionLegend()
        self.report_panel = ReportPanel()

        side = QTabWidget()
        side.addTab(self.wall_panel, "Wall")
        side.addTab(self.rules_panel, "Rules")
        side.addTab(self.legend, "Legend")
        self._dock("Properties", side, Qt.DockWidgetArea.RightDockWidgetArea, 330)
        self._dock(
            "Takeoff", self.report_panel, Qt.DockWidgetArea.RightDockWidgetArea, 720
        )

        self._build_actions()
        self.statusBar().showMessage("Ready")

        self.view.wall_clicked.connect(self._on_wall_clicked)
        self.view.junction_clicked.connect(self._on_junction_clicked)
        self.view.wall_finished.connect(self._on_wall_finished)
        self.view.calibration_done.connect(self._on_calibration)
        self.view.status.connect(lambda t: self.statusBar().showMessage(t))
        self.wall_panel.changed.connect(self.refresh)
        self.wall_panel.delete_requested.connect(self._delete_wall)
        self.rules_panel.changed.connect(self._on_rules_changed)

        if path:
            self.open_path(Path(path))
        elif demo_plan:
            self.load_demo_plan()
        else:
            self.load_demo()

    def _dock(self, title: str, widget: QWidget, area, width: int) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.addDockWidget(area, dock)
        widget.setMinimumWidth(width)
        return dock

    # ------------------------------------------------------------- actions

    def _build_actions(self) -> None:
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        menu_file = self.menuBar().addMenu("&File")
        menu_tools = self.menuBar().addMenu("&Tools")

        def act(text, slot, shortcut=None, to_bar=True, menu=None, checkable=False):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            if to_bar:
                bar.addAction(a)
            (menu or menu_file).addAction(a)
            return a

        act("Open", self.open_file, QKeySequence.StandardKey.Open)
        act("Save", self.save, QKeySequence.StandardKey.Save)
        act("Save As", self.save_as, "Ctrl+Shift+S", to_bar=False)
        bar.addSeparator()
        act("Load plan", self.load_plan, None, menu=menu_file)
        act("Demo", self.load_demo, None, menu=menu_file)
        bar.addSeparator()

        self.act_select = act("Select", lambda: self.set_mode(Mode.SELECT), "1",
                              menu=menu_tools, checkable=True)
        self.act_calibrate = act("Set scale", lambda: self.set_mode(Mode.CALIBRATE), "2",
                                 menu=menu_tools, checkable=True)
        self.act_draw = act("Draw wall", lambda: self.set_mode(Mode.DRAW_WALL), "3",
                            menu=menu_tools, checkable=True)
        bar.addSeparator()
        act("Fit", self.view.fit, "Ctrl+0", menu=menu_tools)
        act("Export CSV", self.export_csv, "Ctrl+E", menu=menu_file)
        self.set_mode(Mode.SELECT)

    def set_mode(self, mode: Mode) -> None:
        self.view.set_mode(mode)
        self.act_select.setChecked(mode is Mode.SELECT)
        self.act_calibrate.setChecked(mode is Mode.CALIBRATE)
        self.act_draw.setChecked(mode is Mode.DRAW_WALL)
        hints = {
            Mode.SELECT: "Click a wall to edit it. Shift-drag to pan, wheel to zoom.",
            Mode.CALIBRATE: "Click two points a known distance apart.",
            Mode.DRAW_WALL: (
                "Click to place vertices. Double-click or Enter to finish, "
                "Esc to cancel."
            ),
        }
        self.statusBar().showMessage(hints[mode])

    # --------------------------------------------------------------- files

    def load_demo(self) -> None:
        self.project = demo_project()
        self.project.px_per_ft = DEFAULT_PX_PER_FT
        self.path = None
        self._after_load()

    def load_demo_plan(self) -> None:
        """The demo building, already traced over the sample drawing.

        Renders the sample PDF to a PNG next to it, then positions the known
        walls over it. Useful for seeing the overlay without tracing by hand.
        """
        from ..demo import PLAN_DPI, demo_project_on_plan

        pdf = Path(__file__).resolve().parents[3] / "assets" / "demo_plan.pdf"
        if not pdf.exists():
            QMessageBox.warning(
                self, "No sample plan",
                f"{pdf} is missing. Run tools/make_demo_plan.py to create it.",
            )
            return self.load_demo()
        png = self._render_pdf(pdf, dpi=PLAN_DPI)
        if png is None:
            return self.load_demo()
        self.project = demo_project_on_plan(str(png))
        self.path = None
        self._after_load()

    def open_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Open takeoff", "", "Takeoff files (*.ctk);;All files (*)"
        )
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> None:
        try:
            self.project = sqlite_store.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open", str(exc))
            return
        self.path = path
        self._after_load()

    def save(self) -> None:
        if self.path is None:
            self.save_as()
            return
        try:
            sqlite_store.save(self.project, self.path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self.statusBar().showMessage(f"Saved {self.path}")

    def save_as(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save takeoff", "takeoff.ctk", "Takeoff files (*.ctk)"
        )
        if name:
            self.path = Path(name)
            self.save()

    def load_plan(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Load plan", "", "Plans (*.pdf *.png *.jpg *.jpeg);;All files (*)"
        )
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() == ".pdf":
            path = self._render_pdf(path)
            if path is None:
                return
        self.project.plan_path = str(path)
        self.view.set_project(self.project, self.view.solution)
        self.view.fit()
        self.statusBar().showMessage(
            "Plan loaded. Set the scale before drawing walls."
        )
        self.set_mode(Mode.CALIBRATE)

    def _render_pdf(self, path: Path, dpi: int = 150) -> Path | None:
        """Rasterise page one so the underlay stays sharp when zoomed."""
        try:
            import pymupdf
        except ImportError:
            QMessageBox.critical(self, "PDF support missing", "pymupdf is not installed")
            return None
        try:
            with pymupdf.open(path) as doc:
                page = doc[0]
                pix = page.get_pixmap(dpi=dpi)
            out = Path(tempfile.gettempdir()) / f"coursework_{path.stem}.png"
            pix.save(out)
            return out
        except Exception as exc:
            QMessageBox.critical(self, "Could not read PDF", str(exc))
            return None

    def export_csv(self) -> None:
        if self._report is None:
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "Export takeoff", "takeoff.csv", "CSV (*.csv)"
        )
        if not name:
            return
        Path(name).write_text(render.as_csv(self._report))
        self.statusBar().showMessage(f"Exported {name}")

    # -------------------------------------------------------------- edits

    def _on_calibration(self, pixels: float, a: QPointF, b: QPointF) -> None:
        if pixels <= 0:
            return
        text, ok = QInputDialog.getText(
            self,
            "Set scale",
            f"That line is {pixels:,.1f} pixels.\nHow long is it on the drawing?",
            text="20'-0\"",
        )
        if not ok:
            return
        try:
            feet = parse_ft_in(text)
        except UnitParseError as exc:
            QMessageBox.warning(self, "Could not read that dimension", str(exc))
            return
        if feet <= 0:
            return
        self.project.px_per_ft = pixels / feet
        self.statusBar().showMessage(
            f"Scale set: {self.project.px_per_ft:,.3f} px per ft "
            f"({format_ft_in(feet)} over {pixels:,.1f} px)"
        )
        self.set_mode(Mode.SELECT)
        self.refresh()

    def _on_wall_finished(self, vertices: list) -> None:
        wall = Wall(
            id=self.project.next_wall_id(),
            vertices=[tuple(v) for v in vertices],
            assembly_key=DEFAULT_ASSEMBLY,
            height_ft=DEFAULT_WALL_HEIGHT,
        )
        self.project.walls.append(wall)
        self.view.selected_wall = wall.id
        self.refresh()
        self.wall_panel.set_wall(wall, self._report)

    def _on_junction_clicked(self, junction) -> None:
        """Explain a junction in the words the report uses."""
        names = {
            "L": "L corner",
            "T": "T intersection",
            "X": "X crossing",
            "multi": "Multi-way junction",
        }
        walls = ", ".join(str(w) for w in junction.wall_ids)
        if junction.adjustments:
            moved = "; ".join(
                f"wall {wid} {'+' if d >= 0 else '-'}{format_ft_in(abs(d))}"
                for wid, d in sorted(junction.adjustments.items())
            )
        else:
            moved = "no change"
        self.statusBar().showMessage(
            f"{names.get(junction.kind.value, junction.kind.value)} "
            f"(walls {walls}): {junction.note} -> {moved}"
        )

    def _on_wall_clicked(self, wall_id: int) -> None:
        self.wall_panel.set_wall(self.project.wall(wall_id), self._report)

    def _delete_wall(self, wall_id: int) -> None:
        self.project.walls = [w for w in self.project.walls if w.id != wall_id]
        self.project.openings = [o for o in self.project.openings if o.wall_id != wall_id]
        self.view.selected_wall = None
        self.wall_panel.set_wall(None)
        self.refresh()

    def _on_rules_changed(self) -> None:
        self.rules_panel.apply_to(self.project)
        self.refresh()

    # ------------------------------------------------------------ refresh

    def _after_load(self) -> None:
        self.rules_panel.set_project(self.project)
        self.view.selected_wall = None
        self.wall_panel.set_wall(None)
        self.refresh()
        self.view.fit()
        title = self.path.name if self.path else self.project.name
        self.setWindowTitle(f"Coursework  |  {title}")

    def refresh(self) -> None:
        """Re-solve and redraw. Cheap enough to run on every keystroke."""
        self._report = takeoff.build(self.project)
        self.view.set_project(self.project, self._report.solution)
        self.report_panel.show_report(render.as_text(self._report))
        if self.view.selected_wall is not None:
            try:
                self.wall_panel.set_wall(
                    self.project.wall(self.view.selected_wall), self._report
                )
            except KeyError:
                self.wall_panel.set_wall(None)


def run(path: str | None = None, *, demo_plan: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Coursework")
    window = MainWindow(path, demo_plan=demo_plan)
    window.show()
    return app.exec()
