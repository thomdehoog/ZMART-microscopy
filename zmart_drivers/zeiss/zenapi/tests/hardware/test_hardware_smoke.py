"""Bench run against a real ZEN API gateway (excluded from the offline run).

Needs a live ZEN (or ZEISS's simulator) with the gateway running, the
``zen_api`` wheel, and a ``config.ini`` for it. Then::

    set ZENAPI_CONFIG=C:\\path\\to\\config.ini
    set ZENAPI_EXPERIMENT=ZMART_Snap          # a saved ZEN experiment to acquire with
    pytest -m hardware                        # or: python run_ci.py --hardware

These are the same round-trip checks the fake-gateway suite runs
(``tests/helpers/roundtrip_checks.py``), so a green bench run means the
driver behaves on ZEN exactly as it does on the fake. The moves are small
(100 um in XY, 10 um in Z) and return to the start position.
"""

import os

import pytest

pytestmark = pytest.mark.hardware


@pytest.fixture(scope="module")
def live_client():
    config = os.environ.get("ZENAPI_CONFIG")
    if not config:
        pytest.skip("set ZENAPI_CONFIG to a ZEN API config.ini to run hardware tests")
    import zenapi as drv

    client = drv.connect(config)
    # The bench envelope: generous limits so the small test moves pass; the
    # real per-microscope limits live in the machine folder (see the adapter).
    drv.set_stage_limits(x_min=-1e6, x_max=1e6, y_min=-1e6, y_max=1e6, z_min=-1e6, z_max=1e6)
    try:
        yield client
    finally:
        drv.close(client)


def test_reads(live_client):
    from roundtrip_checks import check_reads

    reads = check_reads(live_client)
    print("ZEN reports:", reads)


def test_small_moves(live_client):
    from roundtrip_checks import check_motion

    check_motion(live_client, dx_um=100.0, dz_um=10.0, tolerance_um=2.0)


def test_objective_switch(live_client):
    from roundtrip_checks import check_objective_switch

    check_objective_switch(live_client)


def test_snap(live_client):
    from roundtrip_checks import check_experiment_run

    experiment = os.environ.get("ZENAPI_EXPERIMENT")
    if not experiment:
        pytest.skip("set ZENAPI_EXPERIMENT to the name of a saved ZEN experiment")
    result = check_experiment_run(
        live_client, experiment, output_name="zmart_bench_snap", mode="snap"
    )
    print("CZI written to:", result["czi"])


def test_monitor_started_experiment(live_client):
    from roundtrip_checks import check_started_experiment_can_be_monitored

    experiment = os.environ.get("ZENAPI_EXPERIMENT")
    if not experiment:
        pytest.skip("set ZENAPI_EXPERIMENT to the name of a saved ZEN experiment")
    updates = check_started_experiment_can_be_monitored(
        live_client, experiment, output_name="zmart_bench_monitor"
    )
    print(f"{len(updates)} status updates; last: {updates[-1]}")
