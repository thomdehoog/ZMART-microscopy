"""acquire() success/raise and save(): the CZI lands under <type>/data/."""

import pytest
import zenapi as drv
from mock_zen_api import FakeGRPCError
from zenapi.acquisition.naming import Naming, run_hash


def test_acquire_experiment_success(fake_client, tmp_path):
    client, scope = fake_client
    scope.image_output_folder = str(tmp_path / "zen_out")
    exp = drv.load_experiment(client, "ZMART_ZStack")
    acq = drv.acquire(client, exp, output_name="run1")
    assert acq.output_name == "run1"
    assert acq.command_result["success"] is True
    assert acq.command_result["confirmed"] is True
    assert acq.command_result["status"]["is_experiment_running"] is False
    assert acq.finished_at >= acq.started_at
    assert (tmp_path / "zen_out" / "run1.czi").exists()


def test_acquire_snap_keeps_zen_output_name(fake_client):
    client, scope = fake_client
    exp = drv.load_experiment(client, "ZMART_Snap")
    acq = drv.acquire(client, exp, mode="snap")  # ZEN chooses the name
    assert acq.output_name.startswith("auto_")
    assert scope.calls[-1][0] == "run_snap"


def test_acquire_raises_on_failure(fake_client):
    client, scope = fake_client
    scope.errors["run_experiment"] = FakeGRPCError("INTERNAL", "boom")
    exp = drv.load_experiment(client, "ZMART_Snap")
    with pytest.raises(RuntimeError, match="acquire failed"):
        drv.acquire(client, exp)


def test_load_unknown_experiment_raises(fake_client):
    client, _ = fake_client
    with pytest.raises(FakeGRPCError, match="NOT_FOUND"):
        drv.load_experiment(client, "does-not-exist")


def test_save_copies_czi(fake_client, tmp_path):
    client, scope = fake_client
    scope.image_output_folder = str(tmp_path / "zen_out")

    exp = drv.load_experiment(client, "ZMART_ZStack")
    acq = drv.acquire(client, exp, output_name="run1")

    naming = Naming(
        acquisition_type="overview", hash6=run_hash(1767225601), position_label="000000"
    )
    saved = drv.save(client, acq, tmp_path / "run", naming, stable_poll_s=0.01)

    assert saved.czi_path.exists()
    assert saved.czi_path.read_bytes() == (tmp_path / "zen_out" / "run1.czi").read_bytes()
    assert saved.czi_path.suffix == ".czi"
    assert "overview" in saved.czi_path.name
    # ``<type>/data``: the same shape every ZMART driver writes, so what is
    # made from a capture later becomes a folder beside the pixels.
    assert saved.czi_path.parent.name == "data"
    assert saved.czi_path.parent.parent.name == "overview"


def test_save_times_out_when_zen_folder_unreachable(fake_client, tmp_path):
    client, scope = fake_client
    scope.image_output_folder = str(tmp_path / "zen_out")
    exp = drv.load_experiment(client, "ZMART_Snap")
    acq = drv.acquire(client, exp, mode="snap", output_name="gone")
    (tmp_path / "zen_out" / "gone.czi").unlink()  # as if the share were not mounted
    naming = Naming(acquisition_type="snap", hash6=run_hash(1767225601), position_label="a")
    with pytest.raises(TimeoutError, match="reachable"):
        drv.save(client, acq, tmp_path / "run", naming, stable_timeout_s=0.05, stable_poll_s=0.01)
