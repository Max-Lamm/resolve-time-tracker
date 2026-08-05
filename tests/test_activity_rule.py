from datetime import datetime, timezone

import pytest

from resolve_time_tracker.models import (
    ResolveSnapshot,
    Tick,
    is_active,
    is_project_loaded,
    is_resolve_frontmost,
)

RESOLVE_BUNDLE = "com.blackmagic-design.DaVinciResolve"
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def make_tick(
    *,
    connected=True,
    project="Kunde_Film",
    idle=1.0,
    frontmost=RESOLVE_BUNDLE,
    manual_pause=False,
):
    snapshot = ResolveSnapshot(
        connected=connected,
        project_name=project,
        database_name="Local",
        page="color",
        timeline_name="v1",
        timecode="01:00:00:00",
    )
    return Tick(
        now=NOW,
        snapshot=snapshot,
        idle_seconds=idle,
        frontmost_bundle_id=frontmost,
        manual_pause=manual_pause,
    )


@pytest.mark.parametrize(
    "bundle_id,expected",
    [
        ("com.blackmagic-design.DaVinciResolve", True),
        ("com.blackmagic-design.DaVinciResolveStudio", True),
        ("com.apple.mail", False),
        (None, False),
    ],
)
def test_resolve_frontmost_matches_by_prefix(bundle_id, expected):
    assert is_resolve_frontmost(bundle_id) is expected


def test_active_when_resolve_frontmost_and_recent_input():
    assert is_active(make_tick(idle=5.0), input_grace_seconds=30) is True


def test_inactive_when_another_app_is_frontmost():
    tick = make_tick(frontmost="com.apple.mail", idle=1.0)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_input_is_stale():
    # Kein Playback-Signal mehr als Alternative: abgelaufener Input heisst immer inaktiv.
    tick = make_tick(idle=120.0)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_resolve_not_connected():
    tick = make_tick(connected=False, project=None)
    assert is_active(tick, input_grace_seconds=30) is False


def test_inactive_when_no_project_open():
    tick = make_tick(project=None)
    assert is_active(tick, input_grace_seconds=30) is False


def test_manual_pause_overrides_everything():
    tick = make_tick(idle=0.0, manual_pause=True)
    assert is_active(tick, input_grace_seconds=30) is False


def test_project_overview_placeholder_is_not_loaded():
    # Resolve liefert in der Projektuebersicht "Untitled Project" mit 0 Timelines.
    assert (
        is_project_loaded(
            "Untitled Project", timeline_count=0, ignored_projects=("Untitled Project",)
        )
        is False
    )


def test_real_project_with_a_timeline_is_loaded():
    assert (
        is_project_loaded(
            "Kunde_A", timeline_count=1, ignored_projects=("Untitled Project",)
        )
        is True
    )


def test_real_project_literally_named_like_the_placeholder_is_loaded_once_it_has_a_timeline():
    assert (
        is_project_loaded(
            "Untitled Project", timeline_count=1, ignored_projects=("Untitled Project",)
        )
        is True
    )


def test_fresh_real_project_without_a_timeline_yet_is_loaded():
    # Kein Timeline-Count-Blackout fuer echte, nur noch nicht umbenannte Projekte.
    assert (
        is_project_loaded("Kunde_B", timeline_count=0, ignored_projects=("Untitled Project",))
        is True
    )


def test_no_project_at_all_is_not_loaded():
    assert is_project_loaded(None, timeline_count=0, ignored_projects=()) is False


def test_empty_ignore_list_never_filters_by_name():
    assert is_project_loaded("Untitled Project", timeline_count=0, ignored_projects=()) is True
