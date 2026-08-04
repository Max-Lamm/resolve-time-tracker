# Resolve Time Tracker

A macOS menubar application that automatically tracks work time per DaVinci Resolve project. It integrates with DaVinci Resolve through its scripting API to monitor active timelines and measure work sessions.

## Prerequisites

This application requires **DaVinci Resolve Studio** (version TBD) to be installed and running on your macOS machine. The free version of DaVinci Resolve does not include Python scripting capabilities, so Resolve Studio is mandatory.

## Smoke Test

To verify that the Resolve Studio integration works on your machine, run the smoke test script with the required environment variables:

```bash
RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
uv run python scripts/smoke_resolve.py
```

The script will print diagnostic information about your Resolve installation, active project, and timeline information. It also tests whether timecode changes are detectable during playback, which determines what monitoring features are available.
