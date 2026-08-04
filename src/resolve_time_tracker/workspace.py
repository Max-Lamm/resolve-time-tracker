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
