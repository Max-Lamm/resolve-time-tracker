from datetime import datetime, timezone

import pytest

from resolve_time_tracker.models import (
    ResolveSnapshot,
    Tick,
    is_active,
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
