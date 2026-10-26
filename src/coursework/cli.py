"""Command line entry point.

The engine is useful without the window, which is the point of keeping Qt out
of everything below ``coursework.ui``. This is also what makes the numbers
testable in CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .demo import demo_project
from .model.types import Project
from .quantities import render, takeoff
from .store import sqlite_store


def _load(args: argparse.Namespace) -> Project:
    if args.demo:
        return demo_project()
    if not args.file:
        raise SystemExit("give a .ctk file or pass --demo")
    return sqlite_store.load(args.file)


def _add_source(p: argparse.ArgumentParser) -> None:
    p.add_argument("file", nargs="?", help="a .ctk takeoff file")
    p.add_argument("--demo", action="store_true", help="use the built-in demo building")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="coursework",
        description="Masonry quantity takeoff with honest junction resolution.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="print the takeoff")
    _add_source(p_report)
    p_report.add_argument("--waste", type=float, help="override the waste factor")

    p_export = sub.add_parser("export", help="write the takeoff as CSV")
    _add_source(p_export)
    p_export.add_argument("-o", "--output", required=True, help="CSV path")

    p_save = sub.add_parser("save-demo", help="write the demo building to a .ctk file")
    p_save.add_argument("output", help="where to write it")

    p_bench = sub.add_parser("bench", help="benchmark junction detection")
    p_bench.add_argument("--max-walls", type=int, default=400)
    p_bench.add_argument("--repeats", type=int, default=3)

    p_ui = sub.add_parser("ui", help="open the desktop app")
    p_ui.add_argument("file", nargs="?", help="a .ctk file to open")
    p_ui.add_argument(
        "--demo-plan",
        action="store_true",
        help="open the demo building already traced over assets/demo_plan.pdf",
    )

    args = parser.parse_args(argv)

    if args.command == "report":
        project = _load(args)
        if args.waste is not None:
            project = project.with_settings(waste_factor=args.waste)
        print(render.as_text(takeoff.build(project)))
        return 0

    if args.command == "export":
        project = _load(args)
        out = Path(args.output)
        out.write_text(render.as_csv(takeoff.build(project)))
        print(f"wrote {out}")
        return 0

    if args.command == "save-demo":
        sqlite_store.save(demo_project(), args.output)
        print(f"wrote {args.output}")
        return 0

    if args.command == "bench":
        from .bench import run_benchmark

        print(run_benchmark(max_walls=args.max_walls, repeats=args.repeats))
        return 0

    if args.command == "ui":
        from .ui.app import run

        return run(args.file, demo_plan=args.demo_plan)

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
