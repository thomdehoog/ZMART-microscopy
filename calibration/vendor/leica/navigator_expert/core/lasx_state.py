"""LAS X state and acquisition helpers for objective calibration."""

import logging
import time

import navigator_expert.driver as drv
from navigator_expert.driver.experimental.lrp_edits.focus import lrp_set_stack_calculation_mode
from navigator_expert.driver.experimental.lrp_edits.roi import lrp_enable_roi_scan
from navigator_expert.driver.experimental.lrp_edits.scan import lrp_set_pan
from navigator_expert.driver.experimental.lrp_edits.z import (
    lrp_set_sections,
    lrp_set_z_stack_active,
    lrp_set_z_use_mode,
)
from navigator_expert.driver.templates.files import TEMPLATE_XML
from navigator_expert.driver.templates.transaction import apply_lrp_change


log = logging.getLogger(__name__)

JOB_SELECT_RETRIES = 3


def reset_pan_roi_zstack(client, job):
    """Pan -> 0, ROI -> off, Z-stack -> off, sections -> 1."""
    def _setup(p):
        lrp_set_pan(p, 0, 0, job)
        lrp_enable_roi_scan(p, False, job)
        lrp_set_z_stack_active(p, False, job)
        lrp_set_sections(p, 1, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))


def configure_z_stack(client, job, *, half_range_um, step_um,
                      z_drive="z-galvo",
                      begin_um=None, end_um=None,
                      centre_um=0.0):
    """Enable a Z-stack scanned on the chosen drive.

    ``z_drive`` selects which physical drive scans the stack:
        - ``"z-galvo"`` — small range (~±200 um), centred at 0 by default.
        - ``"z-wide"`` — wide focus motor; pass ``centre_um`` (the
          current z-wide reading) so begin/end live around it.

    Convention: ``begin > end`` so positive slice indices run from
    high-Z down. Brenner peaks indexed against this layout convert to
    Z via ``centre + half_range - peak_sub * step``.
    """
    sections = int(2 * half_range_um / step_um) + 1
    b = begin_um if begin_um is not None else (centre_um + half_range_um)
    e = end_um if end_um is not None else (centre_um - half_range_um)

    def _setup(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_z_use_mode(p, z_drive, job)
        lrp_set_stack_calculation_mode(p, 1, job)
        lrp_set_sections(p, sections, job)
        lrp_set_z_stack_active(p, True, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))
    drv.set_z_stack_definition(client, job, begin_um=b, end_um=e)
    drv.set_z_stack_step_size(client, job, step_um)


def disable_z_stack(client, job):
    def _setup(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_sections(p, 1, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))


def reselect_job(client, job):
    """No-op: operator pre-selects the job in LAS X GUI before running.

    Calling select_job from the API on this rig triggers spurious CAM
    errors and unreliable readbacks. Skip entirely.
    """
    return


def apply_scan_format_and_speed(client, job, scan_format, scan_speed):
    """Pin image format + scan speed so calibration is reproducible.

    Re-applied after every objective switch because LAS X may reset job
    settings on switch.
    """
    if scan_format:
        drv.set_image_format(client, job, scan_format)
    if scan_speed:
        drv.set_scan_speed(client, job, scan_speed)


def setup_reference_state(client, job, hw, *, ref_slot, ref_zoom, settle_s,
                          scan_format=None, scan_speed=None):
    """Switch to the reference slot and put the scope in canonical state.

    Z-galvo is forced to 0 — the calibration model holds galvo at 0
    throughout and uses z-wide for all focal-plane motion.
    """
    log.info("reference state: slot=%d, zoom=%.2f", ref_slot, ref_zoom)
    r = drv.set_objective(client, job, hw, slot_index=ref_slot)
    if not r or not r.get("success"):
        raise RuntimeError(f"objective switch to ref slot {ref_slot} failed: {r}")
    time.sleep(settle_s)
    reselect_job(client, job)
    reset_pan_roi_zstack(client, job)
    drv.set_zoom(client, job, ref_zoom)
    apply_scan_format_and_speed(client, job, scan_format, scan_speed)
    time.sleep(1.0)
    rz = drv.move_z(client, job, 0.0, unit="um", z_mode="galvo")
    if not rz or not rz.get("success"):
        raise RuntimeError(f"could not zero z-galvo in reference setup: {rz}")
    idle = drv.check_idle(client, timeout=30)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"LAS X not idle after reference setup: {idle}")


def switch_to_target(client, job, hw, slot, *, settle_s, zoom,
                     scan_format=None, scan_speed=None):
    """Switch to a target objective and re-establish job + zoom.

    Z-galvo is forced to 0 after the switch so the rest of the
    calibration measures purely on z-wide.
    """
    log.info("switching to target slot=%d (zoom=%.2f)", slot, zoom)
    r = drv.set_objective(client, job, hw, slot_index=slot)
    if not r or not r.get("success"):
        raise RuntimeError(f"objective switch to slot {slot} failed: {r}")
    time.sleep(settle_s)
    reselect_job(client, job)
    reset_pan_roi_zstack(client, job)
    drv.set_zoom(client, job, zoom)
    apply_scan_format_and_speed(client, job, scan_format, scan_speed)
    time.sleep(1.0)
    rz = drv.move_z(client, job, 0.0, unit="um", z_mode="galvo")
    if not rz or not rz.get("success"):
        raise RuntimeError(f"could not zero z-galvo after target switch: {rz}")


def make_acquirer(client, job, stage_cfg):
    """Return ``(acquire_single, acquire_stack)`` closures pinned to
    this client/job/backlash config.

    Each closure call pre-applies the configured +X+Y backlash takeup
    and forwards to the shared driver helpers
    (``drv.acquire_frame`` / ``drv.acquire_stack``), so calibration and
    cookbook scripts share one acquire path.
    """
    backlash_params = stage_cfg["backlash"]

    def acquire_single():
        img, _ = drv.acquire_frame(client, job, backlash_params=backlash_params)
        return img

    def acquire_stack():
        return drv.acquire_stack(client, job, backlash_params=backlash_params)

    return acquire_single, acquire_stack


# ``apply_stage_limits_from_config`` lives in driver/stage/limits.py; both
# calibration and the cookbook share that single helper.
