"""Verhindert, dass zwei Tracking-Prozesse gleichzeitig gegen dieselbe Datenbank schreiben.

Seit es zwei Startwege gibt (LaunchAgent-Autostart und eine manuell
gestartete App/CLI), kann der Tracker sonst versehentlich doppelt laufen.
Zwei `Runner`-Instanzen mit eigenem In-Memory-Zustand, die gegen dieselbe
SQLite-Datei schreiben, koennten sich gegenseitig Segmente ueberschreiben
oder parallel offene Segmente fuers selbe Projekt erzeugen.

Ein Datei-Lock reicht dafuer aus und braucht keine externe Abhaengigkeit:
das Lock haengt am offenen File-Handle und wird beim Prozessende automatisch
freigegeben, anders als ein PID-File gibt es also kein verwaistes Lock nach
einem Absturz.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO


class AlreadyRunning(Exception):
    """Ein anderer Resolve-Time-Tracker-Prozess haelt das Lock bereits."""


def acquire_lock(path: Path) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise AlreadyRunning() from exc
    return handle


def release_lock(handle: IO[str]) -> None:
    fcntl.flock(handle, fcntl.LOCK_UN)
    handle.close()
