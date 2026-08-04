import base64
import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from resolve_time_tracker.toggl import BASE_URL, TogglClient, TogglError, TogglRateLimited

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


@respx.mock
def test_network_errors_are_converted_to_toggl_error(client):
    respx.post(f"{BASE_URL}/workspaces/111/time_entries").mock(
        side_effect=httpx.ConnectError("Network unreachable")
    )

    with pytest.raises(TogglError):
        client.create_time_entry(111, 222, "Kunde_A", START, 60, [])
