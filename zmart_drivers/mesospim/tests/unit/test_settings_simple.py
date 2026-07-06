"""A minimal walk through every setting change -- one line per setting."""

from __future__ import annotations

from mesospim import commands as cmd


def test_every_setting_change(client):
    # select the emission filter
    assert cmd.set_filter(client, "561/LP")["success"]
    # select the zoom (magnification)
    assert cmd.set_zoom(client, "2x")["success"]
    # select the active laser line
    assert cmd.set_laser(client, "561 nm")["success"]
    # set the active laser intensity (0-100 %)
    assert cmd.set_intensity(client, 42)["success"]
    # select the light-sheet shutter configuration
    assert cmd.set_shutter(client, "Both")["success"]
    # set the left ETL amplitude and offset
    assert cmd.set_etl(client, "left", amplitude=3.0, offset=1.5)["success"]
