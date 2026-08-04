"""Kommandozeile."""

from __future__ import annotations

import argparse
import getpass
import logging
import subprocess
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from . import config as cfg
from .runner import Runner, local_day_start
from .singleton import AlreadyRunning, acquire_lock
from .store import Store
from .toggl import TogglError, check_token
from .tracker import Tracker

log = logging.getLogger(__name__)


def build_runner(store: Store, config: cfg.Config) -> Runner:
    from .activity import frontmost_bundle_id, is_resolve_running, seconds_since_input
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
        resolve_running_source=is_resolve_running,
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
    # Vor dem Store: ein zweiter Tracking-Prozess (z. B. LaunchAgent laeuft
    # schon im Hintergrund) darf nicht gegen dieselbe Datenbank schreiben.
    # Der Handle muss in einer Variable gehalten werden, die den ganzen
    # Prozess ueberlebt -- sonst schliesst der GC ihn sofort wieder und das
    # Lock ist augenblicklich weg (derselbe Fehler wie beim rumps.Timer in
    # menubar.py, siehe dortiger Kommentar zu _quit()).
    try:
        _lock = acquire_lock(cfg.lock_path())
    except AlreadyRunning:
        print("Resolve Time Tracker laeuft bereits (Menubar oder ein anderer Daemon). Abbruch.")
        return 1

    config = cfg.load_config()
    store = _open_store()
    runner = build_runner(store, config)
    print("Tracker laeuft. Abbruch mit Strg-C.")
    try:
        while True:
            try:
                runner.tick_once()
            except Exception:
                log.exception("Fehler beim Tick, fortfahren")
            time.sleep(config.tick_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        store.close()


def cmd_menubar(_args) -> int:
    from .menubar import run_menubar

    # Referenz auf den Handle muss bis zum Prozessende leben, siehe Kommentar
    # in cmd_daemon -- hier laeuft run_menubar() blockierend in derselben
    # Aufrufkette weiter, solange bleibt _lock im Scope und damit lebendig.
    try:
        _lock = acquire_lock(cfg.lock_path())
    except AlreadyRunning:
        # Kein rumps-App-Kontext an dieser Stelle fuer rumps.notification,
        # deshalb ein natives Alert per osascript.
        subprocess.run(
            [
                "osascript",
                "-e",
                'display alert "Resolve Time Tracker" message '
                '"Laeuft bereits – siehe Menueleiste." as warning',
            ],
            check=False,
        )
        print("Resolve Time Tracker laeuft bereits.")
        return 1

    return run_menubar()


def cmd_token(_args) -> int:
    token = getpass.getpass("Toggl-API-Token (Profile > API Token): ").strip()
    if not token:
        print("Nichts eingegeben, abgebrochen.")
        return 1
    try:
        check_token(token)
    except TogglError as e:
        print(f"Token von Toggl abgelehnt, nicht gespeichert: {e}")
        return 1
    cfg.set_token(token)
    print("Token in der Keychain abgelegt.")
    return 0


def cmd_map(_args) -> int:
    from .workspace import resolve_workspace_id

    store = _open_store()
    try:
        unmapped = store.unmapped_projects()
        if not unmapped:
            print("Alle Projekte sind zugeordnet.")
            return 0

        client = _client()
        workspace_id = resolve_workspace_id(store, client, cfg.load_config())
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
            config=config,
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
        day_start = local_day_start(now)
        totals = store.totals_since(day_start)
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


def _configure_logging() -> None:
    """Schreibt sowohl in eine rotierende Logdatei als auch auf stderr.

    Vor dem eigenstaendigen App-Bundle fing das LaunchAgent-Plist stderr ab
    und leitete es in die Logdatei um -- ohne LaunchAgent geht stderr im
    Bundle ins Nichts, und "Log oeffnen" im Menue haette nichts zu zeigen.
    Der Datei-Handler ist deshalb jetzt fest verdrahtet statt sich auf eine
    aeussere Umleitung zu verlassen. Der Stream-Handler bleibt daneben
    bestehen, damit `rtt daemon`/`rtt sync` im Terminal weiterhin live
    mitlesbar sind. force=True, damit wiederholte main()-Aufrufe (Tests,
    potenzielle Re-Entry) nicht auf einen laengst veralteten log_path()
    aus einem frueheren Aufruf sitzen bleiben.
    """
    log_path = cfg.log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler], force=True)
    # httpx loggt jede einzelne Anfrage auf INFO -- bei einer dauerhaft
    # laufenden Menubar-App wuerde das die rotierende Logdatei schnell mit
    # Rauschen fuellen und echte Fehler darin verstecken.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
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
