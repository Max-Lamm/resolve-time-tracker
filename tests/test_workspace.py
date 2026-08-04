import pytest

from resolve_time_tracker.config import Config
from resolve_time_tracker.store import Store
from resolve_time_tracker.toggl import TogglError
from resolve_time_tracker.workspace import resolve_workspace_id


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
