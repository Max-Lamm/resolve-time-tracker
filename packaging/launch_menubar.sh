#!/bin/bash
# Ausfuehrbare Datei im per `make app` gebauten "Resolve Time Tracker.app"
# (Contents/MacOS/ResolveTimeTracker). Setzt dieselben Resolve-
# Umgebungsvariablen wie das LaunchAgent-Plist, weil ein per
# Finder/Spotlight gestarteter App-Bundle sie nicht von selbst hat.
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"
exec "__PYTHON__" -m resolve_time_tracker menubar
