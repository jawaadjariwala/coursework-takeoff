"""Cases an estimator can check on paper.

Every test here states its arithmetic in the docstring. If one fails, the
docstring says what the answer should have been and why, without anyone
needing to read the solver.
"""

from __future__ import annotations

import math

import pytest

from coursework.geometry.junctions import JunctionKind, solve
from coursework.model.types import Wall
from coursework.quantities.catalog import CATALOG

T8 = CATALOG["cmu8"].thickness_ft  # 7-5/8" actual = 0.635417 ft
T12 = CATALOG["cmu12"].thickness_ft  # 11-5/8" actual
T4 = CATALOG["brick4"].thickness_ft  # 3-5/8" actual

H = 10.0


def wall(i: int, pts, key="cmu8") -> Wall:
    return Wall(i, pts, key, H)


def test_single_wall_is_untouched():
    """One wall, no junctions. Net equals gross, 40 ft."""
    s = solve([wall(1, [(0, 0), (40, 0)])], CATALOG)
    assert s.junctions == []
    assert s.net_length_ft[1] == pytest.approx(40.0)


def test_polyline_interior_vertex_is_not_an_end():
    """A single wall bent 90 degrees mid-run has no junction with itself.

    Centerline 30 + 20 = 50 ft. The bend is an interior vertex, not a free
    end, so nothing is corrected.
    """
    s = solve([wall(1, [(0, 0), (30, 0), (30, 20)])], CATALOG)
    assert s.junctions == []
    assert s.net_length_ft[1] == pytest.approx(50.0)


def test_closed_rectangle_takes_no_correction():
    """Four 8" walls on a 20 x 30 centerline rectangle.

    Centerline perimeter 2 x (20 + 30) = 100 ft. All four junctions are L
    corners between identical assemblies, where the double-counted overlap and
    the uncovered outer notch are both ta*tb/4 and cancel. Net stays 100 ft.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)]),
        wall(2, [(20, 0), (20, 30)]),
        wall(3, [(20, 30), (0, 30)]),
        wall(4, [(0, 30), (0, 0)]),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"L": 4}
    assert s.total_gross_ft == pytest.approx(100.0)
    assert s.total_net_ft == pytest.approx(100.0)
    assert all(j.adjustments == {} for j in s.junctions)


def test_t_intersection_removes_half_the_host_thickness():
    """A partition crossing a 20 ft bay, butting both side walls.

    The partition centerline runs wall-centerline to wall-centerline, so it
    penetrates t/2 into each host. Two T ends, so it overstates by
    2 x (0.635417 / 2) = 0.635417 ft, exactly one wall thickness.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)]),
        wall(2, [(20, 0), (20, 30)]),
        wall(3, [(20, 30), (0, 30)]),
        wall(4, [(0, 30), (0, 0)]),
        wall(5, [(0, 15), (20, 15)]),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"L": 4, "T": 2}
    assert s.net_length_ft[5] == pytest.approx(20.0 - T8)
    assert s.total_net_ft == pytest.approx(120.0 - T8)


def test_t_into_a_thicker_host_removes_more():
    """Butting into 12" block costs more than butting into 8".

    Host is 12" CMU (0.96875 ft actual), so the butting wall loses
    0.96875 / 2 = 0.484375 ft at that end.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)], "cmu12"),
        wall(2, [(10, 0), (10, 12)], "cmu8"),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"T": 1}
    assert s.net_length_ft[2] == pytest.approx(12.0 - T12 / 2)
    assert s.net_length_ft[1] == pytest.approx(20.0)


def test_x_crossing_removes_the_full_owner_thickness():
    """Two walls crossing mid-run, 8" through 8".

    The owner keeps the crossing, the other wall gives up the whole width it
    passes through: 0.635417 ft.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)]),
        wall(2, [(10, -8), (10, 8)]),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"X": 1}
    assert s.total_net_ft == pytest.approx(36.0 - T8)
    loser = s.junctions[0].adjustments
    assert len(loser) == 1
    assert next(iter(loser.values())) == pytest.approx(-T8)


