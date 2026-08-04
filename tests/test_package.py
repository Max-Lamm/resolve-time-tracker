def test_package_importable():
    import resolve_time_tracker

    assert resolve_time_tracker.__name__ == "resolve_time_tracker"
