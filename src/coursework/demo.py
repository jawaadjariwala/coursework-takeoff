"""A small commercial shell, built to exercise every junction type at once.

    (0,40)                                            (60,40)
       +------------------- W3 8" --------------------+
       |                                              |
       W4                                            W2
       8"                                           12"
       |                                              |
       +--------- P1 8" (T both ends) ----------------+
       |                     |                        |
       |                    P2 8"                     |
       |                     | (T into W1 and P1)     |
       +------------------- W1 8" --------------------+
    (0,0)                                            (60,0)

W2 is 12 inch block, which is common where one bay carries more load. That
makes the two corners it forms mixed-assembly corners, where the plan area is
already right but the split between the two block sizes is not.

A freestanding brick screen wall sits off to the side, because masonry
contractors bid those alongside the building and it puts a second material in
the bill without inventing a strange cavity detail.
"""

from __future__ import annotations

from .model.types import Opening, OpeningKind, Project, Wall

SHELL_H = 16.0
PARTITION_H = 12.0
SCREEN_H = 6.0


def demo_project() -> Project:
    walls = [
        Wall(1, [(0.0, 0.0), (60.0, 0.0)], "cmu8", SHELL_H, "South wall"),
        Wall(2, [(60.0, 0.0), (60.0, 40.0)], "cmu12", SHELL_H, "East wall"),
        Wall(3, [(60.0, 40.0), (0.0, 40.0)], "cmu8", SHELL_H, "North wall"),
        Wall(4, [(0.0, 40.0), (0.0, 0.0)], "cmu8", SHELL_H, "West wall"),
        Wall(5, [(0.0, 20.0), (60.0, 20.0)], "cmu8", PARTITION_H, "Corridor wall"),
        Wall(6, [(30.0, 0.0), (30.0, 20.0)], "cmu8", PARTITION_H, "Demising wall"),
        Wall(7, [(72.0, 0.0), (72.0, 30.0)], "brick4", SCREEN_H, "Screen wall"),
    ]
    openings = [
        Opening(1, 1, 12.0, 14.0, 14.0, kind=OpeningKind.DOOR, label="Overhead door"),
        Opening(2, 1, 3.0, 7.0, 45.0, kind=OpeningKind.DOOR, label="Man door"),
        Opening(3, 3, 5.0, 4.0, 12.0, sill_ft=4.0, label="Window"),
        Opening(4, 3, 5.0, 4.0, 30.0, sill_ft=4.0, label="Window"),
        Opening(5, 3, 5.0, 4.0, 48.0, sill_ft=4.0, label="Window"),
        Opening(6, 5, 3.0, 7.0, 18.0, kind=OpeningKind.DOOR, label="Corridor door"),
        # Deliberately under the 10 sf threshold, to show the rule working.
        Opening(
            7, 4, 2.0, 2.0, 30.0,
            sill_ft=7.0, kind=OpeningKind.OTHER, label="Louver",
        ),
    ]
    return Project(name="Demo: 60 x 40 masonry shell", walls=walls, openings=openings)


#: Where the building sits on ``assets/demo_plan.pdf`` once that page is
#: rendered at 150 dpi, in feet, in the canvas coordinate system. Derived from
#: the generator's origin rather than measured by eye, so the two stay in step.
PLAN_DPI = 150
PLAN_PX_PER_FT = 9.0 / 72.0 * PLAN_DPI  # 1/8" = 1'-0" at 150 dpi
PLAN_OFFSET_FT = (96.0 / 72.0 * PLAN_DPI / PLAN_PX_PER_FT, -52.0)


def demo_project_on_plan(plan_png: str) -> Project:
    """The same building, positioned over the rendered sample drawing.

    Tracing a real plan puts the walls wherever the user clicked, so model
    coordinates are only ever meaningful relative to the underlay. This
    translates the demo building onto the sample drawing so the two line up
    without anyone having to trace it by hand.
    """
    dx, dy = PLAN_OFFSET_FT
    project = demo_project()
    for wall in project.walls:
        wall.vertices = [(x + dx, y + dy) for x, y in wall.vertices]
    project.plan_path = plan_png
    project.px_per_ft = PLAN_PX_PER_FT
    project.name = "Demo: traced over assets/demo_plan.pdf"
    return project