def test_block_outranks_veneer_at_a_crossing():
    """Priority, not wall order, decides who owns shared material.

    Structural block runs continuous and veneer stops against it, so the brick
    wall is the one that loses length regardless of which was drawn first.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)], "brick4"),
        wall(2, [(10, -8), (10, 8)], "cmu8"),
    ]
    s = solve(walls, CATALOG)
    j = s.junctions[0]
    assert j.owner_wall_id == 2
    assert j.adjustments[1] == pytest.approx(-T8)


def test_mixed_assembly_corner_moves_material_without_changing_the_total():
    """8" CMU meets 4" brick veneer at an L corner.

    The overlap (t_cmu/2 x t_brick/2) sits in both bills of material and the
    outer notch of the same area sits in neither. Total plan area is therefore
    already right, but the split is not. The block takes the corner:

        brick loses  t_cmu   / 4 = 0.158854 ft
        block gains  t_brick / 4 = 0.075521 ft

    Those are different lengths but identical areas, because each is converted
    through its own wall thickness:

        0.158854 x 0.302083 = 0.047988 sf
        0.075521 x 0.635417 = 0.047988 sf
    """
    walls = [
        wall(1, [(0, 0), (20, 0)], "cmu8"),
        wall(2, [(20, 0), (20, 15)], "brick4"),
    ]
    s = solve(walls, CATALOG)
    j = s.junctions[0]
    assert j.kind is JunctionKind.L_CORNER
    assert j.owner_wall_id == 1

    assert j.adjustments[2] == pytest.approx(-T8 / 4)
    assert j.adjustments[1] == pytest.approx(+T4 / 4)

    area_moved_from_brick = (T8 / 4) * T4
    area_moved_to_block = (T4 / 4) * T8
    assert area_moved_from_brick == pytest.approx(area_moved_to_block)

    gained = (s.net_length_ft[1] - 20.0) * T8
    lost = (s.net_length_ft[2] - 15.0) * T4
    assert gained + lost == pytest.approx(0.0, abs=1e-12)


def test_same_assembly_corner_is_explicitly_a_no_op():
    """The report has to say why nothing happened, not just show a zero."""
    walls = [wall(1, [(0, 0), (20, 0)]), wall(2, [(20, 0), (20, 15)])]
    s = solve(walls, CATALOG)
    j = s.junctions[0]
    assert j.adjustments == {}
    assert "self-correct" in j.note


def test_three_walls_at_one_point_are_flagged_for_review():
    """A corner post with a partition running off it.

    The pairwise rules still fire, but the interaction of three walls at one
    point is not something this solver claims to resolve exactly, so it says
    so rather than quietly returning a number.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)]),
        wall(2, [(20, 0), (20, 15)]),
        wall(3, [(20, 0), (35, 12)]),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"multi": 1}
    assert s.junctions[0].needs_review
    assert any("needs review" in w for w in s.warnings)


def test_overlapping_walls_are_reported_not_corrected():
    """Two walls traced on top of each other is a mistake, not a junction."""
    walls = [wall(1, [(0, 0), (20, 0)]), wall(2, [(5, 0), (15, 0)])]
    s = solve(walls, CATALOG)
    assert s.junctions == []
    assert any("overlap" in w for w in s.warnings)


def test_correction_larger_than_the_wall_is_clamped_and_reported():
    """A stub shorter than the block it butts into cannot go negative."""
    walls = [
        wall(1, [(0, 0), (20, 0)], "cmu12"),
        wall(2, [(10, 0), (10, 0.2)], "cmu8"),
    ]
    s = solve(walls, CATALOG)
    assert s.net_length_ft[2] == 0.0
    assert any("clamped to zero" in w for w in s.warnings)


def test_degenerate_walls_are_rejected_at_construction():
    with pytest.raises(ValueError):
        Wall(1, [(0, 0)], "cmu8", 10)
    with pytest.raises(ValueError):
        Wall(1, [(0, 0), (10, 0)], "cmu8", 0)


def test_the_published_overstatement_is_what_the_readme_claims():
    """The demo plan in the README must keep matching the code.

    A 20 x 30 shell with two partitions: four L corners contribute nothing and
    four T ends contribute t/2 each, so the centerline figure is high by
    2 x 0.635417 = 1.270833 ft of wall, which at 10 ft tall is 12.71 sf.
    """
    walls = [
        wall(1, [(0, 0), (20, 0)]),
        wall(2, [(20, 0), (20, 30)]),
        wall(3, [(20, 30), (0, 30)]),
        wall(4, [(0, 30), (0, 0)]),
        wall(5, [(0, 10), (20, 10)]),
        wall(6, [(0, 20), (20, 20)]),
    ]
    s = solve(walls, CATALOG)
    assert s.counts_by_kind() == {"L": 4, "T": 4}
    overstated_ft = s.total_gross_ft - s.total_net_ft
    assert overstated_ft == pytest.approx(2 * T8)
    assert overstated_ft * H == pytest.approx(12.708333, abs=1e-5)
    assert math.isclose(overstated_ft / s.total_gross_ft, 0.00908, abs_tol=1e-4)
