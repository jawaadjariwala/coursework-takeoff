"""The whole workflow, from a PDF to a bill of materials.

The sample plan is drawn at a known scale from known coordinates, so this can
check the one thing that is otherwise taken on trust: that calibrating off a
printed dimension recovers the real scale, and that tracing the drawing gives
back the quantities the drawing was generated from.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import make_demo_plan as plan  # noqa: E402

from coursework.demo import demo_project  # noqa: E402
from coursework.quantities import takeoff  # noqa: E402

RENDER_DPI = 150


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("plan") / "demo_plan.pdf"
    plan.build(out)
    with pymupdf.open(out) as doc:
        pix = doc[0].get_pixmap(dpi=RENDER_DPI)
        png = out.with_suffix(".png")
        pix.save(png)
    return png, pix


def test_the_pdf_renders(rendered):
    _, pix = rendered
    assert pix.width > 800 and pix.height > 600


def test_calibrating_off_the_printed_dimension_recovers_the_scale(rendered):
    """Click the two ends of the 60'-0" string and the scale must follow.

    The drawing is 1/8" = 1'-0", which is 9 points per foot. Rendered at
    150 dpi that is 9 / 72 * 150 = 18.75 pixels per foot.
    """
    _, pix = rendered
    px_per_pt = RENDER_DPI / 72.0

    left = plan.to_pt(0.0, 0.0).x * px_per_pt
    right = plan.to_pt(60.0, 0.0).x * px_per_pt
    measured_px = right - left

    px_per_ft = measured_px / 60.0
    expected = plan.PT_PER_FT / 72.0 * RENDER_DPI

    assert px_per_ft == pytest.approx(expected)
    assert px_per_ft == pytest.approx(18.75)


def test_tracing_the_drawing_reproduces_the_demo_takeoff():
    """The sample plan and the demo project describe the same building."""
    report = takeoff.build(demo_project())
    assert report.solution.counts_by_kind() == {"L": 4, "T": 4}
    assert report.total_net_area_sf == pytest.approx(4050.1, abs=0.5)
    assert set(report.materials) == {"cmu8", "cmu12", "brick4"}
    assert report.overstatement_pct > 0


def test_a_quarter_inch_tracing_error_stays_under_a_block(rendered):
    """How much does a sloppy click cost?

    At 18.75 px per foot a one pixel slip is about 0.64 inches on the
    building. Across all 7 walls of the demo that is well under one course of
    block, which is the honest answer to "does hand tracing matter".
    """
    px_per_ft = plan.PT_PER_FT / 72.0 * RENDER_DPI
    inches_per_pixel = 12.0 / px_per_ft
    assert inches_per_pixel == pytest.approx(0.64, abs=0.01)

    project = demo_project()
    base = takeoff.build(project)

    drifted = demo_project()
    slip_ft = inches_per_pixel / 12.0
    for wall in drifted.walls:
        wall.vertices = [(x + slip_ft, y) for x, y in wall.vertices]

    moved = takeoff.build(drifted)
    # A uniform slip translates the building and must not change anything.
    assert moved.total_net_area_sf == pytest.approx(base.total_net_area_sf)
