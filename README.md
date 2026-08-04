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

### 2. Everything else happens in the menubar

Resolve usually fills most of the menubar, so the app shows a single colored circle there: 🟢 while tracking, 🟡 while idle or paused, ⚪ when nothing is being tracked (Resolve closed, or open without a project). Click it for the full menu:

- **Toggl-Token einrichten…** — stores your Toggl API token in the macOS keychain. Only needed once.
- **Zuordnen** — one submenu entry per Resolve project you've worked in. Each opens your active Toggl projects (archived ones are filtered out); clicking one maps it, and a checkmark shows the current mapping so you can correct it later. **Neues Toggl-Projekt anlegen…** creates a new Toggl project on the spot and maps it immediately. Projects you never got around to mapping aren't left behind either — see the sync note below.
- **Jetzt synchronisieren** — pushes finished, unsynced segments to Toggl right away, instead of waiting for the automatic 10-minute sync.
- **Pause** — stops tracking until you resume it, independent of Resolve's own state.
- **Beim Login starten** — toggles the launch agent on or off for future logins (via `launchctl enable`/`disable`); the app keeps running either way. Disabled until `make install` has registered the agent once.
- **Log oeffnen** — opens the log file for troubleshooting.

There's only one Toggl workspace to worry about for most setups: the app detects it automatically on first use and remembers it. If your account has more than one workspace, set `default_workspace_id` under `[toggl]` in the config file to pick one explicitly.

A Resolve project that's never been mapped doesn't get skipped on sync anymore: it's pushed to a catch-all Toggl project called **RESOLVE (Auto-Track)** (created automatically if it doesn't exist yet), and that mapping is remembered — the project shows up as mapped to it in the **Zuordnen** menu afterwards, ready to be corrected there if you want it somewhere more specific.

The CLI equivalents (`rtt token`, `rtt map`, `rtt sync`, `rtt status`) still work and are useful for scripting or headless setups (see `uv run rtt --help`), but the menubar is the primary way to use the app day to day.

### 3. Optional: a clickable app icon

`make install` already means you never touch the CLI day to day — the launch agent starts the tracker automatically on login. If you'd rather start it manually sometimes (or don't want the launch agent at all), run:

```bash
make app
```

This assembles `dist/Resolve Time Tracker.app` directly (a `.app` bundle is just a folder with a script and an `Info.plist`, no packaging tool needed — and nothing gets frozen, so it can't drift out of sync with the interpreter DaVinci Resolve's scripting API expects). Drag it into `/Applications` (or leave it in `dist/`) and double-click to start. It's a manual alternative to the launch agent, not a replacement for it: starting it while the launch agent is already running is refused with a native "already running" alert, since two tracking processes writing to the same database at once could create conflicting segments.

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
# Workspace ID to use. Leave at 0 to auto-detect: the app resolves it the
# first time it needs one (as long as your account has exactly one
# workspace) and remembers it. Only set this explicitly if you have more
# than one Toggl workspace.
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
