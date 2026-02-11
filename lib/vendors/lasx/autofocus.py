#!/usr/bin/env python3
"""
vendors.lasx.autofocus — Leica LAS X autofocus hardware control.

LAS X API client wrapper, stage movement, autofocus execution,
and image acquisition — all specific to the Leica LAS X platform.

For vendor-agnostic ordering algorithms and workflow helpers,
see ``utils.autofocus``.

Usage::

    from vendors.lasx.autofocus import (
        LasXClient,
        LasXAutofocusRunner,
        run_autofocus_sequence,
        acquire_all_positions,
    )
"""

import threading
import time
from copy import deepcopy
from typing import List, Dict, Any, Optional, Callable, Tuple

from ...utils.autofocus import (
    OrderStrategy,
    PositionReadback,
    order_tiles_in_group,
)


# ━━━ LAS X API Client Wrapper ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LasXClient:
    """
    Thread-safe LAS X API client with automatic reconnection.

    Usage::

        lasx = LasXClient("PythonClient", max_retries=3)
        client = lasx.client          # raw API handle
        result = lasx.execute_with_retry(some_function, arg1, arg2)
    """

    def __init__(self, client_name: str = "PythonClient", max_retries: int = 3):
        self.client_name = client_name
        self.max_retries = max_retries
        self.client = None
        self._lock = threading.Lock()
        self.connect()

    # —— Connection management ——————————————————————————————————————————————————
    def connect(self):
        """Connect (or reconnect) to LAS X, closing any existing connection."""
        with self._lock:
            if self.client is not None:
                try:
                    self.client.Disconnect()
                except Exception:
                    pass
                time.sleep(0.5)

            from LasxApi import PYLICamApiConnector as lasxApi

            self.client = lasxApi.LasxApiClientPyModel
            confirmed = self.client.Connect(self.client_name)
            if not confirmed:
                raise ConnectionError("Failed to connect to LAS X")

            # Configure
            self.client.PyApiClient.DelayInMilliseconds = 300
            mode = self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
            self.client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
                type(mode).Only_the_CAM_interface_is_used
            )
            self.client.PyApiSetApiInterfaceToUse.UpdateSync(10)

        # Verify the connection actually works
        self.ping()

        return self.client

    def ping(self, timeout: float = 5.0) -> bool:
        """
        Verify the API connection is alive by reading the scan status.

        Raises ConnectionError if unresponsive.
        """
        import concurrent.futures

        def _read_status():
            return str(self.client.PyApiStatusScan.Model.ScanStatus)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_read_status)
            try:
                status = future.result(timeout=timeout)
                print(f"  \u2713 LAS X ping OK (scan status: {status})")
                return True
            except concurrent.futures.TimeoutError:
                raise ConnectionError(
                    f"LAS X connection ping timed out after {timeout}s \u2014 "
                    "API is connected but not responding. "
                    "Check that LAS X is running and not busy."
                )

    def disconnect(self):
        """Gracefully disconnect."""
        with self._lock:
            if self.client is not None:
                try:
                    self.client.Disconnect()
                except Exception:
                    pass
                self.client = None

    # —— Retry wrapper ——————————————————————————————————————————————————————————
    def execute_with_retry(self, func: Callable, *args, **kwargs):
        """Execute *func* with serialised API access and auto-reconnect."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                with self._lock:
                    return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                print(f"  \u26a0 Attempt {attempt + 1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    print("  Reconnecting...")
                    time.sleep(1.0)
                    self.connect()
        raise last_error  # type: ignore[misc]


# Legacy helper — kept for backward compatibility
def connect_to_lasx(client_name: str = "PythonClient"):
    """Legacy connect function.  Prefer ``LasXClient`` instead."""
    from LasxApi import PYLICamApiConnector as lasxApi

    client = lasxApi.LasxApiClientPyModel
    confirmed = client.Connect(client_name)
    if not confirmed:
        raise ConnectionError("Failed to connect to LAS X")

    client.PyApiClient.DelayInMilliseconds = 300
    mode = client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse
    client.PyApiSetApiInterfaceToUse.Model.ApiInterfaceToUse = (
        type(mode).Only_the_CAM_interface_is_used
    )
    client.PyApiSetApiInterfaceToUse.UpdateSync(10)
    return client


# ━━━ LAS X Hardware Runner ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LasXAutofocusRunner:
    """
    Wrapper for LAS X hardware operations (stage moves, AF, image save).

    All methods are synchronous and wait for completion.
    Set ``verbose=True`` for per-call diagnostics (helps find hangs).
    """

    def __init__(self, client, af_job_name: str = "AF Job", verbose: bool = True):
        self.client = client
        self.af_job_name = af_job_name
        self.verbose = verbose

    def _log(self, msg: str):
        if self.verbose:
            import sys
            print(f"    [HW] {msg}", flush=True)
            sys.stdout.flush()

    # —— Position readout ———————————————————————————————————————————————————————
    def get_xy_position(self, timeout: int = 15) -> Tuple[float, float]:
        """
        Read current XY stage position in \u00b5m.

        Uses PyApiCommand "GetXY" to query the hardware.
        """
        self._log("reading XY position ...")
        self.client.PyApiCommand.Model.Command = "GetXY"
        confirmed = self.client.PyApiCommand.UpdateSync(timeout)

        if self.client.PyApiCommandEcho.Model.HasError:
            error_msg = self.client.PyApiCommandEcho.Model.Error
            raise RuntimeError(f"GetXY failed: {error_msg}")

        x = float(self.client.PyApiGetXY.Model.XPosition) * 1e6  # m \u2192 \u00b5m
        y = float(self.client.PyApiGetXY.Model.YPosition) * 1e6  # m \u2192 \u00b5m
        self._log(f"XY = ({x:.1f}, {y:.1f}) \u00b5m [{'OK' if confirmed else 'Timeout'}]")
        return (x, y)

    def get_z_position(
        self, job_name: str | None = None, use_galvo: bool = True,
    ) -> float:
        """
        Read current Z position in \u00b5m for a specific job.

        Args:
            job_name: Job to query Z for (defaults to af_job_name).
            use_galvo: Read galvo-Z (True) or wide-Z (False).
        """
        import json as _json

        job = job_name or self.af_job_name
        self._log(f"reading Z position (job={job}) ...")
        self.client.PyApiGetJobSettingsByName.Model.JobName = job
        self.client.PyApiGetJobSettingsByName.UpdateAsync()
        self.client.PyApiCommand.Model.Command = "GetJobSettingsByName"
        self.client.PyApiCommand.UpdateAsync()

        # Wait for async result
        time.sleep(0.5)

        settings = self.client.PyApiGetJobSettingsByName.Model.Settings
        if isinstance(settings, str):
            settings = _json.loads(settings)

        z_key = "z-galvo" if use_galvo else "z-wide"
        try:
            z = float(settings["zPosition"][z_key]["position"])
            self._log(f"Z = {z:.2f} \u00b5m ({z_key})")
            return z
        except (KeyError, TypeError) as e:
            raise ValueError(
                f"Could not extract Z position from settings: {e}\n"
                f"Settings: {settings}"
            )

    # —— Stage movement —————————————————————————————————————————————————————————
    def move_stage_xy(
        self, x_um: float, y_um: float,
        timeout: int = 10, verify: bool = True,
        tolerance_um: float = 1.0,
    ) -> PositionReadback:
        """
        Move XY stage to absolute position.

        Args:
            x_um, y_um: Target position in \u00b5m.
            timeout: Timeout for the move command.
            verify: If True, read position before and after move.
            tolerance_um: Position error threshold for warnings.

        Returns:
            PositionReadback with before/after positions and confirmation.
        """
        readback = PositionReadback(confirmed=False, target_x=x_um, target_y=y_um)

        if verify:
            try:
                bx, by = self.get_xy_position()
                readback.before_x, readback.before_y = bx, by
            except Exception as e:
                self._log(f"\u26a0 XY readout before move failed: {e}")

        self._log(f"move XY \u2192 ({x_um:.1f}, {y_um:.1f}) \u00b5m ...")
        self.client.PyApiMoveHardwareXY.Model.RelativePosition = False
        self.client.PyApiMoveHardwareXY.Model.XPosition = x_um
        self.client.PyApiMoveHardwareXY.Model.YPosition = y_um
        self.client.PyApiMoveHardwareXY.Model.MoveXyMode = type(
            self.client.PyApiMoveHardwareXY.Model.MoveXyMode
        ).eMoveXY
        self.client.PyApiMoveHardwareXY.Model.Units = type(
            self.client.PyApiMoveHardwareXY.Model.Units
        ).eMicrons
        readback.confirmed = self.client.PyApiMoveHardwareXY.UpdateSync(timeout)
        self._log(f"move XY done (confirmed={readback.confirmed})")

        if verify:
            try:
                ax, ay = self.get_xy_position()
                readback.after_x, readback.after_y = ax, ay
                ex = readback.error_x
                ey = readback.error_y
                if ex is not None and ey is not None:
                    if ex > tolerance_um or ey > tolerance_um:
                        self._log(
                            f"\u26a0 Position error: "
                            f"\u0394x={ex:.2f} \u00b5m, \u0394y={ey:.2f} \u00b5m "
                            f"(tolerance={tolerance_um:.1f} \u00b5m)"
                        )
            except Exception as e:
                self._log(f"\u26a0 XY readout after move failed: {e}")

        return readback

    def move_stage_z(
        self, z_um: float, job_name: str | None = None,
        use_galvo: bool = True, timeout: int = 30,
        verify: bool = True, tolerance_um: float = 0.5,
    ) -> PositionReadback:
        """
        Move Z stage to absolute position.

        Args:
            z_um: Target Z position in \u00b5m.
            job_name: Job name (defaults to af_job_name).
            use_galvo: Use galvo Z (True) or wide Z (False).
            timeout: Timeout for the move command.
            verify: If True, read Z before and after move.
            tolerance_um: Position error threshold for warnings.

        Returns:
            PositionReadback with before/after Z and confirmation.
        """
        job = job_name or self.af_job_name
        readback = PositionReadback(confirmed=False, target_z=z_um)

        if verify:
            try:
                readback.before_z = self.get_z_position(
                    job_name=job, use_galvo=use_galvo,
                )
            except Exception as e:
                self._log(f"\u26a0 Z readout before move failed: {e}")

        self._log(f"move Z \u2192 {z_um:.2f} \u00b5m (job={job}, galvo={use_galvo}) ...")
        self.client.PyApiMoveZByJobName.Model.JobName = job
        self.client.PyApiMoveZByJobName.Model.RelativePosition = False
        self.client.PyApiMoveZByJobName.Model.ZPosition = z_um
        mode_type = type(self.client.PyApiMoveZByJobName.Model.ZUseMode)
        self.client.PyApiMoveZByJobName.Model.ZUseMode = (
            mode_type.eUseGalvo if use_galvo else mode_type.eUseWide
        )
        self.client.PyApiMoveZByJobName.Model.Units = type(
            self.client.PyApiMoveZByJobName.Model.Units
        ).eMicrons
        readback.confirmed = self.client.PyApiMoveZByJobName.UpdateSync(timeout)
        self._log(f"move Z done (confirmed={readback.confirmed})")

        if verify:
            try:
                readback.after_z = self.get_z_position(
                    job_name=job, use_galvo=use_galvo,
                )
                ez = readback.error_z
                if ez is not None and ez > tolerance_um:
                    self._log(
                        f"\u26a0 Z position error: "
                        f"\u0394z={ez:.2f} \u00b5m (tolerance={tolerance_um:.1f} \u00b5m)"
                    )
            except Exception as e:
                self._log(f"\u26a0 Z readout after move failed: {e}")

        return readback


    # —— Autofocus / Acquisition ————————————————————————————————————————————————
    def run_autofocus(self, timeout: int = 30) -> bool:
        self._log(f"autofocus (job={self.af_job_name}) ...")
        self.client.PyApiAcquireJob.Model.JobName = self.af_job_name
        confirmed = self.client.PyApiAcquireJob.UpdateSync(timeout)
        self._log(f"acquire returned (confirmed={confirmed}), waiting for idle ...")
        self.wait_for_idle()
        self._log("autofocus done")
        return confirmed

    def acquire_job(self, job_name: str, timeout: int = 30) -> bool:
        self._log(f"acquire job '{job_name}' ...")
        self.client.PyApiAcquireJob.Model.JobName = job_name
        confirmed = self.client.PyApiAcquireJob.UpdateSync(timeout)
        self._log(f"acquire returned (confirmed={confirmed}), waiting for idle ...")
        self.wait_for_idle()
        self._log("acquire done")
        return confirmed

    def wait_for_idle(self, poll_interval: float = 0.2, max_wait: float = 120):
        """Block until scan status is idle (with timeout)."""
        start = time.time()
        last_status = None
        while True:
            try:
                status = str(self.client.PyApiStatusScan.Model.ScanStatus)
            except Exception as e:
                self._log(f"\u26a0 ScanStatus read failed: {e}")
                status = "ERROR"

            if status != last_status:
                self._log(f"scan status: {status}")
                last_status = status

            if status == "ScanIsIdle":
                return

            elapsed = time.time() - start
            if elapsed > max_wait:
                raise TimeoutError(
                    f"Timed out after {elapsed:.0f}s waiting for idle "
                    f"(last status: {status})"
                )
            time.sleep(poll_interval)

    # —— Image saving ———————————————————————————————————————————————————————————
    def save_current_image(
        self,
        output_dir: str,
        format: str = "OMETIFF",
        timeout: int = 30,
    ) -> bool:
        """
        Save the currently selected image.

        Uses the correct LAS X save pattern with trailing backslash.
        """
        self._log(f"saving image to {output_dir} ...")
        # LAS X requires Windows-style trailing backslash
        path = str(output_dir)
        if not path.endswith("\\"):
            path += "\\\\"

        save_model = self.client.PyApiSaveCurrentSelectedImage.Model
        save_model.FilePath = path

        fmt_type = type(save_model.FileFormat)
        fmt_map = {
            "OMETIFF": fmt_type.OMETIFF,
            "TIFF": fmt_type.TIFF,
            "PNG": fmt_type.PNG,
        }
        save_model.FileFormat = fmt_map.get(format.upper(), fmt_type.OMETIFF)
        save_model.MultiPageTiff = False
        save_model.AllImagesToSameDirectory = True
        save_model.ExportMetadata = True

        result = self.client.PyApiSaveCurrentSelectedImage.UpdateSync(timeout)
        self._log(f"save done (confirmed={result})")
        return result


# ━━━ Autofocus Sequence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_autofocus_sequence(
    ordered_points: List[Dict[str, Any]],
    client,
    af_job_name: str = "AF Job",
    progress_callback: Optional[Callable[[int, int, Dict], None]] = None,
    dry_run: bool = False,
    get_z_function: Optional[Callable[[], float]] = None,
) -> List[Dict[str, Any]]:
    """
    Run autofocus sequence on ordered focus points.

    The *progress_callback* receives ``(current, total, info_dict)`` where
    ``info_dict`` always contains ``"status"`` (one of ``"moving"``,
    ``"focusing"``, ``"complete"``) and ``"identifier"``.  On ``"complete"``
    it also contains ``"z_um"``.

    Returns list of points with measured Z values.
    """
    if dry_run:
        import random
        measured: list[dict] = []
        for i, point in enumerate(ordered_points):
            ident = point.get("identifier", f"#{i}")

            if progress_callback:
                progress_callback(i, len(ordered_points),
                                  {"status": "moving", "identifier": ident})

            mp = deepcopy(point)
            mp["z_um"] = (
                100.0
                + point["x_um"] * 0.001
                + point["y_um"] * 0.0005
                + random.uniform(-2, 2)
            )
            mp["z_measured"] = True
            measured.append(mp)

            if progress_callback:
                progress_callback(i + 1, len(ordered_points),
                                  {"status": "complete", "identifier": ident,
                                   "z_um": mp["z_um"]})
        return measured

    # Real hardware
    runner = LasXAutofocusRunner(client, af_job_name)
    measured = []

    for i, point in enumerate(ordered_points):
        ident = point.get("identifier", f"#{i}")

        if progress_callback:
            progress_callback(i, len(ordered_points),
                              {"status": "moving", "identifier": ident})

        runner.move_stage_xy(point["x_um"], point["y_um"])

        if progress_callback:
            progress_callback(i, len(ordered_points),
                              {"status": "focusing", "identifier": ident})

        success = runner.run_autofocus()
        if not success:
            print(f"  \u26a0 Autofocus failed at {ident}")

        z_um = get_z_function() if get_z_function else runner.get_z_position()

        mp = deepcopy(point)
        mp["z_um"] = z_um
        mp["z_measured"] = True
        measured.append(mp)

        if progress_callback:
            progress_callback(i + 1, len(ordered_points),
                              {"status": "complete", "identifier": ident,
                               "z_um": z_um})

    return measured


# ━━━ Image Acquisition ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def acquire_all_positions(
    updated_positions: Dict[str, Dict[str, Any]],
    client,
    output_dir: str,
    image_format: str = "OMETIFF",
    use_galvo_z: bool = True,
    group_order: Optional[List[str]] = None,
    tile_strategy: OrderStrategy = "shortest_path",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[str]:
    """
    Acquire images at all positions with interpolated Z values.

    Args:
        updated_positions: Positions with interpolated Z.
        client: Connected LAS X API client.
        output_dir: Directory to save images.
        image_format: "OMETIFF", "TIFF", or "PNG".
        use_galvo_z: Use galvo Z (True) or wide Z (False).
        group_order: Optional pre-computed group ordering.
        tile_strategy: Ordering strategy for tiles within each group.
        progress_callback: callback(current, total, message).

    Returns:
        List of saved image file paths.
    """
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    runner = LasXAutofocusRunner(client)
    saved_images: list[str] = []

    total_tiles = sum(len(g.get("tiles", [])) for g in updated_positions.values())
    current_tile = 0

    gids = group_order or list(updated_positions.keys())

    for gid in gids:
        group = updated_positions[gid]
        job_name = group["job_name"]
        tiles = group.get("tiles", [])

        tile_indices = order_tiles_in_group(group, tile_strategy)

        for tile_idx in tile_indices:
            tile = tiles[tile_idx]
            current_tile += 1

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: Moving...")

            runner.move_stage_xy(tile["x_um"], tile["y_um"])

            if tile.get("z_interpolated", False) or tile.get("z_um", 0) != 0:
                runner.move_stage_z(tile["z_um"], job_name=job_name, use_galvo=use_galvo_z)

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: Acquiring...")

            runner.acquire_job(job_name)

            # Save image with the correct LAS X pattern
            runner.save_current_image(str(output_path), format=image_format)

            filename = f"tile_{gid}_{tile_idx:04d}.ome.tiff"
            saved_images.append(str(output_path / filename))

            if progress_callback:
                progress_callback(current_tile, total_tiles,
                                  f"Group {gid}, Tile {tile_idx}: \u2713")

    return saved_images
