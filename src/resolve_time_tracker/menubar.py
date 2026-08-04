"""Menubar-Oberflaeche. Bewusst duenn, alle Logik liegt im Runner.

Resolve nimmt in der Statusleiste fast den ganzen Platz ein, deshalb bleibt
vom Tracker dort nur ein einziges Zeichen uebrig. Alles Weitere -- Projekt,
Dauer, Zuordnung, Login-Autostart -- steckt im Klappmenue.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import rumps

from . import config as cfg
from .runner import RunnerStatus
from .store import Store
from .toggl import TogglError
from .tracker import TrackerState
from .workspace import resolve_workspace_id

log = logging.getLogger(__name__)

LAUNCH_AGENT_LABEL = "com.monacoframe.resolve-time-tracker"

_TRACKING_STATES = (TrackerState.ACTIVE, TrackerState.PENDING_IDLE)
_PAUSED_STATES = (TrackerState.PAUSED_IDLE, TrackerState.PAUSED_MANUAL)

_STATUS_TEXT = {
    TrackerState.ACTIVE: "Wird getrackt",
    TrackerState.PENDING_IDLE: "Kurze Pause, zaehlt noch",
    TrackerState.PAUSED_IDLE: "Idle, Segment beendet",
    TrackerState.PAUSED_MANUAL: "Manuell pausiert",
}


def format_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    return f"{total_minutes // 60}:{total_minutes % 60:02d}"


def format_title(status: RunnerStatus) -> str:
    """Ein einziges Zeichen -- alles andere steht im Klappmenue."""
    if status.tracker_state in _TRACKING_STATES:
        return "●"
    if status.tracker_state in _PAUSED_STATES:
        return "○"
    return "·"


def format_status_line(status: RunnerStatus) -> str:
    text = _STATUS_TEXT.get(status.tracker_state)
    if text is not None:
        return text
    # NO_RESOLVE: zwei Gruende, die der Nutzer unterscheiden koennen muss.
    if not status.resolve_connected:
        return "Resolve laeuft nicht"
    return "Kein Projekt offen"


def format_header(status: RunnerStatus) -> str:
    if status.is_running and status.project:
        return f"{format_title(status)} {status.project}  {format_duration(status.current_seconds)}"
    return f"{format_title(status)} {format_status_line(status)}"


def _is_service_disabled(output: str, label: str) -> bool:
    """Parst `launchctl print-disabled gui/<uid>`. Fehlt das Label, ist der Dienst

    nicht deaktiviert (launchd fuehrt nur explizit abgeschaltete Dienste auf).
    """
    needle = f'"{label}"'
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(needle):
            return line.endswith("=> disabled")
    return False


def _project_menu_entries(
    toggl_projects: list[dict], selected_id: int | None
) -> list[tuple[str, int, bool]]:
    """(Name, Toggl-Projekt-ID, ist-aktuell-zugeordnet), alphabetisch sortiert."""
    return [
        (p["name"], p["id"], p["id"] == selected_id)
        for p in sorted(toggl_projects, key=lambda p: p["name"].lower())
    ]


def _mapping_signature(
    resolve_projects: list[str], mappings: dict[str, int | None], toggl_projects: list[dict]
) -> tuple:
    """Fasst zusammen, wovon das Zuordnen-Untermenue abhaengt, um es nicht bei

    jedem 5-Sekunden-Tick neu zu bauen, sondern nur wenn sich wirklich etwas
    geaendert hat.
    """
    return (
        tuple(sorted(resolve_projects)),
        tuple(sorted(mappings.items())),
        tuple(sorted((p["id"], p["name"]) for p in toggl_projects)),
    )


def _launch_agent_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


class TrackerApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("·", quit_button=None)
        self._config = cfg.load_config()
        self._store = Store(cfg.database_path())

        from .cli import build_runner

        self._runner = build_runner(self._store, self._config)

        self._toggl_projects: list[dict] = []
        self._toggl_fetch_in_progress = False
        self._mapping_signature: tuple | None = None
        self._autostart_dirty = True

        self._header_item = rumps.MenuItem("· Resolve laeuft nicht")
        self._today_item = rumps.MenuItem("Heute gesamt: 0:00")
        self._status_item = rumps.MenuItem("Status: Resolve laeuft nicht")
        self._pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self._map_item = rumps.MenuItem("Zuordnen")
        # rumps.MenuItem erzeugt sein Submenu (NSMenu) erst beim ersten add();
        # clear() setzt es aber ungeprueft voraus. Ein Platzhalter hier legt
        # es an, damit _refresh_mapping_menu() gleich beim ersten Refresh
        # sicher clear() aufrufen kann.
        self._map_item.add(rumps.MenuItem("Wird geladen…"))
        self._token_item = rumps.MenuItem("Toggl-Token einrichten…", callback=self._set_token)
        self._autostart_item = rumps.MenuItem("Beim Login starten", callback=self._toggle_autostart)
        self.menu = [
            self._header_item,
            self._today_item,
            self._status_item,
            None,
            self._pause_item,
            self._map_item,
            rumps.MenuItem("Jetzt synchronisieren", callback=self._sync_now),
            None,
            self._token_item,
            self._autostart_item,
            rumps.MenuItem("Log oeffnen", callback=self._open_log),
            rumps.MenuItem("Beenden", callback=self._quit),
        ]

        self._tick_timer = rumps.Timer(self._on_tick, int(self._config.tick_seconds))
        self._tick_timer.start()
        self._sync_timer = None
        if self._config.auto_push:
            self._sync_timer = rumps.Timer(self._on_sync_timer, 600)
            self._sync_timer.start()

        self._start_toggl_projects_fetch()
        self._refresh()

    def _on_tick(self, _timer) -> None:
        try:
            self._runner.tick_once()
            self._refresh()
        except Exception:
            log.exception("Tick fehlgeschlagen")
            return

    def _refresh(self) -> None:
        status = self._runner.status()
        self.title = format_title(status)
        self._header_item.title = format_header(status)
        self._today_item.title = f"Heute gesamt: {format_duration(status.today_seconds)}"
        self._status_item.title = f"Status: {format_status_line(status)}"
        self._pause_item.title = "Fortsetzen" if self._runner.manual_pause else "Pause"

        self._refresh_mapping_menu()
        self._refresh_autostart_item()

    def _refresh_mapping_menu(self) -> None:
        resolve_projects = self._store.all_projects()
        mapping_ids: dict[str, int | None] = {}
        for project in resolve_projects:
            mapping = self._store.get_mapping(project)
            mapping_ids[project] = mapping.toggl_project_id if mapping else None
        signature = _mapping_signature(resolve_projects, mapping_ids, self._toggl_projects)
        if signature == self._mapping_signature:
            return
        self._mapping_signature = signature

        self._map_item.clear()
        self._map_item.add(
            rumps.MenuItem("Toggl-Projekte neu laden", callback=self._reload_toggl_projects)
        )
        if not resolve_projects:
            return
        self._map_item.add(None)
        for project in resolve_projects:
            self._map_item.add(self._build_project_submenu(project, mapping_ids[project]))

    def _build_project_submenu(self, resolve_project: str, selected_id: int | None) -> rumps.MenuItem:
        submenu = rumps.MenuItem(resolve_project)
        for name, toggl_id, checked in _project_menu_entries(self._toggl_projects, selected_id):
            item = rumps.MenuItem(name, callback=self._make_map_callback(resolve_project, toggl_id))
            item.state = 1 if checked else 0
            submenu.add(item)
        if self._toggl_projects:
            submenu.add(None)
        submenu.add(
            rumps.MenuItem(
                "Neues Toggl-Projekt anlegen…",
                callback=self._make_create_callback(resolve_project),
            )
        )
        return submenu

    def _refresh_autostart_item(self) -> None:
        if not self._autostart_dirty:
            return
        self._autostart_dirty = False

        if not _launch_agent_plist_path().exists():
            self._autostart_item.title = "Beim Login starten (erst 'make install')"
            self._autostart_item.state = 0
            return

        self._autostart_item.title = "Beim Login starten"
        self._autostart_item.state = 0 if _autostart_disabled() else 1

    def _toggle_pause(self, _sender) -> None:
        self._runner.manual_pause = not self._runner.manual_pause
        self._refresh()

    def _toggle_autostart(self, _sender) -> None:
        if not _launch_agent_plist_path().exists():
            rumps.notification(
                "Resolve Time Tracker", "Noch nicht installiert", "Erst 'make install' ausfuehren."
            )
            return
        _set_autostart_enabled(_autostart_disabled())  # aktuell aus -> jetzt an, und umgekehrt
        self._autostart_dirty = True
        self._refresh()

    def _set_token(self, _sender) -> None:
        response = rumps.Window(
            message="Toggl-API-Token (Profil > API Token in Toggl):",
            title="Toggl-Token einrichten",
            ok="Speichern",
            cancel="Abbrechen",
            secure=True,
        ).run()
        if not response.clicked or not response.text.strip():
            return
        cfg.set_token(response.text.strip())
        rumps.notification("Resolve Time Tracker", "Token gespeichert", "")
        self._start_toggl_projects_fetch()

    def _on_sync_timer(self, _timer) -> None:
        self._sync_now(None)

    def _sync_now(self, _sender) -> None:
        from .syncer import sync

        client = self._toggl_client()
        if client is None:
            return
        try:
            result = sync(
                self._store,
                client,
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

    def _toggl_client(self):
        token = cfg.get_token()
        if token is None:
            rumps.notification(
                "Resolve Time Tracker", "Kein Toggl-Token", "Erst 'Toggl-Token einrichten…' verwenden."
            )
            return None
        from .toggl import TogglClient

        return TogglClient(token)

    def _reload_toggl_projects(self, _sender) -> None:
        self._start_toggl_projects_fetch()

    def _start_toggl_projects_fetch(self) -> None:
        """Holt die aktiven Toggl-Projekte im Hintergrund.

        Laeuft in einem eigenen Thread, der ausschliesslich das Netz anfasst --
        weder SQLite (der Store ist nicht threadsicher) noch AppKit (der
        Run-Loop gehoert dem Hauptthread). Die Workspace-Aufloesung, die den
        Store lesen und schreiben kann, passiert deshalb synchron vorher.
        """
        if self._toggl_fetch_in_progress:
            return
        client = self._toggl_client()
        if client is None:
            return
        try:
            workspace_id = resolve_workspace_id(self._store, client, self._config)
        except TogglError:
            log.exception("Workspace konnte nicht aufgeloest werden")
            return

        self._toggl_fetch_in_progress = True

        def _worker() -> None:
            try:
                projects = client.projects(workspace_id)
            except Exception:
                log.exception("Toggl-Projekte konnten nicht geladen werden")
                projects = None
            self._toggl_fetch_in_progress = False
            if projects is not None:
                self._toggl_projects = projects

        threading.Thread(target=_worker, daemon=True).start()

    def _make_map_callback(self, resolve_project: str, toggl_project_id: int):
        def _callback(_sender) -> None:
            client = self._toggl_client()
            if client is None:
                return
            try:
                workspace_id = resolve_workspace_id(self._store, client, self._config)
            except TogglError:
                log.exception("Workspace konnte nicht aufgeloest werden")
                return
            self._store.set_mapping(resolve_project, workspace_id, toggl_project_id)
            self._refresh()

        return _callback

    def _make_create_callback(self, resolve_project: str):
        def _callback(_sender) -> None:
            client = self._toggl_client()
            if client is None:
                return
            response = rumps.Window(
                message=f"Name des neuen Toggl-Projekts fuer '{resolve_project}':",
                title="Neues Toggl-Projekt anlegen",
                default_text=resolve_project,
                ok="Anlegen",
                cancel="Abbrechen",
            ).run()
            if not response.clicked or not response.text.strip():
                return
            try:
                workspace_id = resolve_workspace_id(self._store, client, self._config)
                project = client.create_project(workspace_id, response.text.strip())
            except TogglError:
                log.exception("Neues Toggl-Projekt konnte nicht angelegt werden")
                rumps.notification("Resolve Time Tracker", "Anlegen fehlgeschlagen", "Details im Log.")
                return
            self._store.set_mapping(resolve_project, workspace_id, project["id"])
            self._start_toggl_projects_fetch()
            self._refresh()

        return _callback

    def _open_log(self, _sender) -> None:
        subprocess.run(["open", str(cfg.log_path())], check=False)

    def _quit(self, _sender) -> None:
        # Timer must be stopped before the store closes: rumps schedules ticks on
        # the same run loop this callback runs on, and a tick already queued
        # ahead of quit_application() would otherwise fire against a closed
        # sqlite connection.
        self._tick_timer.stop()
        if self._sync_timer is not None:
            self._sync_timer.stop()
        self._store.close()
        rumps.quit_application()


def _autostart_disabled() -> bool:
    result = subprocess.run(
        ["launchctl", "print-disabled", f"gui/{os.getuid()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return _is_service_disabled(result.stdout, LAUNCH_AGENT_LABEL)


def _set_autostart_enabled(enabled: bool) -> None:
    # Bewusst enable/disable statt bootstrap/bootout: bootout wuerde den
    # gerade laufenden Prozess beenden, der dieses Menue zeichnet. disable
    # wirkt erst beim naechsten Login, "Beenden" bleibt der Weg, die App
    # jetzt zu schliessen.
    action = "enable" if enabled else "disable"
    subprocess.run(["launchctl", action, f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"], check=False)


def run_menubar() -> int:
    TrackerApp().run()
    return 0
