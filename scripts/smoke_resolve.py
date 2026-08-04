"""Manuelle Machbarkeitsprüfung. Resolve Studio muss laufen und ein Projekt offen sein.

Aufruf:
    RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
    RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
    PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
    uv run python scripts/smoke_resolve.py
"""

import os
import sys
import time


def main() -> int:
    for var in ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB"):
        if not os.environ.get(var):
            print(f"FEHLT: {var} ist nicht gesetzt")
            return 1

    print(f"Python: {sys.version}")

    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        print(f"FEHLGESCHLAGEN: Import von DaVinciResolveScript: {exc}")
        return 1

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("FEHLGESCHLAGEN: scriptapp('Resolve') gab None zurueck. Laeuft Resolve Studio?")
        return 1

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    print(f"Projekt:     {project.GetName() if project else None}")
    print(f"Datenbank:   {pm.GetCurrentDatabase()}")
    print(f"Page:        {resolve.GetCurrentPage()}")

    timeline = project.GetCurrentTimeline() if project else None
    print(f"Timeline:    {timeline.GetName() if timeline else None}")

    if timeline is None:
        print("HINWEIS: keine Timeline offen, Timecode-Test uebersprungen")
    else:
        first = timeline.GetCurrentTimecode()
        print(f"Timecode 1:  {first}")
        print("Starte jetzt Playback in Resolve, 2 Sekunden Zeit...")
        time.sleep(2)
        second = timeline.GetCurrentTimecode()
        print(f"Timecode 2:  {second}")
        if first == second:
            print("ERGEBNIS: Timecode bewegt sich NICHT. Playback-Signal entfaellt.")
        else:
            print("ERGEBNIS: Timecode bewegt sich. Playback-Signal nutzbar.")

    started = time.perf_counter()
    for _ in range(10):
        resolve.GetCurrentPage()
        pm.GetCurrentProject().GetName()
    per_poll_ms = (time.perf_counter() - started) / 10 * 1000
    print(f"Poll-Kosten: {per_poll_ms:.1f} ms pro Zyklus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
