# Resolve Time Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein macOS-Hintergrunddienst, der Arbeitszeit pro DaVinci-Resolve-Projekt automatisch erfasst, Pausen herausrechnet und fertige Zeiten nach Toggl schiebt.

**Architecture:** Ein Prozess mit 5-Sekunden-Tick. Zwei dünne Adapter lesen die Außenwelt (Resolve-API, macOS-Systemidle), eine reine Zustandsmaschine ohne I/O entscheidet daraus, ob gerade gearbeitet wird, und SQLite hält append-only Segmente als einzige Wahrheit. Ein separater Syncer verschmilzt geschlossene Segmente und legt sie in Toggl an.

**Tech Stack:** Python 3.11, uv, pytest, rumps (Menubar), pyobjc (Quartz/Cocoa), httpx + respx, keyring, SQLite (stdlib), tomllib (stdlib).

**Spec:** `docs/superpowers/specs/2026-08-03-resolve-time-tracker-design.md`

## Global Constraints

- Zielplattform ist ausschließlich macOS. Kein Windows-, kein Linux-Pfad.
- DaVinci Resolve **Studio** ist Voraussetzung, externes Scripting läuft in der freien Version nicht.
- Python 3.11 als Untergrenze (`requires-python = ">=3.11"`), damit `tomllib` aus der Standardbibliothek verfügbar ist.
- Alle Zeitstempel im Code sind `datetime` mit `timezone.utc`. In SQLite werden sie als ISO-8601-String mit Offset abgelegt. Naive Datetimes sind an keiner Stelle erlaubt.
- Die Zustandsmaschine in `tracker.py` darf **niemals** I/O machen, keine Datenbank, kein Netz, kein `datetime.now()`. Die Zeit wird immer hereingereicht.
- Der Toggl-API-Token steht niemals in einer Datei im Repo oder in der Config. Er lebt ausschließlich in der macOS-Keychain unter Service `resolve-time-tracker`, Key `toggl_api_token`.
- Toggl-Requests werden auf höchstens 1 Request pro Sekunde gedrosselt.
- Jeder Toggl-Eintrag trägt `created_with = "resolve-time-tracker"`.
- Zeit darf im Zweifel unterschätzt, nie überschätzt werden. Wenn ein Segment nicht sauber begrenzbar ist, wird auf den letzten bekannten Aktiv-Zeitpunkt zurückgeschnitten.

## Dateistruktur

| Datei | Verantwortung |
|---|---|
| `pyproject.toml` | Paket, Abhängigkeiten, pytest-Konfiguration, `rtt`-Entrypoint |
| `scripts/smoke_resolve.py` | Manuelles Wegwerf-Skript zur Machbarkeitsprüfung |
| `src/resolve_time_tracker/models.py` | Gemeinsame Dataclasses (`ResolveSnapshot`, `Tick`, `Segment`, Kommandos) |
| `src/resolve_time_tracker/tracker.py` | Reine Zustandsmaschine, das Herzstück |
| `src/resolve_time_tracker/store.py` | SQLite, Segmente und Projekt-Mapping |
| `src/resolve_time_tracker/resolve_probe.py` | Adapter zur Resolve-API |
| `src/resolve_time_tracker/activity.py` | Adapter zu macOS (Idle, Frontmost-App) |
| `src/resolve_time_tracker/toggl.py` | Adapter zur Toggl-API v9 |
| `src/resolve_time_tracker/syncer.py` | Verschmelzung und Push, Idempotenz |
| `src/resolve_time_tracker/config.py` | TOML-Config und Keychain-Zugriff |
| `src/resolve_time_tracker/runner.py` | Tick-Loop, verdrahtet Adapter, Tracker und Store |
| `src/resolve_time_tracker/menubar.py` | rumps-UI, dünn |
| `src/resolve_time_tracker/cli.py` | Unterbefehle `menubar`, `daemon`, `token`, `map`, `sync`, `status` |
| `packaging/com.monacoframe.resolve-time-tracker.plist` | LaunchAgent-Vorlage |
| `Makefile` | `make install`, `make uninstall`, `make test` |

Erster Schritt der Umsetzung: diesen Plan nach `docs/superpowers/plans/2026-08-03-resolve-time-tracker.md` schreiben und committen.

---

### Task 1: Projektgerüst und Resolve-Machbarkeitsprüfung

Das ist der blockierende Task. Wenn die Python-Anbindung an Resolve auf dieser Maschine nicht läuft, ist der Rest wertlos, und das muss vor jeder Zeile Produktionscode feststehen.

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`
- Create: `src/resolve_time_tracker/__init__.py`
- Create: `scripts/smoke_resolve.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: nichts
- Produces: importierbares Paket `resolve_time_tracker`, lauffähiges `uv run pytest`

- [ ] **Schritt 1: `pyproject.toml` anlegen**

```toml
[project]
name = "resolve-time-tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "rumps>=0.4.0",
    "pyobjc-framework-Cocoa>=10.0",
    "pyobjc-framework-Quartz>=10.0",
    "httpx>=0.27",
    "keyring>=25.0",
]

[project.scripts]
rtt = "resolve_time_tracker.cli:main"

[dependency-groups]
dev = ["pytest>=8.0", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/resolve_time_tracker"]

[tool.pytest.ini_options]
testpaths = ["tests"]
# "." muss mit rein, weil spaetere Tests Hilfsfunktionen aus tests.test_tracker_basics importieren.
pythonpath = ["src", "."]
```

- [ ] **Schritt 2: `.gitignore` anlegen**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
dist/
*.db
*.db-wal
*.db-shm
```

- [ ] **Schritt 3: Failing test schreiben**

Zuerst `tests/__init__.py` als leere Datei anlegen, damit spätere Tasks Hilfsfunktionen aus `tests.test_tracker_basics` importieren können.

Dann `tests/test_package.py`:

```python
def test_package_importable():
    import resolve_time_tracker

    assert resolve_time_tracker.__name__ == "resolve_time_tracker"
```

- [ ] **Schritt 4: Test laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_package.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker'`

- [ ] **Schritt 5: Leeres Paket anlegen**

`src/resolve_time_tracker/__init__.py` mit einer Zeile:

```python
__all__: list[str] = []
```

- [ ] **Schritt 6: Test laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_package.py -v`
Expected: PASS

- [ ] **Schritt 7: Smoke-Skript schreiben**

`scripts/smoke_resolve.py`:

```python
"""Manuelle Machbarkeitsprüfung. Resolve Studio muss laufen und ein Projekt offen sein.

Aufruf:
    RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
    RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
    PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
    uv run python scripts/smoke_resolve.py
"""

import os
import sys
import time


