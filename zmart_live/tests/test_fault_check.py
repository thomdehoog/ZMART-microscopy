"""The mutation checker must not mistake a broken runner or subject for evidence."""

import pytest

from zmart_live.tests._fault_check import PytestRun, replace_source


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
