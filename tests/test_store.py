from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Store

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def test_open_segment_returns_an_id_and_is_retrievable(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    current = store.current_open_segment()

    assert current is not None
    assert current.id == segment_id
    assert current.resolve_project == "Kunde_A"
    assert current.started_at == START
    assert current.last_active_at == START
    assert current.ended_at is None
    assert current.pages_seen == ["color"]


def test_touch_updates_last_active_and_collects_pages(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=5), "edit")
    store.touch_segment(segment_id, START + timedelta(seconds=10), "color")

    current = store.current_open_segment()
    assert current.last_active_at == START + timedelta(seconds=10)
    assert sorted(current.pages_seen) == ["color", "edit"]


def test_close_segment_sets_end_and_clears_the_open_slot(store):
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=60), "color")
    store.close_segment(segment_id, START + timedelta(seconds=60))

    assert store.current_open_segment() is None
    closed = store.segments_since(START)[0]
    assert closed.ended_at == START + timedelta(seconds=60)


def test_timestamps_survive_a_roundtrip_with_timezone(store):
    store.open_segment("Kunde_A", "Local", START, "color")
    current = store.current_open_segment()

    assert current.started_at.tzinfo is not None
    assert current.started_at == START


def test_reopening_the_database_keeps_the_data(tmp_path):
    path = tmp_path / "tracker.db"
    first = Store(path)
    segment_id = first.open_segment("Kunde_A", "Local", START, "color")
    first.close()

    second = Store(path)
    assert second.current_open_segment().id == segment_id
    second.close()


def test_close_stale_segments_cuts_back_to_last_activity(store):
    """Nach einem harten Absturz darf ein offenes Segment nicht weiterlaufen."""
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    store.touch_segment(segment_id, START + timedelta(seconds=120), "color")

    closed_count = store.close_stale_segments()

    assert closed_count == 1
    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=120)


def test_close_stale_segments_is_a_noop_when_nothing_is_open(store):
    assert store.close_stale_segments() == 0


def test_open_segment_rejects_naive_datetime(store):
    """Naive datetimes are forbidden to prevent silent data corruption."""
    naive_dt = datetime(2026, 8, 3, 10, 0)
    with pytest.raises(ValueError, match="Naive datetime not allowed"):
        store.open_segment("Kunde_A", "Local", naive_dt, "color")


def test_touch_segment_rejects_naive_datetime(store):
    """Naive datetimes are forbidden to prevent silent data corruption."""
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    naive_dt = datetime(2026, 8, 3, 10, 5)
    with pytest.raises(ValueError, match="Naive datetime not allowed"):
        store.touch_segment(segment_id, naive_dt, "edit")


def test_close_segment_rejects_naive_datetime(store):
    """Naive datetimes are forbidden to prevent silent data corruption."""
    segment_id = store.open_segment("Kunde_A", "Local", START, "color")
    naive_dt = datetime(2026, 8, 3, 10, 5)
    with pytest.raises(ValueError, match="Naive datetime not allowed"):
        store.close_segment(segment_id, naive_dt)


def test_segments_since_rejects_naive_datetime(store):
    """Naive datetimes are forbidden to prevent silent data corruption."""
    store.open_segment("Kunde_A", "Local", START, "color")
    naive_dt = datetime(2026, 8, 3, 10, 0)
    with pytest.raises(ValueError, match="Naive datetime not allowed"):
        store.segments_since(naive_dt)


def test_open_segment_rejects_non_utc_datetime(store):
    """Non-UTC datetimes are forbidden to prevent sorting corruption."""
    # Datetime with offset of +02:00 instead of UTC
    non_utc_dt = datetime(2026, 8, 3, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    with pytest.raises(ValueError, match="Non-UTC datetime not allowed"):
        store.open_segment("Kunde_A", "Local", non_utc_dt, "color")


def test_meta_roundtrip(store):
    store.set_meta("toggl_workspace_id", "3578077")

    assert store.get_meta("toggl_workspace_id") == "3578077"


def test_meta_is_none_for_unknown_key(store):
    assert store.get_meta("nichts_da") is None


def test_setting_meta_twice_overwrites(store):
    store.set_meta("toggl_workspace_id", "111")
    store.set_meta("toggl_workspace_id", "222")

    assert store.get_meta("toggl_workspace_id") == "222"