def main() -> int:
    for var in ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB"):
        if not os.environ.get(var):
            print(f"FEHLT: {var} ist nicht gesetzt")
            return 1

    print(f"Python: {sys.version}")

    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        print(f"FEHLGESCHLAGEN: Import von DaVinciResolveScript: {exc}")
        return 1

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("FEHLGESCHLAGEN: scriptapp('Resolve') gab None zurueck. Laeuft Resolve Studio?")
        return 1

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    print(f"Projekt:     {project.GetName() if project else None}")
    print(f"Datenbank:   {pm.GetCurrentDatabase()}")
    print(f"Page:        {resolve.GetCurrentPage()}")

    timeline = project.GetCurrentTimeline() if project else None
    print(f"Timeline:    {timeline.GetName() if timeline else None}")

    if timeline is None:
        print("HINWEIS: keine Timeline offen, Timecode-Test uebersprungen")
    else:
        first = timeline.GetCurrentTimecode()
        print(f"Timecode 1:  {first}")
        print("Starte jetzt Playback in Resolve, 2 Sekunden Zeit...")
        time.sleep(2)
        second = timeline.GetCurrentTimecode()
        print(f"Timecode 2:  {second}")
        if first == second:
            print("ERGEBNIS: Timecode bewegt sich NICHT. Playback-Signal entfaellt.")
        else:
            print("ERGEBNIS: Timecode bewegt sich. Playback-Signal nutzbar.")

    started = time.perf_counter()
    for _ in range(10):
        resolve.GetCurrentPage()
        pm.GetCurrentProject().GetName()
    per_poll_ms = (time.perf_counter() - started) / 10 * 1000
    print(f"Poll-Kosten: {per_poll_ms:.1f} ms pro Zyklus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Schritt 8: Smoke-Skript gegen laufendes Resolve ausführen**

Resolve Studio öffnen, ein Projekt mit Timeline laden, Skript starten und während der 2-Sekunden-Pause Playback starten.

Expected: Projektname, Page und Timeline erscheinen, und die Zeile `ERGEBNIS:` sagt eindeutig ob sich der Timecode bewegt.

**Wenn der Timecode sich nicht bewegt:** Das Playback-Signal entfällt. Dann in Task 2 die Bedingung `timecode != previous_timecode` weglassen und in der Spec vermerken. Alles andere bleibt unverändert.

**Wenn der Import scheitert:** Python-Version wechseln (Resolve bringt `fusionscript.so` gegen eine bestimmte Version mit) und `requires-python` sowie die uv-Umgebung entsprechend anpassen. Nicht weitermachen, bevor das läuft.

- [ ] **Schritt 9: README-Gerüst anlegen**

Drei Absätze reichen an dieser Stelle: was das Ding tut, dass Resolve Studio Voraussetzung ist, und wie man den Smoke-Test startet. Ausgebaut wird es in Task 15.

- [ ] **Schritt 10: Committen**

```bash
git add pyproject.toml .gitignore README.md src/resolve_time_tracker/__init__.py scripts/smoke_resolve.py tests/__init__.py tests/test_package.py
git commit -m "chore: Projektgeruest und Resolve-Machbarkeitspruefung"
```

---

### Task 2: Datenmodelle und Aktivitätsregel

**Files:**
- Create: `src/resolve_time_tracker/models.py`
- Test: `tests/test_activity_rule.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `ResolveSnapshot(connected: bool, project_name: str | None, database_name: str | None, page: str | None, timeline_name: str | None, timecode: str | None)`, alle Felder außer `connected` mit Default `None`. `timecode` ist rein informativ (Anzeige/Diagnose) und fließt in keine Aktivitätsentscheidung ein.
  - `Tick(now: datetime, snapshot: ResolveSnapshot, idle_seconds: float, frontmost_bundle_id: str | None, manual_pause: bool = False)`
  - `is_resolve_frontmost(bundle_id: str | None) -> bool`
  - `is_active(tick: Tick, input_grace_seconds: float) -> bool`
  - Kommandos `OpenSegment(project: str, database: str | None, started_at: datetime, page: str | None)`, `TouchSegment(last_active_at: datetime, page: str | None)`, `CloseSegment(ended_at: datetime)`

**Hinweis zum Live-Test (Schritt 0):** `GetCurrentTimecode()` aktualisiert sich laut Live-Test gegen echtes Resolve Studio (2026-08-04) während aktiver Wiedergabe nicht zuverlässig per Skript-Poll (bekannte API-Einschränkung). Das ursprünglich vorgesehene Playback-Signal (Timecode-Änderung als Alternative zu Input) entfällt deshalb vollständig. `is_active` prüft ausschließlich Input-Aktualität, solange Resolve vorne ist.

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_activity_rule.py`:

```python
from datetime import datetime, timezone

import pytest

from resolve_time_tracker.models import (
    ResolveSnapshot,
    Tick,
    is_active,
    is_resolve_frontmost,
)

RESOLVE_BUNDLE = "com.blackmagic-design.DaVinciResolve"
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def make_tick(
    *,
    connected=True,
    project="Kunde_Film",
    idle=1.0,
    frontmost=RESOLVE_BUNDLE,
    manual_pause=False,
):
    snapshot = ResolveSnapshot(
        connected=connected,
        project_name=project,
        database_name="Local",
        page="color",
        timeline_name="v1",
        timecode="01:00:00:00",
    )
    return Tick(
        now=NOW,
        snapshot=snapshot,
        idle_seconds=idle,
        frontmost_bundle_id=frontmost,
        manual_pause=manual_pause,
    )


@pytest.mark.parametrize(
    "bundle_id,expected",
    [
        ("com.blackmagic-design.DaVinciResolve", True),
        ("com.blackmagic-design.DaVinciResolveStudio", True),
        ("com.apple.mail", False),
        (None, False),
    ],
)
def test_resolve_frontmost_matches_by_prefix(bundle_id, expected):
    assert is_resolve_frontmost(bundle_id) is expected


def test_active_when_resolve_frontmost_and_recent_input():
    assert is_active(make_tick(idle=5.0), input_grace_seconds=30) is True


def test_inactive_when_another_app_is_frontmost():
    tick = make_tick(frontmost="com.apple.mail", idle=1.0)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_input_is_stale():
    # Kein Playback-Signal mehr als Alternative: abgelaufener Input heisst immer inaktiv.
    tick = make_tick(idle=120.0)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_resolve_not_connected():
    tick = make_tick(connected=False, project=None)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_no_project_open():
    tick = make_tick(project=None)
    assert is_active(tick, input_grace_seconds=30) is False


def test_manual_pause_overrides_everything():
    tick = make_tick(idle=0.0, manual_pause=True)
    assert is_active(tick, input_grace_seconds=30) is False
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_activity_rule.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.models'`

- [ ] **Schritt 3: `models.py` implementieren**

```python
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
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_activity_rule.py -v`
Expected: PASS, 9 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/models.py tests/test_activity_rule.py
git commit -m "feat: Datenmodelle und Aktivitaetsregel"
```

---

### Task 3: Zustandsmaschine, Grundfluss

**Files:**
- Create: `src/resolve_time_tracker/tracker.py`
- Test: `tests/test_tracker_basics.py`

**Interfaces:**
- Consumes: `models.Tick`, `models.ResolveSnapshot`, `models.is_active`, `models.OpenSegment`, `models.TouchSegment`, `models.CloseSegment`
- Produces:
  - `TrackerState` mit den Werten `NO_RESOLVE`, `ACTIVE`, `PENDING_IDLE`, `PAUSED_IDLE`, `PAUSED_MANUAL`
  - `Tracker(input_grace_seconds: float = 30.0, idle_threshold_seconds: float = 300.0)`
  - `Tracker.tick(t: Tick) -> list[Command]`
  - `Tracker.state -> TrackerState`, `Tracker.current_project -> str | None`, `Tracker.last_active_at -> datetime | None`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_tracker_basics.py`:

```python
from datetime import datetime, timedelta, timezone

from resolve_time_tracker.models import CloseSegment, OpenSegment, ResolveSnapshot, Tick, TouchSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

RESOLVE = "com.blackmagic-design.DaVinciResolveStudio"
START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def tick_at(
    seconds: float,
    *,
    project="Kunde_Film",
    idle=1.0,
    frontmost=RESOLVE,
    connected=True,
    timecode="01:00:00:00",
    manual_pause=False,
) -> Tick:
    return Tick(
        now=START + timedelta(seconds=seconds),
        snapshot=ResolveSnapshot(
            connected=connected,
            project_name=project,
            database_name="Local",
            page="color",
            timeline_name="v1",
            timecode=timecode,
        ),
        idle_seconds=idle,
        frontmost_bundle_id=frontmost,
        manual_pause=manual_pause,
    )


def test_starts_in_no_resolve():
    assert Tracker().state is TrackerState.NO_RESOLVE


def test_first_active_tick_opens_a_segment():
    tracker = Tracker()
    commands = tracker.tick(tick_at(0))

    assert commands == [OpenSegment(project="Kunde_Film", database="Local", started_at=START, page="color")]
    assert tracker.state is TrackerState.ACTIVE


def test_following_active_ticks_touch_the_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    commands = tracker.tick(tick_at(5))

    assert commands == [TouchSegment(last_active_at=START + timedelta(seconds=5), page="color")]
    assert tracker.last_active_at == START + timedelta(seconds=5)


def test_resolve_closing_ends_the_segment_immediately():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(5))
    commands = tracker.tick(tick_at(10, connected=False, project=None, timecode=None))

    # Zurueckgeschnitten auf den letzten bekannten Aktiv-Zeitpunkt, nicht auf now.
    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=5))]
    assert tracker.state is TrackerState.NO_RESOLVE


def test_ticks_without_resolve_produce_nothing():
    tracker = Tracker()
    assert tracker.tick(tick_at(0, connected=False, project=None, timecode=None)) == []
    assert tracker.tick(tick_at(5, connected=False, project=None, timecode=None)) == []


def test_going_inactive_does_not_close_immediately():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    commands = tracker.tick(tick_at(5, frontmost="com.apple.mail"))

    assert commands == []
    assert tracker.state is TrackerState.PENDING_IDLE
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_tracker_basics.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.tracker'`

- [ ] **Schritt 3: `tracker.py` implementieren**

```python
"""Die Zustandsmaschine. Kein I/O, keine echte Uhr, alles wird hereingereicht."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto

from .models import (
    CloseSegment,
    Command,
    OpenSegment,
    Tick,
    TouchSegment,
    is_active,
)


class TrackerState(Enum):
    NO_RESOLVE = auto()
    ACTIVE = auto()
    PENDING_IDLE = auto()
    PAUSED_IDLE = auto()
    PAUSED_MANUAL = auto()


_OPEN_STATES = (TrackerState.ACTIVE, TrackerState.PENDING_IDLE)


class Tracker:
    def __init__(
        self,
        input_grace_seconds: float = 30.0,
        idle_threshold_seconds: float = 300.0,
    ) -> None:
        self.input_grace_seconds = input_grace_seconds
        self.idle_threshold_seconds = idle_threshold_seconds
        self._state = TrackerState.NO_RESOLVE
        self._current_project: str | None = None
        self._last_active_at: datetime | None = None

    @property
    def state(self) -> TrackerState:
        return self._state

    @property
    def current_project(self) -> str | None:
        return self._current_project

    @property
    def last_active_at(self) -> datetime | None:
        return self._last_active_at

    def tick(self, t: Tick) -> list[Command]:
        if is_active(t, self.input_grace_seconds):
            return self._handle_active(t)
        return self._handle_inactive(t)

    def _handle_active(self, t: Tick) -> list[Command]:
        project = t.snapshot.project_name
        assert project is not None  # von is_active garantiert

        commands: list[Command] = []
        if self._state in _OPEN_STATES and self._current_project == project:
            commands.append(TouchSegment(last_active_at=t.now, page=t.snapshot.page))
        else:
            commands.extend(self._close_open_segment())
            commands.append(
                OpenSegment(
                    project=project,
                    database=t.snapshot.database_name,
                    started_at=t.now,
                    page=t.snapshot.page,
                )
            )
            self._current_project = project

        self._state = TrackerState.ACTIVE
        self._last_active_at = t.now
        return commands

    def _handle_inactive(self, t: Tick) -> list[Command]:
        resolve_gone = not t.snapshot.connected or t.snapshot.project_name is None
        project_changed = (
            t.snapshot.project_name is not None
            and self._current_project is not None
            and t.snapshot.project_name != self._current_project
        )

        # Sofortige Abschluesse: hier gibt es nichts, worauf zu warten waere.
        if self._state in _OPEN_STATES and (resolve_gone or project_changed or t.manual_pause):
            commands = self._close_open_segment()
            if resolve_gone:
                self._state = TrackerState.NO_RESOLVE
                self._current_project = None
            elif t.manual_pause:
                self._state = TrackerState.PAUSED_MANUAL
            else:
                self._state = TrackerState.PAUSED_IDLE
            return commands

        if self._state is TrackerState.ACTIVE:
            self._state = TrackerState.PENDING_IDLE
            return []

        if self._state is TrackerState.PENDING_IDLE:
            assert self._last_active_at is not None
            still_for = (t.now - self._last_active_at).total_seconds()
            if still_for >= self.idle_threshold_seconds:
                commands = self._close_open_segment()
                self._state = TrackerState.PAUSED_IDLE
                return commands
            return []

        if resolve_gone:
            self._state = TrackerState.NO_RESOLVE
            self._current_project = None
        return []

    def _close_open_segment(self) -> list[Command]:
        if self._state not in _OPEN_STATES or self._last_active_at is None:
            return []
        return [CloseSegment(ended_at=self._last_active_at)]
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_tracker_basics.py -v`
Expected: PASS, 6 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/tracker.py tests/test_tracker_basics.py
git commit -m "feat: Zustandsmaschine Grundfluss"
```

---

### Task 4: Idle-Rückschnitt und Wiederaufnahme

Hier steckt der eigentliche Wert des Projekts: kurze Denkpausen zählen mit, echte Abwesenheit fällt raus, und zwar rückwirkend genau auf den letzten Aktiv-Zeitpunkt.

**Files:**
- Modify: `src/resolve_time_tracker/tracker.py` (nur falls Tests etwas aufdecken)
- Test: `tests/test_tracker_idle.py`

**Interfaces:**
- Consumes: `Tracker`, `TrackerState` aus Task 3
- Produces: keine neuen Namen, nur abgesichertes Verhalten

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_tracker_idle.py`:

```python
from datetime import timedelta

from resolve_time_tracker.models import CloseSegment, OpenSegment, TouchSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

from tests.test_tracker_basics import START, tick_at


def test_short_pause_below_threshold_counts_as_work():
    """Zwei Minuten nachdenken sind Arbeit, das Segment darf nicht zerrissen werden."""
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, idle=120))  # PENDING_IDLE
    tracker.tick(tick_at(120, idle=180))  # immer noch unter der Schwelle
    commands = tracker.tick(tick_at(180, idle=1))  # zurueck an der Maus

    assert commands == [TouchSegment(last_active_at=START + timedelta(seconds=180), page="color")]
    assert tracker.state is TrackerState.ACTIVE


def test_long_pause_closes_and_cuts_back_to_last_activity():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60))  # letzter aktiver Tick
    tracker.tick(tick_at(120, idle=90))  # PENDING_IDLE
    commands = tracker.tick(tick_at(400, idle=400))  # 340 s still, Schwelle gerissen

    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=60))]
    assert tracker.state is TrackerState.PAUSED_IDLE


def test_closing_happens_exactly_once():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(400, idle=400))
    tracker.tick(tick_at(405, idle=405))

    assert tracker.tick(tick_at(410, idle=410)) == []


def test_work_resumes_with_a_new_segment_after_a_long_pause():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(400, idle=400))  # schliesst
    commands = tracker.tick(tick_at(500, idle=1))

    assert commands == [
        OpenSegment(
            project="Kunde_Film",
            database="Local",
            started_at=START + timedelta(seconds=500),
            page="color",
        )
    ]


def test_idle_without_input_closes_even_while_playhead_could_move():
    # Kein Playback-Signal mehr (siehe Task 2): abgelaufener Input schliesst immer,
    # unabhaengig davon ob in Resolve etwas laeuft.
    tracker = Tracker(input_grace_seconds=30, idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, idle=60))
    commands = tracker.tick(tick_at(400, idle=400))

    assert commands == [CloseSegment(ended_at=START)]
```

- [ ] **Schritt 2: Tests laufen lassen**

Run: `uv run pytest tests/test_tracker_idle.py -v`
Expected: PASS, weil Task 3 die Logik bereits enthält. Falls einer fehlschlägt, ist die Implementierung aus Task 3 falsch und wird repariert, nicht der Test angepasst.

- [ ] **Schritt 3: Committen**

```bash
git add tests/test_tracker_idle.py
git commit -m "test: Idle-Rueckschnitt und Wiederaufnahme"
```

---

### Task 5: Projektwechsel und manuelle Pause

**Files:**
- Modify: `src/resolve_time_tracker/tracker.py` (nur falls Tests etwas aufdecken)
- Test: `tests/test_tracker_switching.py`

**Interfaces:**
- Consumes: `Tracker`, `TrackerState` aus Task 3
- Produces: keine neuen Namen

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_tracker_switching.py`:

```python
from datetime import timedelta

from resolve_time_tracker.models import CloseSegment, OpenSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

from tests.test_tracker_basics import START, tick_at


def test_switching_project_closes_the_old_and_opens_a_new_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_A"))
    commands = tracker.tick(tick_at(120, project="Kunde_B"))

    assert commands == [
        CloseSegment(ended_at=START + timedelta(seconds=60)),
        OpenSegment(
            project="Kunde_B",
            database="Local",
            started_at=START + timedelta(seconds=120),
            page="color",
        ),
    ]
    assert tracker.current_project == "Kunde_B"


def test_manual_pause_closes_immediately_without_waiting_for_the_threshold():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60))
    commands = tracker.tick(tick_at(65, manual_pause=True))

    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=60))]
    assert tracker.state is TrackerState.PAUSED_MANUAL


