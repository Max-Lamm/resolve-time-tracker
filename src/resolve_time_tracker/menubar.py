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
            self._refresh()
        except Exception:
            log.exception("Tick fehlgeschlagen")
            return

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
