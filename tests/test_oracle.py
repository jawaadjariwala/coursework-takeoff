"""Analytic solver vs polygon measurement, on plans neither method was tuned for."""

from __future__ import annotations

import pytest

from coursework.geometry.junctions import solve
from coursework.quantities.catalog import CATALOG

from . import plans
from .oracle import material_area_sf

KEYS = ["cmu6", "cmu8", "cmu12", "brick4"]


def analytic_area_sf(walls, key: str) -> float:
    t = CATALOG[key].thickness_ft
    return solve(walls, CATALOG).total_net_ft * t


@pytest.mark.parametrize("key", KEYS)
def test_shell_matches_the_polygon(key):
    walls = plans.shell(20.0, 30.0, key)
    t = CATALOG[key].thickness_ft
    assert analytic_area_sf(walls, key) == pytest.approx(
        material_area_sf(walls, t), rel=1e-9
    )


@pytest.mark.parametrize("seed", range(25))
def test_random_buildings_match_the_polygon(seed):
    """25 generated plans, each checked two independent ways.

    This is the test that earns the right to trust the per-wall numbers. The
    solver reasons about junctions; the oracle measures a polygon. They have
    no code in common.
    """
    key = "cmu8"
    walls = plans.building(seed, key=key)
    t = CATALOG[key].thickness_ft
    assert analytic_area_sf(walls, key) == pytest.approx(
        material_area_sf(walls, t), rel=1e-9
    )


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("seed", [101, 202, 303])
def test_every_thickness_matches_the_polygon(seed, key):
    walls = plans.building(seed, key=key)
    t = CATALOG[key].thickness_ft
    assert analytic_area_sf(walls, key) == pytest.approx(
        material_area_sf(walls, t), rel=1e-9
    )


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_crossing_lattices_match_the_polygon(n):
    """An n x n lattice is nothing but X crossings, the worst case for
    double counting. A 5 x 5 lattice has 25 of them."""
    key = "cmu8"
    walls = plans.grid(n, key=key)
    t = CATALOG[key].thickness_ft
    assert analytic_area_sf(walls, key) == pytest.approx(
        material_area_sf(walls, t), rel=1e-9
    )


def test_the_naive_answer_is_actually_wrong():
    """Guard against the solver quietly becoming a no-op.

    If someone deletes the corrections, every other test comparing net to the
    oracle would still need to fail, but this one states the point directly:
    the uncorrected centerline total does not match the polygon.
    """
    key = "cmu8"
    walls = plans.grid(4, key=key)
    t = CATALOG[key].thickness_ft
    s = solve(walls, CATALOG)
    measured = material_area_sf(walls, t)
    assert s.total_gross_ft * t > measured * 1.02
    assert s.total_net_ft * t == pytest.approx(measured, rel=1e-9)
