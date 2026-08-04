from resolve_time_tracker.menubar import format_duration, format_title
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
