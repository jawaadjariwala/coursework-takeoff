"""Quantity arithmetic, checked against figures an estimator would recognise."""

from __future__ import annotations

import pytest

from coursework.model.types import Opening, Project, Wall
from coursework.quantities import takeoff
from coursework.quantities.catalog import CATALOG

from . import plans

T8 = CATALOG["cmu8"].thickness_ft


def test_the_textbook_wall():
    """A 60 x 10 ft CMU wall, standing alone.

    600 sf at 1.125 block per sf is 675 block. With 5% waste that is 708.75,
    and at 3 bags per 100 block that is 21.26 bags.
    """
    p = Project(walls=[Wall(1, [(0, 0), (60, 0)], "cmu8", 10)])
    r = takeoff.build(p)
    cmu = r.materials["cmu8"]
    assert r.total_net_area_sf == pytest.approx(600.0)
    assert cmu.units == pytest.approx(675.0)
    assert cmu.units_with_waste == pytest.approx(708.75)
    assert cmu.mortar_bags == pytest.approx(21.2625)
    assert cmu.sand_cy == pytest.approx(21.2625 / 7)


def test_brick_rate():
    """200 sf of modular brick veneer at 6.75 per sf is 1,350 brick."""
    p = Project(walls=[Wall(1, [(0, 0), (20, 0)], "brick4", 10)])
    r = takeoff.build(p)
    assert r.materials["brick4"].units == pytest.approx(1350.0)


def test_large_openings_deduct_and_small_ones_do_not():
    """A 3 x 7 door (21 sf) comes out. A 2 x 2 vent (4 sf) stays in."""
    p = Project(
        walls=[Wall(1, [(0, 0), (60, 0)], "cmu8", 10)],
        openings=[
            Opening(1, 1, 3.0, 7.0, 10.0),
            Opening(2, 1, 2.0, 2.0, 30.0),
        ],
    )
    r = takeoff.build(p)
    assert r.total_net_area_sf == pytest.approx(600.0 - 21.0)
    assert any("not deducted" in w for w in r.warnings)


def test_threshold_is_a_setting_not_a_rule():
    p = Project(
        walls=[Wall(1, [(0, 0), (60, 0)], "cmu8", 10)],
        openings=[Opening(1, 1, 2.0, 2.0, 30.0)],
    )
    r = takeoff.build(p.with_settings(min_deduct_area_sf=0.0))
    assert r.total_net_area_sf == pytest.approx(596.0)


def test_overstatement_is_reported_against_the_naive_takeoff():
    """20 x 30 shell with two partitions, 10 ft tall.

    Four T ends remove 2 x 0.635417 ft of wall, which at 10 ft is 12.71 sf.
    """
    walls = plans.shell(20.0, 30.0) + [
        Wall(5, [(0, 10), (20, 10)], "cmu8", 10),
        Wall(6, [(0, 20), (20, 20)], "cmu8", 10),
    ]
    r = takeoff.build(Project(walls=walls))
    assert r.junction_overstatement_sf == pytest.approx(2 * T8 * 10)
    assert r.overstatement_sf == pytest.approx(12.708333, abs=1e-5)
    assert 0.8 < r.overstatement_pct < 1.0


def test_openings_also_land_in_the_overstatement():
    walls = plans.shell(20.0, 30.0)
    p = Project(walls=walls, openings=[Opening(1, 1, 6.0, 7.0, 10.0)])
    r = takeoff.build(p)
    assert r.overstatement_sf == pytest.approx(42.0)


def test_mixed_assembly_splits_into_two_bills():
    """8" CMU meets 4" brick at a corner. The block takes the corner.

    The conserved quantity here is plan material, not face area. Length moves
    off the brick and onto the block, and because the two walls are different
    thicknesses, a foot of one is not a foot of the other:

        brick gives up  0.158854 ft x 0.302083 ft = 0.047988 sf of plan
        block takes on  0.075521 ft x 0.635417 ft = 0.047988 sf of plan

    Face area therefore does not stay at 350 sf. It drops by
    (0.075521 - 0.158854) x 10 = 0.833 sf, because the same cubic material
    spread across a thicker wall covers less wall face. Asserting 350 here
    would be asserting the wrong invariant.
    """
    walls = [
        Wall(1, [(0, 0), (20, 0)], "cmu8", 10),
        Wall(2, [(20, 0), (20, 15)], "brick4", 10),
    ]
    r = takeoff.build(Project(walls=walls))
    assert set(r.materials) == {"cmu8", "brick4"}

    t_cmu = CATALOG["cmu8"].thickness_ft
    t_brick = CATALOG["brick4"].thickness_ft
    plan_before = 20.0 * t_cmu + 15.0 * t_brick
    plan_after = (
        r.solution.net_length_ft[1] * t_cmu + r.solution.net_length_ft[2] * t_brick
    )
    assert plan_after == pytest.approx(plan_before, rel=1e-12)

    assert r.materials["cmu8"].net_area_sf > 200.0
    assert r.materials["brick4"].net_area_sf < 150.0
    assert r.total_net_area_sf == pytest.approx(350.0 - 0.833333, abs=1e-5)


def test_waste_factor_is_validated():
    with pytest.raises(ValueError):
        Project().with_settings(waste_factor=1.5)
