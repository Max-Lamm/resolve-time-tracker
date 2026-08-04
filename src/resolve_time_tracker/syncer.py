"""Verschmilzt geschlossene Segmente und legt sie in Toggl an."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .store import Segment, Store
from .toggl import TogglError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SegmentGroup:
    project: str
    segment_ids: list[int]
    started_at: datetime
    duration_seconds: int
    tags: list[str]


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
    )


def sync(store: Store, client, now: datetime, merge_gap_seconds: float) -> SyncResult:
    result = SyncResult()
    cutoff = now - timedelta(seconds=merge_gap_seconds)
    pending = store.unsynced_segments(closed_before=cutoff)

    for group in merge_segments(pending, merge_gap_seconds):
        mapping = store.get_mapping(group.project)
        if mapping is None:
            if group.project not in result.skipped_unmapped:
                result.skipped_unmapped.append(group.project)
            continue

        try:
            entry_id = client.create_time_entry(
                workspace_id=mapping.toggl_workspace_id,
                project_id=mapping.toggl_project_id,
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
