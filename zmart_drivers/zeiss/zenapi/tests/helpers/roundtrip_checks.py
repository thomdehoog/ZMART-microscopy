"""
The driver's round trip, written once for any ZEN API endpoint.
==============================================================
These checks drive the public driver surface -- connect, read, move, switch
objective, load and run an experiment, fetch the CZI -- through a real
``ZenClient`` over a real gRPC/TLS connection. They know nothing about who is
on the other end, so the same functions run against:

* the fake gateway (``tests/gateway``, the default offline run), and
* ZEISS's simulator or a real ZEN (``tests/hardware``, with ``ZENAPI_CONFIG``).

When the simulator arrives, the bench run is these same checks with a
different ``config.ini``. Keep them free of fake-only assumptions: they only
assert what ZEN documents (positions come back where we sent them, an
objective switch lands on the requested position, a run produces the named
CZI in the reported image folder).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from pathlib import Path

import zenapi as drv


def check_reads(client) -> dict:
    """Positions read as numbers in micrometres and the objective list is populated."""
    xy = drv.get_xy(client)
    z = drv.get_z(client)
    assert isinstance(xy["x_um"], float) and isinstance(xy["y_um"], float)
    assert isinstance(z, float)
    objectives = drv.get_objectives(client)
    assert objectives, "ZEN reported no objectives"
    current = drv.get_objective(client)
    assert current["index"] in {o["index"] for o in objectives}
    return {"xy": xy, "z": z, "objective": current, "objectives": objectives}


def check_motion(client, *, dx_um: float = 100.0, dz_um: float = 10.0, tolerance_um: float = 1.0):
    """A small relative XY and Z move lands within tolerance, then returns home."""
    start_xy = drv.get_xy(client)
    start_z = drv.get_z(client)
    r = drv.move_xy(client, start_xy["x_um"] + dx_um, start_xy["y_um"] + dx_um)
    assert r["success"], r["message"]
    assert r["confirmed"], r["message"]
    r = drv.move_z(client, start_z + dz_um)
    assert r["success"] and r["confirmed"], r["message"]
    moved = drv.get_xy(client)
    assert abs(moved["x_um"] - start_xy["x_um"] - dx_um) < tolerance_um
    assert abs(drv.get_z(client) - start_z - dz_um) < tolerance_um
    # home again, so a bench run leaves the microscope where it found it
    assert drv.move_xy(client, start_xy["x_um"], start_xy["y_um"])["success"]
    assert drv.move_z(client, start_z)["success"]


def check_objective_switch(client):
    """Switch to another objective by position index and back."""
    objectives = drv.get_objectives(client)
    current = drv.get_objective(client)["index"]
    other = next((o["index"] for o in objectives if o["index"] != current), None)
    if other is None:
        return  # a single-objective system: nothing to switch
    r = drv.set_objective(client, index=other)
    assert r["success"] and r["confirmed"], r["message"]
    assert drv.get_objective(client)["index"] == other
    r = drv.set_objective(client, index=current)
    assert r["success"] and r["confirmed"], r["message"]


def check_experiment_run(client, experiment_name: str, *, output_name: str, mode: str = "snap"):
    """Load an experiment, acquire, and find the CZI where ZEN says it writes images."""
    assert experiment_name in drv.get_available_experiments(client)
    exp = drv.load_experiment(client, experiment_name)
    assert exp.experiment_id
    acq = drv.acquire(client, exp, mode=mode, output_name=output_name)
    assert acq.output_name == output_name
    assert acq.command_result["success"]
    status = acq.command_result["status"]
    assert status is not None and status["is_experiment_running"] is False
    folder = Path(drv.get_image_output_path(client))
    czi = folder / f"{output_name}.czi"
    assert czi.exists(), f"expected the acquisition at {czi}"
    assert drv.get_status(client)["is_experiment_running"] is False
    return {"experiment": exp, "acquisition": acq, "czi": czi}


def check_started_experiment_can_be_monitored(client, experiment_name: str, *, output_name: str):
    """start_experiment + monitor: updates arrive and the last one says finished."""
    exp = drv.load_experiment(client, experiment_name)
    started = drv.start_experiment(client, exp, output_name=output_name)
    assert started["output_name"] == output_name
    updates = list(drv.monitor(client, exp))
    assert updates, "no status updates arrived"
    assert updates[-1]["is_experiment_running"] is False
    return updates
