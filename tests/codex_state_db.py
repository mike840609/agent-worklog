"""Shared Codex `state_<n>.sqlite` schema and builder.

Both the unit-level Codex harness tests and the `codex_home` acceptance fixture
in `conftest.py` need a real `threads` + `thread_spawn_edges` database. This is
the one place the `CREATE TABLE` text exists, so a schema change (a new column,
a changed constraint) only has to be made once.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    agent_nickname TEXT,
    thread_source TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE thread_spawn_edges (
    parent_thread_id TEXT NOT NULL,
    child_thread_id TEXT NOT NULL PRIMARY KEY,
    status TEXT NOT NULL
);
"""


def seconds(value: datetime) -> int:
    """Convert a datetime to unix timestamp."""
    return int(value.timestamp())


def write_database(
    path: Path, rows: list[tuple], edges: list[tuple] | None = None
) -> None:
    """Create and populate a Codex state database with threads and edges."""
    if edges is None:
        edges = []
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO threads (id, rollout_path, created_at, updated_at, cwd,"
            " title, agent_nickname, thread_source, archived)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO thread_spawn_edges"
            " (parent_thread_id, child_thread_id, status) VALUES (?, ?, ?)",
            edges,
        )
        connection.commit()
    finally:
        connection.close()
