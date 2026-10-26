"""Turn resolved geometry into a bill of materials.

The chain is deliberately short and each step is reportable, because an
estimator who cannot see where a number came from will not use it:

    centerline length
      - junction corrections        -> net length
      x wall height                 -> gross face area
      - openings over the threshold -> net face area
      x units per sf                -> unit count
      x (1 + waste)                 -> ordered count
      -> mortar bags -> sand
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..geometry.junctions import Solution, solve
from ..model.types import Assembly, Opening, Project
from .catalog import CATALOG, get


@dataclass
class WallLine:
    wall_id: int
    label: str
    assembly: Assembly
    height_ft: float
    gross_length_ft: float
    net_length_ft: float
    openings: list[Opening] = field(default_factory=list)
    deducted_openings: list[Opening] = field(default_factory=list)

    @property
    def junction_correction_ft(self) -> float:
        return self.net_length_ft - self.gross_length_ft

    @property
    def gross_area_sf(self) -> float:
        """Face area before openings, using the corrected length."""
        return self.net_length_ft * self.height_ft

    @property
    def naive_area_sf(self) -> float:
        """What the uncorrected centerline would have claimed."""
        return self.gross_length_ft * self.height_ft

    @property
    def opening_deduction_sf(self) -> float:
        return sum(o.area_sf for o in self.deducted_openings)

    @property
    def ignored_opening_sf(self) -> float:
        kept = {id(o) for o in self.deducted_openings}
        return sum(o.area_sf for o in self.openings if id(o) not in kept)

    @property
    def net_area_sf(self) -> float:
        return max(0.0, self.gross_area_sf - self.opening_deduction_sf)

    @property
    def units(self) -> float:
        return self.net_area_sf * self.assembly.units_per_sf


@dataclass
class MaterialTotal:
    assembly: Assembly
    net_area_sf: float
    naive_area_sf: float
    units: float
    units_with_waste: float
    mortar_bags: float
    sand_cy: float

    @property
    def overstatement_sf(self) -> float:
        return self.naive_area_sf - self.net_area_sf


@dataclass
class Report:
    project_name: str
    lines: list[WallLine]
    materials: dict[str, MaterialTotal]
    solution: Solution
    waste_factor: float
    min_deduct_area_sf: float
    warnings: list[str] = field(default_factory=list)

    @property
    def total_net_area_sf(self) -> float:
        return sum(line.net_area_sf for line in self.lines)

    @property
    def total_naive_area_sf(self) -> float:
        """Face area with no junction corrections and no opening deductions.

        This is the number a takeoff produces when walls are summed straight
        off their centerlines, which is the common case worth comparing to.
        """
        return sum(line.naive_area_sf for line in self.lines)

    @property
    def overstatement_sf(self) -> float:
        return self.total_naive_area_sf - self.total_net_area_sf

    @property
    def overstatement_pct(self) -> float:
        if self.total_naive_area_sf == 0:
            return 0.0
        return 100.0 * self.overstatement_sf / self.total_naive_area_sf

    @property
    def junction_overstatement_sf(self) -> float:
        """The part of the overstatement caused by junctions alone."""
        return sum(
            -line.junction_correction_ft * line.height_ft for line in self.lines
        )


def build(project: Project, assemblies: dict[str, Assembly] | None = None) -> Report:
    asm = assemblies or CATALOG
    solution = solve(project.walls, asm)
    threshold = project.settings.min_deduct_area_sf

    lines: list[WallLine] = []
    for wall in project.walls:
        openings = project.openings_for(wall.id)
        line = WallLine(
            wall_id=wall.id,
            label=wall.label or f"W{wall.id}",
            assembly=(
                get(wall.assembly_key)
                if assemblies is None
                else asm[wall.assembly_key]
            ),
            height_ft=wall.height_ft,
            gross_length_ft=solution.gross_length_ft[wall.id],
            net_length_ft=solution.net_length_ft[wall.id],
            openings=openings,
            deducted_openings=[o for o in openings if o.area_sf > threshold],
        )
        lines.append(line)

    materials: dict[str, MaterialTotal] = {}
    for line in lines:
        key = line.assembly.key
        t = materials.get(key)
        if t is None:
            t = MaterialTotal(line.assembly, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            materials[key] = t
        t.net_area_sf += line.net_area_sf
        t.naive_area_sf += line.naive_area_sf
        t.units += line.units

    waste = project.settings.waste_factor
    for t in materials.values():
        t.units_with_waste = t.units * (1.0 + waste)
        t.mortar_bags = (
            t.units_with_waste / 100.0
        ) * t.assembly.mortar_bags_per_100_units
        t.sand_cy = t.mortar_bags * project.settings.sand_cy_per_bag

    warnings = list(solution.warnings)
    ignored = sum(line.ignored_opening_sf for line in lines)
    if ignored > 0:
        warnings.append(
            f"{ignored:.1f} sf of openings at or below the "
            f"{threshold:.0f} sf threshold were not deducted"
        )

    return Report(
        project_name=project.name,
        lines=lines,
        materials=materials,
        solution=solution,
        waste_factor=waste,
        min_deduct_area_sf=threshold,
        warnings=warnings,
    )
