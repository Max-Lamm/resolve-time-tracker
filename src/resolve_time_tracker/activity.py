"""macOS-Signale: wie lange ist die letzte Eingabe her, welche App ist vorne,
laeuft Resolve ueberhaupt.

Alles hier geht ohne Accessibility-Berechtigung, es werden keine Eingaben
mitgelesen, nur Zeitpunkte und der Prozess-/App-Zustand abgefragt.
"""

from __future__ import annotations

from AppKit import NSWorkspace
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateCombinedSessionState,
)

from .models import RESOLVE_BUNDLE_PREFIX


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


def is_resolve_running() -> bool:
    """Laeuft der Resolve-Prozess ueberhaupt, unabhaengig von der Scripting-API.

    Unterscheidet fuer die Statusanzeige zwei Faelle, die sonst beide als
    "Resolve laeuft nicht" erscheinen wuerden: Resolve ist zu, oder Resolve
    laeuft, aber External Scripting steht in dessen Preferences auf None
    statt Local -- ein haeufiger Erststart-Stolperstein bei Empfaengern, die
    die App zum ersten Mal einrichten.
    """
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        bundle_id = app.bundleIdentifier()
        if bundle_id is not None and bundle_id.startswith(RESOLVE_BUNDLE_PREFIX):
            return True
    return False
