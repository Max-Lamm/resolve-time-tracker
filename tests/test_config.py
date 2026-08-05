from resolve_time_tracker.config import DEFAULT_CONFIG_TOML, Config, load_config


def test_missing_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)

    assert path.exists()
    assert config == Config()


def test_values_from_file_override_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[tracking]\n"
        "tick_seconds = 10\n"
        "idle_threshold_seconds = 120\n"
        "[sync]\n"
        "auto_push = false\n"
        "[toggl]\n"
        "default_workspace_id = 4711\n"
    )
    config = load_config(path)

    assert config.tick_seconds == 10
    assert config.idle_threshold_seconds == 120
    assert config.auto_push is False
    assert config.default_workspace_id == 4711
    # Nicht genannte Werte bleiben auf dem Default.
    assert config.input_grace_seconds == 30.0


def test_partial_sections_do_not_crash(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[tracking]\ntick_seconds = 3\n")

    assert load_config(path).merge_gap_seconds == 600.0


def test_default_toml_template_parses_into_the_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(DEFAULT_CONFIG_TOML)

    assert load_config(path) == Config()


def test_ignored_projects_defaults_to_the_untitled_placeholder(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)

    assert config.ignored_projects == ("Untitled Project",)


def test_ignored_projects_from_file_override_the_default(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[tracking]\nignored_projects = ["Untitled Project", "Testprojekt"]\n')

    config = load_config(path)

    assert config.ignored_projects == ("Untitled Project", "Testprojekt")
