"""Wall junction resolution: the part that stops material being counted twice.

Why this exists
---------------
Masonry is measured along wall centerlines. That convention has a property
most people never notice, and one that bites whenever they rely on it too far.

**At an L corner it is exactly self-correcting.** Put wall A along +x with
thickness ``ta`` and wall B along +y with thickness ``tb``, both ending at the
origin:

    A covers  x in [0, La],        y in [-ta/2, ta/2]
    B covers  y in [0, Lb],        x in [-tb/2, tb/2]

    overlap   x in [0, tb/2],      y in [0, ta/2]      area = ta*tb/4
    notch     x in [-tb/2, 0],     y in [-ta/2, 0]     area = ta*tb/4

The overlap is counted twice and the notch is counted by nobody, and the two
areas are equal for *any* pair of thicknesses. They cancel. A closed loop of
walls measured on the centerline gives exactly the right material, which is
why the convention survives.

**Nowhere else does it self-correct.**

    T intersection   the butting wall runs to the host's centerline, so it
                     overstates by  t_host / 2  at that end.
    X crossing       the non-owning wall runs clean through the owner, so it
                     overstates by  t_owner.
    Mixed-assembly   the areas still cancel, but across two different
    L corner         materials. The overlap lands in both bills of material
                     and the notch in neither. The total is right and the
                     split is wrong, which matters when the block and the
                     brick are two separate purchase orders.

Everything below is that set of four observations turned into code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..model.types import Assembly, Point, Wall
from .primitives import (
    TOL,
    dist,
    norm,
    polyline_length,
    same_point,
    segment_intersection,
    sub,
)


class ContactType(StrEnum):
    """How a wall meets a junction point."""

    #: The junction is at one of the wall's two free ends.
    END = "end"
    #: The junction is somewhere along the wall's body, including at an
    #: interior vertex of a polyline.
    BODY = "body"


class JunctionKind(StrEnum):
    L_CORNER = "L"
    T_INTERSECTION = "T"
    X_CROSSING = "X"
    MULTI = "multi"


@dataclass(frozen=True)
class Contact:
    wall_id: int
    contact_type: ContactType
    #: Distance along the wall centerline from its first vertex.
    station_ft: float


@dataclass
class Junction:
    kind: JunctionKind
    point: Point
    contacts: list[Contact]
    #: Wall that keeps the shared material. Geometry forces this at a T (the
    #: continuous wall wins); assembly priority decides it elsewhere.
    owner_wall_id: int | None = None
    #: Signed length change per wall, in feet. Negative removes material.
    adjustments: dict[int, float] = field(default_factory=dict)
    note: str = ""
    needs_review: bool = False

    @property
    def wall_ids(self) -> list[int]:
        return [c.wall_id for c in self.contacts]


@dataclass
class Solution:
    junctions: list[Junction]
    gross_length_ft: dict[int, float]
    net_length_ft: dict[int, float]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_gross_ft(self) -> float:
        return sum(self.gross_length_ft.values())

    @property
    def total_net_ft(self) -> float:
        return sum(self.net_length_ft.values())

    def counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for j in self.junctions:
            out[j.kind.value] = out.get(j.kind.value, 0) + 1
        return out


# --------------------------------------------------------------------------
# contact discovery
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Seg:
    wall_id: int
    index: int
    a: Point
    b: Point
    #: Centerline distance from the wall's first vertex to ``a``.
    station_at_a: float

    @property
    def length(self) -> float:
        return dist(self.a, self.b)


def _segments(walls: list[Wall]) -> list[_Seg]:
    segs: list[_Seg] = []
    for w in walls:
        station = 0.0
        for i, (a, b) in enumerate(w.segments):
            segs.append(_Seg(w.id, i, a, b, station))
            station += dist(a, b)
    return segs


def naive_pairs(segs: list[_Seg]) -> list[tuple[int, int]]:
    """Every cross-wall segment pair. O(n^2), the obvious implementation."""
    out = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i].wall_id != segs[j].wall_id:
                out.append((i, j))
    return out


def grid_pairs(segs: list[_Seg], cell: float | None = None) -> list[tuple[int, int]]:
    """Candidate pairs from a uniform grid hash over segment bounding boxes.

    Walls in a floor plan are sparse: a segment can only meet the handful of
    segments near it, so testing all pairs wastes almost all of the work. The
    cell defaults to the mean segment length, which keeps the average number
    of segments per cell near constant as a plan grows.
    """
    if not segs:
        return []
    if cell is None:
        mean_len = sum(s.length for s in segs) / len(segs)
        cell = max(mean_len, TOL * 10)

    buckets: dict[tuple[int, int], list[int]] = {}
    for idx, s in enumerate(segs):
        x0, x1 = sorted((s.a[0], s.b[0]))
        y0, y1 = sorted((s.a[1], s.b[1]))
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                buckets.setdefault((gx, gy), []).append(idx)

    seen: set[tuple[int, int]] = set()
    for members in buckets.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if segs[a].wall_id == segs[b].wall_id:
                    continue
                seen.add((a, b) if a < b else (b, a))
    return sorted(seen)


def _contact_type(wall: Wall, point: Point, tol: float) -> ContactType:
    """END only at a wall's two free ends, not at interior polyline vertices."""
    if same_point(point, wall.vertices[0], tol) or same_point(
        point, wall.vertices[-1], tol
    ):
        return ContactType.END
    return ContactType.BODY