def test_manual_pause_blocks_new_segments_while_active():
    tracker = Tracker()
    tracker.tick(tick_at(0, manual_pause=True))
    tracker.tick(tick_at(60, idle=0, manual_pause=True))

    assert tracker.state is not TrackerState.ACTIVE


def test_resuming_after_manual_pause_opens_a_new_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, manual_pause=True))
    commands = tracker.tick(tick_at(120))

    assert commands == [
        OpenSegment(
            project="Kunde_Film",
            database="Local",
            started_at=START + timedelta(seconds=120),
            page="color",
        )
    ]


def test_resolve_quitting_during_a_pending_idle_closes_the_segment():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, frontmost="com.apple.mail"))  # PENDING_IDLE
    commands = tracker.tick(tick_at(120, connected=False, project=None, timecode=None))

    assert commands == [CloseSegment(ended_at=START)]
    assert tracker.state is TrackerState.NO_RESOLVE
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschläge reparieren**

Run: `uv run pytest tests/test_tracker_switching.py -v`
Expected: PASS. Falls `test_manual_pause_closes_immediately_without_waiting_for_the_threshold` fehlschlägt, prüfen ob `_handle_inactive` den `manual_pause`-Zweig vor dem `PENDING_IDLE`-Zweig auswertet.

- [ ] **Schritt 3: Gesamte Test-Suite laufen lassen**

Run: `uv run pytest -v`
Expected: alle Tests grün

- [ ] **Schritt 4: Committen**

```bash
git add tests/test_tracker_switching.py src/resolve_time_tracker/tracker.py
git commit -m "test: Projektwechsel und manuelle Pause"
```

---

### Task 6: SQLite-Store, Schema und Segment-Lebenszyklus

**Files:**
- Create: `src/resolve_time_tracker/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nichts aus früheren Tasks
- Produces:
  - `Segment(id: int, resolve_project: str, resolve_database: str | None, started_at: datetime, last_active_at: datetime, ended_at: datetime | None, pages_seen: list[str], note: str | None, toggl_entry_id: int | None, synced_at: datetime | None)`
  - `Store(path: Path)` mit `open_segment(project, database, started_at, page) -> int`, `touch_segment(segment_id, last_active_at, page) -> None`, `close_segment(segment_id, ended_at) -> None`, `current_open_segment() -> Segment | None`, `close_stale_segments() -> int`, `segments_since(since: datetime) -> list[Segment]`, `close()`
  - `Store.SCHEMA_VERSION = 1`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_store.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Store

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def test_open_segment_returns_an_id_and_is_retrievable(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    current = store.current_open_segment()

    assert current is not None
    assert current.id == segment_id
    assert current.resolve_project == "Kunde_A"
    assert current.started_at == START
    assert current.last_active_at == START
    assert current.ended_at is None
    assert current.pages_seen == ["color"]


def test_touch_updates_last_active_and_collects_pages(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=5), "edit")
    store.touch_segment(segment_id, START + timedelta(seconds=10), "color")

    current = store.current_open_segment()
    assert current.last_active_at == START + timedelta(seconds=10)
    assert sorted(current.pages_seen) == ["color", "edit"]


def test_close_segment_sets_end_and_clears_the_open_slot(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=60), "color")
    store.close_segment(segment_id, START + timedelta(seconds=60))

    assert store.current_open_segment() is None
    closed = store.segments_since(START)[0]
    assert closed.ended_at == START + timedelta(seconds=60)


def test_timestamps_survive_a_roundtrip_with_timezone(store):
    store.open_segment("Kunde_A", "Local", START, "color")
    current = store.current_open_segment()

    assert current.started_at.tzinfo is not None
    assert current.started_at == START


def test_reopening_the_database_keeps_the_data(tmp_path):
    path = tmp_path / "tracker.db"
    first = Store(path)
    segment_id = first.open_segment("Kunde_A", "Local", START, "color")
    first.close()

    second = Store(path)
    assert second.current_open_segment().id == segment_id
    second.close()


def test_close_stale_segments_cuts_back_to_last_activity(store):
    """Nach einem harten Absturz darf ein offenes Segment nicht weiterlaufen."""
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=120), "color")

    closed_count = store.close_stale_segments()

    assert closed_count == 1
    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=120)


def test_close_stale_segments_is_a_noop_when_nothing_is_open(store):
    assert store.close_stale_segments() == 0
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.store'`

- [ ] **Schritt 3: `store.py` implementieren**

```python
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
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS, 7 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/store.py tests/test_store.py
git commit -m "feat: SQLite-Store fuer Segmente"
```

---

### Task 7: Projekt-Mapping und Auswertungsabfragen

**Files:**
- Modify: `src/resolve_time_tracker/store.py`
- Test: `tests/test_store_mapping.py`

**Interfaces:**
- Consumes: `Store`, `Segment` aus Task 6
- Produces:
  - `ProjectMapping(resolve_project: str, toggl_workspace_id: int, toggl_project_id: int | None)`
  - `Store.get_mapping(resolve_project) -> ProjectMapping | None`
  - `Store.set_mapping(resolve_project, workspace_id, project_id) -> None`
  - `Store.unmapped_projects() -> list[str]`
  - `Store.unsynced_segments(closed_before: datetime) -> list[Segment]`
  - `Store.mark_synced(segment_ids: list[int], toggl_entry_id: int, synced_at: datetime) -> None`
  - `Store.totals_since(since: datetime) -> dict[str, float]`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_store_mapping.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Store

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def add_closed_segment(store, project, offset_seconds, duration_seconds):
    started = START + timedelta(seconds=offset_seconds)
    segment_id = store.open_segment(project, "Local", started, "color")
    ended = started + timedelta(seconds=duration_seconds)
    store.touch_segment(segment_id, ended, "color")
    store.close_segment(segment_id, ended)
    return segment_id


