"""A minimal walk through every setting change -- one line per setting, each
confirmed by reading the state back."""

from __future__ import annotations

from mesospim import commands as cmd
from mesospim import readers


def test_every_setting_change(client):
    # select the emission filter
    assert cmd.set_filter(client, "561/LP")["success"]
    assert readers.get_state(client)["filter"] == "561/LP"

    # select the zoom (magnification)
    assert cmd.set_zoom(client, "2x")["success"]
    assert readers.get_state(client)["zoom"] == "2x"

    # select the active laser line
    assert cmd.set_laser(client, "561 nm")["success"]
    assert readers.get_state(client)["laser"] == "561 nm"

    # set the active laser intensity (0-100 %)
    assert cmd.set_intensity(client, 42)["success"]
    assert readers.get_state(client)["intensity"] == 42

    # select the light-sheet shutter configuration
    assert cmd.set_shutter(client, "Both")["success"]
    assert readers.get_state(client)["shutterconfig"] == "Both"

    # set the left ETL amplitude and offset
    assert cmd.set_etl(client, "left", amplitude=3.0, offset=1.5)["success"]
    assert readers.get_state(client)["etl_l_amplitude"] == 3.0
