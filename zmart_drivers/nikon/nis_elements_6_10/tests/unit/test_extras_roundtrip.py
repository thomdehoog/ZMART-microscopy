"""Piezo Z, autofocus, PFS, exposure, live view and Z-stacks through the real bridge server."""

import pytest
from nis_elements_6_10.commands import commands as cmd
from nis_elements_6_10.commands.commands import LimitError
from nis_elements_6_10.connection.client import NisClient
from nis_elements_6_10.readers import readers


def test_z_drives_report_the_piezo(client):
    drives = readers.get_z_drives(client)
    assert drives["piezo_index"] == 1
    assert [d["kind"] for d in drives["drives"]] == ["motoric", "piezo"]


def test_move_piezo_z(client, fake_api):
    assert cmd.move_piezo_z(client, 12.5) == 12.5 and fake_api.piezo_z == 12.5


def test_move_piezo_without_piezo_is_refused(bridge, fake_api):
    fake_api.has_piezo = False
    c = NisClient("127.0.0.1", bridge.server_address[1])
    c.connect()
    try:
        with pytest.raises(RuntimeError, match="no piezo"):
            cmd.move_piezo_z(c, 1.0)
    finally:
        c.close()


def test_autofocus_returns_new_position(client, fake_api):
    result = cmd.autofocus(client, range_um=40, speed=20)
    assert result["position"]["z"] == pytest.approx(503.0)
    assert fake_api.calls == ["autofocus(40.0,20)"]


def test_autofocus_argument_checks(client):
    with pytest.raises(ValueError, match="range_um"):
        cmd.autofocus(client, range_um=-1)
    with pytest.raises(ValueError, match="speed"):
        cmd.autofocus(client, speed=200)


def test_pfs_on_waits_for_lock(client, fake_api):
    assert readers.get_pfs(client)["on"] is False
    pfs = cmd.set_pfs(client, True)
    assert pfs["on"] is True and pfs["focused"] is True
    assert fake_api.calls == ["set_pfs(True)", "wait_for_pfs(8.0)"]


def test_exposure_round_trip(client, fake_api):
    assert readers.get_exposure_ms(client) == 100.0
    assert cmd.set_exposure_ms(client, 25) == 25.0 and fake_api.exposure_ms == 25.0
    with pytest.raises(ValueError, match="positive"):
        cmd.set_exposure_ms(client, 0)


def test_live_and_freeze(client, fake_api):
    cmd.live(client)
    assert fake_api.is_live
    cmd.freeze(client)
    assert not fake_api.is_live


def test_z_stack_counts_planes_and_checks_limits(client, fake_api, tmp_path):
    info = cmd.capture_z_stack(client, z_top=510, z_bottom=490, z_step=5)
    assert info["z_planes"] == 5 and fake_api.z_series == (510.0, 490.0, 5.0, 5)
    cmd.save_image(client, str(tmp_path / "stack.nd2"), format="nd2")
    assert fake_api.saved[0][1] == 14
    with pytest.raises(LimitError):
        cmd.capture_z_stack(client, z_top=20000, z_bottom=0, z_step=1)
