import pytest

from resolve_time_tracker.singleton import AlreadyRunning, acquire_lock, release_lock


def test_second_acquire_fails_while_the_first_is_held(tmp_path):
    path = tmp_path / "tracker.lock"
    first = acquire_lock(path)
    try:
        with pytest.raises(AlreadyRunning):
            acquire_lock(path)
    finally:
        release_lock(first)


def test_lock_is_available_again_after_release(tmp_path):
    path = tmp_path / "tracker.lock"
    first = acquire_lock(path)
    release_lock(first)

    second = acquire_lock(path)
    release_lock(second)


def test_lock_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "tracker.lock"
    handle = acquire_lock(path)
    try:
        assert path.exists()
    finally:
        release_lock(handle)