def test_mapping_roundtrip(store):
    store.set_mapping("Kunde_A", 111, 222)
    mapping = store.get_mapping("Kunde_A")

    assert mapping.toggl_workspace_id == 111
    assert mapping.toggl_project_id == 222


def test_mapping_is_none_for_unknown_project(store):
    assert store.get_mapping("Kunde_Unbekannt") is None


def test_setting_a_mapping_twice_overwrites(store):
    store.set_mapping("Kunde_A", 111, 222)
    store.set_mapping("Kunde_A", 111, 333)

    assert store.get_mapping("Kunde_A").toggl_project_id == 333


def test_unmapped_projects_lists_only_projects_with_unsynced_work(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    add_closed_segment(store, "Kunde_B", 700, 600)
    store.set_mapping("Kunde_A", 111, 222)

    assert store.unmapped_projects() == ["Kunde_B"]


def test_unsynced_segments_only_returns_closed_ones(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    store.open_segment("Kunde_A", "Local", START + timedelta(seconds=1000), "color")

    unsynced = store.unsynced_segments(closed_before=START + timedelta(days=1))
    assert len(unsynced) == 1


def test_unsynced_segments_respects_the_cutoff(store):
    add_closed_segment(store, "Kunde_A", 0, 600)

    assert store.unsynced_segments(closed_before=START) == []


def test_mark_synced_removes_segments_from_the_queue(store):
    first = add_closed_segment(store, "Kunde_A", 0, 600)
    second = add_closed_segment(store, "Kunde_A", 700, 600)

    store.mark_synced([first, second], toggl_entry_id=999, synced_at=START)

    assert store.unsynced_segments(closed_before=START + timedelta(days=1)) == []
    assert store.segments_since(START)[0].toggl_entry_id == 999


def test_totals_since_sums_per_project(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    add_closed_segment(store, "Kunde_A", 700, 300)
    add_closed_segment(store, "Kunde_B", 2000, 1200)

    totals = store.totals_since(START)
    assert totals == {"Kunde_A": 900.0, "Kunde_B": 1200.0}
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_store_mapping.py -v`
Expected: FAIL mit `AttributeError: 'Store' object has no attribute 'set_mapping'`

- [ ] **Schritt 3: `store.py` erweitern**

`ProjectMapping` neben `Segment` ergänzen:

```python
@dataclass(frozen=True)
class ProjectMapping:
    resolve_project: str
    toggl_workspace_id: int
    toggl_project_id: int | None
```

Und diese Methoden an `Store` anhängen:

```python
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

    def totals_since(self, since: datetime) -> dict[str, float]:
        totals: dict[str, float] = {}
        for segment in self.segments_since(since):
            totals[segment.resolve_project] = (
                totals.get(segment.resolve_project, 0.0) + segment.duration_seconds
            )
        return totals
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_store_mapping.py -v`
Expected: PASS, 8 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/store.py tests/test_store_mapping.py
git commit -m "feat: Projekt-Mapping und Auswertungsabfragen"
```

---

### Task 8: Config und Keychain

**Files:**
- Create: `src/resolve_time_tracker/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `Config(tick_seconds: float, input_grace_seconds: float, idle_threshold_seconds: float, merge_gap_seconds: float, auto_push: bool, default_workspace_id: int | None)` mit Defaults 5.0, 30.0, 300.0, 600.0, True, None
  - `load_config(path: Path | None = None) -> Config`, legt bei Nichtexistenz eine Datei mit Defaults an
  - `config_path() -> Path` (`~/.config/resolve-time-tracker/config.toml`)
  - `database_path() -> Path` (`~/Library/Application Support/resolve-time-tracker/tracker.db`)
  - `log_path() -> Path` (`~/Library/Logs/resolve-time-tracker.log`)
  - `get_token() -> str | None`, `set_token(token: str) -> None`
  - `KEYCHAIN_SERVICE = "resolve-time-tracker"`, `KEYCHAIN_KEY = "toggl_api_token"`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_config.py`:

```python
from resolve_time_tracker.config import DEFAULT_CONFIG_TOML, Config, load_config


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)

    assert path.exists()
    assert config == Config()


def test_values_from_file_override_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[tracking]\n"
        "tick_seconds = 10\n"
        "idle_threshold_seconds = 120\n"
        "[sync]\n"
        "auto_push = false\n"
        "[toggl]\n"
        "default_workspace_id = 4711\n"
    )
    config = load_config(path)

    assert config.tick_seconds == 10
    assert config.idle_threshold_seconds == 120
    assert config.auto_push is False
    assert config.default_workspace_id == 4711
    # Nicht genannte Werte bleiben auf dem Default.
    assert config.input_grace_seconds == 30.0


def test_partial_sections_do_not_crash(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[tracking]\ntick_seconds = 3\n")

    assert load_config(path).merge_gap_seconds == 600.0


def test_default_toml_template_parses_into_the_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML)

    assert load_config(path) == Config()
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.config'`

- [ ] **Schritt 3: `config.py` implementieren**

```python
"""Konfiguration und Token-Ablage.

Der Toggl-Token gehoert in die Keychain, nie in eine Datei.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import keyring

KEYCHAIN_SERVICE = "resolve-time-tracker"
KEYCHAIN_KEY = "toggl_api_token"

DEFAULT_CONFIG_TOML = """# Resolve Time Tracker

[tracking]
# Abstand zwischen zwei Polls in Sekunden.
tick_seconds = 5
# So lange nach der letzten Eingabe gilt Arbeit noch als aktiv.
input_grace_seconds = 30
# So lange muss es still sein, bevor ein Segment geschlossen wird.
idle_threshold_seconds = 300

[sync]
# Segmente mit kleinerer Luecke werden zu einem Toggl-Eintrag verschmolzen.
merge_gap_seconds = 600
auto_push = true

[toggl]
# 0 bedeutet: noch nicht gesetzt.
default_workspace_id = 0
"""


@dataclass(frozen=True)
class Config:
    tick_seconds: float = 5.0
    input_grace_seconds: float = 30.0
    idle_threshold_seconds: float = 300.0
    merge_gap_seconds: float = 600.0
    auto_push: bool = True
    default_workspace_id: int | None = None


def config_path() -> Path:
    return Path.home() / ".config" / "resolve-time-tracker" / "config.toml"


def database_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "resolve-time-tracker" / "tracker.db"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "resolve-time-tracker.log"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TOML)

    data = tomllib.loads(path.read_text())
    tracking = data.get("tracking", {})
    sync = data.get("sync", {})
    toggl = data.get("toggl", {})
    workspace_id = toggl.get("default_workspace_id", 0)

    defaults = Config()
    return Config(
        tick_seconds=float(tracking.get("tick_seconds", defaults.tick_seconds)),
        input_grace_seconds=float(
            tracking.get("input_grace_seconds", defaults.input_grace_seconds)
        ),
        idle_threshold_seconds=float(
            tracking.get("idle_threshold_seconds", defaults.idle_threshold_seconds)
        ),
        merge_gap_seconds=float(sync.get("merge_gap_seconds", defaults.merge_gap_seconds)),
        auto_push=bool(sync.get("auto_push", defaults.auto_push)),
        default_workspace_id=workspace_id or None,
    )


def get_token() -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_KEY)


def set_token(token: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_KEY, token)
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 4 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/config.py tests/test_config.py
git commit -m "feat: Konfiguration und Keychain-Anbindung"
```

---

### Task 9: Toggl-API-Client

**Files:**
- Create: `src/resolve_time_tracker/toggl.py`
- Test: `tests/test_toggl.py`

**Interfaces:**
- Consumes: nichts aus früheren Tasks
- Produces:
  - `TogglError(Exception)`, `TogglRateLimited(TogglError)`
  - `TogglClient(token: str, http: httpx.Client | None = None, min_interval_seconds: float = 1.0, sleep=time.sleep)`
  - `TogglClient.workspaces() -> list[dict]`
  - `TogglClient.projects(workspace_id: int) -> list[dict]`
  - `TogglClient.create_time_entry(workspace_id: int, project_id: int | None, description: str, start: datetime, duration_seconds: int, tags: list[str]) -> int`
  - `BASE_URL = "https://api.track.toggl.com/api/v9"`, `CREATED_WITH = "resolve-time-tracker"`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_toggl.py`:

```python
import base64
import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from resolve_time_tracker.toggl import BASE_URL, TogglClient, TogglRateLimited

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return TogglClient(token="secret-token", min_interval_seconds=0.0, sleep=lambda _: None)


@respx.mock
def test_create_time_entry_posts_the_expected_body(client):
    route = respx.post(f"{BASE_URL}/workspaces/111/time_entries").mock(
        return_value=httpx.Response(200, json={"id": 4242})
    )

    entry_id = client.create_time_entry(
        workspace_id=111,
        project_id=222,
        description="Kunde_A",
        start=START,
        duration_seconds=3600,
        tags=["color", "edit"],
    )

    assert entry_id == 4242
    body = json.loads(route.calls[0].request.content)
    assert body["created_with"] == "resolve-time-tracker"
    assert body["workspace_id"] == 111
    assert body["project_id"] == 222
    assert body["description"] == "Kunde_A"
    assert body["duration"] == 3600
    assert body["start"] == "2026-08-03T10:00:00Z"
    assert body["stop"] == "2026-08-03T11:00:00Z"
    assert body["tags"] == ["color", "edit"]


@respx.mock
def test_auth_uses_the_token_as_username_and_the_literal_api_token_as_password(client):
    route = respx.post(f"{BASE_URL}/workspaces/111/time_entries").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )

    client.create_time_entry(111, None, "Kunde_A", START, 60, [])

    header = route.calls[0].request.headers["authorization"]
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    assert decoded == "secret-token:api_token"


@respx.mock
def test_project_id_none_is_sent_as_null(client):
    route = respx.post(f"{BASE_URL}/workspaces/111/time_entries").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )

    client.create_time_entry(111, None, "Kunde_A", START, 60, [])

    assert json.loads(route.calls[0].request.content)["project_id"] is None


@respx.mock
def test_rate_limit_is_retried_then_raises(client):
    respx.post(f"{BASE_URL}/workspaces/111/time_entries").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )

    with pytest.raises(TogglRateLimited):
        client.create_time_entry(111, 222, "Kunde_A", START, 60, [])


