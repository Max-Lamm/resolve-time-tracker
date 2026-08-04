"""SQLite-Persistenz. Segmente sind append-only, die Datenbank ist die einzige Wahrheit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
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


@dataclass(frozen=True)
class ProjectMapping:
    resolve_project: str
    toggl_workspace_id: int
    toggl_project_id: int | None


def _require_utc(value: datetime) -> datetime:
    """Enforce that datetime values are timezone-aware UTC.

    Raises ValueError if the datetime is naive or not in UTC timezone.
    """
    if value.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed: {value}. All datetimes must be timezone-aware UTC.")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"Non-UTC datetime not allowed: {value}. All datetimes must be in UTC timezone.")
    return value


def _dump(value: datetime | None) -> str | None:
    if value is None:
        return None
    _require_utc(value)
    return value.isoformat()


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

    def get_mapping(self, resolve_project: str) -> ProjectMapping | None:
        row = self._conn.execute(
            "SELECT * FROM project_map WHERE resolve_project = ?", (resolve_project,)
        ).fetchone()
        if row is None:
            return None
        return ProjectMapping(
            resolve_project=row["resolve_project"],
            toggl_workspace_id=row["toggl_workspace_id"],
            toggl_project_id=row["toggl_project_id"],
        )

    def set_mapping(
        self, resolve_project: str, workspace_id: int, project_id: int | None
    ) -> None:
        self._conn.execute(
            "INSERT INTO project_map(resolve_project, toggl_workspace_id, toggl_project_id)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(resolve_project) DO UPDATE SET"
            " toggl_workspace_id = excluded.toggl_workspace_id,"
            " toggl_project_id = excluded.toggl_project_id",
            (resolve_project, workspace_id, project_id),
        )

    def all_projects(self) -> list[str]:
        """Alle Resolve-Projekte, die je ein Segment hatten -- zugeordnet oder nicht.

        Fuer die Zuordnen-UI: unmapped_projects() reicht dort nicht, weil eine
        bestehende Zuordnung sich auch korrigieren lassen soll.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT resolve_project FROM segments ORDER BY resolve_project"
        ).fetchall()
        return [row["resolve_project"] for row in rows]

    def unmapped_projects(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT s.resolve_project FROM segments s"
            " LEFT JOIN project_map m ON m.resolve_project = s.resolve_project"
            " WHERE s.toggl_entry_id IS NULL AND m.resolve_project IS NULL"
            " ORDER BY s.resolve_project"
        ).fetchall()
        return [row["resolve_project"] for row in rows]

    def unsynced_segments(self, closed_before: datetime) -> list[Segment]:
        rows = self._conn.execute(
            "SELECT * FROM segments"
            " WHERE ended_at IS NOT NULL AND toggl_entry_id IS NULL AND ended_at < ?"
            " ORDER BY started_at",
            (_dump(closed_before),),
        ).fetchall()
        return [_row_to_segment(row) for row in rows]

    def mark_synced(
        self, segment_ids: list[int], toggl_entry_id: int, synced_at: datetime
    ) -> None:
        placeholders = ",".join("?" for _ in segment_ids)
        self._conn.execute(
            f"UPDATE segments SET toggl_entry_id = ?, synced_at = ? WHERE id IN ({placeholders})",
            (toggl_entry_id, _dump(synced_at), *segment_ids),
        )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def totals_since(self, since: datetime) -> dict[str, float]:
        totals: dict[str, float] = {}
        for segment in self.segments_since(since):
            totals[segment.resolve_project] = (
                totals.get(segment.resolve_project, 0.0) + segment.duration_seconds
            )
        return totals


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
