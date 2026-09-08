"""A focussing stack's planes are stamped where they were taken -- live.

Run against LAS X (the simulator or the stand) rather than a stub: the
stamps are the driver's account of the instrument, and only the instrument
can say whether that account is right. Skipped unless ``ZMART_LIVE_LASX=1``
names a registered instrument and it answers, so a suite run with no
microscope is untouched.

What the workflow stands on, and what this pins: after a drive to
``(x, y, z)``, the capture's planes carry that ``x`` and ``y``; every plane
carries a finite ``z_um``; one height per z index, evenly spaced; and the
stack is centred on the height it was driven to, within one step. Every
consumer downstream believes these numbers -- the store places each plane
at its ``z_um``, the focus score is shifted onto the drive by the planes'
midpoint, the surface is fitted through the result -- so a stack stamped in
another frame, or flat at one height, is a wrong picture and a wrong map,
not a warning in a log.

Measured 2026-09-08 on the STELLARIS simulator (``AF Job``, 18 planes):
every plane stamped at the drive's own height, the driver saying "the job
said nothing usable about its stack". On the stand the first real run
stamped a stack near -5800 um while the stage stood at 7 um. Both fail here.

    ZMART_LIVE_LASX=1 python -m pytest application/parts/microscope/test_focus_stack_stamps_live.py -s

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import os
import statistics

import pytest

#: The instrument this runs against, as the registry lists it. The
#: configuration is the one this PC keeps for the simulator.
INSTRUMENT = {
    "vendor": os.environ.get("ZMART_LIVE_VENDOR", "leica"),
    "microscope": os.environ.get("ZMART_LIVE_MICROSCOPE", "stellaris5-y42h93"),
    "api": os.environ.get("ZMART_LIVE_API", "navigator-expert"),
}


@pytest.fixture(scope="module")
def session():
    if os.environ.get("ZMART_LIVE_LASX") != "1":
        pytest.skip("set ZMART_LIVE_LASX=1 to run against LAS X")
    import zmart_controller
    from zmart_drivers.discovery import register_every_driver

    register_every_driver(say=lambda *_a, **_k: None)
    configurations = zmart_controller.get_configurations(INSTRUMENT)
    if not configurations:
        pytest.skip(f"{INSTRUMENT} keeps no configuration on this PC")
    try:
        opened = zmart_controller.set_instrument(
            {**INSTRUMENT, "configuration": configurations[0]["id"]}
        )
    except Exception as why:  # noqa: BLE001 -- no LAS X is a skip, not a failure
        pytest.skip(f"LAS X did not answer: {why}")
    try:
        yield opened
    finally:
        opened.disconnect()


def test_a_focussing_stack_is_stamped_where_it_was_taken(session):
    here = session.get_xyz()
    x, y, z = (float(here[axis]["value"]) for axis in ("x", "y", "z"))
    session.set_xyz(x, y, z)
    record = session.acquire(acquisition_type="focussing", position_label="stamp-check")

    planes = record["planes"]
    assert planes, "the capture reported no planes"
    for plane in planes:
        assert plane["x_um"] == pytest.approx(x, abs=0.01), plane
        assert plane["y_um"] == pytest.approx(y, abs=0.01), plane
        assert isinstance(plane["z_um"], (int, float)), f"a plane with no height: {plane}"

    # One height per z index, whatever the channel.
    by_index: dict[int, set[float]] = {}
    for plane in planes:
        by_index.setdefault(int(plane["z"]), set()).add(float(plane["z_um"]))
    assert all(len(heights) == 1 for heights in by_index.values()), by_index
    heights = [next(iter(by_index[index])) for index in sorted(by_index)]
    print(f"\n{len(heights)} planes stamped at {heights[0]:.3f} .. {heights[-1]:.3f} um; drive z {z:.3f} um")

    if len(heights) > 1:
        assert len(set(heights)) == len(heights), (
            f"{len(heights)} planes stamped at {sorted(set(heights))} um: the stack is "
            "written flat, so the store cannot place its planes"
        )
        steps = [b - a for a, b in zip(heights, heights[1:])]
        step = statistics.median(steps)
        assert all(abs(one - step) <= abs(step) * 0.05 for one in steps), steps
        midpoint = (min(heights) + max(heights)) / 2
        assert midpoint == pytest.approx(z, abs=abs(step)), (
            f"the stack is centred at {midpoint:.3f} um, the drive stood at {z:.3f} um: "
            "the planes are stamped in another frame than the stage drives in"
        )
