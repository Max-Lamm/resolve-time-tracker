from datetime import datetime, timedelta, timezone

import pytest

from resolve_time_tracker.store import Segment, Store
from resolve_time_tracker.syncer import merge_segments, sync
from resolve_time_tracker.toggl import TogglError

START = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def segment(seg_id, project, offset_seconds, duration_seconds, pages=("color",)):
    started = START + timedelta(seconds=offset_seconds)
    ended = started + timedelta(seconds=duration_seconds)
    return Segment(
        id=seg_id,
        resolve_project=project,
        resolve_database="Local",
        started_at=started,
        last_active_at=ended,
        ended_at=ended,
        pages_seen=list(pages),
        note=None,
        toggl_entry_id=None,
        synced_at=None,
    )


class FakeToggl:
    def __init__(self, fail_times=0):
        self.calls = []
        self._fail_times = fail_times
        self._next_id = 1000

    def create_time_entry(self, workspace_id, project_id, description, start, duration_seconds, tags):
        if self._fail_times > 0:
            self._fail_times -= 1
            raise TogglError("simulierter Fehler")
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "description": description,
                "start": start,
                "duration_seconds": duration_seconds,
                "tags": tags,
            }
        )
        self._next_id += 1
        return self._next_id


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "tracker.db")
    yield s
    s.close()


def add(store, project, offset_seconds, duration_seconds, page="color"):
    started = START + timedelta(seconds=offset_seconds)
    seg_id = store.open_segment(project, "Local", started, page)
    ended = started + timedelta(seconds=duration_seconds)
    store.touch_segment(seg_id, ended, page)
    store.close_segment(seg_id, ended)
    return seg_id


def test_close_segments_within_the_gap_are_merged():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_A", 900, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert len(groups) == 1
    assert groups[0].segment_ids == [1, 2]
    assert groups[0].started_at == START
    # 300 s Luecke zaehlen nicht mit.
    assert groups[0].duration_seconds == 1200


def test_segments_beyond_the_gap_stay_separate():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_A", 5000, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert [g.segment_ids for g in groups] == [[1], [2]]


def test_different_projects_are_never_merged():
    segments = [segment(1, "Kunde_A", 0, 600), segment(2, "Kunde_B", 620, 600)]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert len(groups) == 2
    assert {g.project for g in groups} == {"Kunde_A", "Kunde_B"}


def test_merged_group_collects_the_union_of_pages():
    segments = [
        segment(1, "Kunde_A", 0, 600, pages=("color",)),
        segment(2, "Kunde_A", 700, 600, pages=("edit", "color")),
    ]

    groups = merge_segments(segments, merge_gap_seconds=600)

    assert sorted(groups[0].tags) == ["color", "edit"]


def test_sync_pushes_mapped_projects_and_marks_them(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.pushed == 1
    assert client.calls[0]["workspace_id"] == 111
    assert client.calls[0]["project_id"] == 222
    assert client.calls[0]["duration_seconds"] == 600
    assert store.unsynced_segments(closed_before=START + timedelta(days=1)) == []


def test_sync_skips_unmapped_projects_without_losing_them(store):
    add(store, "Kunde_Unbekannt", 0, 600)
    client = FakeToggl()

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.pushed == 0
    assert result.skipped_unmapped == ["Kunde_Unbekannt"]
    assert len(store.unsynced_segments(closed_before=START + timedelta(days=1))) == 1


def test_running_sync_twice_creates_no_duplicates(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)
    sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert len(client.calls) == 1


def test_a_failed_push_leaves_the_segment_in_the_queue(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl(fail_times=1)

    result = sync(store, client, now=START + timedelta(days=1), merge_gap_seconds=600)

    assert result.failed == 1
    assert len(store.unsynced_segments(closed_before=START + timedelta(days=1))) == 1


def test_recent_segments_are_held_back_until_the_gap_has_passed(store):
    add(store, "Kunde_A", 0, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    # Nur 60 s nach Segmentende: koennte noch weitergearbeitet werden, also nicht pushen.
    result = sync(store, client, now=START + timedelta(seconds=660), merge_gap_seconds=600)

    assert result.pushed == 0
    assert client.calls == []


def test_segments_within_merge_gap_are_not_fragmented_if_second_segment_is_recent(store):
    """Two segments of same project, 300s apart (within 600s merge gap).

    Scenario: A (0-600s), B (900-1500s), merge_gap=600s.
    Sync at 1600s (only 100s after B closes).
    Expected: 0 pushes (entire group deferred until settled)
    Later sync at 2100s: 1 push with both merged (600s after B ends)

    Reproduces the fragmentation bug where cutoff filtering before merge
    would split A and B into separate pushes.
    """
    add(store, "Kunde_A", 0, 600)
    add(store, "Kunde_A", 900, 600)
    store.set_mapping("Kunde_A", 111, 222)
    client = FakeToggl()

    # First sync: 100s after second segment closes, merge_gap=600s
    # Group should be deferred, not split
    result = sync(store, client, now=START + timedelta(seconds=1600), merge_gap_seconds=600)
    assert result.pushed == 0
    assert client.calls == []
    assert len(store.unsynced_segments(closed_before=START + timedelta(seconds=1600))) == 2

    # Second sync: 600s after second segment closes, now past the gap
    result = sync(store, client, now=START + timedelta(seconds=2100), merge_gap_seconds=600)
    assert result.pushed == 1
    assert len(client.calls) == 1
    # Verify the merged entry has both segments' duration
    assert client.calls[0]["duration_seconds"] == 1200
    assert len(store.unsynced_segments(closed_before=START + timedelta(seconds=2100))) == 0
