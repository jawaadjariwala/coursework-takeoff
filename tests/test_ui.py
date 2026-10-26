"""The window, driven headlessly.

Qt runs on the offscreen platform here, so these are real widgets handling
real signals in CI, without a display. They cover the wiring between an edit
and the number that comes out of it, which is where a desktop app usually
breaks: the geometry stays correct and the screen stops agreeing with it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from coursework.model.types import Opening, Project, Wall  # noqa: E402
from coursework.quantities import takeoff  # noqa: E402
from coursework.store import sqlite_store  # noqa: E402
from coursework.ui.app import MainWindow  # noqa: E402
from coursework.ui.canvas import Mode  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp):
    w = MainWindow()
    w.resize(1280, 800)
    yield w
    w.close()


def test_window_opens_on_the_demo_and_agrees_with_the_engine(window):
    direct = takeoff.build(window.project)
    assert window._report.total_net_area_sf == pytest.approx(direct.total_net_area_sf)
    assert window._report.solution.counts_by_kind() == {"L": 4, "T": 4}
    assert "TOTAL NET" in window.report_panel.toPlainText()


def test_drawing_a_wall_updates_the_takeoff(window):
    before_walls = len(window.project.walls)
    before_area = window._report.total_net_area_sf

    window.set_mode(Mode.DRAW_WALL)
    # Full width of the shell, so both ends butt an exterior wall.
    window.view.wall_finished.emit([(0.0, 30.0), (60.0, 30.0)])

    assert len(window.project.walls) == before_walls + 1
    assert window._report.total_net_area_sf > before_area
    assert window._report.solution.counts_by_kind()["T"] == 6

    new_wall = window.project.walls[-1]
    line = next(x for x in window._report.lines if x.wall_id == new_wall.id)
    # 60 ft drawn, minus half of each host it butts into.
    assert line.gross_length_ft == pytest.approx(60.0)
    assert line.net_length_ft < 60.0


def test_deleting_a_wall_takes_its_openings_with_it(window):
    wall_id = 3  # north wall, carries three windows
    assert len(window.project.openings_for(wall_id)) == 3
    window._delete_wall(wall_id)
    assert all(w.id != wall_id for w in window.project.walls)
    assert window.project.openings_for(wall_id) == []
    assert window.wall_panel._wall is None


def test_calibration_converts_pixels_to_feet(window):
    from PySide6.QtCore import QPointF

    window.project.px_per_ft = None
    # 240 px measured across a run the user says is 20 ft.
    window.project.px_per_ft = 240.0 / 20.0
    assert window.view.px_per_ft == pytest.approx(12.0)
    # Plan y grows upward, screen y downward, so scene y is negated.
    assert window.view.to_feet(QPointF(120.0, -60.0)) == pytest.approx((10.0, 5.0))
    assert window.view.to_scene((10.0, 5.0)).x() == pytest.approx(120.0)
    assert window.view.to_scene((10.0, 5.0)).y() == pytest.approx(-60.0)


def test_changing_the_waste_factor_changes_the_order(window):
    before = window._report.materials["cmu8"].units_with_waste
    window.rules_panel.waste.setValue(10.0)
    after = window._report.materials["cmu8"].units_with_waste
    assert after > before
    assert window.project.settings.waste_factor == pytest.approx(0.10)
    # Waste must not touch the measured area, only the order quantity.
    assert window._report.materials["cmu8"].units == pytest.approx(
        window._report.materials["cmu8"].units_with_waste / 1.10
    )


def test_changing_the_deduction_threshold_moves_the_area(window):
    """The demo has a 4 sf louver that sits under the default 10 sf floor."""
    before = window._report.total_net_area_sf
    window.rules_panel.threshold.setValue(0.0)
    assert window._report.total_net_area_sf == pytest.approx(before - 4.0)


def test_changing_an_assembly_rebuilds_the_bill(window):
    window.view.selected_wall = 7
    window.wall_panel.set_wall(window.project.wall(7), window._report)
    window.wall_panel.assembly.setCurrentIndex(
        window.wall_panel.assembly.findData("cmu8")
    )
    assert "brick4" not in window._report.materials
    assert window.project.wall(7).assembly_key == "cmu8"


def test_clicking_a_junction_explains_it(window):
    t = next(j for j in window._report.solution.junctions if j.kind.value == "T")
    window._on_junction_clicked(t)
    message = window.statusBar().currentMessage()
    assert "T intersection" in message
    assert "butts into" in message
    # Half of 7-5/8 inch block is 3-13/16 inch.
    assert '3 13/16"' in message


def test_mixed_corner_explanation_names_both_assemblies(window):
    mixed = next(j for j in window._report.solution.junctions if j.adjustments)
    window._on_junction_clicked(mixed)
    message = window.statusBar().currentMessage()
    assert "cmu12" in message and "cmu8" in message


def test_open_and_save_round_trip_through_the_window(window, tmp_path):
    path = tmp_path / "from_ui.ctk"
    window.path = path
    window.save()
    assert path.exists()

    reopened = MainWindow(str(path))
    try:
        assert reopened._report.total_net_area_sf == pytest.approx(
            window._report.total_net_area_sf
        )
    finally:
        reopened.close()


def test_an_empty_project_does_not_crash_the_window(window):
    window.project = Project()
    window.refresh()
    assert window._report.total_net_area_sf == 0.0
    assert window._report.solution.junctions == []


def test_a_project_with_no_scale_still_draws(window):
    window.project = Project(
        walls=[Wall(1, [(0, 0), (10, 0)], "cmu8", 8)],
        openings=[Opening(1, 1, 3, 7, 5)],
    )
    window.project.px_per_ft = None
    window.refresh()
    window.view.fit()
    assert window.view.px_per_ft > 0


def test_the_report_panel_matches_the_cli(window, tmp_path):
    from coursework.quantities import render

    path = tmp_path / "x.ctk"
    sqlite_store.save(window.project, path)
    from_disk = render.as_text(takeoff.build(sqlite_store.load(path)))
    assert window.report_panel.toPlainText().strip() == from_disk.strip()
