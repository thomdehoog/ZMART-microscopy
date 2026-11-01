"""A name the page sends is checked before it becomes a folder.

The kind of scan (``acquisition_type``) arrives from the page and is joined
onto the run folder. Starting a scan removes what an earlier scan of that kind
left behind, so a kind that was really an absolute path, or one with ``..``
in it, deleted pictures outside the run: the review reproduced it with
``POST /api/scan {"acquisition_type": "<any folder>"}``. These tests hold the
bridge to refusing such a name before anything is touched.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import pytest

from . import ledgers, pictures, scan, state

NAMES_THAT_LEAVE_THE_RUN = ["..", "../elsewhere", "..\\elsewhere", "a/b", "", "overview "]


@pytest.fixture()
def run_and_a_bystander(tmp_path, monkeypatch):
    """A run folder, and beside it someone else's images that must survive."""
    run = tmp_path / "target-acquisition_000001"
    run.mkdir()
    bystander = tmp_path / "someone-elses-data"
    (bystander / "view").mkdir(parents=True)
    (bystander / "field_1.ome.zarr").mkdir()
    (bystander / "positions" / "x" / "field_2.ome.zarr").mkdir(parents=True)
    monkeypatch.setattr(state, "run", run)
    monkeypatch.setattr(state, "records", {})
    monkeypatch.setitem(ledgers.scan, "running", False)
    return run, bystander


def everything_under(folder):
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))


def test_a_scan_named_by_an_absolute_folder_is_refused_and_deletes_nothing(run_and_a_bystander):
    run, bystander = run_and_a_bystander
    before = everything_under(bystander)
    with pytest.raises(ValueError, match="acquisition_type"):
        scan.start_scan({"acquisition_type": str(bystander), "positions": []})
    assert everything_under(bystander) == before
    assert ledgers.scan["running"] is False


@pytest.mark.parametrize("name", NAMES_THAT_LEAVE_THE_RUN)
def test_a_scan_named_with_a_path_is_refused(run_and_a_bystander, name):
    with pytest.raises(ValueError, match="acquisition_type"):
        scan.start_scan({"acquisition_type": name, "positions": []})
    assert state.records == {}


@pytest.mark.parametrize("name", [*NAMES_THAT_LEAVE_THE_RUN, "C:\\data", "/data"])
def test_the_pictures_of_a_kind_are_only_ever_inside_the_run(run_and_a_bystander, name):
    with pytest.raises(ValueError, match="acquisition_type"):
        pictures.view_of(name)
    with pytest.raises(ValueError, match="acquisition_type"):
        pictures.replace_the_acquisition(name)


def test_an_ordinary_kind_is_still_a_folder_in_the_run(run_and_a_bystander):
    run, _ = run_and_a_bystander
    assert pictures.view_of("overview") == run / "overview" / pictures.VIEW
    assert pictures.view_of("focussing") == run / "focussing" / pictures.VIEW
