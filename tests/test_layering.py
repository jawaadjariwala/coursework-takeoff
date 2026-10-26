"""The geometry engine must stay runnable without a display.

Qt is confined to ``coursework.ui``. That is what lets the solver be tested in
CI, benchmarked in a loop and driven from the command line. It is easy to
break by accident with one convenience import, so it is checked rather than
trusted.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "coursework"
FORBIDDEN = {"PySide6", "PyQt5", "PyQt6", "shiboken6"}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_the_ui_package_imports_qt():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC).parts[0] == "ui":
            continue
        hits = _imported_roots(path) & FORBIDDEN
        if hits:
            offenders.append(f"{path.relative_to(SRC)} imports {sorted(hits)}")
    assert not offenders, "Qt leaked out of the ui package:\n" + "\n".join(offenders)


def test_the_engine_carries_no_geometry_library():
    """shapely is a test dependency. It must not reach production code."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if "shapely" in _imported_roots(path):
            offenders.append(str(path.relative_to(SRC)))
    assert not offenders, f"shapely leaked into production code: {offenders}"
