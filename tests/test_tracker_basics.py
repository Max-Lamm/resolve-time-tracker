from datetime import datetime, timedelta, timezone

from resolve_time_tracker.models import CloseSegment, OpenSegment, ResolveSnapshot, Tick, TouchSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

RESOLVE = "com.blackmagic-design.DaVinciResolveStudio"
START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def tick_at(
    seconds: float,
    *,
    project="Kunde_Film",
    idle=1.0,
    frontmost=RESOLVE,
    connected=True,
    timecode="01:00:00:00",
    manual_pause=False,
) -> Tick:
    return Tick(
        now=START + timedelta(seconds=seconds),
        snapshot=ResolveSnapshot(
            connected=connected,
            project_name=project,
            database_name="Local",
            page="color",
            timeline_name="v1",
            timecode=timecode,
        ),
        idle_seconds=idle,
        frontmost_bundle_id=frontmost,
        manual_pause=manual_pause,
    )


def test_starts_in_no_resolve():
    assert Tracker().state is TrackerState.NO_RESOLVE


def test_first_active_tick_opens_a_segment():
    tracker = Tracker()
    commands = tracker.tick(tick_at(0))

    assert commands == [OpenSegment(project="Kunde_Film", database="Local", started_at=START, page="color")]
    assert tracker.state is TrackerState.ACTIVE


def test_following_active_ticks_touch_the_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    commands = tracker.tick(tick_at(5))

    assert commands == [TouchSegment(last_active_at=START + timedelta(seconds=5), page="color")]
    assert tracker.last_active_at == START + timedelta(seconds=5)


def test_resolve_closing_ends_the_segment_immediately():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(5))
    commands = tracker.tick(tick_at(10, connected=False, project=None, timecode=None))

    # Zurueckgeschnitten auf den letzten bekannten Aktiv-Zeitpunkt, nicht auf now.
    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=5))]
    assert tracker.state is TrackerState.NO_RESOLVE


def test_ticks_without_resolve_produce_nothing():
    tracker = Tracker()
    assert tracker.tick(tick_at(0, connected=False, project=None, timecode=None)) == []
    assert tracker.tick(tick_at(5, connected=False, project=None, timecode=None)) == []


def test_going_inactive_does_not_close_immediately():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    commands = tracker.tick(tick_at(5, frontmost="com.apple.mail"))

    assert commands == []
    assert tracker.state is TrackerState.PENDING_IDLE
