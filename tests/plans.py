"""Synthetic plan generators shared by the oracle, property and bench suites."""

from __future__ import annotations

import math
import random

from coursework.model.types import Point, Wall

HEIGHT = 10.0


def shell(width: float, depth: float, key: str = "cmu8", start: int = 1) -> list[Wall]:
    """A closed rectangular shell traced as four walls."""
    pts = [(0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth)]
    return [
        Wall(start + i, [pts[i], pts[(i + 1) % 4]], key, HEIGHT) for i in range(4)
    ]


def building(
    seed: int,
    *,
    key: str = "cmu8",
    n_partitions: int = 3,
    n_crossers: int = 2,
) -> list[Wall]:
    """A shell with interior partitions, built to contain only L, T and X nodes.

    Coordinates are kept on distinct lanes so that three walls never land on
    one point, which would make a multi-way node. Multi-way nodes are the one
    case the solver only approximates, so they are excluded here and tested
    separately by hand.
    """
    rng = random.Random(seed)
    width = rng.uniform(24.0, 60.0)
    depth = rng.uniform(24.0, 60.0)
    walls = shell(width, depth, key)
    next_id = 5

    lanes = rng.sample(range(2, 20), n_partitions)
    ys = sorted(depth * lane / 21.0 for lane in lanes)
    for y in ys:
        walls.append(Wall(next_id, [(0.0, y), (width, y)], key, HEIGHT))
        next_id += 1

    # Crossers run between two partitions so both ends land on wall bodies,
    # producing X nodes rather than T nodes.
    if len(ys) >= 2:
        xlanes = rng.sample(range(2, 20), n_crossers)
        for lane in xlanes:
            x = width * lane / 21.0
            walls.append(
                Wall(next_id, [(x, ys[0] - 2.0), (x, ys[-1] + 2.0)], key, HEIGHT)
            )
            next_id += 1
    return walls


def grid(n: int, spacing: float = 12.0, key: str = "cmu8") -> list[Wall]:
    """An n x n lattice of crossing walls. Used to grow the benchmark."""
    walls: list[Wall] = []
    span = (n - 1) * spacing
    wid = 1
    for i in range(n):
        y = i * spacing
        walls.append(Wall(wid, [(-2.0, y), (span + 2.0, y)], key, HEIGHT))
        wid += 1
    for i in range(n):
        x = i * spacing
        walls.append(Wall(wid, [(x, -2.0), (x, span + 2.0)], key, HEIGHT))
        wid += 1
    return walls


def transform(
    walls: list[Wall], *, dx: float = 0.0, dy: float = 0.0, theta: float = 0.0
) -> list[Wall]:
    c, s = math.cos(theta), math.sin(theta)

    def t(p: Point) -> Point:
        x, y = p
        return (c * x - s * y + dx, s * x + c * y + dy)

    return [
        Wall(w.id, [t(p) for p in w.vertices], w.assembly_key, w.height_ft, w.label)
        for w in walls
    ]
