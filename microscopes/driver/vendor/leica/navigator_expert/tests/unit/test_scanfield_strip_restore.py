"""Offline strip/restore smoke test for Leica scan-field bundles."""

from __future__ import annotations

import shutil

from navigator_expert.scanfields import strip_restore
from navigator_expert.scanfields.files import (
    STRIPPED_LRP,
    STRIPPED_RGN,
    STRIPPED_XML,
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


def test_strip_restore_round_trip_preserves_offline_workflow(
    general_workflow_data,
    monkeypatch,
):
    """Strip and restore a real workflow bundle without LAS X or hardware."""
    templates_dir = general_workflow_data
    _install_template_bundle(general_workflow_data, templates_dir)

    monkeypatch.setattr(
        strip_restore, "find_scanning_templates_dir", lambda: templates_dir)
    monkeypatch.setattr(
        strip_restore, "save_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )
    monkeypatch.setattr(
        strip_restore, "load_experiment",
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

    monkeypatch.setattr(
        strip_restore, "find_scanning_templates_dir", lambda: templates_dir)
    monkeypatch.setattr(
        strip_restore, "save_experiment",
        lambda *_args, **_kwargs: {"success": True, "confirmed": True},
    )
    monkeypatch.setattr(
        strip_restore, "load_experiment",
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
