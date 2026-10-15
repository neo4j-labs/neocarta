"""Shared fixtures for the CLI unit tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    """Restore ``os.environ`` after each test.

    ``load_settings`` loads any ``.env`` it finds into ``os.environ``, and
    ``monkeypatch`` cannot undo writes it did not make. Without this, a local
    ``.env`` loaded by one test leaks into every test after it.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
