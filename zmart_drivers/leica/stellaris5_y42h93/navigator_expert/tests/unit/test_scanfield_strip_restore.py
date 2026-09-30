"""Offline strip/restore smoke test for Leica scan-field bundles."""

from __future__ import annotations

import shutil

import pytest
from navigator_expert.scanfields import strip_restore
from navigator_expert.scanfields.files import (
    STRIPPED_LRP,
    STRIPPED_RGN,
    STRIPPED_XML,
    TEMPLATE_BASE,
    TEMPLATE_LRP,
    TEMPLATE_RGN,
    TEMPLATE_XML,
)


def _install_template_bundle(source_dir, templates_dir):
    """Copy one source LRP/XML/RGN bundle to the driver's canonical names."""
    source_xml = next(source_dir.glob("*.xml"))
    base = source_xml.stem
    for suffix, target_name in (
        (".xml", TEMPLATE_XML),
        (".rgn", TEMPLATE_RGN),
        (".lrp", TEMPLATE_LRP),
    ):
        shutil.copy2(source_dir / f"{base}{suffix}", templates_dir / target_name)


class _Scripted:
    """Callable that pops one scripted result per call.

    Entries may be plain result values or zero-arg callables (used to
    simulate what "LAS X" writes to disk during that save/load).
    """

    def __init__(self, script):
        self.calls = 0
        self._script = list(script)

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        step = self._script.pop(0) if self._script else {"success": True}
        return step() if callable(step) else step


@pytest.fixture
def bundle_dir(general_workflow_data):
    """Writable templates dir populated with the canonical bundle."""
    _install_template_bundle(general_workflow_data, general_workflow_data)
    return general_workflow_data


@pytest.fixture
def patch_lasx(bundle_dir, monkeypatch):
    """Point strip_restore at bundle_dir with scriptable save/load fakes.

    Returns a function taking save/load scripts; defaults are all-success.
    Also neutralises the 15 s post-failure lock wait so failure-ladder
    tests stay fast (the wait is a live-LAS-X file-lock concern).
    """

    def _apply(save_script=(), load_script=()):
        save = _Scripted(save_script)
        load = _Scripted(load_script)
        monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: bundle_dir)
        monkeypatch.setattr(strip_restore, "save_experiment", save)
        monkeypatch.setattr(strip_restore, "load_experiment", load)
        monkeypatch.setattr(strip_restore, "_wait_file_stable", lambda *a, **k: True)
        return save, load

    return _apply


