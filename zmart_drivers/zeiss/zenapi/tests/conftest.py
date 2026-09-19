"""Shared pytest setup: import bootstrap + a fake-client fixture."""

import sys
from pathlib import Path

import pytest

# Add the vendor dir (parent of zenapi) so `import zenapi` works regardless of
# where pytest is invoked from, and the repo root so `zmart_controller` does.
# parents: [0]=tests [1]=zenapi [2]=zeiss [3]=zmart_drivers [4]=repo root.
_ZEISS_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
for entry in (_ZEISS_DIR, _REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# Add the helpers dir so `import mock_zen_api` works.
_HELPERS = Path(__file__).resolve().parent / "helpers"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))


def pytest_report_header(config):
    """Environment context at the top of every run (never breaks a run)."""
    try:
        from _diagnostics import header_lines

        return header_lines()
    except Exception as exc:  # pragma: no cover - diagnostics must not fail a run
        return [f"zenapi context: diagnostics unavailable ({exc!r})"]


@pytest.fixture
def fake_client():
    """A real ZenClient over the fake ZEN API. Yields ``(client, scope)``."""
    from mock_zen_api import build_fake_client

    client, scope = build_fake_client()
    try:
        yield client, scope
    finally:
        client.close()
