"""acquire() success/raise and save() CZI resolve + copy."""

import pytest
import zenapi as drv
from mock_zen_api import FakeGRPCError, idle_status, running_status

from shared.output_layout.naming import Naming, run_hash


def test_acquire_success(fake_client):
    client, scope = fake_client
    scope.status_script = [running_status(), idle_status()]
    exp = drv.load_experiment(client, "E")
    acq = drv.acquire(client, exp, output_name="run1")
    assert acq.output_name == "run1"
    assert acq.command_result["success"] is True
    assert acq.finished_at >= acq.started_at


def test_acquire_raises_on_failure(fake_client):
    client, scope = fake_client
    scope.errors["run_experiment"] = FakeGRPCError("INTERNAL", "boom")
    exp = drv.load_experiment(client, "E")
    with pytest.raises(RuntimeError, match="acquire failed"):
        drv.acquire(client, exp)


def test_save_copies_czi(fake_client, tmp_path):
    client, scope = fake_client
    src = tmp_path / "zen_output.czi"
    src.write_bytes(b"CZIDATA")
    scope.czi_path = str(src)
    scope.status_script = [running_status(), idle_status()]

    exp = drv.load_experiment(client, "E")
    acq = drv.acquire(client, exp, output_name="run1")

    naming = Naming(acquisition_type="overview", hash6=run_hash(1767225601), position_label="000000")
    saved = drv.save(client, acq, tmp_path / "run", naming, stable_poll_s=0.01)

    assert saved.czi_path.exists()
    assert saved.czi_path.read_bytes() == b"CZIDATA"
    assert saved.czi_path.suffix == ".czi"
    assert "overview" in saved.czi_path.name