def test_strip_restore_round_trip_preserves_offline_workflow(
    general_workflow_data,
    monkeypatch,
):
    """Strip and restore a real workflow bundle without LAS X or hardware."""
    templates_dir = general_workflow_data
    _install_template_bundle(general_workflow_data, templates_dir)

    monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: templates_dir)
    monkeypatch.setattr(
        strip_restore,
        "save_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )
    monkeypatch.setattr(
        strip_restore,
        "load_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP
    original_lrp = lrp_path.read_bytes()
    original_counts = strip_restore._count_objects(xml_path, rgn_path)

    assert original_counts[1] > 0

    strip_result = strip_restore.strip_template(object(), save_timeout=1)

    assert strip_result is not None
    assert strip_result["success"] is True
    assert (templates_dir / STRIPPED_XML).is_file()
    assert (templates_dir / STRIPPED_RGN).is_file()
    assert (templates_dir / STRIPPED_LRP).is_file()
    assert strip_restore._count_objects(
        templates_dir / STRIPPED_XML,
        templates_dir / STRIPPED_RGN,
    ) == (0, 0, 0)

    restore_result = strip_restore.restore_template(object())

    assert restore_result is not None
    assert restore_result["success"] is True
    assert strip_restore._count_objects(xml_path, rgn_path) == original_counts
    assert lrp_path.read_bytes() == original_lrp
    assert not (templates_dir / STRIPPED_XML).exists()
    assert not (templates_dir / STRIPPED_RGN).exists()
    assert not (templates_dir / STRIPPED_LRP).exists()


def test_strip_template_in_place_has_no_sidecar_or_restore(
    general_workflow_data,
    monkeypatch,
):
    """The non-return strip keeps PythonInspect canonical and removes sidecars."""
    templates_dir = general_workflow_data
    _install_template_bundle(general_workflow_data, templates_dir)

    monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: templates_dir)
    monkeypatch.setattr(
        strip_restore,
        "save_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )
    monkeypatch.setattr(
        strip_restore,
        "load_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )

    # Stale sidecars from a previous reversible strip must not define
    # state after the in-place routine takes ownership of the canonical
    # template.
    for name in (STRIPPED_XML, STRIPPED_RGN, STRIPPED_LRP):
        (templates_dir / name).write_text("stale", encoding="utf-8")

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    original_counts = strip_restore._count_objects(xml_path, rgn_path)
    assert original_counts[1] > 0

    result = strip_restore.strip_template_in_place(object(), save_timeout=1)

    assert result is not None
    assert result["success"] is True
    assert strip_restore._count_objects(xml_path, rgn_path) == (0, 0, 0)
    assert (templates_dir / TEMPLATE_LRP).is_file()
    assert not (templates_dir / STRIPPED_XML).exists()
    assert not (templates_dir / STRIPPED_RGN).exists()
    assert not (templates_dir / STRIPPED_LRP).exists()


# =============================================================================
# _strip_xml
# =============================================================================


def test_strip_xml_replaces_scanfields_block(tmp_path):
    src = tmp_path / "src.xml"
    dst = tmp_path / "dst.xml"
    src.write_text(
        "<Root><Before />"
        '<ScanFields><ScanFieldData X="1" /><ScanFieldData X="2" /></ScanFields>'
        "<After /></Root>",
        encoding="utf-8",
    )
    strip_restore._strip_xml(src, dst)
    text = dst.read_text(encoding="utf-8")
    assert "<ScanFields />" in text
    assert "ScanFieldData" not in text
    assert "<Before />" in text and "<After />" in text  # surroundings intact


# =============================================================================
# strip_template failure ladder
# =============================================================================


def test_strip_template_without_templates_dir_returns_none(monkeypatch):
    monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: None)
    assert strip_restore.strip_template(object()) is None


def test_strip_template_initial_save_failure_aborts_before_stripping(bundle_dir, patch_lasx):
    patch_lasx(save_script=[None])
    assert strip_restore.strip_template(object(), save_timeout=1) is None
    # Nothing was stripped: no sidecar files appeared.
    assert not (bundle_dir / STRIPPED_XML).exists()
    assert not (bundle_dir / STRIPPED_RGN).exists()


def test_strip_template_load_failure_returns_none(bundle_dir, patch_lasx):
    patch_lasx(load_script=[None])
    assert strip_restore.strip_template(object(), save_timeout=1) is None


def test_strip_template_confirm_save_failure_returns_none(bundle_dir, patch_lasx):
    save, _ = patch_lasx(save_script=[{"success": True}, None])
    assert strip_restore.strip_template(object(), save_timeout=1) is None
    assert save.calls == 2  # initial save + failed confirm-save


def test_strip_template_residual_objects_after_confirm_save_returns_none(bundle_dir, patch_lasx):
    # LAS X re-saving the "stripped" template with objects still in it must
    # fail the strip, not report an editable template. The bundle's objects
    # live in the RGN (region items), so the fake re-save restores those.
    original_rgn = (bundle_dir / TEMPLATE_RGN).read_text(encoding="utf-8")

    def lasx_rewrites_objects():
        (bundle_dir / STRIPPED_RGN).write_text(original_rgn, encoding="utf-8")
        return {"success": True}

    patch_lasx(save_script=[{"success": True}, lasx_rewrites_objects])
    assert strip_restore.strip_template(object(), save_timeout=1) is None


def test_strip_template_warns_when_xml_strip_is_incomplete(bundle_dir, patch_lasx, caplog):
    # A ScanFields block without its closing tag cannot be text-stripped;
    # the incomplete strip is surfaced and the residual-object check then
    # fails the operation.
    xml_path = bundle_dir / TEMPLATE_XML
    text = xml_path.read_text(encoding="utf-8") + '<ScanFields><ScanFieldData X="1" />'
    xml_path.write_text(text, encoding="utf-8")
    patch_lasx()
    with caplog.at_level("WARNING", logger="navigator_expert.scanfields.strip_restore"):
        assert strip_restore.strip_template(object(), save_timeout=1) is None
    assert any("Strip incomplete" in m for m in caplog.messages)


# =============================================================================
# strip_template_in_place failure ladder
# =============================================================================


def test_strip_in_place_without_templates_dir_returns_none(monkeypatch):
    monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: None)
    assert strip_restore.strip_template_in_place(object()) is None


def test_strip_in_place_initial_save_failure_leaves_canonical_untouched(bundle_dir, patch_lasx):
    original = (bundle_dir / TEMPLATE_XML).read_bytes()
    patch_lasx(save_script=[None])
    assert strip_restore.strip_template_in_place(object(), save_timeout=1) is None
    assert (bundle_dir / TEMPLATE_XML).read_bytes() == original


def test_strip_in_place_missing_lrp_returns_none(bundle_dir, patch_lasx):
    (bundle_dir / TEMPLATE_LRP).unlink()
    patch_lasx()
    assert strip_restore.strip_template_in_place(object(), save_timeout=1) is None


def test_strip_in_place_load_failure_returns_none(bundle_dir, patch_lasx):
    patch_lasx(load_script=[None])
    assert strip_restore.strip_template_in_place(object(), save_timeout=1) is None


def test_strip_in_place_confirm_save_failure_returns_none(bundle_dir, patch_lasx):
    save, _ = patch_lasx(save_script=[{"success": True}, None])
    assert strip_restore.strip_template_in_place(object(), save_timeout=1) is None
    assert save.calls == 2


def test_strip_in_place_residual_objects_returns_none(bundle_dir, patch_lasx):
    original_rgn = (bundle_dir / TEMPLATE_RGN).read_text(encoding="utf-8")

    def lasx_rewrites_objects():
        (bundle_dir / TEMPLATE_RGN).write_text(original_rgn, encoding="utf-8")
        return {"success": True}

    patch_lasx(save_script=[{"success": True}, lasx_rewrites_objects])
    assert strip_restore.strip_template_in_place(object(), save_timeout=1) is None


# =============================================================================
# restore_template paths
# =============================================================================


def test_restore_without_templates_dir_returns_none(monkeypatch):
    monkeypatch.setattr(strip_restore, "find_scanning_templates_dir", lambda: None)
    assert strip_restore.restore_template(object()) is None


def test_restore_without_stripped_lrp_discards_stale_lrp_backup(bundle_dir, patch_lasx):
    # A leftover .lrp.bak from a crashed prior run must not be restored
    # over the current LRP when this run never produced a modified LRP.
    stale_bak = bundle_dir / (TEMPLATE_BASE + ".lrp.bak")
    stale_bak.write_text("stale junk from a crashed run", encoding="utf-8")
    current_lrp = (bundle_dir / TEMPLATE_LRP).read_bytes()
    patch_lasx()

    result = strip_restore.restore_template(object())

    assert result is not None and result["success"] is True
    assert (bundle_dir / TEMPLATE_LRP).read_bytes() == current_lrp
    assert not stale_bak.exists()


def test_restore_retries_after_load_failure(bundle_dir, patch_lasx):
    patch_lasx(load_script=[None, {"success": True}])
    result = strip_restore.restore_template(object())
    assert result is not None and result["success"] is True
    assert result["attempts"] == 2


def test_restore_retries_after_confirm_save_timeout_and_restores_backup(bundle_dir, patch_lasx):
    original_xml = (bundle_dir / TEMPLATE_XML).read_bytes()
    original_rgn = (bundle_dir / TEMPLATE_RGN).read_bytes()
    save, _ = patch_lasx(save_script=[None, {"success": True}])

    result = strip_restore.restore_template(object())

    assert result is not None and result["success"] is True
    assert result["attempts"] == 2
    assert save.calls == 2
    # The failed attempt rolled the canonical files back from the backup.
    assert (bundle_dir / TEMPLATE_XML).read_bytes() == original_xml
    assert (bundle_dir / TEMPLATE_RGN).read_bytes() == original_rgn


def test_restore_retries_after_object_count_regression(bundle_dir, patch_lasx):
    # Attempt 1: LAS X "saves" a template that lost its objects. The
    # mismatch must trigger a backup rollback and another attempt.
    xml_path = bundle_dir / TEMPLATE_XML
    rgn_path = bundle_dir / TEMPLATE_RGN
    expected = strip_restore._count_objects(xml_path, rgn_path)
    assert expected[1] > 0

    def lasx_saves_empty_template():
        strip_restore._strip_xml(xml_path, xml_path)
        strip_restore._strip_rgn(rgn_path, rgn_path)
        return {"success": True}

    patch_lasx(save_script=[lasx_saves_empty_template, {"success": True}])

    result = strip_restore.restore_template(object())

    assert result is not None and result["success"] is True
    assert result["attempts"] == 2
    assert (result["fields"], result["items"], result["focus"]) == expected
    assert strip_restore._count_objects(xml_path, rgn_path) == expected


def test_restore_exhausts_attempts_and_keeps_backups_for_recovery(bundle_dir, patch_lasx):
    n = len(strip_restore._RESTORE_SAVE_TIMEOUTS)
    _, load = patch_lasx(load_script=[None] * n)

    assert strip_restore.restore_template(object()) is None
    assert load.calls == n
    # The .bak files are the only good state left; they must survive.
    assert (bundle_dir / (TEMPLATE_BASE + ".xml.bak")).is_file()
    assert (bundle_dir / (TEMPLATE_BASE + ".rgn.bak")).is_file()
