"""Verschmilzt geschlossene Segmente und legt sie in Toggl an."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Config
from .store import Segment, Store
from .toggl import TogglError
from .workspace import resolve_default_project_id, resolve_workspace_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentGroup:
    project: str
    segment_ids: list[int]
    started_at: datetime
    duration_seconds: int
    tags: list[str]
    ended_at: datetime


@dataclass
class SyncResult:
    pushed: int = 0
    skipped_unmapped: list[str] = field(default_factory=list)
    failed: int = 0


def merge_segments(segments: list[Segment], merge_gap_seconds: float) -> list[SegmentGroup]:
    """Segmente desselben Projekts mit kleiner Luecke werden zu einem Eintrag."""
    gap = timedelta(seconds=merge_gap_seconds)
    buckets: dict[str, list[Segment]] = {}
    for seg in sorted(segments, key=lambda s: s.started_at):
        buckets.setdefault(seg.resolve_project, []).append(seg)

    groups: list[SegmentGroup] = []
    for project, project_segments in buckets.items():
        run: list[Segment] = []
        for seg in project_segments:
            if run and seg.started_at - (run[-1].ended_at or run[-1].last_active_at) > gap:
                groups.append(_to_group(project, run))
                run = []
            run.append(seg)
        if run:
            groups.append(_to_group(project, run))

    return sorted(groups, key=lambda g: g.started_at)


def _to_group(project: str, run: list[Segment]) -> SegmentGroup:
    tags: list[str] = []
    for seg in run:
        for page in seg.pages_seen:
            if page not in tags:
                tags.append(page)
    return SegmentGroup(
        project=project,
        segment_ids=[seg.id for seg in run],
        started_at=run[0].started_at,
        # Nur echte Arbeitszeit, die Luecken zwischen den Segmenten sind Pausen.
        duration_seconds=int(sum(seg.duration_seconds for seg in run)),
        tags=tags,
        ended_at=run[-1].ended_at,
    )


def sync(store: Store, client, now: datetime, merge_gap_seconds: float, config: Config) -> SyncResult:
    result = SyncResult()
    # Fetch all unsynced segments closed so far, don't filter by cutoff yet
    pending = store.unsynced_segments(closed_before=now)
    gap = timedelta(seconds=merge_gap_seconds)

    # Only one segment can be open across the whole app at a time. If it exists
    # and could still merge into a settled group of the same project, that
    # group must be held back too -- otherwise it gets pushed alone now and the
    # open segment (once closed) gets pushed again as a second, separate entry.
    open_segment = store.current_open_segment()

    for group in merge_segments(pending, merge_gap_seconds):
        # Only push if the group has settled (last segment ended long enough ago)
        settle_time = now - group.ended_at
        if settle_time < gap:
            # Group hasn't settled yet, hold it for the next sync run
            continue

        if (
            open_segment is not None
            and open_segment.resolve_project == group.project
            and open_segment.started_at - group.ended_at <= gap
        ):
            # An open segment for the same project could still merge with this
            # group once it closes. Hold the group back rather than fragment it.
            continue

        mapping = store.get_mapping(group.project)
        if mapping is not None:
            workspace_id = mapping.toggl_workspace_id
            project_id = mapping.toggl_project_id
        else:
            # Noch keine Zuordnung -- statt die Zeit stillschweigend liegen zu
            # lassen, faellt sie auf ein Default-Projekt zurueck. Nur wenn
            # nicht mal der Workspace sicher aufloesbar ist (mehrere
            # Workspaces ohne Override), bleibt der alte skipped_unmapped-Pfad.
            try:
                workspace_id = resolve_workspace_id(store, client, config)
                project_id = resolve_default_project_id(store, client, workspace_id)
            except TogglError:
                log.exception(
                    "Workspace/Default-Projekt fuer %s nicht aufloesbar", group.project
                )
                if group.project not in result.skipped_unmapped:
                    result.skipped_unmapped.append(group.project)
                continue
            store.set_mapping(group.project, workspace_id, project_id)

        try:
            entry_id = client.create_time_entry(
                workspace_id=workspace_id,
                project_id=project_id,
                description=group.project,
                start=group.started_at,
                duration_seconds=group.duration_seconds,
                tags=group.tags,
            )
        except TogglError:
            log.exception("Push fuer %s gescheitert, Segmente bleiben in der Warteschlange", group.project)
            result.failed += 1
            continue

        store.mark_synced(group.segment_ids, toggl_entry_id=entry_id, synced_at=now)
        result.pushed += 1

    return result
