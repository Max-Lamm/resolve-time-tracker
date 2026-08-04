"""Adapter zur Resolve-Scripting-API.

Jeder Fehler wird zu einem nicht verbundenen Snapshot. Der Tracker soll nie
wegen eines API-Zuckens abstuerzen, im Zweifel wird lieber nicht getrackt.
"""

from __future__ import annotations

import logging
import os

from .models import ResolveSnapshot

log = logging.getLogger(__name__)

DISCONNECTED = ResolveSnapshot(connected=False)

DEFAULT_SCRIPT_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
DEFAULT_SCRIPT_LIB = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
)


def ensure_environment() -> None:
    """Setzt die Resolve-Variablen, falls der Prozess sie nicht geerbt hat."""
    os.environ.setdefault("RESOLVE_SCRIPT_API", DEFAULT_SCRIPT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", DEFAULT_SCRIPT_LIB)
    modules = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if modules not in os.environ.get("PYTHONPATH", ""):
        os.environ["PYTHONPATH"] = f"{os.environ.get('PYTHONPATH', '')}:{modules}".strip(":")
    import sys

    if modules not in sys.path:
        sys.path.append(modules)


class ResolveProbe:
    def __init__(self) -> None:
        ensure_environment()
        self._resolve = None

    def _connect(self):
        if self._resolve is not None:
            return self._resolve
        try:
            import DaVinciResolveScript as dvr

            self._resolve = dvr.scriptapp("Resolve")
        except Exception:
            log.debug("Verbindung zu Resolve nicht moeglich", exc_info=True)
            self._resolve = None
        return self._resolve

    def poll(self) -> ResolveSnapshot:
        resolve = self._connect()
        if resolve is None:
            return DISCONNECTED

        try:
            manager = resolve.GetProjectManager()
            project = manager.GetCurrentProject()
            if project is None:
                return ResolveSnapshot(connected=True)

            timecode = None
            timeline_name = None
            timeline = project.GetCurrentTimeline()
            if timeline is not None:
                timeline_name = timeline.GetName()
                timecode = timeline.GetCurrentTimecode()

            return ResolveSnapshot(
                connected=True,
                project_name=project.GetName(),
                database_name=_database_name(manager),
                page=resolve.GetCurrentPage(),
                timeline_name=timeline_name,
                timecode=timecode,
            )
        except Exception:
            # Resolve wurde vermutlich beendet. Verbindung verwerfen, beim naechsten
            # Tick wird neu verbunden.
            log.debug("Poll fehlgeschlagen, Verbindung wird verworfen", exc_info=True)
            self._resolve = None
            return DISCONNECTED


def _database_name(manager) -> str | None:
    try:
        database = manager.GetCurrentDatabase()
        if isinstance(database, dict):
            return database.get("DbName")
        return str(database) if database else None
    except Exception:
        return None
