"""The limits gate: the one check every set command must pass.

The gate sits inside the set dispatcher, so no set command can skip it: the
only way to the hardware goes through it. It compares a request with the
limits from the configuration and refuses anything outside them, before a
single command is sent.

Stage positions are checked in **raw stage coordinates**. Recording a new
origin therefore never moves the safe travel range.

When the limits could not be loaded, the gate refuses every change. An
unknown limit is never treated as "no limit".

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any


class Gate:
    """Checks requests against the loaded limits.

    ``limits`` is the checked ``limits`` configuration item, or ``None`` when
    it could not be loaded, which makes the gate refuse everything.
    """

    def __init__(self, limits: dict[str, Any] | None) -> None:
        self._limits = limits

    def check(self, key: str, values: dict[str, Any]) -> str | None:
        """Return why the request is refused, or ``None`` when it may go ahead.

        ``key`` names what is being changed: ``"stage"`` (with raw ``x``,
        ``y`` and ``z``), a setting name such as ``"laser_power"`` (with
        ``value``), ``"objective"`` (with ``slot``) or ``"acquire"`` (with
        ``z_planes``, ``z_bottom`` and ``z_top``). An unknown key is refused.
        """
        limits = self._limits
        if limits is None:
            return "the limits are not loaded, so nothing on the microscope may change"
        if key == "stage":
            return self._stage(values, limits["stage_um"])
        if key in limits["settings"]:
            low, high = limits["settings"][key]
            value = values["value"]
            if not low <= value <= high:
                return f"{key} = {value} is outside the limits [{low}, {high}]"
            return None
        if key == "objective":
            if values["slot"] not in limits["objectives"]:
                return f"objective {values['slot']} is not allowed; the limits allow {limits['objectives']}"
            return None
        if key == "acquire":
            most = limits["acquisition"]["max_z_planes"]
            if values["z_planes"] > most:
                return f"{values['z_planes']} z planes is more than the limit of {most}"
            low, high = limits["stage_um"]["z"]
            if values["z_bottom"] < low or values["z_top"] > high:
                return (
                    f"the z-stack would reach from {values['z_bottom']:.2f} to "
                    f"{values['z_top']:.2f} µm (stage coordinates), outside the travel "
                    f"range [{low}, {high}]"
                )
            return None
        return f"there is no limit for {key!r}, so it is refused"

    @staticmethod
    def _stage(values: dict[str, float], stage: dict[str, list[float]]) -> str | None:
        for axis in ("x", "y", "z"):
            low, high = stage[axis]
            if not low <= values[axis] <= high:
                return (
                    f"{axis} would go to {values[axis]:.2f} µm (stage coordinates), "
                    f"outside the travel range [{low}, {high}] set in the limits"
                )
        return None
