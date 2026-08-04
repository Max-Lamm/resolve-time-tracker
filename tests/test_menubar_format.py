from unittest.mock import MagicMock, patch

from resolve_time_tracker.menubar import (
    SETUP_WIZARD_META_KEY,
    TrackerApp,
    _autostart_enabled,
    _mapping_signature,
    _project_menu_entries,
    _set_autostart_enabled,
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
        resolve_app_running=True,
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


def test_status_line_distinguishes_the_three_no_tracking_reasons():
    closed = status(
        tracker_state=TrackerState.NO_RESOLVE, resolve_app_running=False, resolve_connected=False
    )
    assert format_status_line(closed) == "Resolve laeuft nicht"

    scripting_disabled = status(
        tracker_state=TrackerState.NO_RESOLVE, resolve_app_running=True, resolve_connected=False
    )
    assert format_status_line(scripting_disabled) == "Resolve-Scripting nicht aktiviert"

    no_project = status(
        tracker_state=TrackerState.NO_RESOLVE,
        resolve_app_running=True,
        resolve_connected=True,
        resolve_project_open=False,
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
    header = format_header(
        status(
            tracker_state=TrackerState.NO_RESOLVE, resolve_app_running=False, resolve_connected=False
        )
    )
    assert header == "⚪ Resolve laeuft nicht"


def test_autostart_enabled_reflects_the_service_status():
    with patch("resolve_time_tracker.menubar.SMAppService") as mock_cls:
        mock_cls.mainAppService.return_value.status.return_value = 1  # Enabled
        assert _autostart_enabled() is True

        mock_cls.mainAppService.return_value.status.return_value = 0  # NotRegistered
        assert _autostart_enabled() is False


def test_set_autostart_enabled_registers_when_turning_on():
    with patch("resolve_time_tracker.menubar.SMAppService") as mock_cls:
        service = mock_cls.mainAppService.return_value
        _set_autostart_enabled(True)
        service.registerAndReturnError_.assert_called_once_with(None)
        service.unregisterAndReturnError_.assert_not_called()


def test_set_autostart_enabled_unregisters_when_turning_off():
    with patch("resolve_time_tracker.menubar.SMAppService") as mock_cls:
        service = mock_cls.mainAppService.return_value
        _set_autostart_enabled(False)
        service.unregisterAndReturnError_.assert_called_once_with(None)
        service.registerAndReturnError_.assert_not_called()


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


def test_setup_wizard_runs_every_step_once_and_sets_the_marker():
    app = TrackerApp.__new__(TrackerApp)
    app._store = MagicMock()

    with (
        patch("resolve_time_tracker.menubar.rumps.alert") as alert_mock,
        patch.object(TrackerApp, "_setup_wizard_check_resolve") as check_mock,
        patch.object(TrackerApp, "_setup_wizard_offer_token") as token_mock,
        patch.object(TrackerApp, "_setup_wizard_offer_autostart") as autostart_mock,
    ):
        app._run_setup_wizard(None)

    alert_mock.assert_called_once()  # die Begruessung
    check_mock.assert_called_once()
    token_mock.assert_called_once()
    autostart_mock.assert_called_once()
    app._store.set_meta.assert_called_once_with(SETUP_WIZARD_META_KEY, "1")


def test_setup_wizard_offer_token_skips_the_dialog_when_a_token_already_exists():
    app = TrackerApp.__new__(TrackerApp)
    with (
        patch("resolve_time_tracker.menubar.cfg.get_token", return_value="existing"),
        patch("resolve_time_tracker.menubar.rumps.alert") as alert_mock,
    ):
        app._setup_wizard_offer_token()
    alert_mock.assert_not_called()


def test_setup_wizard_offer_token_opens_the_token_dialog_when_accepted():
    app = TrackerApp.__new__(TrackerApp)
    app._set_token = MagicMock()
    with (
        patch("resolve_time_tracker.menubar.cfg.get_token", return_value=None),
        patch("resolve_time_tracker.menubar.rumps.alert", return_value=1),
    ):
        app._setup_wizard_offer_token()
    app._set_token.assert_called_once_with(None)


def test_setup_wizard_offer_token_stays_skipped_when_declined():
    """Der Assistent darf nie feststecken -- Abbrechen muss der Ausweg bleiben,

    falls jemand seinen Toggl-Token gerade nicht zur Hand hat.
    """
    app = TrackerApp.__new__(TrackerApp)
    app._set_token = MagicMock()
    with (
        patch("resolve_time_tracker.menubar.cfg.get_token", return_value=None),
        patch("resolve_time_tracker.menubar.rumps.alert", return_value=0),
    ):
        app._setup_wizard_offer_token()
    app._set_token.assert_not_called()


def test_setup_wizard_offer_autostart_skips_the_dialog_when_already_enabled():
    app = TrackerApp.__new__(TrackerApp)
    with (
        patch("resolve_time_tracker.menubar.SMAppService") as mock_cls,
        patch("resolve_time_tracker.menubar.rumps.alert") as alert_mock,
    ):
        mock_cls.mainAppService.return_value.status.return_value = 1  # Enabled
        app._setup_wizard_offer_autostart()
    alert_mock.assert_not_called()


def test_setup_wizard_offer_autostart_registers_when_accepted():
    app = TrackerApp.__new__(TrackerApp)
    app._refresh = MagicMock()
    with (
        patch("resolve_time_tracker.menubar.SMAppService") as mock_cls,
        patch("resolve_time_tracker.menubar.rumps.alert", return_value=1),
    ):
        mock_cls.mainAppService.return_value.status.return_value = 0  # NotRegistered
        app._setup_wizard_offer_autostart()
    mock_cls.mainAppService.return_value.registerAndReturnError_.assert_called_once_with(None)
    assert app._autostart_dirty is True
    app._refresh.assert_called_once()


def test_setup_wizard_check_resolve_does_nothing_when_already_connected():
    app = TrackerApp.__new__(TrackerApp)
    app._runner = MagicMock()
    app._runner.status.return_value = status(resolve_connected=True)
    with (
        patch("resolve_time_tracker.activity.is_resolve_running") as running_mock,
        patch("resolve_time_tracker.menubar.rumps.alert") as alert_mock,
    ):
        app._setup_wizard_check_resolve()
    app._runner.tick_once.assert_called_once()
    running_mock.assert_not_called()
    alert_mock.assert_not_called()


def test_setup_wizard_check_resolve_explains_when_resolve_is_not_running():
    app = TrackerApp.__new__(TrackerApp)
    app._runner = MagicMock()
    app._runner.status.return_value = status(resolve_connected=False)
    with (
        patch("resolve_time_tracker.activity.is_resolve_running", return_value=False),
        patch("resolve_time_tracker.menubar.rumps.alert") as alert_mock,
    ):
        app._setup_wizard_check_resolve()
    assert alert_mock.call_count == 1
    assert "Resolve Studio" in alert_mock.call_args.kwargs["message"]


def test_setup_wizard_check_resolve_shows_scripting_help_when_resolve_runs_unconnected():
    app = TrackerApp.__new__(TrackerApp)
    app._runner = MagicMock()
    app._runner.status.return_value = status(resolve_connected=False)
    app._show_scripting_help = MagicMock()
    with patch("resolve_time_tracker.activity.is_resolve_running", return_value=True):
        app._setup_wizard_check_resolve()
    app._show_scripting_help.assert_called_once_with(None)