@respx.mock
def test_rate_limit_recovers_when_the_retry_succeeds(client):
    route = respx.post(f"{BASE_URL}/workspaces/111/time_entries")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"id": 77}),
    ]

    assert client.create_time_entry(111, 222, "Kunde_A", START, 60, []) == 77


@respx.mock
def test_workspaces_and_projects_are_returned_as_lists(client):
    respx.get(f"{BASE_URL}/me/workspaces").mock(
        return_value=httpx.Response(200, json=[{"id": 111, "name": "monacoframe"}])
    )
    respx.get(f"{BASE_URL}/workspaces/111/projects").mock(
        return_value=httpx.Response(200, json=[{"id": 222, "name": "Kunde A"}])
    )

    assert client.workspaces()[0]["name"] == "monacoframe"
    assert client.projects(111)[0]["id"] == 222
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_toggl.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.toggl'`

- [ ] **Schritt 3: `toggl.py` implementieren**

```python
"""Adapter zur Toggl Track API v9."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

BASE_URL = "https://api.track.toggl.com/api/v9"
CREATED_WITH = "resolve-time-tracker"
MAX_ATTEMPTS = 3


class TogglError(Exception):
    pass


class TogglRateLimited(TogglError):
    pass


def _iso_z(value: datetime) -> str:
    """Toggl erwartet UTC mit Z-Suffix, nicht mit +00:00."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TogglClient:
    def __init__(
        self,
        token: str,
        http: httpx.Client | None = None,
        min_interval_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client(timeout=30.0)
        self._auth = httpx.BasicAuth(token, "api_token")
        self._min_interval = min_interval_seconds
        self._sleep = sleep
        self._last_request_at = 0.0

    def workspaces(self) -> list[dict[str, Any]]:
        return self._request("GET", "/me/workspaces")

    def projects(self, workspace_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/workspaces/{workspace_id}/projects")

    def create_time_entry(
        self,
        workspace_id: int,
        project_id: int | None,
        description: str,
        start: datetime,
        duration_seconds: int,
        tags: list[str],
    ) -> int:
        payload = {
            "created_with": CREATED_WITH,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "description": description,
            "start": _iso_z(start),
            "stop": _iso_z(start + timedelta(seconds=duration_seconds)),
            "duration": int(duration_seconds),
            "tags": tags,
        }
        response = self._request("POST", f"/workspaces/{workspace_id}/time_entries", json=payload)
        return int(response["id"])

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _request(self, method: str, path: str, json: Any = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            response = self._http.request(method, f"{BASE_URL}{path}", auth=self._auth, json=json)

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2**attempt))
                last_error = TogglRateLimited(f"429 auf {method} {path}")
                self._sleep(retry_after)
                continue

            if response.status_code >= 400:
                raise TogglError(f"{response.status_code} auf {method} {path}: {response.text}")

            return response.json()

        raise last_error or TogglError(f"{method} {path} nach {MAX_ATTEMPTS} Versuchen gescheitert")
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_toggl.py -v`
Expected: PASS, 6 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/toggl.py tests/test_toggl.py
git commit -m "feat: Toggl-API-Client mit Drosselung und 429-Behandlung"
```

---

### Task 10: Syncer, Verschmelzung und idempotenter Push

Wichtige inhaltliche Festlegung: die Dauer eines verschmolzenen Eintrags ist die **Summe der aktiven Segmentdauern**, nicht die Spanne vom ersten Start bis zum letzten Ende. Die Lücken zwischen den Segmenten sind echte Pausen und dürfen nicht mitzählen. Dadurch endet der Toggl-Eintrag rechnerisch etwas früher als die reale Arbeit, aber die abgerechnete Dauer stimmt. Genau so ist es gewollt.

**Files:**
- Create: `src/resolve_time_tracker/syncer.py`
- Test: `tests/test_syncer.py`

**Interfaces:**
- Consumes: `Store`, `Segment`, `ProjectMapping` aus Task 6/7, `TogglClient`, `TogglError` aus Task 9
- Produces:
  - `SegmentGroup(project: str, segment_ids: list[int], started_at: datetime, duration_seconds: int, tags: list[str])`
  - `merge_segments(segments: list[Segment], merge_gap_seconds: float) -> list[SegmentGroup]`
  - `SyncResult(pushed: int, skipped_unmapped: list[str], failed: int)`
  - `sync(store: Store, client: TogglClient, now: datetime, merge_gap_seconds: float) -> SyncResult`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_syncer.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Segment, Store
from resolve_time_tracker.syncer import merge_segments, sync
from resolve_time_tracker.toggl import TogglError

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def segment(seg_id, project, offset_seconds, duration_seconds, pages=("color",)):
    started = START + timedelta(seconds=offset_seconds)
    ended = started + timedelta(seconds=duration_seconds)
    return Segment(
        id=seg_id,
        resolve_project=project,
        resolve_database="Local",
        started_at=started,
        last_active_at=ended,
        ended_at=ended,
        pages_seen=list(pages),
        note=None,
        toggl_entry_id=None,
        synced_at=None,
    )


class FakeToggl:
    def __init__(self, fail_times=0):
        self.calls = []
        self._fail_times = fail_times
        self._next_id = 1000

    def create_time_entry(self, workspace_id, project_id, description, start, duration_seconds, tags):
        if self._fail_times > 0:
            self._fail_times -= 1
            raise TogglError("simulierter Fehler")
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "description": description,
                "start": start,
                "duration_seconds": duration_seconds,
                "tags": tags,
            }
        )
        self._next_id += 1
        return self._next_id


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def add(store, project, offset_seconds, duration_seconds, page="color"):
    started = START + timedelta(seconds=offset_seconds)
    seg_id = store.open_segment(project, "Local", started, page)
    ended = started + timedelta(seconds=duration_seconds)
    store.touch_segment(seg_id, ended, page)
    store.close_segment(seg_id, ended)
    return seg_id


def test_close_segments_within_the_gap_are_merged():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_A", 900, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert len(groups) == 1
    assert groups[0].segment_ids == [1, 2]
    assert groups[0].started_at == START
    # 300 s Luecke zaehlen nicht mit.
    assert groups[0].duration_seconds == 1200


def test_segments_beyond_the_gap_stay_separate():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_A", 5000, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert [g.segment_ids for g in groups] == [[1], [2]]


def test_different_projects_are_never_merged():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_B", 620, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert len(groups) == 2
    assert {g.project for g in groups} == {"Kunde_A", "Kunde_B"}


def test_merged_group_collects_the_union_of_pages():
    segments = [
        segment(1, "Kunde_A", 0, 600, pages=("color",)),
        segment(2, "Kunde_A", 700, 600, pages=("edit", "color")),
    ]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert sorted(groups[0].tags) == ["color", "edit"]


def test_sync_pushes_mapped_projects_and_marks_them(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.pushed == 1
    assert client.calls[0]["workspace_id"] == 111
    assert client.calls[0]["project_id"] == 222
    assert client.calls[0]["duration_seconds"] == 600
    assert store.unsynced_segments(closed_before=START + timedelta(days=1)) == []


def test_sync_skips_unmapped_projects_without_losing_them(store):
    add(store, "Kunde_Unbekannt", 0, 600)
    client = FakeToggl()

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.pushed == 0
    assert result.skipped_unmapped == ["Kunde_Unbekannt"]
    assert len(store.unsynced_segments(closed_before=START + timedelta(days=1))) == 1


def test_running_sync_twice_creates_no_duplicates(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)
    sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert len(client.calls) == 1


def test_a_failed_push_leaves_the_segment_in_the_queue(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl(fail_times=1)

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.failed == 1
    assert len(store.unsynced_segments(closed_before=START + timedelta(days=1))) == 1


def test_recent_segments_are_held_back_until_the_gap_has_passed(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    # Nur 60 s nach Segmentende: koennte noch weitergearbeitet werden, also nicht pushen.
    result = sync(store, client, now=START + timedelta(seconds=660), merge_gap_seconds=600)

    assert result.pushed == 0
    assert client.calls == []
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_syncer.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.syncer'`

- [ ] **Schritt 3: `syncer.py` implementieren**

