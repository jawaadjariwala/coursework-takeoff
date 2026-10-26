"""Benchmark for junction detection, and a record of getting it wrong first.

There are two stages that could blow up on a large plan:

1. **Pair scan.** Deciding which wall segments might touch. Testing every
   pair is O(n^2) in segments.
2. **Clustering.** Collapsing the pairwise hits that land on the same point
   into one junction node. Comparing each hit to every known node is O(n^2)
   in hits.

Stage 1 is the one that looks expensive, so it got a uniform grid hash first.
Profiling then showed where the time actually went on a 24 x 24 lattice:
3 ms in intersection testing and 229 ms in clustering. The index had been
aimed at the wrong stage. Clustering now hashes nodes into cells too.

Both stages keep their original implementations behind ``use_index=False``,
partly so this benchmark can show the difference and partly so the test suite
can assert the fast path returns identical junctions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .geometry.junctions import _segments, find_junctions, grid_pairs, naive_pairs, solve
from .model.types import Wall
from .quantities.catalog import CATALOG

HEIGHT = 10.0


def lattice(n: int, spacing: float = 12.0) -> list[Wall]:
    """An n x n lattice: 2n walls, n*n crossings. A dense, honest worst case."""
    walls: list[Wall] = []
    span = (n - 1) * spacing
    wid = 1
    for i in range(n):
        walls.append(
            Wall(wid, [(-2.0, i * spacing), (span + 2.0, i * spacing)], "cmu8", HEIGHT)
        )
        wid += 1
    for i in range(n):
        walls.append(
            Wall(wid, [(i * spacing, -2.0), (i * spacing, span + 2.0)], "cmu8", HEIGHT)
        )
        wid += 1
    return walls


def rooms(n: int, size: float = 14.0) -> list[Wall]:
    """An n x n block of rooms drawn as short wall runs, one room edge each.

    This is what a floor plan actually looks like: lots of short walls, each
    near only a handful of others. A lattice is the opposite, and the two
    cases answer different questions about the index.
    """
    walls: list[Wall] = []
    wid = 1
    for i in range(n):
        for j in range(n + 1):
            y = j * size
            walls.append(
                Wall(wid, [(i * size, y), ((i + 1) * size, y)], "cmu8", HEIGHT)
            )
            wid += 1
    for j in range(n):
        for i in range(n + 1):
            x = i * size
            walls.append(
                Wall(wid, [(x, j * size), (x, (j + 1) * size)], "cmu8", HEIGHT)
            )
            wid += 1
    return walls


@dataclass
class Row:
    walls: int
    segments: int
    junctions: int
    naive_pairs: int
    index_pairs: int
    pair_naive_ms: float
    pair_index_ms: float
    total_naive_ms: float
    total_index_ms: float

    @property
    def speedup(self) -> float:
        return self.total_naive_ms / self.total_index_ms if self.total_index_ms else 0.0

    @property
    def pair_reduction(self) -> float:
        if not self.naive_pairs:
            return 0.0
        return 100.0 * (1 - self.index_pairs / self.naive_pairs)

    @property
    def pair_share_of_naive(self) -> float:
        """How much of the slow run the pair scan was ever responsible for."""
        if not self.total_naive_ms:
            return 0.0
        return 100.0 * self.pair_naive_ms / self.total_naive_ms


def _time(fn, repeats: int) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


def measure(n: int, repeats: int = 3, builder=lattice) -> Row:
    walls = builder(n)
    segs = _segments(walls)
    junctions, _ = find_junctions(walls)
    return Row(
        walls=len(walls),
        segments=len(segs),
        junctions=len(junctions),
        naive_pairs=len(naive_pairs(segs)),
        index_pairs=len(grid_pairs(segs)),
        pair_naive_ms=_time(lambda: naive_pairs(segs), repeats),
        pair_index_ms=_time(lambda: grid_pairs(segs), repeats),
        total_naive_ms=_time(lambda: solve(walls, CATALOG, use_index=False), repeats),
        total_index_ms=_time(lambda: solve(walls, CATALOG, use_index=True), repeats),
    )


def _table(rows: list[Row], title: str) -> list[str]:
    out = [
        title,
        "",
        f"{'WALLS':>6}{'SEGS':>6}{'JUNC':>7}{'PAIRS n^2':>12}{'PAIRS idx':>11}"
        f"{'CUT':>7}{'SLOW ms':>10}{'FAST ms':>10}{'SPEEDUP':>9}{'PAIR%':>7}",
        "-" * 85,
    ]
    for r in rows:
        out.append(
            f"{r.walls:>6}{r.segments:>6}{r.junctions:>7}{r.naive_pairs:>12,}"
            f"{r.index_pairs:>11,}{r.pair_reduction:>6.0f}%"
            f"{r.total_naive_ms:>10.1f}{r.total_index_ms:>10.1f}"
            f"{r.speedup:>8.1f}x{r.pair_share_of_naive:>6.1f}%"
        )
    return out


def run_benchmark(max_walls: int = 256, repeats: int = 3) -> str:
    lattice_sizes = [n for n in (8, 16, 32, 48, 64, 96, 128) if 2 * n <= max_walls]
    lattice_rows = [measure(n, repeats, lattice) for n in lattice_sizes]

    room_sizes = [n for n in (2, 4, 6, 8, 10, 12, 14) if 2 * n * (n + 1) <= max_walls]
    room_rows = [measure(n, repeats, rooms) for n in room_sizes]

    out: list[str] = []
    out += _table(lattice_rows, "A. Lattice: every wall spans the whole plan")
    out += [
        "",
        "CUT is 0% here and that is correct. Every wall crosses the full extent,",
        "so every segment's bounding box touches every grid cell and no pair can",
        "be ruled out. The speedup in this table is entirely from clustering.",
        "",
        "",
    ]
    out += _table(room_rows, "B. Rooms: short wall runs, the realistic case")
    out += [
        "",
        "Here the index does its job: a short wall covers few cells, so most",
        "pairs are never tested.",
        "",
    ]

    if lattice_rows and room_rows:
        a, b = lattice_rows[-1], room_rows[-1]
        out += [
            "headline",
            f"  lattice  {a.walls} walls, {a.junctions} junctions: "
            f"{a.total_naive_ms:.0f} ms -> {a.total_index_ms:.0f} ms ({a.speedup:.0f}x)",
            f"  rooms    {b.walls} walls, {b.junctions} junctions: "
            f"{b.total_naive_ms:.0f} ms -> {b.total_index_ms:.0f} ms ({b.speedup:.0f}x), "
            f"{b.pair_reduction:.0f}% of pairs skipped",
            "",
            "PAIR% is the share of the slow run spent generating candidate pairs.",
            "It never gets large, which is the finding: the pair scan looked like",
            "the bottleneck and was not. Clustering the hits was.",
        ]
    return "\n".join(out)
