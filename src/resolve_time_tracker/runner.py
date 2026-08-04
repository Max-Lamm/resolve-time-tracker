"""Verdrahtet Adapter, Zustandsmaschine und Datenbank zu einem Tick."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable

from .config import Config
from .models import CloseSegment, OpenSegment, ResolveSnapshot, Tick, TouchSegment
from .store import Store
from .tracker import Tracker, TrackerState

log = logging.getLogger(__name__)


def local_day_start(now: datetime, tz: tzinfo | None = None) -> datetime:
    """Start of the calendar day containing `now`, in the given timezone (or the

    real system's local timezone if tz is None), returned back in UTC.

    This constructs local midnight as a real local-time value first (letting the
    tzinfo resolve the correct offset for that day-instant), then converts to
    UTC -- unlike a plain `now.astimezone().replace(hour=0, ...)`, it does not
    reuse `now`'s UTC offset for a different instant, so it is correct across
    DST transitions.
    """
    local_now = now.astimezone(tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


@dataclass(frozen=True)
class RunnerStatus:
    project: str | None
    is_running: bool
    current_seconds: float
    today_seconds: float
    unmapped: list[str]
    tracker_state: TrackerState
    resolve_connected: bool
    resolve_project_open: bool
    resolve_app_running: bool = True


class Runner:
    def __init__(
        self,
        store: Store,
        tracker: Tracker,
        probe,
        clock: Callable[[], datetime],
        idle_source: Callable[[], float],
        frontmost_source: Callable[[], str | None],
        config: Config,
        local_tz: tzinfo | None = None,
        resolve_running_source: Callable[[], bool] = lambda: True,
    ) -> None:
        self._store = store
        self._tracker = tracker
        self._probe = probe
        self._clock = clock
        self._idle_source = idle_source
        self._frontmost_source = frontmost_source
        self._config = config
        self._local_tz = local_tz
        self._resolve_running_source = resolve_running_source
        self._open_segment_id: int | None = None
        self._last_snapshot: ResolveSnapshot = ResolveSnapshot(connected=False)
        self.manual_pause = False

        # Nach einem Absturz kann ein Segment offen stehengeblieben sein. Es wird
        # auf seinen letzten bekannten Aktiv-Zeitpunkt zurueckgeschnitten.
        closed = self._store.close_stale_segments()
        if closed:
            log.warning("%d verwaiste Segmente beim Start geschlossen", closed)

    def tick_once(self) -> None:
        frontmost = self._frontmost_source()
        snapshot = self._probe.poll()
        self._last_snapshot = snapshot
        tick = Tick(
            now=self._clock(),
            snapshot=snapshot,
            idle_seconds=self._idle_source(),
            frontmost_bundle_id=frontmost,
            manual_pause=self.manual_pause,
        )

        for command in self._tracker.tick(tick):
            self._apply(command)

    def _apply(self, command) -> None:
        if isinstance(command, OpenSegment):
            self._open_segment_id = self._store.open_segment(
                command.project, command.database, command.started_at, command.page
            )
        elif isinstance(command, TouchSegment):
            if self._open_segment_id is not None:
                self._store.touch_segment(
                    self._open_segment_id, command.last_active_at, command.page
                )
        elif isinstance(command, CloseSegment):
            if self._open_segment_id is not None:
                self._store.close_segment(self._open_segment_id, command.ended_at)
                self._open_segment_id = None

    def status(self) -> RunnerStatus:
        now = self._clock()
        open_segment = self._store.current_open_segment()
        current_seconds = (
            (open_segment.last_active_at - open_segment.started_at).total_seconds()
            if open_segment
            else 0.0
        )
        day_start = local_day_start(now, self._local_tz)
        totals = self._store.totals_since(day_start)
        return RunnerStatus(
            project=self._tracker.current_project if open_segment else None,
            is_running=open_segment is not None,
            current_seconds=current_seconds,
            today_seconds=sum(totals.values()),
            unmapped=self._store.unmapped_projects(),
            tracker_state=self._tracker.state,
            resolve_connected=self._last_snapshot.connected,
            resolve_project_open=(
                self._last_snapshot.connected and self._last_snapshot.project_name is not None
            ),
            resolve_app_running=self._resolve_running_source(),
        )
