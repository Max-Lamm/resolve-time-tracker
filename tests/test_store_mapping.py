from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Store

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def add_closed_segment(store, project, offset_seconds, duration_seconds):
    started = START + timedelta(seconds=offset_seconds)
    segment_id = store.open_segment(project, "Local", started, "color")
    ended = started + timedelta(seconds=duration_seconds)
    store.touch_segment(segment_id, ended, "color")
    store.close_segment(segment_id, ended)
    return segment_id


def test_mapping_roundtrip(store):
    store.set_mapping("Kunde_A", 111, 222)
    mapping = store.get_mapping("Kunde_A")

    assert mapping.toggl_workspace_id == 111
    assert mapping.toggl_project_id == 222


def test_mapping_is_none_for_unknown_project(store):
    assert store.get_mapping("Kunde_Unbekannt") is None


def test_setting_a_mapping_twice_overwrites(store):
    store.set_mapping("Kunde_A", 111, 222)
    store.set_mapping("Kunde_A", 111, 333)

    assert store.get_mapping("Kunde_A").toggl_project_id == 333


def test_unmapped_projects_lists_only_projects_with_unsynced_work(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    add_closed_segment(store, "Kunde_B", 700, 600)
    store.set_mapping("Kunde_A", 111, 222)

    assert store.unmapped_projects() == ["Kunde_B"]


def test_unsynced_segments_only_returns_closed_ones(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    store.open_segment("Kunde_A", "Local", START + timedelta(seconds=1000), "color")

    unsynced = store.unsynced_segments(closed_before=START + timedelta(days=1))
    assert len(unsynced) == 1


def test_unsynced_segments_respects_the_cutoff(store):
    add_closed_segment(store, "Kunde_A", 0, 600)

    assert store.unsynced_segments(closed_before=START) == []


def test_mark_synced_removes_segments_from_the_queue(store):
    first = add_closed_segment(store, "Kunde_A", 0, 600)
    second = add_closed_segment(store, "Kunde_A", 700, 600)

    store.mark_synced([first, second], toggl_entry_id=999, synced_at=START)

    assert store.unsynced_segments(closed_before=START + timedelta(days=1)) == []
    assert store.segments_since(START)[0].toggl_entry_id == 999


def test_totals_since_sums_per_project(store):
    add_closed_segment(store, "Kunde_A", 0, 600)
    add_closed_segment(store, "Kunde_A", 700, 300)
    add_closed_segment(store, "Kunde_B", 2000, 1200)

    totals = store.totals_since(START)
    assert totals == {"Kunde_A": 900.0, "Kunde_B": 1200.0}
