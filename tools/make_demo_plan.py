"""Draw a sample floor plan PDF matching ``coursework.demo``.

This is a synthetic drawing, not a real project. It exists so the full
workflow has something to run against: open a PDF, calibrate off a printed
dimension, trace the walls, compare the answer to the known geometry.

Drawn at 1/8" = 1'-0" on letter landscape, which is 9 points per foot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

PT_PER_FT = 9.0  # 1/8" = 1'-0"
PAGE = pymupdf.paper_rect("letter-l")
ORIGIN_X, ORIGIN_Y = 96.0, 108.0

WALL_T_FT = 7.625 / 12
INK = (0.1, 0.1, 0.1)
THIN = (0.45, 0.45, 0.45)

# (x, y) in feet, y measured up from the building's south wall.
BUILDING_W, BUILDING_D = 60.0, 40.0


def to_pt(x_ft: float, y_ft: float) -> pymupdf.Point:
    """Plan feet to page points, flipping y so the drawing reads upright."""
    return pymupdf.Point(
        ORIGIN_X + x_ft * PT_PER_FT,
        ORIGIN_Y + (BUILDING_D - y_ft) * PT_PER_FT,
    )


def draw_wall(page, a, b, thickness_ft=WALL_T_FT, openings=()):
    """A wall as two parallel lines, with gaps where openings sit."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / length, dy / length
    nx, ny = -uy * thickness_ft / 2, ux * thickness_ft / 2

    spans = [(0.0, length)]
    for station, width in openings:
        lo, hi = station - width / 2, station + width / 2
        new = []
        for s0, s1 in spans:
            if hi <= s0 or lo >= s1:
                new.append((s0, s1))
                continue
            if s0 < lo:
                new.append((s0, lo))
            if hi < s1:
                new.append((hi, s1))
        spans = new

    for side in (1, -1):
        for s0, s1 in spans:
            p0 = to_pt(ax + ux * s0 + nx * side, ay + uy * s0 + ny * side)
            p1 = to_pt(ax + ux * s1 + nx * side, ay + uy * s1 + ny * side)
            page.draw_line(p0, p1, color=INK, width=1.1)

    # Cap the ends of every solid span so openings read as jambs.
    for s0, s1 in spans:
        for s in (s0, s1):
            p0 = to_pt(ax + ux * s + nx, ay + uy * s + ny)
            p1 = to_pt(ax + ux * s - nx, ay + uy * s - ny)
            page.draw_line(p0, p1, color=INK, width=1.1)


def dimension(page, a, b, text, offset_ft=3.0, vertical=False):
    (ax, ay), (bx, by) = a, b
    if vertical:
        ax -= offset_ft
        bx -= offset_ft
    else:
        ay -= offset_ft
        by -= offset_ft
    p0, p1 = to_pt(ax, ay), to_pt(bx, by)
    page.draw_line(p0, p1, color=THIN, width=0.6)
    for p in (p0, p1):
        tick = 3.0
        page.draw_line(
            pymupdf.Point(p.x - tick, p.y - tick),
            pymupdf.Point(p.x + tick, p.y + tick),
            color=THIN,
            width=0.6,
        )
    mid = pymupdf.Point((p0.x + p1.x) / 2, (p0.y + p1.y) / 2)
    if vertical:
        page.insert_text(
            pymupdf.Point(mid.x - 6, mid.y + 22), text,
            fontsize=7.5, color=THIN, rotate=90,
        )
    else:
        page.insert_text(
            pymupdf.Point(mid.x - 18, mid.y - 5), text, fontsize=7.5, color=THIN
        )


def build(out: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE.width, height=PAGE.height)

    # Shell. Openings are (station along the wall, width) in feet.
    draw_wall(page, (0, 0), (BUILDING_W, 0), openings=[(14, 12), (45, 3)])
    draw_wall(page, (BUILDING_W, 0), (BUILDING_W, BUILDING_D), 11.625 / 12)
    draw_wall(page, (BUILDING_W, BUILDING_D), (0, BUILDING_D),
              openings=[(12, 5), (30, 5), (48, 5)])
    draw_wall(page, (0, BUILDING_D), (0, 0), openings=[(30, 2)])

    # Interior.
    draw_wall(page, (0, 20), (BUILDING_W, 20), openings=[(18, 3)])
    draw_wall(page, (30, 0), (30, 20))

    # Freestanding brick screen wall.
    draw_wall(page, (72, 0), (72, 30), 3.625 / 12)

    dimension(page, (0, 0), (BUILDING_W, 0), "60'-0\"")
    dimension(page, (0, 0), (0, BUILDING_D), "40'-0\"", vertical=True)

    page.insert_text(to_pt(2, 36), "SUITE 100", fontsize=8, color=THIN)
    page.insert_text(to_pt(32, 36), "SUITE 200", fontsize=8, color=THIN)
    page.insert_text(to_pt(2, 16), "SUITE 101", fontsize=8, color=THIN)
    page.insert_text(to_pt(32, 16), "SUITE 102", fontsize=8, color=THIN)
    page.insert_text(to_pt(66, 31), "SCREEN WALL", fontsize=7, color=THIN)

    # Title block.
    block = pymupdf.Rect(PAGE.width - 250, PAGE.height - 96, PAGE.width - 40,
                         PAGE.height - 36)
    page.draw_rect(block, color=INK, width=0.8)
    page.insert_text(
        pymupdf.Point(block.x0 + 10, block.y0 + 18),
        "SAMPLE DRAWING - NOT A REAL PROJECT",
        fontsize=8, color=INK,
    )
    page.insert_text(
        pymupdf.Point(block.x0 + 10, block.y0 + 32),
        "60 x 40 MASONRY SHELL   |   FIRST FLOOR PLAN",
        fontsize=7.5, color=THIN,
    )
    page.insert_text(
        pymupdf.Point(block.x0 + 10, block.y0 + 46),
        'SCALE: 1/8" = 1\'-0"   |   A-101',
        fontsize=7.5, color=THIN,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/demo_plan.pdf")
    print("wrote", build(target))
