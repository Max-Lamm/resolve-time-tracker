from unittest.mock import MagicMock, patch

from resolve_time_tracker.menubar import TrackerApp, format_duration, format_title
from resolve_time_tracker.runner import RunnerStatus


def status(**kwargs):
    base = dict(project=None, is_running=False, current_seconds=0.0, today_seconds=0.0, unmapped=[])
    base.update(kwargs)
    return RunnerStatus(**base)


def test_duration_is_hours_and_minutes():
    assert format_duration(0) == "0:00"
    assert format_duration(60) == "0:01"
    assert format_duration(3600) == "1:00"
    assert format_duration(8100) == "2:15"
    assert format_duration(360000) == "100:00"


def test_running_title_shows_marker_time_and_project():
    title = format_title(status(project="Kunde_A", is_running=True, current_seconds=8100))
    assert title == "● 2:15 Kunde_A"


def test_paused_title_shows_the_hollow_marker_without_project():
    assert format_title(status(project="Kunde_A", is_running=False, today_seconds=3600)) == "○ 1:00"


def test_title_without_resolve_is_a_dash():
    assert format_title(status()) == "–"


def test_long_project_names_are_shortened():
    title = format_title(
        status(project="Sehr_Langer_Kundenprojektname_2026", is_running=True, current_seconds=60)
    )
    assert len(title) <= 28
    assert title.endswith("…")


def test_quit_stops_timers_before_closing_the_store():
    """A tick already queued on the run loop ahead of quit_application() must not
    be able to fire against an already-closed sqlite connection."""
    app = TrackerApp.__new__(TrackerApp)
    order = []
    app._tick_timer = MagicMock()
    app._tick_timer.stop.side_effect = lambda: order.append("tick_timer.stop")
    app._sync_timer = MagicMock()
    app._sync_timer.stop.side_effect = lambda: order.append("sync_timer.stop")
    app._store = MagicMock()
    app._store.close.side_effect = lambda: order.append("store.close")

    with patch("resolve_time_tracker.menubar.rumps.quit_application") as quit_mock:
        quit_mock.side_effect = lambda: order.append("quit_application")
        app._quit(None)

    assert order.index("tick_timer.stop") < order.index("store.close")
    assert order.index("sync_timer.stop") < order.index("store.close")
    assert order.index("store.close") < order.index("quit_application")


def test_quit_works_without_a_sync_timer():
    """auto_push disabled means _sync_timer is None; quit must not blow up on it."""
    app = TrackerApp.__new__(TrackerApp)
    app._tick_timer = MagicMock()
    app._sync_timer = None
    app._store = MagicMock()

    with patch("resolve_time_tracker.menubar.rumps.quit_application"):
        app._quit(None)

    app._tick_timer.stop.assert_called_once()
    app._store.close.assert_called_once()
