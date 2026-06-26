"""Test setup: put the source root on sys.path and register the mock driver.

The mock is a test-only integration, so it is wired into the registry here --
production registry.py never imports it.
"""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _TESTS_DIR.parents[1]  # microscopes/
for _path in (str(_SRC_ROOT), str(_TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import mock_driver  # noqa: E402

mock_driver.register_mock()
