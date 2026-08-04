"""Adapter zur Toggl Track API v9."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

BASE_URL = "https://api.track.toggl.com/api/v9"
CREATED_WITH = "resolve-time-tracker"
MAX_ATTEMPTS = 3
PROJECTS_PAGE_SIZE = 200


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

    def projects(self, workspace_id: int, active_only: bool = True) -> list[dict[str, Any]]:
        """Alle Projekte eines Workspace, standardmaessig ohne Archiv.

        Gegen das echte Konto geprueft: 201 Projekte insgesamt, nur 6 davon
        aktiv. Ohne serverseitigen Filter waere die Auswahl unbrauchbar gross,
        und ohne Paginierung wuerde eine Antwort ueber PROJECTS_PAGE_SIZE
        Eintraegen still abgeschnitten.
        """
        params: dict[str, Any] = {"per_page": PROJECTS_PAGE_SIZE}
        if active_only:
            params["active"] = "true"

        projects: list[dict[str, Any]] = []
        page = 1
        while True:
            params["page"] = page
            batch = self._request("GET", f"/workspaces/{workspace_id}/projects", params=params)
            projects.extend(batch)
            if len(batch) < PROJECTS_PAGE_SIZE:
                break
            page += 1
        return projects

    def create_project(self, workspace_id: int, name: str) -> dict[str, Any]:
        payload = {"name": name, "active": True}
        return self._request("POST", f"/workspaces/{workspace_id}/projects", json=payload)

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

    def _request(
        self, method: str, path: str, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                response = self._http.request(
                    method, f"{BASE_URL}{path}", auth=self._auth, json=json, params=params
                )
            except httpx.HTTPError as e:
                raise TogglError(f"Netzwerkfehler bei {method} {path}: {e}")

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2**attempt))
                last_error = TogglRateLimited(f"429 auf {method} {path}")
                self._sleep(retry_after)
                continue

            if response.status_code >= 400:
                raise TogglError(f"{response.status_code} auf {method} {path}: {response.text}")

            return response.json()

        raise last_error or TogglError(f"{method} {path} nach {MAX_ATTEMPTS} Versuchen gescheitert")


def check_token(token: str) -> None:
    """Prueft einen Toggl-Token, bevor er in der Keychain landet.

    Ein Vertipper beim Einrichten wuerde sonst still gespeichert und sich
    erst spaeter als leere Projektliste bzw. fehlgeschlagener Sync zeigen.
    `/me/workspaces` ist der billigste authentifizierte Endpunkt und wird
    bereits von TogglClient.workspaces() genutzt. Wirft TogglError, wenn
    Toggl den Token ablehnt.
    """
    TogglClient(token).workspaces()