```python
"""Verschmilzt geschlossene Segmente und legt sie in Toggl an."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .store import Segment, Store
from .toggl import TogglError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentGroup:
    project: str
    segment_ids: list[int]
    started_at: datetime
    duration_seconds: int
    tags: list[str]


@dataclass
class SyncResult:
    pushed: int = 0
    skipped_unmapped: list[str] = field(default_factory=list)
    failed: int = 0


def merge_segments(segments: list[Segment], merge_gap_seconds: float) -> list[SegmentGroup]:
    """Segmente desselben Projekts mit kleiner Luecke werden zu einem Eintrag."""
    gap = timedelta(seconds=merge_gap_seconds)
    buckets: dict[str, list[Segment]] = {}
    for seg in sorted(segments, key=lambda s: s.started_at):
        buckets.setdefault(seg.resolve_project, []).append(seg)

    groups: list[SegmentGroup] = []
    for project, project_segments in buckets.items():
        run: list[Segment] = []
        for seg in project_segments:
            if run and seg.started_at - (run[-1].ended_at or run[-1].last_active_at) > gap:
                groups.append(_to_group(project, run))
                run = []
            run.append(seg)
        if run:
            groups.append(_to_group(project, run))

    return sorted(groups, key=lambda g: g.started_at)


def _to_group(project: str, run: list[Segment]) -> SegmentGroup:
    tags: list[str] = []
    for seg in run:
        for page in seg.pages_seen:
            if page not in tags:
                tags.append(page)
    return SegmentGroup(
        project=project,
        segment_ids=[seg.id for seg in run],
        started_at=run[0].started_at,
        # Nur echte Arbeitszeit, die Luecken zwischen den Segmenten sind Pausen.
        duration_seconds=int(sum(seg.duration_seconds for seg in run)),
        tags=tags,
    )


def sync(store: Store, client, now: datetime, merge_gap_seconds: float) -> SyncResult:
    result = SyncResult()
    cutoff = now - timedelta(seconds=merge_gap_seconds)
    pending = store.unsynced_segments(closed_before=cutoff)

    for group in merge_segments(pending, merge_gap_seconds):
        mapping = store.get_mapping(group.project)
        if mapping is None:
            if group.project not in result.skipped_unmapped:
                result.skipped_unmapped.append(group.project)
            continue

        try:
            entry_id = client.create_time_entry(
                workspace_id=mapping.toggl_workspace_id,
                project_id=mapping.toggl_project_id,
                description=group.project,
                start=group.started_at,
                duration_seconds=group.duration_seconds,
                tags=group.tags,
            )
        except TogglError:
            log.exception("Push fuer %s gescheitert, Segmente bleiben in der Warteschlange", group.project)
            result.failed += 1
            continue

        store.mark_synced(group.segment_ids, toggl_entry_id=entry_id, synced_at=now)
        result.pushed += 1

    return result
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_syncer.py -v`
Expected: PASS, 9 Tests

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/syncer.py tests/test_syncer.py
git commit -m "feat: Syncer mit Verschmelzung und Idempotenz"
```

---

### Task 11: Adapter zu Resolve und macOS

Diese beiden Module bekommen keine Unit-Tests. Sie sind dünne Übersetzer zu Systemschnittstellen, die sich nicht sinnvoll mocken lassen, ohne den Test zu einer Tautologie zu machen. Verifiziert werden sie über ein manuelles Prüfskript.

**Files:**
- Create: `src/resolve_time_tracker/resolve_probe.py`
- Create: `src/resolve_time_tracker/activity.py`
- Create: `scripts/smoke_adapters.py`

**Interfaces:**
- Consumes: `models.ResolveSnapshot`
- Produces:
  - `ResolveProbe()` mit `poll() -> ResolveSnapshot`
  - `seconds_since_input() -> float`
  - `frontmost_bundle_id() -> str | None`

**Hinweis zum Live-Test:** Der ursprünglich geplante `include_timecode`-Parameter (Timecode nur pollen, wenn Resolve vorne ist, um Kosten für die Aktivitätsprüfung zu sparen) entfällt, weil das Playback-Signal in Task 2 komplett gestrichen wurde. `poll()` liest Timecode/Timeline jetzt immer mit, wenn eine Timeline offen ist — laut Live-Test kostet ein voller Poll-Zyklus ohnehin nur ca. 3,3 ms.

- [ ] **Schritt 1: `activity.py` implementieren**

```python
"""macOS-Signale: wie lange ist die letzte Eingabe her, welche App ist vorne.

Beides geht ohne Accessibility-Berechtigung, es werden keine Eingaben mitgelesen,
nur der Zeitpunkt der letzten Eingabe abgefragt.
"""

from __future__ import annotations

from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)


def seconds_since_input() -> float:
    return float(
        CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType
        )
    )


def frontmost_bundle_id() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    return app.bundleIdentifier()
```

- [ ] **Schritt 2: `resolve_probe.py` implementieren**

```python
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
```

- [ ] **Schritt 3: Prüfskript für beide Adapter schreiben**

`scripts/smoke_adapters.py`:

```python
"""Manuelle Pruefung der Adapter. Zeigt zehn Sekunden lang, was der Tracker sehen wuerde."""

import time

from resolve_time_tracker.activity import frontmost_bundle_id, seconds_since_input
from resolve_time_tracker.resolve_probe import ResolveProbe


def main() -> None:
    probe = ResolveProbe()
    for _ in range(10):
        bundle = frontmost_bundle_id()
        snapshot = probe.poll()
        print(
            f"idle={seconds_since_input():6.1f}s  vorne={bundle}  "
            f"resolve={snapshot.connected}  projekt={snapshot.project_name}  "
            f"page={snapshot.page}  tc={snapshot.timecode}"
        )
        time.sleep(1)


if __name__ == "__main__":
    main()
```

- [ ] **Schritt 4: Prüfskript ausführen**

Run: `uv run python scripts/smoke_adapters.py`

Expected: Zehn Zeilen. Während der Ausführung einmal in eine andere App wechseln und einmal die Hände von der Tastatur nehmen. Dabei muss `idle` steigen und `vorne` sich ändern. `tc` ist nur informativ (siehe Live-Test-Hinweis: Timecode bewegt sich während Playback nicht zuverlässig), keine Erwartung daran geknüpft.

- [ ] **Schritt 5: Committen**

```bash
git add src/resolve_time_tracker/activity.py src/resolve_time_tracker/resolve_probe.py scripts/smoke_adapters.py
git commit -m "feat: Adapter zu Resolve und macOS"
```

---

### Task 12: Runner, der alles verdrahtet

**Files:**
- Create: `src/resolve_time_tracker/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Tracker`, `Store`, `ResolveProbe`, `activity`, `Config`, `syncer.sync`, `models.*`
- Produces:
  - `Runner(store: Store, tracker: Tracker, probe, clock, idle_source, frontmost_source, config: Config)`
  - `Runner.tick_once() -> None`
  - `Runner.manual_pause: bool` (setzbar)
  - `Runner.status() -> RunnerStatus`
  - `RunnerStatus(project: str | None, is_running: bool, current_seconds: float, today_seconds: float, unmapped: list[str])`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_runner.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.config import Config
from resolve_time_tracker.models import ResolveSnapshot
from resolve_time_tracker.runner import Runner
from resolve_time_tracker.store import Store
from resolve_time_tracker.tracker import Tracker

RESOLVE = "com.blackmagic-design.DaVinciResolveStudio"
START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


class FakeProbe:
    def __init__(self):
        self.snapshot = ResolveSnapshot(
            connected=True,
            project_name="Kunde_A",
            database_name="Local",
            page="color",
            timeline_name="v1",
            timecode="01:00:00:00",
        )

    def poll(self):
        return self.snapshot


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "tracker.db")
    probe = FakeProbe()
    state = {"now": START, "idle": 1.0, "frontmost": RESOLVE}
    runner = Runner(
        store=store,
        tracker=Tracker(idle_threshold_seconds=300),
        probe=probe,
        clock=lambda: state["now"],
        idle_source=lambda: state["idle"],
        frontmost_source=lambda: state["frontmost"],
        config=Config(),
    )
    yield runner, store, probe, state
    store.close()


def test_tick_opens_a_segment_in_the_database(setup):
    runner, store, _, _ = setup
    runner.tick_once()

    current = store.current_open_segment()
    assert current is not None
    assert current.resolve_project == "Kunde_A"


def test_further_ticks_extend_the_same_segment(setup):
    runner, store, _, state = setup
    runner.tick_once()
    first_id = store.current_open_segment().id

    state["now"] = START + timedelta(seconds=5)
    runner.tick_once()

    current = store.current_open_segment()
    assert current.id == first_id
    assert current.last_active_at == START + timedelta(seconds=5)


def test_long_idle_closes_the_segment_cut_back_in_the_database(setup):
    runner, store, _, state = setup
    runner.tick_once()
    state["now"] = START + timedelta(seconds=60)
    runner.tick_once()

    state["now"] = START + timedelta(seconds=500)
    state["frontmost"] = "com.apple.mail"
    runner.tick_once()
    state["now"] = START + timedelta(seconds=505)
    runner.tick_once()

    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=60)


def test_manual_pause_stops_tracking(setup):
    runner, store, _, state = setup
    runner.tick_once()
    runner.manual_pause = True
    state["now"] = START + timedelta(seconds=10)
    runner.tick_once()

    assert store.current_open_segment() is None


def test_status_reports_project_and_today_total(setup):
    runner, store, _, state = setup
    runner.tick_once()
    state["now"] = START + timedelta(seconds=120)
    runner.tick_once()

    status = runner.status()
    assert status.project == "Kunde_A"
    assert status.is_running is True
    assert status.current_seconds == pytest.approx(120.0)


def test_startup_closes_a_leftover_open_segment(tmp_path):
    """Nach einem Absturz darf das alte Segment nicht wiederbelebt werden."""
    path = tmp_path / "tracker.db"
    crashed = Store(path)
    seg_id = crashed.open_segment("Kunde_A", "Local", START, "color")
    crashed.touch_segment(seg_id, START + timedelta(seconds=30), "color")
    crashed.close()

    store = Store(path)
    Runner(
        store=store,
        tracker=Tracker(),
        probe=FakeProbe(),
        clock=lambda: START + timedelta(hours=8),
        idle_source=lambda: 1.0,
        frontmost_source=lambda: RESOLVE,
        config=Config(),
    )

    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=30)
    store.close()
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.runner'`

- [ ] **Schritt 3: `runner.py` implementieren**

