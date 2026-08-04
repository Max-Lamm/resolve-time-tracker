# Resolve Time Tracker

A macOS menubar application that automatically tracks work time per DaVinci Resolve project. It integrates with DaVinci Resolve through its scripting API to monitor active timelines and measure work sessions.

## Prerequisites

This application requires **DaVinci Resolve Studio** (version TBD) to be installed and running on your macOS machine. The free version of DaVinci Resolve does not include Python scripting capabilities, so Resolve Studio is mandatory.

## Installation

### 1. Install and configure

First, verify that Resolve Studio is installed and can be accessed via the Python API:

```bash
RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
uv run python scripts/smoke_resolve.py
```

Then install the menubar app as a launch agent:

```bash
make install
```

This will start the app automatically on login and register it with launchd.

### 2. Configure Toggl integration

Before syncing time entries to Toggl, you must obtain and store a Toggl API token:

```bash
uv run rtt token
```

This will prompt you for your Toggl API token and store it securely in the macOS keychain.

### 3. Map Resolve projects to Toggl workspaces and projects

Create a mapping between your Resolve projects and Toggl projects:

```bash
uv run rtt map
```

This interactive command walks you through selecting which Toggl project and workspace each Resolve project should map to.

## Data Storage

Time tracking data and configuration are stored in:

- **Database:** `~/Library/Application Support/resolve-time-tracker/tracker.db`
- **Config:** `~/.config/resolve-time-tracker/config.toml`
- **Logs:** `~/Library/Logs/resolve-time-tracker.log`

## Configuration

The application stores configuration in `~/.config/resolve-time-tracker/config.toml`. This file is created automatically on first run with sensible defaults. You can edit it to adjust behavior:

```toml
[tracking]
# How often to poll for active timeline changes (seconds)
tick_seconds = 5

# Duration after last user input that counts as still active (seconds)
input_grace_seconds = 30

# Duration of inactivity required to close a segment (seconds)
idle_threshold_seconds = 300

[sync]
# Gap between segments small enough to merge into one Toggl entry (seconds)
merge_gap_seconds = 600
auto_push = true

[toggl]
# Default workspace ID (0 = not set)
default_workspace_id = 0
```

To adjust idle behavior, modify `idle_threshold_seconds` (how long inactivity must persist before closing a segment) and `input_grace_seconds` (how long after user input is still considered active work).

## Important Notes

- Time tracking is conservative: when in doubt, the application underestimates rather than overestimates tracked time. Segments are closed when inactivity is detected, and switching between applications briefly pauses tracking.

## Uninstallation

To remove the launch agent and stop automatic startup:

```bash
make uninstall
```

This removes the launchd entry but preserves the database and configuration for potential re-installation later.

## Troubleshooting

To view logs from the running application:

```bash
make logs
```

This streams the application log in real-time, useful for debugging connection issues or monitoring activity.
