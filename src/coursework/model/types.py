"""Core data model for a masonry takeoff.

Internal units are decimal feet everywhere. Thickness is quoted in inches in
the trade, so assemblies carry a nominal label for display and a thickness in
feet for the math.  Keeping one unit internally removes a whole class of bug
that estimating tools are famous for.

Nothing in this module imports Qt. The whole model is plain dataclasses so the
geometry and quantity engines can be exercised headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

Point = tuple[float, float]


class UnitType(StrEnum):
    """What a single masonry unit is, which decides how it is counted."""

    CMU = "cmu"
    BRICK = "brick"


@dataclass(frozen=True)
class Assembly:
    """A wall build-up: one masonry material at one nominal thickness.

    ``units_per_sf`` is per square foot of *wall face*, which is how masonry is
    counted in the trade, not per square foot of plan footprint.

    ``priority`` breaks ownership ties at junctions. The higher number owns the
    shared material. Structural CMU outranks veneer because the block runs
    continuous through a junction and the veneer stops against it.
    """

    key: str
    label: str
    thickness_in: float
    unit_type: UnitType
    units_per_sf: float
    mortar_bags_per_100_units: float
    priority: int = 0

    @property
    def thickness_ft(self) -> float:
        return self.thickness_in / 12.0


class OpeningKind(StrEnum):
    DOOR = "door"
    WINDOW = "window"
    OTHER = "other"


@dataclass
class Opening:
    """A rectangular hole in one wall's face.

    ``station_ft`` is the distance along the wall centerline from its first
    vertex to the centre of the opening. Storing it as a station rather than an
    absolute point means the opening travels with the wall when it is edited.
    """

    id: int
    wall_id: int
    width_ft: float
    height_ft: float
    station_ft: float
    sill_ft: float = 0.0
    kind: OpeningKind = OpeningKind.WINDOW
    label: str = ""

    @property
    def area_sf(self) -> float:
        return self.width_ft * self.height_ft


@dataclass
class Wall:
    """A run of masonry, described by its centerline in plan.

    The centerline is the trade-standard way to measure a wall, and it has a
    property worth knowing: for a closed loop it is exactly self-correcting at
    the corners (see ``geometry.junctions``). It is not self-correcting
    anywhere else, which is what the junction solver exists to fix.
    """

    id: int
    vertices: list[Point]
    assembly_key: str
    height_ft: float
    label: str = ""

    def __post_init__(self) -> None:
        if len(self.vertices) < 2:
            raise ValueError(f"wall {self.id} needs at least 2 vertices")
        if self.height_ft <= 0:
            raise ValueError(f"wall {self.id} needs a positive height")

    @property
    def segments(self) -> list[tuple[Point, Point]]:
        return list(zip(self.vertices, self.vertices[1:], strict=False))

    @property
    def centerline_length_ft(self) -> float:
        total = 0.0
        for (x1, y1), (x2, y2) in self.segments:
            total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return total


@dataclass
class TakeoffSettings:
    """Estimating rules the user is allowed to disagree with.

    These are defaults, not laws. Every shop has its own waste factor and its
    own view on small-opening deductions, so they live in the project file and
    print on the report.
    """

    waste_factor: float = 0.05
    #: Openings at or below this face area are not deducted. The material saved
    #: is offset by the cutting and the labour around the jamb, so most specs
    #: set a floor. 10 sf is a common one.
    min_deduct_area_sf: float = 10.0
    #: Titan America's guide puts sand at 1 cubic yard per 7 bags of mortar.
    sand_cy_per_bag: float = 1.0 / 7.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.waste_factor < 1.0:
            raise ValueError("waste_factor must be in [0, 1)")
        if self.min_deduct_area_sf < 0:
            raise ValueError("min_deduct_area_sf cannot be negative")


@dataclass
class Project:
    """Everything that gets saved to the .ctk file."""

    name: str = "Untitled takeoff"
    plan_path: str | None = None
    #: Pixels per foot, established by the scale calibration. ``None`` until the
    #: user has calibrated, which the UI requires before any wall can be drawn.
    px_per_ft: float | None = None
    walls: list[Wall] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    settings: TakeoffSettings = field(default_factory=TakeoffSettings)

    def wall(self, wall_id: int) -> Wall:
        for w in self.walls:
            if w.id == wall_id:
                return w
        raise KeyError(f"no wall with id {wall_id}")

    def openings_for(self, wall_id: int) -> list[Opening]:
        return [o for o in self.openings if o.wall_id == wall_id]

    def next_wall_id(self) -> int:
        return max((w.id for w in self.walls), default=0) + 1

    def next_opening_id(self) -> int:
        return max((o.id for o in self.openings), default=0) + 1

    def with_settings(self, **kw: object) -> Project:
        return replace(self, settings=replace(self.settings, **kw))
