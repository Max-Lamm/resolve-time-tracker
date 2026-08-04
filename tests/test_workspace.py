import pytest

from resolve_time_tracker.config import Config
from resolve_time_tracker.store import Store
from resolve_time_tracker.toggl import TogglError
from resolve_time_tracker.workspace import (
    DEFAULT_PROJECT_META_KEY,
    DEFAULT_PROJECT_NAME,
    resolve_default_project_id,
    resolve_workspace_id,
)


class FakeToggl:
    def __init__(self, workspaces):
        self._workspaces = workspaces
        self.calls = 0

    def workspaces(self):
        self.calls += 1
        return self._workspaces


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def test_config_override_wins_over_everything(store):
    config = Config(default_workspace_id=999)
    client = FakeToggl([{"id": 111}, {"id": 222}])

    assert resolve_workspace_id(store, client, config) == 999
    assert client.calls == 0


def test_cached_meta_wins_over_the_api_call(store):
    store.set_meta("toggl_workspace_id", "111")
    client = FakeToggl([{"id": 111}, {"id": 222}])

    assert resolve_workspace_id(store, client, Config()) == 111
    assert client.calls == 0


def test_a_single_workspace_is_resolved_and_cached(store):
    client = FakeToggl([{"id": 3578077, "name": "Maximilian Lamm's workspace"}])

    assert resolve_workspace_id(store, client, Config()) == 3578077
    assert store.get_meta("toggl_workspace_id") == "3578077"


def test_multiple_workspaces_without_an_override_raise(store):
    client = FakeToggl([{"id": 111}, {"id": 222}])

    with pytest.raises(TogglError):
        resolve_workspace_id(store, client, Config())


def test_no_workspaces_raise(store):
    client = FakeToggl([])

    with pytest.raises(TogglError):
        resolve_workspace_id(store, client, Config())


class FakeTogglProjects:
    def __init__(self, projects):
        self._projects = projects
        self.created: list[dict] = []

    def projects(self, workspace_id):
        return self._projects

    def create_project(self, workspace_id, name):
        project = {"id": 999, "name": name}
        self.created.append(project)
        return project


def test_default_project_id_is_cached_after_first_resolution(store):
    store.set_meta(DEFAULT_PROJECT_META_KEY, "555")
    client = FakeTogglProjects([])  # sollte gar nicht angefragt werden

    assert resolve_default_project_id(store, client, workspace_id=111) == 555
    assert client.created == []


def test_default_project_id_is_found_by_exact_name_and_cached(store):
    client = FakeTogglProjects(
        [{"id": 111, "name": "Anderes Projekt"}, {"id": 222, "name": DEFAULT_PROJECT_NAME}]
    )

    assert resolve_default_project_id(store, client, workspace_id=111) == 222
    assert store.get_meta(DEFAULT_PROJECT_META_KEY) == "222"
    assert client.created == []


def test_default_project_id_is_created_when_missing(store):
    client = FakeTogglProjects([{"id": 111, "name": "Anderes Projekt"}])

    project_id = resolve_default_project_id(store, client, workspace_id=111)

    assert project_id == 999
    assert client.created == [{"id": 999, "name": DEFAULT_PROJECT_NAME}]
    assert store.get_meta(DEFAULT_PROJECT_META_KEY) == "999"
