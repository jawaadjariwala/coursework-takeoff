"""Persistence round trips and schema migration."""

from __future__ import annotations

import sqlite3

import pytest

from coursework.model.types import Opening, OpeningKind, Project, Wall
from coursework.quantities import takeoff
from coursework.store import sqlite_store

from . import plans


def sample() -> Project:
    walls = plans.shell(20.0, 30.0) + [
        Wall(5, [(0, 10), (20, 10), (8, 22)], "cmu12", 9.5, label="Corridor"),
        Wall(6, [(20, 20), (34, 20)], "brick4", 12.0),
    ]
    return Project(
        name="Test building",
        plan_path="/plans/a1.pdf",
        px_per_ft=14.25,
        walls=walls,
        openings=[
            Opening(1, 1, 3.0, 7.0, 6.0, kind=OpeningKind.DOOR, label="D1"),
            Opening(2, 5, 4.0, 4.0, 12.0, sill_ft=3.0),
        ],
    ).with_settings(waste_factor=0.07, min_deduct_area_sf=8.0)


def test_round_trip_preserves_everything(tmp_path):
    path = tmp_path / "job.ctk"
    original = sample()
    sqlite_store.save(original, path)
    loaded = sqlite_store.load(path)

    assert loaded.name == original.name
    assert loaded.plan_path == original.plan_path
    assert loaded.px_per_ft == pytest.approx(original.px_per_ft)
    assert loaded.settings == original.settings
    assert [w.vertices for w in loaded.walls] == [w.vertices for w in original.walls]
    assert [w.assembly_key for w in loaded.walls] == [
        w.assembly_key for w in original.walls
    ]
    assert loaded.openings == original.openings


def test_round_trip_preserves_the_numbers(tmp_path):
    """The real guarantee: saving and reopening cannot change the takeoff."""
    path = tmp_path / "job.ctk"
    original = sample()
    sqlite_store.save(original, path)
    before = takeoff.build(original)
    after = takeoff.build(sqlite_store.load(path))
    assert after.total_net_area_sf == pytest.approx(before.total_net_area_sf)
    for key, total in before.materials.items():
        assert after.materials[key].units == pytest.approx(total.units)


def test_saving_twice_replaces_rather_than_appends(tmp_path):
    path = tmp_path / "job.ctk"
    sqlite_store.save(sample(), path)
    sqlite_store.save(sample(), path)
    loaded = sqlite_store.load(path)
    assert len(loaded.walls) == 6
    assert len(loaded.openings) == 2


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "job.ctk"
    conn = sqlite3.connect(path)
    try:
        assert sqlite_store.migrate(conn) == sqlite_store.SCHEMA_VERSION
        assert sqlite_store.migrate(conn) == sqlite_store.SCHEMA_VERSION
    finally:
        conn.close()


def test_openings_die_with_their_wall(tmp_path):
    """Foreign keys are on, so an orphaned opening cannot be written."""
    path = tmp_path / "job.ctk"
    sqlite_store.save(sample(), path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("DELETE FROM wall WHERE id = 5")
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM opening").fetchone()[0]
        assert remaining == 1
    finally:
        conn.close()


def test_a_failed_save_leaves_the_old_file_intact(tmp_path):
    """An estimator's afternoon of work survives a bad write."""
    path = tmp_path / "job.ctk"
    good = sample()
    sqlite_store.save(good, path)

    broken = sample()
    broken.walls.append(Wall(99, [(0, 0), (1, 1)], "cmu8", 10))
    broken.walls[-1].height_ft = -5  # violates the CHECK constraint

    with pytest.raises(sqlite3.IntegrityError):
        sqlite_store.save(broken, path)

    reopened = sqlite_store.load(path)
    assert len(reopened.walls) == 6


def test_missing_file_is_an_error_not_an_empty_project(tmp_path):
    with pytest.raises(FileNotFoundError):
        sqlite_store.load(tmp_path / "nope.ctk")
