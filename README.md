# Resolve Time Tracker

A macOS menubar application that automatically tracks work time per DaVinci Resolve project. It integrates with DaVinci Resolve through its scripting API to monitor active timelines and measure work sessions.

## Prerequisites

This application requires **DaVinci Resolve Studio** (version TBD) to be installed and running on your macOS machine. The free version of DaVinci Resolve does not include Python scripting capabilities, so Resolve Studio is mandatory.

## Installation

### For most people: just the app

If you received `Resolve Time Tracker.dmg` (or `.app`) from someone else, see [`docs/RECIPIENT_SETUP.md`](docs/RECIPIENT_SETUP.md) — drag it into `/Applications`, double-click, done. No terminal needed. That guide also covers the one-time Gatekeeper warning that shows up because the app isn't notarized yet.

### For development

Run it straight from the source tree, no build step needed:

```bash
uv run rtt menubar
```

First, verify that Resolve Studio is installed and can be accessed via the Python API:

```bash
RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
PYTHONPATH="$RESOLVE_SCRIPT_API/Modules" \
uv run python scripts/smoke_resolve.py
```

### 2. Everything else happens in the menubar

Resolve usually fills most of the menubar, so the app shows a single colored circle there: 🟢 while tracking, 🟡 while idle or paused, ⚪ when nothing is being tracked (Resolve closed, or open without a project). Click it for the full menu:

- **Toggl-Token einrichten…** — stores your Toggl API token in the macOS keychain. Only needed once.
- **Zuordnen** — one submenu entry per Resolve project you've worked in. Each opens your active Toggl projects (archived ones are filtered out); clicking one maps it, and a checkmark shows the current mapping so you can correct it later. **Neues Toggl-Projekt anlegen…** creates a new Toggl project on the spot and maps it immediately. Projects you never got around to mapping aren't left behind either — see the sync note below.
- **Jetzt synchronisieren** — pushes finished, unsynced segments to Toggl right away, instead of waiting for the automatic 10-minute sync.
- **Pause** — stops tracking until you resume it, independent of Resolve's own state.
- **Beim Login starten** — registers or unregisters the app as a login item (via `SMAppService`); the app keeps running either way, this only affects future logins.
- **Log oeffnen** — opens the log file for troubleshooting.

There's only one Toggl workspace to worry about for most setups: the app detects it automatically on first use and remembers it. If your account has more than one workspace, set `default_workspace_id` under `[toggl]` in the config file to pick one explicitly.

A Resolve project that's never been mapped doesn't get skipped on sync anymore: it's pushed to a catch-all Toggl project called **RESOLVE (Auto-Track)** (created automatically if it doesn't exist yet), and that mapping is remembered — the project shows up as mapped to it in the **Zuordnen** menu afterwards, ready to be corrected there if you want it somewhere more specific.

The CLI equivalents (`rtt token`, `rtt map`, `rtt sync`, `rtt status`) still work and are useful for scripting or headless setups (see `uv run rtt --help`), but the menubar is the primary way to use the app day to day.

### 3. Building the distributable app

```bash
make bundle   # -> dist/Resolve Time Tracker.app
make dmg      # -> dist/Resolve Time Tracker.dmg, for handing to someone else
```

`make bundle` uses PyInstaller (see `packaging/ResolveTimeTracker.spec`) to produce a self-contained `.app` with its own Python interpreter — no venv, no Homebrew, no LaunchAgent involved on the recipient's machine. It's ad-hoc signed (required for arm64 to run at all) but not notarized, hence the Gatekeeper warning covered in `docs/RECIPIENT_SETUP.md`.

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

# Project names to ignore while they have no timeline yet (e.g. Resolve's
# project overview, which reports "Untitled Project"). A real project keeping
# this name is still tracked once it has a timeline.
ignored_projects = ["Untitled Project"]

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

Turn off **Beim Login starten** in the menu if it's on, quit the app (**Beenden**), then move `Resolve Time Tracker.app` to the Trash. The database and config under `~/Library/Application Support/resolve-time-tracker/` and `~/.config/resolve-time-tracker/` are left in place in case you reinstall later; delete them by hand if you want a clean slate.

## Troubleshooting

```bash
make logs
```

streams `~/Library/Logs/resolve-time-tracker.log` in real-time (works whether the app was started from the bundle or via `uv run rtt menubar`), useful for debugging connection issues or monitoring activity. The menu's **Log oeffnen** item opens the same file.
