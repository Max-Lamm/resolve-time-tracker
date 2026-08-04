from unittest.mock import MagicMock, patch

from resolve_time_tracker.menubar import (
    LAUNCH_AGENT_LABEL,
    TrackerApp,
    _is_service_disabled,
    _mapping_signature,
    _project_menu_entries,
    format_duration,
    format_header,
    format_status_line,
    format_title,
)
from resolve_time_tracker.runner import RunnerStatus
from resolve_time_tracker.tracker import TrackerState


def status(**kwargs):
    base = dict(
        project=None,
        is_running=False,
        current_seconds=0.0,
        today_seconds=0.0,
        unmapped=[],
        tracker_state=TrackerState.NO_RESOLVE,
        resolve_connected=False,
        resolve_project_open=False,
    )
    base.update(kwargs)
    return RunnerStatus(**base)


def test_duration_is_hours_and_minutes():
    assert format_duration(0) == "0:00"
    assert format_duration(60) == "0:01"
    assert format_duration(3600) == "1:00"
    assert format_duration(8100) == "2:15"
    assert format_duration(360000) == "100:00"


def test_title_is_green_while_tracking():
    assert format_title(status(tracker_state=TrackerState.ACTIVE)) == "🟢"
    assert format_title(status(tracker_state=TrackerState.PENDING_IDLE)) == "🟢"


def test_title_is_yellow_while_idle_or_paused():
    assert format_title(status(tracker_state=TrackerState.PAUSED_IDLE)) == "🟡"
    assert format_title(status(tracker_state=TrackerState.PAUSED_MANUAL)) == "🟡"


def test_title_is_white_without_resolve():
    assert format_title(status(tracker_state=TrackerState.NO_RESOLVE)) == "⚪"


def test_status_line_covers_every_tracker_state():
    assert format_status_line(status(tracker_state=TrackerState.ACTIVE)) == "Wird getrackt"
    assert (
        format_status_line(status(tracker_state=TrackerState.PENDING_IDLE))
        == "Kurze Pause, zaehlt noch"
    )
    assert (
        format_status_line(status(tracker_state=TrackerState.PAUSED_IDLE))
        == "Idle, Segment beendet"
    )
    assert (
        format_status_line(status(tracker_state=TrackerState.PAUSED_MANUAL)) == "Manuell pausiert"
    )


def test_status_line_distinguishes_the_two_no_resolve_reasons():
    closed = status(tracker_state=TrackerState.NO_RESOLVE, resolve_connected=False)
    assert format_status_line(closed) == "Resolve laeuft nicht"

    no_project = status(
        tracker_state=TrackerState.NO_RESOLVE, resolve_connected=True, resolve_project_open=False
    )
    assert format_status_line(no_project) == "Kein Projekt offen"


def test_header_shows_project_and_duration_while_running():
    header = format_header(
        status(
            tracker_state=TrackerState.ACTIVE,
            is_running=True,
            project="PowerGrades Project",
            current_seconds=8100,
        )
    )
    assert header == "🟢 PowerGrades Project  2:15"


def test_header_falls_back_to_the_status_line_when_not_running():
    header = format_header(status(tracker_state=TrackerState.NO_RESOLVE, resolve_connected=False))
    assert header == "⚪ Resolve laeuft nicht"


def test_is_service_disabled_reads_the_matching_line():
    output = (
        '\tdisabled services = {\n'
        '\t\t"com.apple.Siri.agent" => enabled\n'
        f'\t\t"{LAUNCH_AGENT_LABEL}" => disabled\n'
        '\t}\n'
    )
    assert _is_service_disabled(output, LAUNCH_AGENT_LABEL) is True


def test_is_service_disabled_defaults_to_false_when_label_is_absent():
    output = '\tdisabled services = {\n\t\t"com.apple.Siri.agent" => enabled\n\t}\n'
    assert _is_service_disabled(output, LAUNCH_AGENT_LABEL) is False


def test_is_service_disabled_false_when_explicitly_enabled():
    output = f'\t\t"{LAUNCH_AGENT_LABEL}" => enabled\n'
    assert _is_service_disabled(output, LAUNCH_AGENT_LABEL) is False


def test_project_menu_entries_are_sorted_and_mark_the_selected_one():
    toggl_projects = [
        {"id": 2, "name": "RESOLVE (Auto-Track)"},
        {"id": 1, "name": "Not Payed!"},
    ]
    entries = _project_menu_entries(toggl_projects, selected_id=1)

    assert entries == [
        ("Not Payed!", 1, True),
        ("RESOLVE (Auto-Track)", 2, False),
    ]


def test_project_menu_entries_none_selected_when_unmapped():
    toggl_projects = [{"id": 1, "name": "Not Payed!"}]
    entries = _project_menu_entries(toggl_projects, selected_id=None)

    assert entries == [("Not Payed!", 1, False)]


def test_mapping_signature_changes_when_a_mapping_changes():
    base = _mapping_signature(["Kunde_A"], {"Kunde_A": None}, [{"id": 1, "name": "X"}])
    changed = _mapping_signature(["Kunde_A"], {"Kunde_A": 1}, [{"id": 1, "name": "X"}])

    assert base != changed


def test_mapping_signature_is_stable_for_equivalent_input():
    a = _mapping_signature(["Kunde_B", "Kunde_A"], {"Kunde_A": 1, "Kunde_B": None}, [{"id": 1, "name": "X"}])
    b = _mapping_signature(["Kunde_A", "Kunde_B"], {"Kunde_B": None, "Kunde_A": 1}, [{"id": 1, "name": "X"}])

    assert a == b


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
