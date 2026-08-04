"""Gemeinsame Datentypen und die Aktivitaetsregel.

Dieses Modul ist bewusst frei von I/O. Alles hier ist rein und ohne Seiteneffekt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RESOLVE_BUNDLE_PREFIX = "com.blackmagic-design.DaVinciResolve"


@dataclass(frozen=True)
class ResolveSnapshot:
    """Was ein einzelner Poll aus Resolve herausbekommen hat."""

    connected: bool
    project_name: str | None = None
    database_name: str | None = None
    page: str | None = None
    timeline_name: str | None = None
    timecode: str | None = None


@dataclass(frozen=True)
class Tick:
    now: datetime
    snapshot: ResolveSnapshot
    idle_seconds: float
    frontmost_bundle_id: str | None
    manual_pause: bool = False


@dataclass(frozen=True)
class OpenSegment:
    project: str
    database: str | None
    started_at: datetime
    page: str | None


@dataclass(frozen=True)
class TouchSegment:
    last_active_at: datetime
    page: str | None


@dataclass(frozen=True)
class CloseSegment:
    ended_at: datetime


Command = OpenSegment | TouchSegment | CloseSegment


def is_resolve_frontmost(bundle_id: str | None) -> bool:
    return bundle_id is not None and bundle_id.startswith(RESOLVE_BUNDLE_PREFIX)


def is_active(tick: Tick, input_grace_seconds: float) -> bool:
    """Gearbeitet wird, wenn Resolve vorne ist und kuerzlich Input kam.

    Ein Playback-Signal (Timecode-Aenderung als Alternative zu Input) war urspruenglich
    vorgesehen, entfaellt aber: GetCurrentTimecode() aktualisiert sich laut Live-Test
    waehrend aktiver Wiedergabe nicht zuverlaessig per Skript-Poll.
    """
    if tick.manual_pause:
        return False
    if not tick.snapshot.connected or not tick.snapshot.project_name:
        return False
    if not is_resolve_frontmost(tick.frontmost_bundle_id):
        return False
    return tick.idle_seconds < input_grace_seconds