def _collinear_overlap(s1: _Seg, s2: _Seg, tol: float) -> bool:
    """True when two segments lie on each other rather than crossing."""
    r = sub(s1.b, s1.a)
    if norm(r) == 0:
        return False
    ux, uy = r[0] / norm(r), r[1] / norm(r)
    for p in (s2.a, s2.b):
        d = sub(p, s1.a)
        perp = abs(-uy * d[0] + ux * d[1])
        if perp > tol:
            return False
    # Both endpoints of s2 sit on s1's line. Check the spans actually overlap
    # rather than merely touching end to end.
    def along(p: Point) -> float:
        d = sub(p, s1.a)
        return ux * d[0] + uy * d[1]

    lo2, hi2 = sorted((along(s2.a), along(s2.b)))
    lo1, hi1 = 0.0, norm(r)
    return min(hi1, hi2) - max(lo1, lo2) > tol


def find_junctions(
    walls: list[Wall],
    tol: float = TOL,
    *,
    use_index: bool = True,
) -> tuple[list[Junction], list[str]]:
    """Locate and classify every junction between walls.

    ``use_index`` picks the grid hash over the all-pairs scan. Both produce
    identical results; the flag exists so the benchmark can compare them and
    so the test suite can assert they agree.
    """
    segs = _segments(walls)
    by_id = {w.id: w for w in walls}
    pairs = grid_pairs(segs) if use_index else naive_pairs(segs)

    warnings: list[str] = []
    raw: list[tuple[Point, Contact, Contact]] = []

    for i, j in pairs:
        s1, s2 = segs[i], segs[j]
        hit = segment_intersection(s1.a, s1.b, s2.a, s2.b, tol)
        if hit is None:
            if _collinear_overlap(s1, s2, tol):
                warnings.append(
                    f"walls {s1.wall_id} and {s2.wall_id} overlap along their "
                    f"length; no correction applied, check the tracing"
                )
            continue

        point, ta, tb = hit
        w1, w2 = by_id[s1.wall_id], by_id[s2.wall_id]
        c1 = Contact(
            w1.id,
            _contact_type(w1, point, tol),
            s1.station_at_a + max(0.0, min(1.0, ta)) * s1.length,
        )
        c2 = Contact(
            w2.id,
            _contact_type(w2, point, tol),
            s2.station_at_a + max(0.0, min(1.0, tb)) * s2.length,
        )
        raw.append((point, c1, c2))

    return _cluster(raw, tol, use_index=use_index), sorted(set(warnings))


