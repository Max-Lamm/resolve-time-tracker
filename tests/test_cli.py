import subprocess

import pytest

from resolve_time_tracker.cli import main
from resolve_time_tracker.singleton import AlreadyRunning, acquire_lock, release_lock


def test_unknown_command_exits_with_error():
    with pytest.raises(SystemExit):
        main(["gibtsnicht"])


def test_no_command_prints_help_and_returns_nonzero(capsys):
    assert main([]) != 0
    assert "daemon" in capsys.readouterr().out


def test_status_runs_without_resolve(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("resolve_time_tracker.config.database_path", lambda: tmp_path / "t.db")
    monkeypatch.setattr("resolve_time_tracker.config.config_path", lambda: tmp_path / "c.toml")

    assert main(["status"]) == 0
    assert "Heute" in capsys.readouterr().out


def test_daemon_refuses_a_second_instance(tmp_path, monkeypatch, capsys):
    """Ein zweiter `rtt daemon`/`rtt menubar`-Prozess darf nicht gegen dieselbe

    Datenbank schreiben wie ein bereits laufender (z. B. LaunchAgent im
    Hintergrund) -- er muss abbrechen, bevor er ueberhaupt den Store oeffnet.
    """
    lock_path = tmp_path / "tracker.lock"
    monkeypatch.setattr("resolve_time_tracker.config.lock_path", lambda: lock_path)
    monkeypatch.setattr("resolve_time_tracker.config.database_path", lambda: tmp_path / "t.db")
    monkeypatch.setattr("resolve_time_tracker.config.config_path", lambda: tmp_path / "c.toml")

    held = acquire_lock(lock_path)
    try:
        assert main(["daemon"]) == 1
        assert "laeuft bereits" in capsys.readouterr().out
        # Store darf gar nicht erst angelegt worden sein.
        assert not (tmp_path / "t.db").exists()
    finally:
        release_lock(held)


def test_menubar_refuses_a_second_instance(tmp_path, monkeypatch):
    lock_path = tmp_path / "tracker.lock"
    monkeypatch.setattr("resolve_time_tracker.config.lock_path", lambda: lock_path)
    alerts = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: alerts.append(a))

    held = acquire_lock(lock_path)
    try:
        assert main(["menubar"]) == 1
        assert alerts  # der native "laeuft bereits"-Hinweis wurde ausgeloest
    finally:
        release_lock(held)


def test_menubar_keeps_the_lock_held_for_run_menubars_whole_lifetime(tmp_path, monkeypatch):
    """Regression test for a real bug caught in live testing: acquire_lock()'s

    return value must be kept alive for the whole process, otherwise the
    garbage collector closes the handle right after acquiring it and the
    flock is silently gone again almost immediately -- a second real process
    could then acquire the "same" lock straight away. Verified live: an
    LaunchAgent instance and a manually started app both ran as full
    duplicate trackers against the same database before this fix.
    """
    lock_path = tmp_path / "tracker.lock"
    monkeypatch.setattr("resolve_time_tracker.config.lock_path", lambda: lock_path)

    def fake_run_menubar():
        # Waehrend cmd_menubar "laeuft" (dieser Aufruf steckt mitten in
        # dessen Aufrufkette) muss ein zweiter Versuch, dasselbe Lock zu
        # bekommen, fehlschlagen -- genau wie bei einem echten zweiten Prozess.
        with pytest.raises(AlreadyRunning):
            acquire_lock(lock_path)
        return 0

    monkeypatch.setattr("resolve_time_tracker.menubar.run_menubar", fake_run_menubar)

    assert main(["menubar"]) == 0


def test_daemon_keeps_the_lock_held_during_the_tick_loop(tmp_path, monkeypatch):
    """Dieselbe Regression wie oben, fuer den `daemon`-Einstiegspunkt."""
    lock_path = tmp_path / "tracker.lock"
    monkeypatch.setattr("resolve_time_tracker.config.lock_path", lambda: lock_path)
    monkeypatch.setattr("resolve_time_tracker.config.database_path", lambda: tmp_path / "t.db")
    monkeypatch.setattr("resolve_time_tracker.config.config_path", lambda: tmp_path / "c.toml")

    def fake_sleep(_seconds):
        with pytest.raises(AlreadyRunning):
            acquire_lock(lock_path)
        raise KeyboardInterrupt  # sauberer Ausstieg, wie bei einem echten Strg-C

    monkeypatch.setattr("resolve_time_tracker.cli.time.sleep", fake_sleep)

    assert main(["daemon"]) == 0
