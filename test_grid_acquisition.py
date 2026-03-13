"""Test 2x2 grid of groups, each with 2x2 positions.

Acquires 16 times total (4 groups x 4 positions), saving files
in the SMART directory structure with proper G/P naming.

Layout:
    Carrier_000/
        Compartment_Z00_Y00_X00/   <- Group 0 (P0..P3)
        Compartment_Z00_Y00_X01/   <- Group 1 (P0..P3)
        Compartment_Z00_Y01_X00/   <- Group 2 (P0..P3)
        Compartment_Z00_Y01_X01/   <- Group 3 (P0..P3)
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "controller" / "vendor" / "leica"))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_grid")

# ── Configuration ─────────────────────────────────────────────────
JOB_NAME = "HiRes"
EXPERIMENT = "untitled_experiment"
ACQ_TYPE = "Overview_Scan"
EXPECTED_CHANNELS = 3
EXPECTED_Z = 1
EXPECTED_T = 1

# Grid layout
GROUPS_Y = 2    # rows of groups
GROUPS_X = 2    # columns of groups
POS_Y = 2       # rows of positions per group
POS_X = 2       # columns of positions per group

# Spacing (micrometers) — current stage position is top-left origin
# FOV is ~1165 um (512 px * 2.275 um/px) for HiRes job
FOV = 1165.0              # field of view per tile (um)
POS_SPACING = FOV         # no overlap between positions within a group
GROUP_SPACING = POS_Y * POS_SPACING + 500.0  # gap between groups (positions + 500 um margin)

# ── Build paths ───────────────────────────────────────────────────
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
DESTINATION_ROOT = Path("Z:/zmbstaff/10374/Temporary_Data")
ACQ_DIR = (
    DESTINATION_ROOT
    / "SMART"
    / f"{timestamp}_{EXPERIMENT}"
    / ACQ_TYPE
)

# Pre-create sibling folders
(ACQ_DIR / "analysis").mkdir(parents=True, exist_ok=True)
(ACQ_DIR / "feedback").mkdir(parents=True, exist_ok=True)

# ── Connect ───────────────────────────────────────────────────────
client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    log.error("Cannot connect to LAS X.")
    sys.exit(1)
log.info("Connected to LAS X")

# ── Read settings ─────────────────────────────────────────────────
settings = drv.get_lasx_settings()
if settings is None or "export" not in settings:
    log.error("Cannot read LAS X settings")
    sys.exit(1)

media_path = settings["export"]["media_path"]
log.info("Media path: %s", media_path)

# ── Set stage safety limits ───────────────────────────────────────
# Generous limits — the grid spans ~2 mm from origin at most.
drv.set_stage_limits(
    x_min=0, x_max=130_000,         # full X travel (um)
    y_min=0, y_max=130_000,         # full Y travel (um)
    z_galvo_min=-500, z_galvo_max=500,
    z_wide_min=-500, z_wide_max=500,
)
log.info("Stage limits configured")

# ── Read current position as origin ──────────────────────────────
origin = drv.get_xy(client)
if origin is None:
    log.error("Cannot read stage position")
    sys.exit(1)
origin_x = origin["x_um"]
origin_y = origin["y_um"]
log.info("Origin: X=%.1f um, Y=%.1f um", origin_x, origin_y)

# ── Grid acquisition loop ────────────────────────────────────────
total = GROUPS_Y * GROUPS_X * POS_Y * POS_X
log.info("Grid: %dx%d groups x %dx%d positions = %d acquisitions",
         GROUPS_Y, GROUPS_X, POS_Y, POS_X, total)
log.info("Group spacing: %.0f um, Position spacing: %.0f um",
         GROUP_SPACING, POS_SPACING)

results = []
t0 = time.perf_counter()

for gy in range(GROUPS_Y):
    for gx in range(GROUPS_X):
        group_idx = gy * GROUPS_X + gx
        compartment = f"Compartment_Z00_Y{gy:02d}_X{gx:02d}"
        destination = ACQ_DIR / "data" / "Carrier_000" / compartment

        log.info("=== Group %d (%s) ===", group_idx, compartment)

        for py in range(POS_Y):
            for px in range(POS_X):
                pos_idx = py * POS_X + px
                naming = {"G": group_idx, "P": pos_idx, "V": 0}
                acq_num = len(results) + 1

                # Compute absolute stage position
                x_target = origin_x + gx * GROUP_SPACING + px * POS_SPACING
                y_target = origin_y + gy * GROUP_SPACING + py * POS_SPACING

                log.info("  [%d/%d] G=%d P=%d -> X=%.1f Y=%.1f um",
                         acq_num, total, group_idx, pos_idx,
                         x_target, y_target)

                # Move stage
                move = drv.move_xy(client, x_target, y_target)
                if not move.get("success"):
                    log.error("  Move failed: %s", move.get("message"))
                    results.append({
                        "group": group_idx, "pos": pos_idx,
                        "success": False, "time": 0,
                    })
                    continue

                # Stash baseline
                baseline = drv.read_relative_path(client)

                # Acquire
                acquire_start = time.time()
                acq = drv.acquire(client, JOB_NAME)
                if not acq.get("success"):
                    log.error("  Acquisition failed: %s", acq.get("message"))
                    results.append({
                        "group": group_idx, "pos": pos_idx,
                        "success": False, "time": 0,
                    })
                    continue

                # Confirm, rename, move
                result = drv.confirm_acquisition(
                    client,
                    baseline=baseline,
                    media_path=media_path,
                    destination=str(destination),
                    naming=naming,
                    expected_channels=EXPECTED_CHANNELS,
                    expected_z=EXPECTED_Z,
                    expected_t=EXPECTED_T,
                    acquire_start=acquire_start,
                    fix_ome=True,
                    stability_timeout=60,
                    cleanup_source=True,
                )

                status = "OK" if result["success"] else "FAILED"
                log.info("  %s in %.1fs", status, result["total_s"])

                results.append({
                    "group": group_idx, "pos": pos_idx,
                    "success": result["success"],
                    "time": result["total_s"],
                })

# ── Summary ───────────────────────────────────────────────────────
elapsed = time.perf_counter() - t0
ok = sum(1 for r in results if r["success"])
log.info("=== SUMMARY ===")
log.info("%d/%d acquisitions successful in %.1fs", ok, len(results), elapsed)
for r in results:
    tag = "OK  " if r["success"] else "FAIL"
    log.info("  G%05d P%05d: %s (%.1fs)", r["group"], r["pos"], tag, r["time"])

# Show final tree
log.info("=== FILES ===")
data_dir = ACQ_DIR / "data"
if data_dir.is_dir():
    for p in sorted(data_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(data_dir)
            log.info("  %s  (%d bytes)", rel, p.stat().st_size)