def _cluster(
    raw: list[tuple[Point, Contact, Contact]],
    tol: float,
    *,
    use_index: bool = True,
) -> list[Junction]:
    """Group pairwise hits that share a location into one junction node.

    Three walls meeting at a point produce three pairwise hits at the same
    place. Without this step they would be three junctions and the corrections
    would be applied three times.

    This is the stage that actually costs time on a large plan, which was a
    surprise. The obvious suspect was the segment intersection scan, so that
    got a grid index first. Profiling a 24 x 24 lattice showed intersection
    testing at 3 ms and clustering at 229 ms: comparing every hit against
    every existing node is quadratic, and a dense plan has thousands of hits.
    Hashing the nodes into cells of ``2 * tol`` fixes the real problem.

    ``use_index=False`` keeps the original scan so the benchmark can show the
    difference and the tests can prove the two agree.
    """
    merge_tol = tol * 2
    nodes: list[tuple[list[Point], dict[int, Contact]]] = []

    def absorb(contacts: dict[int, Contact], c: Contact) -> None:
        # An END contact is the stronger statement about a wall, so it wins if
        # the same wall shows up at a node twice.
        prev = contacts.get(c.wall_id)
        if prev is None or (
            prev.contact_type is ContactType.BODY and c.contact_type is ContactType.END
        ):
            contacts[c.wall_id] = c

    if use_index:
        cell = merge_tol * 2
        grid: dict[tuple[int, int], list[int]] = {}

        def cell_of(p: Point) -> tuple[int, int]:
            return (int(p[0] // cell), int(p[1] // cell))

        for point, c1, c2 in raw:
            gx, gy = cell_of(point)
            found = -1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for idx in grid.get((gx + dx, gy + dy), ()):
                        if any(same_point(point, q, merge_tol) for q in nodes[idx][0]):
                            found = idx
                            break
                    if found >= 0:
                        break
                if found >= 0:
                    break

            if found < 0:
                found = len(nodes)
                nodes.append(([], {}))
            pts, contacts = nodes[found]
            pts.append(point)
            absorb(contacts, c1)
            absorb(contacts, c2)
            bucket = grid.setdefault((gx, gy), [])
            if found not in bucket:
                bucket.append(found)
    else:
        for point, c1, c2 in raw:
            for pts, contacts in nodes:
                if any(same_point(point, p, merge_tol) for p in pts):
                    pts.append(point)
                    absorb(contacts, c1)
                    absorb(contacts, c2)
                    break
            else:
                nodes.append(([point], {c1.wall_id: c1, c2.wall_id: c2}))

    out: list[Junction] = []
    for pts, contacts in nodes:
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        members = sorted(contacts.values(), key=lambda c: c.wall_id)
        out.append(Junction(kind=_classify(members), point=(cx, cy), contacts=members))
    return out


def _classify(contacts: list[Contact]) -> JunctionKind:
    if len(contacts) > 2:
        return JunctionKind.MULTI
    ends = sum(1 for c in contacts if c.contact_type is ContactType.END)
    if ends == 2:
        return JunctionKind.L_CORNER
    if ends == 1:
        return JunctionKind.T_INTERSECTION
    return JunctionKind.X_CROSSING


# --------------------------------------------------------------------------
# corrections
# --------------------------------------------------------------------------


def _pick_owner(
    contacts: list[Contact], walls: dict[int, Wall], asm: dict[str, Assembly]
) -> int:
    """Highest assembly priority owns the shared material, lowest id breaks ties.

    Structural block outranks veneer because the block runs continuous through
    the junction and the veneer stops against it. That is how the wall is
    actually built, so that is how the material is assigned.
    """
    return min(
        (c.wall_id for c in contacts),
        key=lambda wid: (-asm[walls[wid].assembly_key].priority, wid),
    )


def _apply(
    junction: Junction, walls: dict[int, Wall], asm: dict[str, Assembly]
) -> None:
    """Fill in ``owner_wall_id``, ``adjustments`` and ``note`` for one junction."""
    t = {
        c.wall_id: asm[walls[c.wall_id].assembly_key].thickness_ft
        for c in junction.contacts
    }
    key = {c.wall_id: walls[c.wall_id].assembly_key for c in junction.contacts}

    if junction.kind is JunctionKind.L_CORNER:
        a, b = junction.contacts[0].wall_id, junction.contacts[1].wall_id
        if key[a] == key[b]:
            # Overlap ta*tb/4 and notch ta*tb/4 cancel inside one material.
            junction.owner_wall_id = None
            junction.note = "same assembly, centerline self-corrects"
            return
        owner = _pick_owner(junction.contacts, walls, asm)
        other = b if owner == a else a
        junction.owner_wall_id = owner
        # Non-owner drops the overlap it was double counting; owner picks up
        # the outer notch that nobody was counting. Equal areas, two materials.
        junction.adjustments[other] = -t[owner] / 4.0
        junction.adjustments[owner] = +t[other] / 4.0
        junction.note = (
            f"mixed assembly corner: {key[owner]} takes the corner from {key[other]}"
        )
        return

    if junction.kind is JunctionKind.T_INTERSECTION:
        butt = next(c for c in junction.contacts if c.contact_type is ContactType.END)
        host = next(c for c in junction.contacts if c.contact_type is ContactType.BODY)
        junction.owner_wall_id = host.wall_id
        junction.adjustments[butt.wall_id] = -t[host.wall_id] / 2.0
        junction.note = (
            f"wall {butt.wall_id} butts into wall {host.wall_id}; "
            f"removed half the host thickness"
        )
        return

    if junction.kind is JunctionKind.X_CROSSING:
        owner = _pick_owner(junction.contacts, walls, asm)
        other = next(c.wall_id for c in junction.contacts if c.wall_id != owner)
        junction.owner_wall_id = owner
        junction.adjustments[other] = -t[owner]
        junction.note = (
            f"wall {other} crosses wall {owner}; removed the full crossing"
        )
        return

    # MULTI: more than two walls at one point. The pairwise rules are applied
    # against the owner, which is right for the common cases (a corner post
    # with partitions running off it) and approximate for the unusual ones.
    # It is flagged so the estimator looks rather than trusts.
    owner = _pick_owner(junction.contacts, walls, asm)
    junction.owner_wall_id = owner
    owner_contact = next(c for c in junction.contacts if c.wall_id == owner)
    for c in junction.contacts:
        if c.wall_id == owner:
            continue
        owner_is_body = owner_contact.contact_type is ContactType.BODY
        if c.contact_type is ContactType.END and owner_is_body:
            junction.adjustments[c.wall_id] = -t[owner] / 2.0
        elif c.contact_type is ContactType.BODY:
            junction.adjustments[c.wall_id] = -t[owner]
        elif key[c.wall_id] != key[owner]:
            junction.adjustments[c.wall_id] = -t[owner] / 4.0
    junction.needs_review = True
    junction.note = (
        f"{len(junction.contacts)} walls meet here; corrections are pairwise "
        f"against wall {owner} and should be reviewed"
    )


def solve(
    walls: list[Wall],
    assemblies: dict[str, Assembly],
    tol: float = TOL,
    *,
    use_index: bool = True,
) -> Solution:
    """Resolve every junction and return gross and net centerline lengths."""
    by_id = {w.id: w for w in walls}
    junctions, warnings = find_junctions(walls, tol, use_index=use_index)

    for j in junctions:
        _apply(j, by_id, assemblies)

    gross = {w.id: polyline_length(w.vertices) for w in walls}
    net = dict(gross)
    for j in junctions:
        for wid, delta in j.adjustments.items():
            net[wid] += delta

    for wid, value in net.items():
        if value < 0:
            warnings.append(
                f"wall {wid} is shorter than the junction corrections against "
                f"it ({gross[wid]:.2f} ft gross); clamped to zero, check the tracing"
            )
            net[wid] = 0.0

    for j in junctions:
        if j.needs_review:
            warnings.append(
                f"{j.kind.value} junction at ({j.point[0]:.2f}, {j.point[1]:.2f}) "
                f"needs review: {j.note}"
            )

    return Solution(junctions, gross, net, sorted(set(warnings)))