```python
"""Verdrahtet Adapter, Zustandsmaschine und Datenbank zu einem Tick."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Config
from .models import CloseSegment, OpenSegment, Tick, TouchSegment
from .store import Store
from .tracker import Tracker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunnerStatus:
    project: str | None
    is_running: bool
    current_seconds: float
    today_seconds: float
    unmapped: list[str]


class Runner:
    def __init__(
        self,
        store: Store,
        tracker: Tracker,
        probe,
        clock: Callable[[], datetime],
        idle_source: Callable[[], float],
        frontmost_source: Callable[[], str | None],
        config: Config,
    ) -> None:
        self._store = store
        self._tracker = tracker
        self._probe = probe
        self._clock = clock
        self._idle_source = idle_source
        self._frontmost_source = frontmost_source
        self._config = config
        self._open_segment_id: int | None = None
        self.manual_pause = False

        # Nach einem Absturz kann ein Segment offen stehengeblieben sein. Es wird
        # auf seinen letzten bekannten Aktiv-Zeitpunkt zurueckgeschnitten.
        closed = self._store.close_stale_segments()
        if closed:
            log.warning("%d verwaiste Segmente beim Start geschlossen", closed)

    def tick_once(self) -> None:
        frontmost = self._frontmost_source()
        snapshot = self._probe.poll()
        tick = Tick(
            now=self._clock(),
            snapshot=snapshot,
            idle_seconds=self._idle_source(),
            frontmost_bundle_id=frontmost,
            manual_pause=self.manual_pause,
        )

        for command in self._tracker.tick(tick):
            self._apply(command)

    def _apply(self, command) -> None:
        if isinstance(command, OpenSegment):
            self._open_segment_id = self._store.open_segment(
                command.project, command.database, command.started_at, command.page
            )
        elif isinstance(command, TouchSegment):
            if self._open_segment_id is not None:
                self._store.touch_segment(
                    self._open_segment_id, command.last_active_at, command.page
                )
        elif isinstance(command, CloseSegment):
            if self._open_segment_id is not None:
                self._store.close_segment(self._open_segment_id, command.ended_at)
                self._open_segment_id = None

    def status(self) -> RunnerStatus:
        now = self._clock()
        open_segment = self._store.current_open_segment()
        current_seconds = (
            (open_segment.last_active_at - open_segment.started_at).total_seconds()
            if open_segment
            else 0.0
        )
        day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        totals = self._store.totals_since(day_start.astimezone(timezone.utc))
        return RunnerStatus(
            project=self._tracker.current_project if open_segment else None,
            is_running=open_segment is not None,
            current_seconds=current_seconds,
            today_seconds=sum(totals.values()),
            unmapped=self._store.unmapped_projects(),
        )
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, 6 Tests

- [ ] **Schritt 5: Gesamte Suite laufen lassen**

Run: `uv run pytest -v`
Expected: alle Tests grün

- [ ] **Schritt 6: Committen**

```bash
git add src/resolve_time_tracker/runner.py tests/test_runner.py
git commit -m "feat: Runner verdrahtet Adapter, Tracker und Store"
```

---

### Task 13: CLI

**Files:**
- Create: `src/resolve_time_tracker/cli.py`
- Create: `src/resolve_time_tracker/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `config.*`, `Store`, `Tracker`, `Runner`, `ResolveProbe`, `activity.*`, `TogglClient`, `syncer.sync`
- Produces:
  - `main(argv: list[str] | None = None) -> int`
  - `build_runner(store: Store, config: Config) -> Runner`
  - Unterbefehle: `daemon`, `menubar`, `token`, `map`, `sync`, `status`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_cli.py`:

```python
import pytest

from resolve_time_tracker.cli import main


def test_unknown_command_exits_with_error():
    with pytest.raises(SystemExit):
        main(["gibtsnicht"])


def test_no_command_prints_help_and_returns_nonzero(capsys):
    assert main([]) != 0
    assert "daemon" in capsys.readouterr().out


def test_status_runs_without_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("resolve_time_tracker.config.database_path", lambda: tmp_path / "t.db")
    monkeypatch.setattr("resolve_time_tracker.config.config_path", lambda: tmp_path / "c.toml")

    assert main(["status"]) == 0
    assert "Heute" in capsys.readouterr().out
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.cli'`

- [ ] **Schritt 3: `cli.py` implementieren**

```python
"""Kommandozeile."""

from __future__ import annotations

import argparse
import getpass
import logging
import time
from datetime import datetime, timezone

from . import config as cfg
from .runner import Runner
from .store import Store
from .tracker import Tracker


def build_runner(store: Store, config: cfg.Config) -> Runner:
    from .activity import frontmost_bundle_id, seconds_since_input
    from .resolve_probe import ResolveProbe

    return Runner(
        store=store,
        tracker=Tracker(
            input_grace_seconds=config.input_grace_seconds,
            idle_threshold_seconds=config.idle_threshold_seconds,
        ),
        probe=ResolveProbe(),
        clock=lambda: datetime.now(timezone.utc),
        idle_source=seconds_since_input,
        frontmost_source=frontmost_bundle_id,
        config=config,
    )


def _open_store() -> Store:
    return Store(cfg.database_path())


def _client():
    from .toggl import TogglClient

    token = cfg.get_token()
    if token is None:
        raise SystemExit("Kein Toggl-Token hinterlegt. Erst 'rtt token' ausfuehren.")
    return TogglClient(token)


def cmd_daemon(_args) -> int:
    config = cfg.load_config()
    store = _open_store()
    runner = build_runner(store, config)
    print("Tracker laeuft. Abbruch mit Strg-C.")
    try:
        while True:
            runner.tick_once()
            time.sleep(config.tick_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        store.close()


def cmd_menubar(_args) -> int:
    from .menubar import run_menubar

    return run_menubar()


def cmd_token(_args) -> int:
    token = getpass.getpass("Toggl-API-Token (Profile > API Token): ").strip()
    if not token:
        print("Nichts eingegeben, abgebrochen.")
        return 1
    cfg.set_token(token)
    print("Token in der Keychain abgelegt.")
    return 0


def cmd_map(_args) -> int:
    store = _open_store()
    try:
        unmapped = store.unmapped_projects()
        if not unmapped:
            print("Alle Projekte sind zugeordnet.")
            return 0

        client = _client()
        workspaces = client.workspaces()
        print("Workspaces:")
        for workspace in workspaces:
            print(f"  {workspace['id']}  {workspace['name']}")
        workspace_id = int(input("Workspace-ID: ").strip())
        projects = client.projects(workspace_id)

        for resolve_project in unmapped:
            print(f"\nResolve-Projekt: {resolve_project}")
            for project in projects:
                print(f"  {project['id']}  {project['name']}")
            answer = input("Toggl-Projekt-ID (leer = ueberspringen): ").strip()
            if not answer:
                continue
            store.set_mapping(resolve_project, workspace_id, int(answer))
            print(f"  zugeordnet auf {answer}")
        return 0
    finally:
        store.close()


def cmd_sync(_args) -> int:
    from .syncer import sync

    config = cfg.load_config()
    store = _open_store()
    try:
        result = sync(
            store,
            _client(),
            now=datetime.now(timezone.utc),
            merge_gap_seconds=config.merge_gap_seconds,
        )
        print(f"Gepusht: {result.pushed}, fehlgeschlagen: {result.failed}")
        if result.skipped_unmapped:
            print("Nicht zugeordnet: " + ", ".join(result.skipped_unmapped))
        return 0
    finally:
        store.close()


def cmd_status(_args) -> int:
    store = _open_store()
    try:
        now = datetime.now(timezone.utc)
        day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        totals = store.totals_since(day_start.astimezone(timezone.utc))
        print("Heute:")
        for project, seconds in sorted(totals.items(), key=lambda item: -item[1]):
            print(f"  {seconds / 3600:5.2f} h  {project}")
        if not totals:
            print("  nichts erfasst")

        open_segment = store.current_open_segment()
        if open_segment:
            print(f"Laufend: {open_segment.resolve_project} seit {open_segment.started_at.astimezone():%H:%M}")

        unmapped = store.unmapped_projects()
        if unmapped:
            print("Nicht zugeordnet: " + ", ".join(unmapped))
        return 0
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="rtt", description="Resolve Time Tracker")
    subparsers = parser.add_subparsers(dest="command")

    for name, handler, help_text in [
        ("daemon", cmd_daemon, "Tracking im Vordergrund, ohne Menubar"),
        ("menubar", cmd_menubar, "Tracking mit Menubar-Icon"),
        ("token", cmd_token, "Toggl-API-Token in der Keychain ablegen"),
        ("map", cmd_map, "Resolve-Projekte auf Toggl-Projekte zuordnen"),
        ("sync", cmd_sync, "Fertige Segmente nach Toggl pushen"),
        ("status", cmd_status, "Heutige Zeiten anzeigen"),
    ]:
        sub = subparsers.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    return args.handler(args)
```

`__main__.py`:

```python
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS, 3 Tests

- [ ] **Schritt 5: CLI von Hand ausprobieren**

Run: `uv run rtt status` und `uv run rtt --help`
Expected: Hilfetext listet alle sechs Unterbefehle, `status` läuft auch ohne Resolve durch.

- [ ] **Schritt 6: Committen**

```bash
git add src/resolve_time_tracker/cli.py src/resolve_time_tracker/__main__.py tests/test_cli.py
git commit -m "feat: Kommandozeile"
```

---

### Task 14: Menubar

**Files:**
- Create: `src/resolve_time_tracker/menubar.py`
- Test: `tests/test_menubar_format.py`

**Interfaces:**
- Consumes: `RunnerStatus` aus Task 12, `cli.build_runner`, `config.*`, `syncer.sync`
- Produces:
  - `format_title(status: RunnerStatus) -> str`
  - `format_duration(seconds: float) -> str`
  - `run_menubar() -> int`
  - `TrackerApp(rumps.App)`

- [ ] **Schritt 1: Failing tests schreiben**

`tests/test_menubar_format.py`:

```python
from resolve_time_tracker.menubar import format_duration, format_title
from resolve_time_tracker.runner import RunnerStatus


def status(**kwargs):
    base = dict(project=None, is_running=False, current_seconds=0.0, today_seconds=0.0, unmapped=[])
    base.update(kwargs)
    return RunnerStatus(**base)


def test_duration_is_hours_and_minutes():
    assert format_duration(0) == "0:00"
    assert format_duration(60) == "0:01"
    assert format_duration(3600) == "1:00"
    assert format_duration(8100) == "2:15"
    assert format_duration(360000) == "100:00"


def test_running_title_shows_marker_time_and_project():
    title = format_title(status(project="Kunde_A", is_running=True, current_seconds=8100))
    assert title == "● 2:15 Kunde_A"


def test_paused_title_shows_the_hollow_marker_without_project():
    assert format_title(status(project="Kunde_A", is_running=False, today_seconds=3600)) == "○ 1:00"


def test_title_without_resolve_is_a_dash():
    assert format_title(status()) == "–"


def test_long_project_names_are_shortened():
    title = format_title(
        status(project="Sehr_Langer_Kundenprojektname_2026", is_running=True, current_seconds=60)
    )
    assert len(title) <= 28
    assert title.endswith("…")
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `uv run pytest tests/test_menubar_format.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'resolve_time_tracker.menubar'`

- [ ] **Schritt 3: `menubar.py` implementieren**

