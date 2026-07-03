"""Unit tests for the galvo-pan LRP helpers (experimental/lrp_edits/pan.py)."""

from navigator_expert.experimental.lrp_edits import pan

_LRP = """<root>
<LDM_Block_Sequence_Block>
<LDM_Block_Sequential BlockName="job1"/>
<ATLConfocalSettingDefinition Zoom="1" BaseZoom="1" PanFirstDim="0" PanSecondDim="0"/>
</LDM_Block_Sequence_Block>
</root>
"""


def _write(tmp_path, text=_LRP):
    p = tmp_path / "template.lrp"
    p.write_text(text, encoding="utf-8")
    return p


def test_set_job_attr_does_not_touch_suffixed_attribute(tmp_path):
    """Editing Zoom must not rewrite BaseZoom that shares its value (C4 regression)."""
    p = _write(tmp_path)
    changed = pan._set_job_attr(p, "Zoom", "2", "job1", "test")
    text = p.read_text(encoding="utf-8")
    assert changed == 1
    assert 'Zoom="2"' in text
    assert 'BaseZoom="1"' in text  # untouched


def test_set_and_get_pan_round_trip(tmp_path):
    p = _write(tmp_path)
    pan.lrp_set_pan(p, 0.003, -0.002, "job1")
    assert pan.lrp_get_pan(p, "job1") == (0.003, -0.002)
    assert pan.lrp_verify_pan(p, 0.003, -0.002, "job1")


def test_get_pan_defaults_to_zero_for_unknown_job(tmp_path):
    assert pan.lrp_get_pan(_write(tmp_path), "missing") == (0.0, 0.0)


def test_galvo_pan_for_pixel_is_centre_relative():
    # Pixel at the centre yields zero delta; off-centre scales by pixel size / pan scale.
    assert pan.galvo_pan_for_pixel(256, 256, pixel_size_um=1.0, image_size=512, pan_scale_um=10.0) == (
        0.0,
        0.0,
    )
    dx, dy = pan.galvo_pan_for_pixel(256 + 10, 256, pixel_size_um=1.0, image_size=512, pan_scale_um=10.0)
    assert dx == -1.0 and dy == 0.0
