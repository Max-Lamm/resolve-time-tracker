"""Konfiguration und Token-Ablage.

Der Toggl-Token gehoert in die Keychain, nie in eine Datei.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import keyring

KEYCHAIN_SERVICE = "resolve-time-tracker"
KEYCHAIN_KEY = "toggl_api_token"

DEFAULT_CONFIG_TOML = """# Resolve Time Tracker

[tracking]
# Abstand zwischen zwei Polls in Sekunden.
tick_seconds = 5
# So lange nach der letzten Eingabe gilt Arbeit noch als aktiv.
input_grace_seconds = 30
# So lange muss es still sein, bevor ein Segment geschlossen wird.
idle_threshold_seconds = 300

[sync]
# Segmente mit kleinerer Luecke werden zu einem Toggl-Eintrag verschmolzen.
merge_gap_seconds = 600
auto_push = true

[toggl]
# 0 bedeutet: automatisch ermitteln (nur moeglich, wenn genau ein Workspace
# existiert -- der Tracker merkt sich das Ergebnis danach selbst). Nur bei
# mehreren Workspaces hier explizit setzen.
default_workspace_id = 0
"""


@dataclass(frozen=True)
class Config:
    tick_seconds: float = 5.0
    input_grace_seconds: float = 30.0
    idle_threshold_seconds: float = 300.0
    merge_gap_seconds: float = 600.0
    auto_push: bool = True
    default_workspace_id: int | None = None


def config_path() -> Path:
    return Path.home() / ".config" / "resolve-time-tracker" / "config.toml"


def database_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "resolve-time-tracker" / "tracker.db"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "resolve-time-tracker.log"


def lock_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "resolve-time-tracker" / "tracker.lock"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TOML)

    data = tomllib.loads(path.read_text())
    tracking = data.get("tracking", {})
    sync = data.get("sync", {})
    toggl = data.get("toggl", {})
    workspace_id = toggl.get("default_workspace_id", 0)

    defaults = Config()
    return Config(
        tick_seconds=float(tracking.get("tick_seconds", defaults.tick_seconds)),
        input_grace_seconds=float(
            tracking.get("input_grace_seconds", defaults.input_grace_seconds)
        ),
        idle_threshold_seconds=float(
            tracking.get("idle_threshold_seconds", defaults.idle_threshold_seconds)
        ),
        merge_gap_seconds=float(sync.get("merge_gap_seconds", defaults.merge_gap_seconds)),
        auto_push=bool(sync.get("auto_push", defaults.auto_push)),
        default_workspace_id=workspace_id or None,
    )


def get_token() -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_KEY)


def set_token(token: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_KEY, token)
