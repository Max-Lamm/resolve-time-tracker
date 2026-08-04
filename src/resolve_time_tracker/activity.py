"""macOS-Signale: wie lange ist die letzte Eingabe her, welche App ist vorne.

Beides geht ohne Accessibility-Berechtigung, es werden keine Eingaben mitgelesen,
nur der Zeitpunkt der letzten Eingabe abgefragt.
"""

from __future__ import annotations

from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)


def seconds_since_input() -> float:
    return float(
        CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateCombinedSessionState, kCGAnyInputEventType
        )
    )


def frontmost_bundle_id() -> str | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    return app.bundleIdentifier()
