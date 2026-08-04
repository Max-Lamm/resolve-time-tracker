from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.config import Config
from resolve_time_tracker.models import ResolveSnapshot
from resolve_time_tracker.runner import Runner
from resolve_time_tracker.store import Store
from resolve_time_tracker.tracker import Tracker

RESOLVE = "com.blackmagic-design.DaVinciResolveStudio"
START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


class FakeProbe:
    def __init__(self):
        self.snapshot = ResolveSnapshot(
            connected=True,
            project_name="Kunde_A",
            database_name="Local",
            page="color",
            timeline_name="v1",
            timecode="01:00:00:00",
        )

    def poll(self):
        return self.snapshot


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "tracker.db")
    probe = FakeProbe()
    state = {"now": START, "idle": 1.0, "frontmost": RESOLVE}
    runner = Runner(
        store=store,
        tracker=Tracker(idle_threshold_seconds=300),
        probe=probe,
        clock=lambda: state["now"],
        idle_source=lambda: state["idle"],
        frontmost_source=lambda: state["frontmost"],
        config=Config(),
    )
    yield runner, store, probe, state
    store.close()


def test_tick_opens_a_segment_in_the_database(setup):
    runner, store, _, _ = setup
    runner.tick_once()

    current = store.current_open_segment()
    assert current is not None
    assert current.resolve_project == "Kunde_A"


def test_further_ticks_extend_the_same_segment(setup):
    runner, store, _, state = setup
    runner.tick_once()
    first_id = store.current_open_segment().id

    state["now"] = START + timedelta(seconds=5)
    runner.tick_once()

    current = store.current_open_segment()
    assert current.id == first_id
    assert current.last_active_at == START + timedelta(seconds=5)


def test_long_idle_closes_the_segment_cut_back_in_the_database(setup):
    runner, store, _, state = setup
    runner.tick_once()
    state["now"] = START + timedelta(seconds=60)
    runner.tick_once()

    state["now"] = START + timedelta(seconds=500)
    state["frontmost"] = "com.apple.mail"
    runner.tick_once()
    state["now"] = START + timedelta(seconds=505)
    runner.tick_once()

    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=60)


def test_manual_pause_stops_tracking(setup):
    runner, store, _, state = setup
    runner.tick_once()
    runner.manual_pause = True
    state["now"] = START + timedelta(seconds=10)
    runner.tick_once()

    assert store.current_open_segment() is None


def test_status_reports_project_and_today_total(setup):
    runner, store, _, state = setup
    runner.tick_once()
    state["now"] = START + timedelta(seconds=120)
    runner.tick_once()

    status = runner.status()
    assert status.project == "Kunde_A"
    assert status.is_running is True
    assert status.current_seconds == pytest.approx(120.0)


def test_startup_closes_a_leftover_open_segment(tmp_path):
    """Nach einem Absturz darf das alte Segment nicht wiederbelebt werden."""
    path = tmp_path / "tracker.db"
    crashed = Store(path)
    seg_id = crashed.open_segment("Kunde_A", "Local", START, "color")
    crashed.touch_segment(seg_id, START + timedelta(seconds=30), "color")
    crashed.close()

    store = Store(path)
    Runner(
        store=store,
        tracker=Tracker(),
        probe=FakeProbe(),
        clock=lambda: START + timedelta(hours=8),
        idle_source=lambda: 1.0,
        frontmost_source=lambda: RESOLVE,
        config=Config(),
    )

    assert store.current_open_segment() is None
    assert store.segments_since(START)[0].ended_at == START + timedelta(seconds=30)
    store.close()
