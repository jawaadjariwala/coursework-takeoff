"""Report output: a readable table and a CSV an estimator can open in Excel."""

from __future__ import annotations

import csv
import io

from ..model.units import format_ft_in
from .takeoff import Report


def as_text(report: Report, *, width: int = 88) -> str:
    out: list[str] = []
    add = out.append

    add("=" * width)
    add(report.project_name)
    add("=" * width)
    add("")
    add(
        f"{'WALL':<16}{'ASSEMBLY':<16}{'GROSS':>13}{'NET':>13}"
        f"{'HT':>7}{'OPENINGS':>11}{'NET SF':>12}"
    )
    add("-" * width)
    for line in sorted(report.lines, key=lambda x: x.wall_id):
        add(
            f"{line.label[:15]:<16}"
            f"{line.assembly.label[:15]:<16}"
            f"{format_ft_in(line.gross_length_ft):>13}"
            f"{format_ft_in(line.net_length_ft):>13}"
            f"{line.height_ft:>6.1f}'"
            f"{line.opening_deduction_sf:>10.1f}"
            f"{line.net_area_sf:>12.1f}"
        )
    add("-" * width)
    add(f"{'TOTAL NET':>{width - 12}}{report.total_net_area_sf:>12.1f}")
    add("")

    add("JUNCTIONS")
    add("-" * width)
    counts = report.solution.counts_by_kind()
    names = {
        "L": "L corner",
        "T": "T intersection",
        "X": "X crossing",
        "multi": "multi-way (review)",
    }
    if counts:
        for kind, n in sorted(counts.items()):
            add(f"  {names.get(kind, kind):<24}{n:>4}")
    else:
        add("  none")
    add("")
    add(
        f"  centerline face area      {report.total_naive_area_sf:>12.1f} sf  "
        f"(no corrections, no deductions)"
    )
    add(f"  junction corrections      {-report.junction_overstatement_sf:>12.1f} sf")
    add(
        f"  opening deductions        "
        f"{-(report.overstatement_sf - report.junction_overstatement_sf):>12.1f} sf"
    )
    add(f"  net face area             {report.total_net_area_sf:>12.1f} sf")
    add(
        f"  overstated by             {report.overstatement_sf:>12.1f} sf  "
        f"({report.overstatement_pct:.2f}%)"
    )
    add("")

    add("MATERIALS")
    add("-" * width)
    add(
        f"{'ASSEMBLY':<18}{'NET SF':>11}{'RATE':>10}{'UNITS':>11}"
        f"{'+WASTE':>11}{'MORTAR':>11}{'SAND CY':>10}"
    )
    for key in sorted(report.materials):
        t = report.materials[key]
        add(
            f"{t.assembly.label[:17]:<18}"
            f"{t.net_area_sf:>11.1f}"
            f"{t.assembly.units_per_sf:>10.3f}"
            f"{t.units:>11.0f}"
            f"{t.units_with_waste:>11.0f}"
            f"{t.mortar_bags:>10.1f}b"
            f"{t.sand_cy:>10.1f}"
        )
    add("")
    add(
        f"rules: {report.waste_factor * 100:.0f}% waste, openings over "
        f"{report.min_deduct_area_sf:.0f} sf deducted"
    )

    if report.warnings:
        add("")
        add("WARNINGS")
        add("-" * width)
        for w in report.warnings:
            add(f"  ! {w}")
    return "\n".join(out)


def as_csv(report: Report) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    w.writerow(["Coursework masonry takeoff"])
    w.writerow(["Project", report.project_name])
    w.writerow(["Waste factor", f"{report.waste_factor:.3f}"])
    w.writerow(["Opening deduction threshold (sf)", f"{report.min_deduct_area_sf:.1f}"])
    w.writerow([])

    w.writerow(
        [
            "Wall",
            "Assembly",
            "Gross length (ft)",
            "Junction correction (ft)",
            "Net length (ft)",
            "Height (ft)",
            "Gross area (sf)",
            "Openings deducted (sf)",
            "Openings ignored (sf)",
            "Net area (sf)",
            "Units",
        ]
    )
    for line in sorted(report.lines, key=lambda x: x.wall_id):
        w.writerow(
            [
                line.label,
                line.assembly.label,
                f"{line.gross_length_ft:.4f}",
                f"{line.junction_correction_ft:.4f}",
                f"{line.net_length_ft:.4f}",
                f"{line.height_ft:.2f}",
                f"{line.gross_area_sf:.2f}",
                f"{line.opening_deduction_sf:.2f}",
                f"{line.ignored_opening_sf:.2f}",
                f"{line.net_area_sf:.2f}",
                f"{line.units:.1f}",
            ]
        )

    w.writerow([])
    w.writerow(
        ["Assembly", "Net area (sf)", "Units per sf", "Units", "Units with waste",
         "Mortar bags", "Sand (CY)"]
    )
    for key in sorted(report.materials):
        t = report.materials[key]
        w.writerow(
            [
                t.assembly.label,
                f"{t.net_area_sf:.2f}",
                f"{t.assembly.units_per_sf:.3f}",
                f"{t.units:.1f}",
                f"{t.units_with_waste:.1f}",
                f"{t.mortar_bags:.2f}",
                f"{t.sand_cy:.2f}",
            ]
        )

    w.writerow([])
    w.writerow(["Centerline face area (sf)", f"{report.total_naive_area_sf:.2f}"])
    w.writerow(["Junction corrections (sf)", f"{-report.junction_overstatement_sf:.2f}"])
    w.writerow(["Net face area (sf)", f"{report.total_net_area_sf:.2f}"])
    w.writerow(["Overstated by (sf)", f"{report.overstatement_sf:.2f}"])
    w.writerow(["Overstated by (%)", f"{report.overstatement_pct:.2f}"])

    w.writerow([])
    w.writerow(["Junction", "Kind", "X", "Y", "Owner wall", "Note"])
    for i, j in enumerate(report.solution.junctions, start=1):
        w.writerow(
            [i, j.kind.value, f"{j.point[0]:.3f}", f"{j.point[1]:.3f}",
             j.owner_wall_id if j.owner_wall_id is not None else "", j.note]
        )

    if report.warnings:
        w.writerow([])
        w.writerow(["Warnings"])
        for warning in report.warnings:
            w.writerow([warning])
    return buf.getvalue()
