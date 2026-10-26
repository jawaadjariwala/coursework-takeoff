"""An independent check on the junction solver.

The solver works analytically: it reasons about what each junction type does
to a wall's measured length and applies a correction. This module answers the
same question a completely different way, by building the actual plan-view
polygon of the masonry and measuring its area.

It shares no code and no reasoning with the solver. It merges all the wall
centerlines into connected linework and lets shapely buffer that by half the
wall thickness with mitred joins, which fills outer corners the way a mason
does. If the two methods disagree, at least one of them is wrong.

Limited to single-assembly plans on purpose. With two materials the polygon
has one total area but the bill of materials has two lines, and splitting the
shared corner between them is exactly the judgement call the solver is making,
so a polygon cannot referee it. Those cases are covered by hand arithmetic in
``test_known_answers.py`` instead.
"""

from __future__ import annotations

from shapely import BufferCapStyle, BufferJoinStyle
from shapely.geometry import LineString
from shapely.ops import linemerge, unary_union

from coursework.model.types import Wall


def material_area_sf(walls: list[Wall], thickness_ft: float) -> float:
    """Plan-view area of masonry, measured from the polygon rather than computed."""
    merged = linemerge(unary_union([LineString(w.vertices) for w in walls]))
    poly = merged.buffer(
        thickness_ft / 2.0,
        cap_style=BufferCapStyle.flat,
        join_style=BufferJoinStyle.mitre,
        mitre_limit=10.0,
    )
    return poly.area