```python
"""Menubar-Oberflaeche. Bewusst duenn, alle Logik liegt im Runner."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import rumps

from . import config as cfg
from .runner import RunnerStatus
from .store import Store

log = logging.getLogger(__name__)

MAX_PROJECT_CHARS = 18


def format_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    return f"{total_minutes // 60}:{total_minutes % 60:02d}"


def format_title(status: RunnerStatus) -> str:
    if status.is_running and status.project:
        project = status.project
        if len(project) > MAX_PROJECT_CHARS:
            project = project[: MAX_PROJECT_CHARS - 1] + "…"
        return f"● {format_duration(status.current_seconds)} {project}"
    if status.today_seconds > 0:
        return f"○ {format_duration(status.today_seconds)}"
    return "–"


class TrackerApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("–", quit_button=None)
        self._config = cfg.load_config()
        self._store = Store(cfg.database_path())

        from .cli import build_runner

        self._runner = build_runner(self._store, self._config)

        self._today_item = rumps.MenuItem("Heute: 0:00")
        self._pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self._unmapped_item = rumps.MenuItem("Alles zugeordnet")
        self.menu = [
            self._today_item,
            None,
            self._pause_item,
            self._unmapped_item,
            rumps.MenuItem("Jetzt synchronisieren", callback=self._sync_now),
            None,
            rumps.MenuItem("Log oeffnen", callback=self._open_log),
            rumps.MenuItem("Beenden", callback=self._quit),
        ]

        rumps.Timer(self._on_tick, int(self._config.tick_seconds)).start()
        if self._config.auto_push:
            rumps.Timer(self._on_sync_timer, 600).start()

    def _on_tick(self, _timer) -> None:
        try:
            self._runner.tick_once()
        except Exception:
            log.exception("Tick fehlgeschlagen")
            return
        self._refresh()

    def _refresh(self) -> None:
        status = self._runner.status()
        self.title = format_title(status)
        self._today_item.title = f"Heute: {format_duration(status.today_seconds)}"
        self._pause_item.title = "Fortsetzen" if self._runner.manual_pause else "Pause"
        self._unmapped_item.title = (
            f"Nicht zugeordnet ({len(status.unmapped)}): " + ", ".join(status.unmapped)
            if status.unmapped
            else "Alles zugeordnet"
        )

    def _toggle_pause(self, _sender) -> None:
        self._runner.manual_pause = not self._runner.manual_pause
        self._refresh()

    def _on_sync_timer(self, _timer) -> None:
        self._sync_now(None)

    def _sync_now(self, _sender) -> None:
        from .syncer import sync
        from .toggl import TogglClient

        token = cfg.get_token()
        if token is None:
            rumps.notification("Resolve Time Tracker", "Kein Toggl-Token", "Erst 'rtt token' ausfuehren.")
            return
        try:
            result = sync(
                self._store,
                TogglClient(token),
                now=datetime.now(timezone.utc),
                merge_gap_seconds=self._config.merge_gap_seconds,
            )
        except Exception:
            log.exception("Sync fehlgeschlagen")
            rumps.notification("Resolve Time Tracker", "Sync fehlgeschlagen", "Details im Log.")
            return
        if result.pushed:
            rumps.notification(
                "Resolve Time Tracker", "Nach Toggl uebertragen", f"{result.pushed} Eintraege"
            )

    def _open_log(self, _sender) -> None:
        import subprocess

        subprocess.run(["open", str(cfg.log_path())], check=False)

    def _quit(self, _sender) -> None:
        self._store.close()
        rumps.quit_application()


def run_menubar() -> int:
    TrackerApp().run()
    return 0
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `uv run pytest tests/test_menubar_format.py -v`
Expected: PASS, 5 Tests

- [ ] **Schritt 5: Menubar von Hand starten**

Run: `uv run rtt menubar`
Expected: Icon erscheint in der Menüleiste, zeigt bei geschlossenem Resolve `–`, bei Arbeit in Resolve `● 0:01 Projektname`.

- [ ] **Schritt 6: Committen**

```bash
git add src/resolve_time_tracker/menubar.py tests/test_menubar_format.py
git commit -m "feat: Menubar-Oberflaeche"
```

---

### Task 15: LaunchAgent und Installation

**Files:**
- Create: `packaging/com.monacoframe.resolve-time-tracker.plist`
- Create: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Consumes: `rtt menubar` aus Task 13/14
- Produces: `make install`, `make uninstall`, `make test`

- [ ] **Schritt 1: LaunchAgent-Vorlage schreiben**

`packaging/com.monacoframe.resolve-time-tracker.plist` mit `__PYTHON__` und `__LOG__` als Platzhaltern, die `make install` ersetzt:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.monacoframe.resolve-time-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>__PYTHON__</string>
        <string>-m</string>
        <string>resolve_time_tracker</string>
        <string>menubar</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>RESOLVE_SCRIPT_API</key>
        <string>/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting</string>
        <key>RESOLVE_SCRIPT_LIB</key>
        <string>/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so</string>
        <key>PYTHONPATH</key>
        <string>/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>__LOG__</string>
    <key>StandardErrorPath</key>
    <string>__LOG__</string>
</dict>
</plist>
```

- [ ] **Schritt 2: Makefile schreiben**

```makefile
LABEL := com.monacoframe.resolve-time-tracker
PLIST := $(HOME)/Library/LaunchAgents/$(LABEL).plist
LOG := $(HOME)/Library/Logs/resolve-time-tracker.log
PYTHON := $(CURDIR)/.venv/bin/python

.PHONY: test install uninstall logs

test:
	uv run pytest -v

$(PYTHON):
	uv sync

install: $(PYTHON)
	mkdir -p $(HOME)/Library/LaunchAgents
	sed -e 's|__PYTHON__|$(PYTHON)|g' -e 's|__LOG__|$(LOG)|g' \
		packaging/$(LABEL).plist > $(PLIST)
	-launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null
	launchctl bootstrap gui/$$(id -u) $(PLIST)
	@echo "Installiert. Naechster Schritt: uv run rtt token"

uninstall:
	-launchctl bootout gui/$$(id -u)/$(LABEL) 2>/dev/null
	rm -f $(PLIST)
	@echo "Deinstalliert. Datenbank und Config bleiben erhalten."

logs:
	tail -f $(LOG)
```

- [ ] **Schritt 3: README schreiben**

Kurz halten: Voraussetzung Resolve Studio, `make install`, `uv run rtt token`, `uv run rtt map`, wo die Datenbank liegt, wie man das Idle-Verhalten in der Config schraubt, und der Hinweis dass die Zeit im Zweifel unterschätzt wird.

- [ ] **Schritt 4: Installation testen**

```bash
make install
launchctl list | grep resolve-time-tracker
```

Expected: Der Dienst erscheint in der Liste, das Menubar-Icon taucht auf, `~/Library/Logs/resolve-time-tracker.log` füllt sich.

- [ ] **Schritt 5: Committen**

```bash
git add packaging/ Makefile README.md
git commit -m "feat: LaunchAgent und Installationsziele"
```

---

## Verifikation Ende-zu-Ende

Nach Abschluss aller Tasks in dieser Reihenfolge durchgehen:

1. `make test`, alle Tests grün.
2. `uv run python scripts/smoke_resolve.py` bei laufendem Resolve. (Bereits am 2026-08-04 gegen echtes Resolve Studio durchgeführt: Verbindung/Projekt/Page/Timeline funktionieren, Playback-Signal verworfen, siehe Task 2.)
3. `uv run rtt token`, danach `uv run rtt map` gegen einen Testworkspace.
4. `make install`, Menubar-Icon erscheint.
5. In Resolve arbeiten, Menubar zeigt `● Zeit Projektname`.
6. Fünf Minuten in Mail arbeiten, zurückkommen. `sqlite3 ~/Library/Application\ Support/resolve-time-tracker/tracker.db "select * from segments"` zeigt ein auf den Wechselzeitpunkt zurückgeschnittenes Segment, nicht ein durchlaufendes.
7. Projekt in Resolve wechseln, zwei getrennte Segmente in der Datenbank.
8. `uv run rtt sync`, danach der Eintrag in Toggl mit korrekter Dauer, Projekt und Page-Tags. Zweiter Lauf legt keinen Duplikat-Eintrag an.
9. `pkill -9 -f resolve_time_tracker` während ein Segment offen ist, dann Neustart. Das Segment ist auf `last_active_at` begrenzt, keine Endlosdauer.

## Selbstprüfung des Plans

- **Spec-Abdeckung:** Smoke-Test (Task 1), Aktiv-Definition (Task 2/4), Zustandsmaschine mit Rückschnitt (Task 3 bis 5), SQLite-Segmente und Crash-Sicherheit (Task 6, Task 12), Projekt-Mapping mit Parken (Task 7, Task 13), Config und Keychain (Task 8), Toggl-Client mit Drosselung (Task 9), Verschmelzung und Idempotenz (Task 10), Adapter (Task 11), Menubar (Task 14), LaunchAgent (Task 15). Jede Zeile der Spec hat einen Task.
- **Platzhalter:** keine. Jeder Codeschritt enthält den tatsächlichen Code.
- **Typkonsistenz:** `Segment`, `ProjectMapping`, `ResolveSnapshot`, `Tick`, `RunnerStatus`, `SegmentGroup` und `SyncResult` werden jeweils in genau einem Task definiert und danach mit denselben Feldnamen verwendet. `create_time_entry` hat in Task 9 (echter Client) und Task 10 (Fake) dieselbe Signatur.
- **Aktualisierung nach Live-Test (2026-08-04):** Der Timecode-Test aus Task 1 ist durchgelaufen und ist negativ ausgefallen (Playback-Signal nicht nutzbar, bekannte Resolve-API-Einschränkung). Wie in der ursprünglichen Fassung vorgesehen wurden daraufhin Task 2 (keine Timecode-Bedingung mehr, `is_active` ohne `previous_timecode`-Parameter), Task 3 (kein `_previous_timecode`/`_remember_timecode` mehr in `Tracker`), Task 4 (die beiden Playback-Tests ersetzt durch einen Test, der zeigt dass abgelaufener Input immer schließt), und Task 11/12 (`ResolveProbe.poll()` ohne `include_timecode`-Parameter, immer wenn eine Timeline offen ist) entsprechend angepasst. Alles Übrige bleibt unverändert.
