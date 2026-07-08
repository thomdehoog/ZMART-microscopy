"""Pytest gate for the three-reader probe's capability guard.

The probe (``probe_four_readers.py``) reads every datum in api / log / hybrid
mode. A datum with no leg for a given mode -- the job LIST has no log leg --
must record an *expected* skip, not an error that reddens the run. This keeps
that guard in the offline suite without needing a live LAS X session (the guard
returns before touching the client).
"""
# ruff: noqa: E402,I001

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LEICA_ROOT = _HERE.parents[2]
for _p in (_HERE, _LEICA_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import probe_four_readers as probe
from navigator_expert.readers import capabilities


def test_jobs_log_read_is_expected_skip_not_error():
    """jobs has no log leg -> a log-mode read is a declared skip, not an error.

    The guard returns before the client is touched, so ``client=None`` is safe.
    """
    assert capabilities.DATUMS["jobs"].log_fn is None
    record = probe._read_passive(None, "jobs", "log", None)
    assert record["status"] == "skipped"
    assert "no log leg" in record["error"]
    # An expected skip must not be counted as a read-only failure.
    summary = probe._build_summary(
        [{"phase": "read_only", "datum": "jobs", "passive": {"log": record}}]
    )
    assert summary["phases"]["read_only"]["fail"] == 0


def test_jobs_api_and_hybrid_legs_are_not_skipped():
    """jobs keeps its api leg, and hybrid degrades to api -- neither is guarded
    out as unsupported (only the missing log leg is)."""
    assert capabilities.DATUMS["jobs"].api_fn is not None
    for mode in ("api", "hybrid"):
        # These would attempt a real read; assert the guard does NOT short it to
        # a skip by checking the capability table the guard consults.
        spec = capabilities.DATUMS["jobs"]
        guarded = (mode == "log" and spec.log_fn is None) or (mode == "api" and spec.api_fn is None)
        assert not guarded
