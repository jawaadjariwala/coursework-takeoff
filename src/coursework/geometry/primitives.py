"""Small 2D geometry helpers. Pure NumPy, no geometry library.

The production path deliberately carries no shapely dependency. Shapely shows
up only in the test suite, where it builds an independent polygon-union oracle
to check these analytic results against. Two unrelated methods landing on the
same number is a much stronger guarantee than one method plus confidence.
"""

from __future__ import annotations

import math

from ..model.types import Point

#: Default coincidence tolerance in feet. 0.02 ft is just under a quarter inch,
#: which is finer than anyone can trace on a scanned plan and coarse enough to
#: absorb float noise from the pixel-to-feet conversion.
TOL = 0.02


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def same_point(a: Point, b: Point, tol: float = TOL) -> bool:
    return dist(a, b) <= tol


def project_param(p: Point, a: Point, b: Point) -> float:
    """Parameter t where p projects onto segment ab, unclamped.

    t == 0 at a, t == 1 at b. Returns 0.0 for a degenerate segment.
    """
    ab = sub(b, a)
    denom = dot(ab, ab)
    if denom == 0.0:
        return 0.0
    return dot(sub(p, a), ab) / denom


def point_segment_distance(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """Distance from p to segment ab, and the clamped parameter of the foot."""
    t = max(0.0, min(1.0, project_param(p, a, b)))
    foot = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return dist(p, foot), t


def segment_intersection(
    a1: Point, a2: Point, b1: Point, b2: Point, tol: float = TOL
) -> tuple[Point, float, float] | None:
    """Intersection of two segments, or None.

    Returns (point, ta, tb) where ta and tb are the parameters along each
    segment. Parameters outside [0, 1] by more than the tolerance mean the
    segments do not actually reach each other, and None comes back.

    Collinear overlap returns None. Two walls lying on top of each other is a
    tracing mistake, not a junction, and the solver reports it separately
    rather than inventing a correction for it.
    """
    r = sub(a2, a1)
    s = sub(b2, b1)
    denom = cross(r, s)
    qp = sub(b1, a1)

    if abs(denom) < 1e-12:
        return None  # parallel or collinear

    ta = cross(qp, s) / denom
    tb = cross(qp, r) / denom

    # Convert the tolerance from feet into parameter space on each segment so
    # that a long wall and a short wall are judged by the same physical slack.
    len_a = norm(r)
    len_b = norm(s)
    pad_a = tol / len_a if len_a else 0.0
    pad_b = tol / len_b if len_b else 0.0

    if not (-pad_a <= ta <= 1.0 + pad_a):
        return None
    if not (-pad_b <= tb <= 1.0 + pad_b):
        return None

    point = (a1[0] + ta * r[0], a1[1] + ta * r[1])
    return point, ta, tb


def polyline_length(points: list[Point]) -> float:
    return sum(dist(p, q) for p, q in zip(points, points[1:], strict=False))
