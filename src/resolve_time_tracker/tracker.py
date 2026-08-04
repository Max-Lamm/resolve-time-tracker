"""Die Zustandsmaschine. Kein I/O, keine echte Uhr, alles wird hereingereicht."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto

from .models import (
    CloseSegment,
    Command,
    OpenSegment,
    Tick,
    TouchSegment,
    is_active,
)


class TrackerState(Enum):
    NO_RESOLVE = auto()
    ACTIVE = auto()
    PENDING_IDLE = auto()
    PAUSED_IDLE = auto()
    PAUSED_MANUAL = auto()


_OPEN_STATES = (TrackerState.ACTIVE, TrackerState.PENDING_IDLE)


class Tracker:
    def __init__(
        self,
        input_grace_seconds: float = 30.0,
        idle_threshold_seconds: float = 300.0,
    ) -> None:
        self.input_grace_seconds = input_grace_seconds
        self.idle_threshold_seconds = idle_threshold_seconds
        self._state = TrackerState.NO_RESOLVE
        self._current_project: str | None = None
        self._last_active_at: datetime | None = None

    @property
    def state(self) -> TrackerState:
        return self._state

    @property
    def current_project(self) -> str | None:
        return self._current_project

    @property
    def last_active_at(self) -> datetime | None:
        return self._last_active_at

    def tick(self, t: Tick) -> list[Command]:
        if is_active(t, self.input_grace_seconds):
            return self._handle_active(t)
        return self._handle_inactive(t)

    def _handle_active(self, t: Tick) -> list[Command]:
        project = t.snapshot.project_name
        assert project is not None  # von is_active garantiert

        commands: list[Command] = []
        if self._state in _OPEN_STATES and self._current_project == project:
            commands.append(TouchSegment(last_active_at=t.now, page=t.snapshot.page))
        else:
            commands.extend(self._close_open_segment())
            commands.append(
                OpenSegment(
                    project=project,
                    database=t.snapshot.database_name,
                    started_at=t.now,
                    page=t.snapshot.page,
                )
            )
            self._current_project = project

        self._state = TrackerState.ACTIVE
        self._last_active_at = t.now
        return commands

    def _handle_inactive(self, t: Tick) -> list[Command]:
        resolve_gone = not t.snapshot.connected or t.snapshot.project_name is None
        project_changed = (
            t.snapshot.project_name is not None
            and self._current_project is not None
            and t.snapshot.project_name != self._current_project
        )

        # Sofortige Abschluesse: hier gibt es nichts, worauf zu warten waere.
        if self._state in _OPEN_STATES and (resolve_gone or project_changed or t.manual_pause):
            commands = self._close_open_segment()
            if resolve_gone:
                self._state = TrackerState.NO_RESOLVE
                self._current_project = None
            elif t.manual_pause:
                self._state = TrackerState.PAUSED_MANUAL
            else:
                self._state = TrackerState.PAUSED_IDLE
            return commands

        if self._state is TrackerState.ACTIVE:
            assert self._last_active_at is not None
            still_for = (t.now - self._last_active_at).total_seconds()
            if still_for >= self.idle_threshold_seconds:
                commands = self._close_open_segment()
                self._state = TrackerState.PAUSED_IDLE
                return commands
            self._state = TrackerState.PENDING_IDLE
            return []

        if self._state is TrackerState.PENDING_IDLE:
            assert self._last_active_at is not None
            still_for = (t.now - self._last_active_at).total_seconds()
            if still_for >= self.idle_threshold_seconds:
                commands = self._close_open_segment()
                self._state = TrackerState.PAUSED_IDLE
                return commands
            return []

        if resolve_gone:
            self._state = TrackerState.NO_RESOLVE
            self._current_project = None
        return []

    def _close_open_segment(self) -> list[Command]:
        if self._state not in _OPEN_STATES or self._last_active_at is None:
            return []
        return [CloseSegment(ended_at=self._last_active_at)]
