"""LAS X state and acquisition helpers for objective calibration."""

import logging
import time

import numpy as np
import tifffile

import navigator_expert.driver as drv
from navigator_expert.driver.scanning_template_editors_focus import lrp_set_stack_calculation_mode
from navigator_expert.driver.scanning_template_editors_roi import lrp_enable_roi_scan
from navigator_expert.driver.scanning_template_editors_scan import lrp_set_pan
from navigator_expert.driver.scanning_template_editors_z import (
    lrp_set_sections,
    lrp_set_z_stack_active,
    lrp_set_z_use_mode,
)
from navigator_expert.driver.scanning_templates import TEMPLATE_XML, apply_lrp_change
from navigator_expert.driver.stage_motion import correct_backlash


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
    """Re-select the job after an objective switch.

    LAS X drops the job selection on objective switch; the readback also
    lags briefly. Retry until the selection sticks.
    """
    for _ in range(JOB_SELECT_RETRIES):
        drv.select_job(client, job)
        time.sleep(2)
        if (drv.get_selected_job(client) or {}).get("Name", "") == job:
            return
    sel = (drv.get_selected_job(client) or {}).get("Name", "")
    raise RuntimeError(
        f"could not select job {job!r} after objective switch (got {sel!r})"
    )


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
    drv.select_job(client, job)
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
    drv.select_job(client, job)
    time.sleep(1.0)
    rz = drv.move_z(client, job, 0.0, unit="um", z_mode="galvo")
    if not rz or not rz.get("success"):
        raise RuntimeError(f"could not zero z-galvo after target switch: {rz}")


def make_acquirer(client, job, stage_cfg):
    """Return (acquire_single, acquire_stack), each preceded by backlash takeup."""
    bk = stage_cfg["backlash"]
    bl_kwargs = dict(
        overshoot_um=bk["overshoot_um"],
        settle_ms=bk["settle_ms"],
        tolerance_um=bk.get("tolerance_um", 20.0),
    )

    def _files():
        correct_backlash(client, **bl_kwargs)
        idle = drv.check_idle(client, timeout=30)
        if not idle or not idle.get("success"):
            raise RuntimeError(f"scanner not idle before acquire: {idle}")
        baseline = drv.read_relative_path(client)
        t0 = time.time()
        result = drv.acquire(client, job)
        if not result or not result.get("success"):
            raise RuntimeError(f"acquire failed: {result}")
        media = drv.get_lasx_settings()["export"]["media_path"]
        det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
        if not det["success"]:
            raise RuntimeError(f"file detection failed: {det.get('error')}")
        files = sorted(det["image_files"])
        if not files:
            raise RuntimeError("acquire produced no files")
        drv.wait_all_stable(files, timeout=30)
        return files

    def acquire_single():
        files = _files()
        img = tifffile.imread(str(files[0]))
        return img[0] if img.ndim == 3 else img

    def acquire_stack():
        files = _files()
        if len(files) == 1:
            stack = tifffile.imread(str(files[0]))
            if stack.ndim == 2:
                stack = stack[np.newaxis, ...]
        else:
            slices = [tifffile.imread(str(f)) for f in files]
            slices = [s[0] if s.ndim == 3 else s for s in slices]
            stack = np.array(slices)
        return stack

    return acquire_single, acquire_stack


# ``apply_stage_limits_from_config`` lives in driver/limits.py — both
# calibration and the cookbook share that single helper.
