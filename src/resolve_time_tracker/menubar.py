"""Menubar-Oberflaeche. Bewusst duenn, alle Logik liegt im Runner.

Resolve nimmt in der Statusleiste fast den ganzen Platz ein, deshalb bleibt
vom Tracker dort nur ein einziges Zeichen uebrig. Alles Weitere -- Projekt,
Dauer, Zuordnung, Login-Autostart -- steckt im Klappmenue.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from datetime import datetime, timezone

import rumps
from ServiceManagement import SMAppService, SMAppServiceStatusEnabled

from . import config as cfg
from .runner import RunnerStatus
from .store import Store
from .toggl import TogglError
from .tracker import TrackerState
from .workspace import resolve_workspace_id

log = logging.getLogger(__name__)

# Marker in der meta-Tabelle (siehe store.py, gleiches Muster wie in
# workspace.py): solange er fehlt, ist das der erste Start der App auf
# diesem Rechner, und der Setup-Assistent laeuft automatisch an.
SETUP_WIZARD_META_KEY = "setup_wizard_completed"

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
    """Ein einziges farbiges Zeichen -- alles andere steht im Klappmenue.

    Farbige Kreis-Emoji statt monochromer Zeichen: Gruen beim Tracken, Gelb
    bei Pause, Weiss als Default (Resolve laeuft oder ist zu, aber es wird
    gerade nicht getrackt). Emoji behalten ihre Farbe unabhaengig vom
    Hell-/Dunkelmodus der Menueleiste.
    """
    if status.tracker_state in _TRACKING_STATES:
        return "🟢"
    if status.tracker_state in _PAUSED_STATES:
        return "🟡"
    return "⚪"


def format_status_line(status: RunnerStatus) -> str:
    text = _STATUS_TEXT.get(status.tracker_state)
    if text is not None:
        return text
    # NO_RESOLVE: drei Gruende, die der Nutzer unterscheiden koennen muss.
    # Der haeufigste Stolperstein bei einem frisch eingerichteten Empfaenger
    # ist der mittlere: Resolve laeuft, aber External Scripting steht noch
    # auf None statt Local -- ohne diese Unterscheidung saehe das genauso
    # aus wie "Resolve ist zu" und fuehrt in die Irre.
    if not status.resolve_app_running:
        return "Resolve laeuft nicht"
    if not status.resolve_connected:
        return "Resolve-Scripting nicht aktiviert"
    return "Kein Projekt offen"


def format_header(status: RunnerStatus) -> str:
    if status.is_running and status.project:
        return f"{format_title(status)} {status.project}  {format_duration(status.current_seconds)}"
    return f"{format_title(status)} {format_status_line(status)}"


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


class TrackerApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("⚪", quit_button=None)
        self._config = cfg.load_config()
        self._store = Store(cfg.database_path())

        from .cli import build_runner

        self._runner = build_runner(self._store, self._config)

        self._toggl_projects: list[dict] = []
        self._toggl_fetch_in_progress = False
        self._mapping_signature: tuple | None = None
        self._autostart_dirty = True

        self._header_item = rumps.MenuItem("⚪ Resolve laeuft nicht")
        self._today_item = rumps.MenuItem("Heute gesamt: 0:00")
        self._status_item = rumps.MenuItem("Status: Resolve laeuft nicht")
        self._scripting_help_item = rumps.MenuItem(
            "Wie aktiviere ich das?", callback=self._show_scripting_help
        )
        self._scripting_help_item.hidden = True
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
            self._scripting_help_item,
            None,
            self._pause_item,
            self._map_item,
            rumps.MenuItem("Jetzt synchronisieren", callback=self._sync_now),
            None,
            self._token_item,
            self._autostart_item,
            rumps.MenuItem("Log oeffnen", callback=self._open_log),
            rumps.MenuItem("Einrichtung erneut starten…", callback=self._run_setup_wizard),
            None,
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

        if self._store.get_meta(SETUP_WIZARD_META_KEY) is None:
            self._run_setup_wizard(None)

    def _on_tick(self, _timer) -> None:
        try:
            self._runner.tick_once()
            self._refresh()
        except Exception:
            log.exception("Tick fehlgeschlagen")
            return

    def _refresh(self) -> None:
        status = self._runner.status()
        status_line = format_status_line(status)
        self.title = format_title(status)
        self._header_item.title = format_header(status)
        self._today_item.title = f"Heute gesamt: {format_duration(status.today_seconds)}"
        self._status_item.title = f"Status: {status_line}"
        self._scripting_help_item.hidden = status_line != "Resolve-Scripting nicht aktiviert"
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

        self._autostart_item.title = "Beim Login starten"
        self._autostart_item.state = 1 if _autostart_enabled() else 0

    def _toggle_pause(self, _sender) -> None:
        self._runner.manual_pause = not self._runner.manual_pause
        self._refresh()

    def _toggle_autostart(self, _sender) -> None:
        _set_autostart_enabled(not _autostart_enabled())
        self._autostart_dirty = True
        self._refresh()

    def _run_setup_wizard(self, _sender) -> None:
        """Gefuehrter Ablauf fuer den ersten Start (und ueber das Menue jederzeit

        wiederholbar). Jeder Schritt ist rein informativ oder per Abbrechen
        uebersprungbar -- der Assistent darf nie feststecken, falls Resolve
        fehlt oder jemand keinen Toggl-Token zur Hand hat.
        """
        rumps.alert(
            title="Willkommen bei Resolve Time Tracker",
            message=(
                "Diese App erfasst automatisch, wie lange du an welchem "
                "DaVinci-Resolve-Projekt arbeitest, und uebertraegt das nach Toggl."
            ),
        )
        self._setup_wizard_check_resolve()
        self._setup_wizard_offer_token()
        self._setup_wizard_offer_autostart()
        self._store.set_meta(SETUP_WIZARD_META_KEY, "1")

    def _setup_wizard_check_resolve(self) -> None:
        from .activity import is_resolve_running

        # status() liest nur den zuletzt getickten Snapshot, ohne einen
        # eigenen Tick waere der Assistent kurz nach dem Start faelschlich
        # immer "Resolve laeuft nicht", selbst wenn Resolve laengst offen ist.
        try:
            self._runner.tick_once()
        except Exception:
            log.exception("Tick fuer den Setup-Check fehlgeschlagen")
        status = self._runner.status()

        if status.resolve_connected:
            return
        if not is_resolve_running():
            rumps.alert(
                title="DaVinci Resolve",
                message=(
                    "DaVinci Resolve Studio wurde nicht gefunden. Die kostenlose "
                    "Version hat kein Scripting, Resolve Studio wird also "
                    "benoetigt. Sobald Resolve laeuft, erkennt der Tracker das "
                    "von selbst -- kein erneutes Einrichten noetig."
                ),
            )
            return
        self._show_scripting_help(None)

    def _setup_wizard_offer_token(self) -> None:
        if cfg.get_token() is not None:
            return
        choice = rumps.alert(
            title="Toggl verbinden",
            message=(
                "Damit erfasste Zeit nach Toggl uebertragen wird, braucht die App "
                "deinen Toggl-API-Token (Toggl-Profil > API Token). Jetzt einrichten?"
            ),
            ok="Weiter",
            cancel="Ueberspringen",
        )
        if choice == 1:
            self._set_token(None)

    def _setup_wizard_offer_autostart(self) -> None:
        if _autostart_enabled():
            return
        choice = rumps.alert(
            title="Beim Login starten",
            message="Soll der Tracker kuenftig automatisch starten, wenn du dich anmeldest?",
            ok="Ja",
            cancel="Nein",
        )
        if choice == 1:
            _set_autostart_enabled(True)
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
        token = response.text.strip()
        from .toggl import check_token

        try:
            check_token(token)
        except TogglError:
            log.exception("Token von Toggl abgelehnt")
            rumps.notification(
                "Resolve Time Tracker", "Token abgelehnt", "Nicht gespeichert, Details im Log."
            )
            return
        cfg.set_token(token)
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
                config=self._config,
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

    def _show_scripting_help(self, _sender) -> None:
        rumps.alert(
            title="Resolve-Scripting aktivieren",
            message=(
                "In DaVinci Resolve: Preferences (Cmd+,) -> System -> General -> "
                '"External scripting using" auf "Local" stellen, dann Resolve neu starten.'
            ),
        )

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


def _autostart_enabled() -> bool:
    return SMAppService.mainAppService().status() == SMAppServiceStatusEnabled


def _set_autostart_enabled(enabled: bool) -> None:
    # register/unregister statt eines LaunchAgent-Plists: die App traegt sich
    # damit selbst als Login-Item ein, ohne dass vorher etwas installiert
    # worden sein muss (siehe SMAppService, macOS 13+). Wirkt erst beim
    # naechsten Login, "Beenden" bleibt der Weg, die App jetzt zu schliessen.
    service = SMAppService.mainAppService()
    if enabled:
        service.registerAndReturnError_(None)
    else:
        service.unregisterAndReturnError_(None)


def run_menubar() -> int:
    TrackerApp().run()
    return 0
