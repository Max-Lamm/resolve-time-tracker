"""Manuelle Pruefung der Adapter. Zeigt zehn Sekunden lang, was der Tracker sehen wuerde."""

import time

from resolve_time_tracker.activity import frontmost_bundle_id, seconds_since_input
from resolve_time_tracker.resolve_probe import ResolveProbe


def main() -> None:
    probe = ResolveProbe()
    for _ in range(10):
        bundle = frontmost_bundle_id()
        snapshot = probe.poll()
        print(
            f"idle={seconds_since_input():6.1f}s  vorne={bundle}  "
            f"resolve={snapshot.connected}  projekt={snapshot.project_name}  "
            f"page={snapshot.page}  tc={snapshot.timecode}"
        )
        time.sleep(1)


if __name__ == "__main__":
    main()
