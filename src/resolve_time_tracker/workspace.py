"""Loest die Toggl-Workspace-ID auf, ohne den Nutzer bei jedem Zuordnen erneut zu fragen.

Reihenfolge: expliziter Config-Override, dann ein einmal in der Datenbank
gemerkter Wert, dann eine Live-Abfrage bei Toggl -- nur bei genau einem
Workspace automatisch uebernommen. Bei mehreren Workspaces gibt es keinen
sicheren Default, das muss ueber default_workspace_id in der Config gesetzt
werden.
"""

from __future__ import annotations

from typing import Any, Protocol

from .config import Config
from .store import Store
from .toggl import TogglError

META_KEY = "toggl_workspace_id"

DEFAULT_PROJECT_META_KEY = "toggl_default_project_id"
DEFAULT_PROJECT_NAME = "RESOLVE (Auto-Track)"


class _WorkspaceSource(Protocol):
    def workspaces(self) -> list[dict[str, Any]]: ...


def resolve_workspace_id(store: Store, client: _WorkspaceSource, config: Config) -> int:
    if config.default_workspace_id is not None:
        return config.default_workspace_id

    cached = store.get_meta(META_KEY)
    if cached is not None:
        return int(cached)

    workspaces = client.workspaces()
    if len(workspaces) != 1:
        raise TogglError(
            f"{len(workspaces)} Workspaces gefunden, es wird aber genau einer benoetigt. "
            "default_workspace_id in der Config setzen, um einen davon fest zu waehlen."
        )

    workspace_id = int(workspaces[0]["id"])
    store.set_meta(META_KEY, str(workspace_id))
    return workspace_id


def resolve_default_project_id(store: Store, client, workspace_id: int) -> int:
    """Toggl-Projekt fuer Resolve-Projekte, die noch keine eigene Zuordnung haben.

    Sucht per exaktem Namen unter den aktiven Projekten, legt es nur an, wenn
    es wirklich fehlt (z. B. in einem frischen Workspace). Damit geht keine
    Arbeitszeit mehr verloren, nur weil `rtt map` noch nicht ausgefuehrt wurde
    -- Aufrufer soll die Zuordnung danach ueber store.set_mapping() festhalten,
    damit sie sich spaeter ueber die Zuordnen-UI korrigieren laesst.
    """
    cached = store.get_meta(DEFAULT_PROJECT_META_KEY)
    if cached is not None:
        return int(cached)

    for project in client.projects(workspace_id):
        if project["name"] == DEFAULT_PROJECT_NAME:
            store.set_meta(DEFAULT_PROJECT_META_KEY, str(project["id"]))
            return int(project["id"])

    created = client.create_project(workspace_id, DEFAULT_PROJECT_NAME)
    store.set_meta(DEFAULT_PROJECT_META_KEY, str(created["id"]))
    return int(created["id"])
