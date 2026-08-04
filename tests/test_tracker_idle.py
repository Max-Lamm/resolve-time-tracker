from datetime import timedelta

from resolve_time_tracker.models import CloseSegment, OpenSegment, TouchSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

from tests.test_tracker_basics import START, tick_at


def test_short_pause_below_threshold_counts_as_work():
    """Zwei Minuten nachdenken sind Arbeit, das Segment darf nicht zerrissen werden."""
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, idle=120))  # PENDING_IDLE
    tracker.tick(tick_at(120, idle=180))  # immer noch unter der Schwelle
    commands = tracker.tick(tick_at(180, idle=1))  # zurueck an der Maus

    assert commands == [TouchSegment(last_active_at=START + timedelta(seconds=180), page="color")]
    assert tracker.state is TrackerState.ACTIVE


def test_long_pause_closes_and_cuts_back_to_last_activity():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60))  # letzter aktiver Tick
    tracker.tick(tick_at(120, idle=90))  # PENDING_IDLE
    commands = tracker.tick(tick_at(400, idle=400))  # 340 s still, Schwelle gerissen

    assert commands == [CloseSegment(ended_at=START + timedelta(seconds=60))]
    assert tracker.state is TrackerState.PAUSED_IDLE


def test_closing_happens_exactly_once():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(400, idle=400))
    tracker.tick(tick_at(405, idle=405))

    assert tracker.tick(tick_at(410, idle=410)) == []


def test_work_resumes_with_a_new_segment_after_a_long_pause():
    tracker = Tracker(idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(400, idle=400))  # schliesst
    commands = tracker.tick(tick_at(500, idle=1))

    assert commands == [
        OpenSegment(
            project="Kunde_Film",
            database="Local",
            started_at=START + timedelta(seconds=500),
            page="color",
        )
    ]


def test_idle_without_input_closes_even_while_playhead_could_move():
    # Kein Playback-Signal mehr (siehe Task 2): abgelaufener Input schliesst immer,
    # unabhaengig davon ob in Resolve etwas laeuft.
    tracker = Tracker(input_grace_seconds=30, idle_threshold_seconds=300)
    tracker.tick(tick_at(0))
    tracker.tick(tick_at(60, idle=60))
    commands = tracker.tick(tick_at(400, idle=400))

    assert commands == [CloseSegment(ended_at=START)]
