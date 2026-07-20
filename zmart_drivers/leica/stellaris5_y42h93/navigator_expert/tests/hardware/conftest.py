"""Shared pytest fixtures for the tests/hardware validator suite."""

from __future__ import annotations

import os

import pytest
from navigator_expert.config import profiles


@pytest.fixture(autouse=True)
def _restore_mock_globals():
    """Restore reader profiles and mock-only environment paths after each test.

    ``hermetic_mock_machine_root()`` (tests/helpers/limits_fixtures.py)
    redirects ``profiles.LOG_READER`` to nonexistent paths under a throwaway
    root, so a ``--mock`` run's log leg reads back "absent" -- not whatever
    real LAS X log history happens to sit on the machine running the suite.
    Several validators also reassign ``profiles.STATE_READERS`` from CLI
    args. Both are module-level globals mutated in place; without this, a
    mock run in one test leaks its redirected/reassigned profile or hermetic
    ProgramData/AppData path into whichever test runs next.
    """
    original_log_reader = profiles.LOG_READER
    original_state_readers = profiles.STATE_READERS
    original_env = {name: os.environ.get(name) for name in ("ZMART_MICROSCOPY_ROOT", "APPDATA")}
    try:
        yield
    finally:
        profiles.LOG_READER = original_log_reader
        profiles.STATE_READERS = original_state_readers
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
