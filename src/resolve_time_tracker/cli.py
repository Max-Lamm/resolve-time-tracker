"""Kommandozeile."""

from __future__ import annotations

import argparse
import getpass
import logging
import time
from datetime import datetime, timezone

from . import config as cfg
from .runner import Runner, local_day_start
from .store import Store
from .tracker import Tracker

log = logging.getLogger(__name__)


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
