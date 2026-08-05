"""Diagnose: was liefert die Resolve-API in der Projektuebersicht vs. bei geladenem Projekt.

Einmaliger Snapshot, kein Loop. Resolve Studio muss laufen.

Aufruf:
    RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
    RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
    PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
    uv run python scripts/probe_diagnostics.py
"""

import os
import sys


def main() -> int:
    for var in ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB"):
        if not os.environ.get(var):
            print(f"FEHLT: {var} ist nicht gesetzt")
            return 1

    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        print(f"FEHLGESCHLAGEN: Import von DaVinciResolveScript: {exc}")
        return 1

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("FEHLGESCHLAGEN: scriptapp('Resolve') gab None zurueck. Laeuft Resolve Studio?")
        return 1

    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject()

    print(f"GetCurrentPage():          {resolve.GetCurrentPage()!r}")
    print(f"GetCurrentProject():       {'<Objekt>' if project else None}")

    if project is None:
        print("Kein Projektobjekt, kein weiterer Vergleich moeglich.")
        return 0

    print(f"project.GetName():         {project.GetName()!r}")
    try:
        count = project.GetTimelineCount()
    except Exception as exc:
        count = f"FEHLER: {exc}"
    print(f"project.GetTimelineCount():{count!r}")

    timeline = project.GetCurrentTimeline()
    timeline_repr = timeline.GetName() if timeline else None
    print(f"project.GetCurrentTimeline():{timeline_repr!r}")

    database = manager.GetCurrentDatabase()
    print(f"manager.GetCurrentDatabase():{database!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
