from datetime import timedelta

from resolve_time_tracker.models import CloseSegment, OpenSegment, TouchSegment
from resolve_time_tracker.tracker import Tracker, TrackerState

from tests.test_tracker_basics import START, tick_at


def test_switching_project_after_settle_closes_the_old_and_opens_a_new_segment():
    tracker = Tracker(project_settle_seconds=120)
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_A"))
    # Erster Kontakt mit Kunde_B startet Pending, Segment bleibt noch bei Kunde_A
    # und bleibt (bewusst) ohne weitere Touches -- der Besuch ist still.
    tracker.tick(tick_at(120, project="Kunde_B"))
    # 121 s nach dem ersten Kunde_B-Tick ist die Settle-Zeit ueberschritten.
    commands = tracker.tick(tick_at(241, project="Kunde_B"))

    # Kunde_A endet beim letzten bestaetigten Kunde_A-Tick (60), nicht am
    # Pending-Beginn -- der User war seitdem nicht mehr im alten Projekt.
    # Kunde_B startet rueckwirkend bei pending_since (120), damit die Besuchs-
    # zeit (die beim Settle-Durchbruch echt neue Arbeit wurde) dem neuen Projekt
    # zugerechnet wird.
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


def test_short_visit_to_other_project_keeps_the_old_segment_open():
    """Grade-Kopieren: kurzer Ausflug zu Kunde_B und zurueck zu Kunde_A -- der
    Tracker darf dafuer kein neues Segment aufmachen, sondern das alte
    weiterlaufen lassen.
    """
    tracker = Tracker(project_settle_seconds=120)
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_A"))

    # Besuch unter der Settle-Schwelle: still, keine Commands.
    visit = tracker.tick(tick_at(70, project="Kunde_B"))
    stay = tracker.tick(tick_at(90, project="Kunde_B"))
    # Zurueck zu Kunde_A: ganz normaler Touch -- der schlaegt die Besuchszeit
    # dem Hauptprojekt zu, weil das Store-Segment einfach auf 100 verlaengert wird.
    back = tracker.tick(tick_at(100, project="Kunde_A"))

    assert visit == []
    assert stay == []
    assert back == [TouchSegment(last_active_at=START + timedelta(seconds=100), page="color")]
    assert tracker.current_project == "Kunde_A"
    assert tracker.state is TrackerState.ACTIVE


def test_leaving_and_coming_back_resets_the_pending_timer():
    """Zwei Mal kurz nach Kunde_B springen, dazwischen zurueck -- der zweite
    Ausflug startet die Settle-Uhr neu, loest also nicht faelschlich den Wechsel aus.
    """
    tracker = Tracker(project_settle_seconds=120)
    tracker.tick(tick_at(0, project="Kunde_A"))
    tracker.tick(tick_at(60, project="Kunde_B"))  # Pending beginnt bei 60
    tracker.tick(tick_at(90, project="Kunde_A"))  # zurueck, Pending verworfen
    tracker.tick(tick_at(150, project="Kunde_B"))  # Pending beginnt neu bei 150
    # 90 s nach dem zweiten Pending-Start -- noch unter Settle.
    commands = tracker.tick(tick_at(240, project="Kunde_B"))

    assert commands == []
    assert tracker.current_project == "Kunde_A"


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
