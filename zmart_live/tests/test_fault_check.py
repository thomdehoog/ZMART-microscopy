"""The mutation checker must not mistake a broken runner or subject for evidence."""

import signal

import pytest

from zmart_live.tests import _fault_check
from zmart_live.tests._fault_check import (
    PytestRun,
    make_interruptions_reach_finally,
    replace_source,
)


def test_only_an_ordinary_test_failure_counts_as_catching_a_fault():
    assert PytestRun(1, "one failed", 1, "test_name").caught_the_fault
    assert not PytestRun(0, "all passed", 0, "").caught_the_fault
    assert not PytestRun(2, "collection error", 1, "").caught_the_fault


def test_collection_and_runner_errors_are_reported_separately():
    assert PytestRun(2, "collection error", 1, "").could_not_run_tests
    assert not PytestRun(1, "one failed", 1, "test_name").could_not_run_tests


def test_a_mutation_checker_cannot_replace_its_subject_with_an_empty_file(tmp_path):
    subject = tmp_path / "subject.py"
    subject.write_text("answer = 42\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="empty file"):
        replace_source(subject, "")

    assert subject.read_text(encoding="utf-8") == "answer = 42\n"


def test_termination_is_turned_into_an_exception_that_reaches_finally():
    before = {
        which: signal.getsignal(which) for which in (signal.SIGINT, signal.SIGTERM)
    }
    restored = False

    with pytest.raises(KeyboardInterrupt, match="mutation campaign interrupted"):
        try:
            with make_interruptions_reach_finally():
                signal.raise_signal(signal.SIGTERM)
        finally:
            restored = True

    assert restored is True
    assert {
        which: signal.getsignal(which) for which in (signal.SIGINT, signal.SIGTERM)
    } == before


def test_post_mutation_verification_refuses_different_source_bytes(
    tmp_path, monkeypatch
):
    subject = tmp_path / "subject.py"
    subject.write_text("answer = 0\n", encoding="utf-8")
    monkeypatch.setattr(
        _fault_check,
        "require_green_subject",
        lambda _repository, _tests, _source: True,
    )

    assert not _fault_check.require_restored_subject(
        tmp_path, tmp_path / "test_subject.py", subject, "answer = 42\n"
    )


def test_post_mutation_verification_reruns_the_clean_subject(
    tmp_path, monkeypatch
):
    subject = tmp_path / "subject.py"
    original = "answer = 42\n"
    subject.write_text(original, encoding="utf-8")
    checked = []

    def green(_repository, _tests, source):
        checked.append(source)
        return True

    monkeypatch.setattr(_fault_check, "require_green_subject", green)
    assert _fault_check.require_restored_subject(
        tmp_path, tmp_path / "test_subject.py", subject, original
    )
    assert checked == [subject]
