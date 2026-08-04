import pytest

from resolve_time_tracker.cli import main


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
