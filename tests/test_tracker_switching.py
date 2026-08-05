from datetime import timedelta

from resolve_time_tracker.models import CloseSegment, OpenSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

from tests.test_tracker_basics import START, tick_at


def test_switching_project_closes_the_old_and_opens_a_new_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_A"))
    commands = tracker.tick(tick_at(120, project="Kunde_B"))

    assert commands == [
        CloseSegment(ended_at=START + timedelta(seconds=60)),
        OpenSegment(
            project="Kunde_B",
            database="Local",
            started_at=START + timedelta(seconds=120),
            page="color",
        ),
    ]
    assert tracker.current_project == "Kunde_B"


def test_manual_pause_closes_immediately_without_waiting_for_the_threshold():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60))
    commands = tracker.tick(tick_at(65, manual_pause=True))

    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=60))]
    assert tracker.state is TrackerState.PAUSED_MANUAL


def test_manual_pause_blocks_new_segments_while_active():
    tracker = Tracker()
    tracker.tick(tick_at(0, manual_pause=True))
    tracker.tick(tick_at(60, idle=0, manual_pause=True))

    assert tracker.state is not TrackerState.ACTIVE


def test_resuming_after_manual_pause_opens_a_new_segment():
    tracker = Tracker()
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, manual_pause=True))
    commands = tracker.tick(tick_at(120))

    assert commands == [
        OpenSegment(
            project="Kunde_Film",
            database="Local",
            started_at=START + timedelta(seconds=120),
            page="color",
        )
    ]


def test_project_closed_back_to_overview_closes_the_segment():
    # Resolve bleibt verbunden, aber es ist kein Projekt mehr geladen (Uebersicht).
    tracker = Tracker()
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_A"))
    commands = tracker.tick(tick_at(120, project=None))

    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=60))]
    assert tracker.state is TrackerState.NO_RESOLVE
    assert tracker.current_project is None


def test_resolve_quitting_during_a_pending_idle_closes_the_segment():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, frontmost="com.apple.mail"))  # PENDING_IDLE
    commands = tracker.tick(tick_at(120, connected=False, project=None, timecode=None))

    assert commands == [CloseSegment(ended_at=START)]
    assert tracker.state is TrackerState.NO_RESOLVE
