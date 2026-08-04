"""SQLite-Persistenz. Segmente sind append-only, die Datenbank ist die einzige Wahrheit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    resolve_project TEXT NOT NULL,
    resolve_database TEXT,
    started_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    ended_at TEXT,
    pages_seen TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    toggl_entry_id INTEGER,
    synced_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_segments_started ON segments(started_at);
CREATE TABLE IF NOT EXISTS project_map (
    resolve_project TEXT PRIMARY KEY,
    toggl_workspace_id INTEGER NOT NULL,
    toggl_project_id INTEGER
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Segment:
    id: int
    resolve_project: str
    resolve_database: str | None
    started_at: datetime
    last_active_at: datetime
    ended_at: datetime | None
    pages_seen: list[str]
    note: str | None
    toggl_entry_id: int | None
    synced_at: datetime | None

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or self.last_active_at
        return (end - self.started_at).total_seconds()


def _dump(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _load(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class Store:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(self.SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self._conn.close()

    def open_segment(
        self,
        project: str,
        database: str | None,
        started_at: datetime,
        page: str | None,
    ) -> int:
        pages = json.dumps([page] if page else [])
        cursor = self._conn.execute(
            "INSERT INTO segments(resolve_project, resolve_database, started_at, last_active_at, pages_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (project, database, _dump(started_at), _dump(started_at), pages),
        )
        return int(cursor.lastrowid)

    def touch_segment(self, segment_id: int, last_active_at: datetime, page: str | None) -> None:
        row = self._conn.execute(
            "SELECT pages_seen FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        pages = json.loads(row["pages_seen"])
        if page and page not in pages:
            pages.append(page)
        self._conn.execute(
            "UPDATE segments SET last_active_at = ?, pages_seen = ? WHERE id = ?",
            (_dump(last_active_at), json.dumps(pages), segment_id),
        )

    def close_segment(self, segment_id: int, ended_at: datetime) -> None:
        self._conn.execute(
            "UPDATE segments SET ended_at = ? WHERE id = ?", (_dump(ended_at), segment_id)
        )

    def current_open_segment(self) -> Segment | None:
        row = self._conn.execute(
            "SELECT * FROM segments WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_segment(row) if row else None

    def close_stale_segments(self) -> int:
        cursor = self._conn.execute(
            "UPDATE segments SET ended_at = last_active_at WHERE ended_at IS NULL"
        )
        return cursor.rowcount

    def segments_since(self, since: datetime) -> list[Segment]:
        rows = self._conn.execute(
            "SELECT * FROM segments WHERE started_at >= ? ORDER BY started_at",
            (_dump(since),),
        ).fetchall()
        return [_row_to_segment(row) for row in rows]


def _row_to_segment(row: sqlite3.Row) -> Segment:
    return Segment(
        id=row["id"],
        resolve_project=row["resolve_project"],
        resolve_database=row["resolve_database"],
        started_at=_load(row["started_at"]),
        last_active_at=_load(row["last_active_at"]),
        ended_at=_load(row["ended_at"]),
        pages_seen=json.loads(row["pages_seen"]),
        note=row["note"],
        toggl_entry_id=row["toggl_entry_id"],
        synced_at=_load(row["synced_at"]),
    )
