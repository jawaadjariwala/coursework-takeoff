"""Properties that must hold no matter how the plan was drawn.

An estimator will rotate a plan, trace walls in a different order, or draw a
wall right to left. None of that is allowed to change the quantities.
"""

from __future__ import annotations

import math
import random

import pytest

from coursework.geometry.junctions import solve
from coursework.model.types import Wall
from coursework.quantities.catalog import CATALOG

from . import plans

SEEDS = [1, 7, 13, 21, 34]


def totals(walls):
    s = solve(walls, CATALOG)
    return s.total_net_ft


@pytest.mark.parametrize("seed", SEEDS)
def test_translation_invariance(seed):
    walls = plans.building(seed)
    moved = plans.transform(walls, dx=-1234.5, dy=987.25)
    assert totals(moved) == pytest.approx(totals(walls), rel=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("deg", [17.0, 45.0, 90.0, 213.7])
def test_rotation_invariance(seed, deg):
    """Plans are not always drawn square to the page."""
    walls = plans.building(seed)
    turned = plans.transform(walls, theta=math.radians(deg))
    assert totals(turned) == pytest.approx(totals(walls), rel=1e-7)


@pytest.mark.parametrize("seed", SEEDS)
def test_wall_order_invariance(seed):
    """Tracing order must not decide the answer.

    Ownership ties break on wall id, so shuffling the list while keeping ids
    attached has to leave the result alone.
    """
    walls = plans.building(seed)
    shuffled = walls[:]
    random.Random(seed).shuffle(shuffled)
    assert totals(shuffled) == pytest.approx(totals(walls), rel=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
def test_vertex_reversal_invariance(seed):
    """Drawing a wall right to left is the same wall."""
    walls = plans.building(seed)
    flipped = [
        Wall(w.id, list(reversed(w.vertices)), w.assembly_key, w.height_ft, w.label)
        for w in walls
    ]
    assert totals(flipped) == pytest.approx(totals(walls), rel=1e-12)


@pytest.mark.parametrize("seed", SEEDS)
def test_scale_equivariance(seed):
    """Doubling every coordinate doubles the length and nothing else.

    This one is a real check rather than a tautology, because the junction
    corrections depend on wall thickness, which does not scale with the plan.
    The scaled total must therefore be bigger than twice the original by
    exactly the corrections that were applied once instead of twice.
    """
    walls = plans.building(seed)
    base = solve(walls, CATALOG)
    scaled = [
        Wall(w.id, [(2 * x, 2 * y) for x, y in w.vertices], w.assembly_key, w.height_ft)
        for w in walls
    ]
    grown = solve(scaled, CATALOG)
    corrections = base.total_gross_ft - base.total_net_ft
    assert grown.total_gross_ft == pytest.approx(2 * base.total_gross_ft, rel=1e-9)
    assert grown.total_net_ft == pytest.approx(
        2 * base.total_gross_ft - corrections, rel=1e-9
    )


@pytest.mark.parametrize("seed", SEEDS + [55, 89, 144])
def test_index_and_naive_scan_agree(seed):
    """The grid hash is an optimisation, not a different algorithm.

    It is only allowed to skip pairs that could not have intersected, so the
    junction set it finds must be identical to the all-pairs scan.
    """
    walls = plans.building(seed, n_partitions=4, n_crossers=3)
    fast = solve(walls, CATALOG, use_index=True)
    slow = solve(walls, CATALOG, use_index=False)

    assert fast.counts_by_kind() == slow.counts_by_kind()
    assert fast.net_length_ft == pytest.approx(slow.net_length_ft)

    def sig(sol):
        return sorted(
            (j.kind.value, round(j.point[0], 6), round(j.point[1], 6), tuple(j.wall_ids))
            for j in sol.junctions
        )

    assert sig(fast) == sig(slow)


@pytest.mark.parametrize("n", [2, 3, 4, 6, 8])
def test_index_and_naive_agree_on_lattices(n):
    walls = plans.grid(n)
    fast = solve(walls, CATALOG, use_index=True)
    slow = solve(walls, CATALOG, use_index=False)
    assert len(fast.junctions) == len(slow.junctions) == n * n
    assert fast.total_net_ft == pytest.approx(slow.total_net_ft, rel=1e-12)
