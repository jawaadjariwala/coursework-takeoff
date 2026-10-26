"""Project persistence in a single SQLite file.

A takeoff is a document, so the obvious options were a JSON file or a small
database. SQLite won because a takeoff is also a thing people query: "every
opening over 20 sf", "every wall of 12 inch block", "what changed since the
last revision". Those are one line of SQL and a page of Python over JSON.

It also writes atomically, which matters for a file an estimator has spent an
afternoon on.

Schema changes go through ``MIGRATIONS``. Each entry runs once, in order, and
``schema_version`` in the meta table records how far a file has come. A file
written by an older build opens in a newer one without the user knowing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..model.types import Opening, OpeningKind, Project, TakeoffSettings, Wall

SCHEMA_VERSION = 1

MIGRATIONS: list[str] = [
    # v1: initial schema
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE project (
        id                 INTEGER PRIMARY KEY CHECK (id = 1),
        name               TEXT    NOT NULL,
        plan_path          TEXT,
        px_per_ft          REAL,
        waste_factor       REAL    NOT NULL,
        min_deduct_area_sf REAL    NOT NULL,
        sand_cy_per_bag    REAL    NOT NULL
    );
    CREATE TABLE wall (
        id           INTEGER PRIMARY KEY,
        assembly_key TEXT    NOT NULL,
        height_ft    REAL    NOT NULL CHECK (height_ft > 0),
        label        TEXT    NOT NULL DEFAULT ''
    );
    CREATE TABLE wall_vertex (
        wall_id INTEGER NOT NULL REFERENCES wall(id) ON DELETE CASCADE,
        seq     INTEGER NOT NULL,
        x       REAL    NOT NULL,
        y       REAL    NOT NULL,
        PRIMARY KEY (wall_id, seq)
    );
    CREATE TABLE opening (
        id         INTEGER PRIMARY KEY,
        wall_id    INTEGER NOT NULL REFERENCES wall(id) ON DELETE CASCADE,
        width_ft   REAL    NOT NULL CHECK (width_ft  > 0),
        height_ft  REAL    NOT NULL CHECK (height_ft > 0),
        station_ft REAL    NOT NULL,
        sill_ft    REAL    NOT NULL DEFAULT 0,
        kind       TEXT    NOT NULL DEFAULT 'window',
        label      TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_opening_wall ON opening(wall_id);
    """,
]


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if row is None:
        return 0
    got = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    # Indexed positionally on purpose: migrate() is public and callers are not
    # required to have set a row_factory on their connection.
    return int(got[0]) if got else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Bring a connection up to the current schema. Returns the version."""
    version = _current_version(conn)
    for index in range(version, len(MIGRATIONS)):
        conn.executescript(MIGRATIONS[index])
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(index + 1),),
        )
    conn.commit()
    return _current_version(conn)


def save(project: Project, path: str | Path) -> None:
    """Write the whole project. Atomic: either the new state or the old one."""
    path = Path(path)
    conn = _connect(path)
    try:
        migrate(conn)
        with conn:  # one transaction, rolled back on any exception
            conn.execute("DELETE FROM opening")
            conn.execute("DELETE FROM wall_vertex")
            conn.execute("DELETE FROM wall")
            conn.execute("DELETE FROM project")
            s = project.settings
            conn.execute(
                "INSERT INTO project(id, name, plan_path, px_per_ft, waste_factor,"
                " min_deduct_area_sf, sand_cy_per_bag) VALUES (1,?,?,?,?,?,?)",
                (
                    project.name,
                    project.plan_path,
                    project.px_per_ft,
                    s.waste_factor,
                    s.min_deduct_area_sf,
                    s.sand_cy_per_bag,
                ),
            )
            for w in project.walls:
                conn.execute(
                    "INSERT INTO wall(id, assembly_key, height_ft, label)"
                    " VALUES (?,?,?,?)",
                    (w.id, w.assembly_key, w.height_ft, w.label),
                )
                conn.executemany(
                    "INSERT INTO wall_vertex(wall_id, seq, x, y) VALUES (?,?,?,?)",
                    [(w.id, i, x, y) for i, (x, y) in enumerate(w.vertices)],
                )
            for o in project.openings:
                conn.execute(
                    "INSERT INTO opening(id, wall_id, width_ft, height_ft,"
                    " station_ft, sill_ft, kind, label) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        o.id,
                        o.wall_id,
                        o.width_ft,
                        o.height_ft,
                        o.station_ft,
                        o.sill_ft,
                        o.kind.value,
                        o.label,
                    ),
                )
    finally:
        conn.close()


def load(path: str | Path) -> Project:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = _connect(path)
    try:
        migrate(conn)
        row = conn.execute("SELECT * FROM project WHERE id = 1").fetchone()
        if row is None:
            return Project()

        vertices: dict[int, list[tuple[float, float]]] = {}
        for v in conn.execute(
            "SELECT wall_id, x, y FROM wall_vertex ORDER BY wall_id, seq"
        ):
            vertices.setdefault(v["wall_id"], []).append((v["x"], v["y"]))

        walls = [
            Wall(
                id=w["id"],
                vertices=vertices.get(w["id"], []),
                assembly_key=w["assembly_key"],
                height_ft=w["height_ft"],
                label=w["label"],
            )
            for w in conn.execute("SELECT * FROM wall ORDER BY id")
        ]
        openings = [
            Opening(
                id=o["id"],
                wall_id=o["wall_id"],
                width_ft=o["width_ft"],
                height_ft=o["height_ft"],
                station_ft=o["station_ft"],
                sill_ft=o["sill_ft"],
                kind=OpeningKind(o["kind"]),
                label=o["label"],
            )
            for o in conn.execute("SELECT * FROM opening ORDER BY id")
        ]
        return Project(
            name=row["name"],
            plan_path=row["plan_path"],
            px_per_ft=row["px_per_ft"],
            walls=walls,
            openings=openings,
            settings=TakeoffSettings(
                waste_factor=row["waste_factor"],
                min_deduct_area_sf=row["min_deduct_area_sf"],
                sand_cy_per_bag=row["sand_cy_per_bag"],
            ),
        )
    finally:
        conn.close()
