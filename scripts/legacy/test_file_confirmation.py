"""Test the full acquisition + file confirmation flow.

Connects to LAS X, acquires a HiRes image, then runs the 10-step
file confirmation routine: detect → stabilise → validate → rename →
move → confirm.
"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "controller" / "vendor" / "leica"))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

# ── Logging — see everything ────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_file_confirmation")

# ── Configuration ───────────────────────────────────────────────
JOB_NAME = "HiRes"
EXPERIMENT = "untitled_experiment"  # e.g. "rare_event_detection"
ACQ_TYPE = "Overview_Scan"     # default acquisition type folder name
EXPECTED_CHANNELS = 3
EXPECTED_Z = 1
EXPECTED_T = 1

# Destination follows: SMART/YYYYMMDD_HHMMSS_[experiment]/Overview_Scan/data/Carrier_000/Compartment_Z00_Y00_X00/
# SMART sits next to the LAS X "Experiments" folder under Temporary_Data.
# Each acquisition type gets: data/ (raw), analysis/ (pipeline output), feedback/ (loop decisions).
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
DESTINATION_ROOT = Path("Z:/zmbstaff/10374/Temporary_Data")
ACQ_DIR = (
    DESTINATION_ROOT
    / "SMART"
    / f"{timestamp}_{EXPERIMENT}"
    / ACQ_TYPE
)
DESTINATION = (
    ACQ_DIR
    / "data"
    / "Carrier_000"
    / "Compartment_Z00_Y00_X00"
)

# Pre-create sibling folders for downstream pipeline
(ACQ_DIR / "analysis").mkdir(parents=True, exist_ok=True)
(ACQ_DIR / "feedback").mkdir(parents=True, exist_ok=True)

# ── Connect ─────────────────────────────────────────────────────
client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    log.error("Cannot connect to LAS X.")
    sys.exit(1)
log.info("Connected to LAS X")

# ── Read settings ───────────────────────────────────────────────
settings = drv.get_lasx_settings()
if settings is None or "export" not in settings:
    log.error("Cannot read LAS X settings — is Navigator Expert configured?")
    sys.exit(1)

media_path = settings["export"]["media_path"]
log.info("Media path: %s", media_path)
log.info("Auto-export: %s", settings["export"].get("auto_export"))

# ── Step 1: stash baseline ──────────────────────────────────────
baseline = drv.read_relative_path(client)
log.info("Baseline RelativePathName: %r", baseline)

# ── Auto-increment P ────────────────────────────────────────────
next_p = drv.next_position_index(DESTINATION)
naming = {"G": 0, "P": next_p, "V": 0}
log.info("Naming: %s (P auto-incremented to %d)", naming, next_p)

# ── Log predicted manifest ──────────────────────────────────────
# job_index not known until after acquisition — J will come from source filenames
manifest = drv.predict_manifest(EXPECTED_CHANNELS, EXPECTED_Z, EXPECTED_T, naming)
log.info("=== EXPECTED FILES (%d) ===", manifest["total"])
log.info("  destination: %s", DESTINATION)
for name in manifest["image_names"]:
    log.info("  [image] %s", name)
for name in manifest["xml_names"]:
    log.info("  [xml]   metadata/%s", name)
log.info("=== END EXPECTED FILES ===")

# ── Step 2: acquire ─────────────────────────────────────────────
log.info("Starting acquisition: %s", JOB_NAME)
acquire_start = time.time()  # for mtime fallback
acq_result = drv.acquire(client, JOB_NAME)
if not acq_result.get("success"):
    log.error("Acquisition failed: %s", acq_result.get("message"))
    sys.exit(1)
log.info("Acquisition complete in %.1fs", acq_result["timing"]["total_s"])

# ── Steps 3–10: confirm acquisition ────────────────────────────
log.info("Running file confirmation...")
result = drv.confirm_acquisition(
    client,
    baseline=baseline,
    media_path=media_path,
    destination=str(DESTINATION),
    naming=naming,
    expected_channels=EXPECTED_CHANNELS,
    expected_z=EXPECTED_Z,
    expected_t=EXPECTED_T,
    acquire_start=acquire_start,
    fix_ome=True,
    stability_timeout=60,
    cleanup_source=True,
)

# ── Report ──────────────────────────────────────────────────────
if result["success"]:
    log.info("SUCCESS in %.1fs", result["total_s"])
    log.info("Files at: %s", DESTINATION)
    # List what ended up at destination
    if DESTINATION.is_dir():
        for f in sorted(DESTINATION.iterdir()):
            if f.is_file():
                log.info("  %s  (%d bytes)", f.name, f.stat().st_size)
        meta = DESTINATION / "metadata"
        if meta.is_dir():
            for f in sorted(meta.iterdir()):
                if f.is_file():
                    log.info("  metadata/%s  (%d bytes)", f.name, f.stat().st_size)
else:
    log.error("FAILED: %s", result.get("error"))
    for step_name, step_result in result.get("steps", {}).items():
        if isinstance(step_result, dict) and not step_result.get("success", True):
            log.error("  Step '%s': %s", step_name,
                      step_result.get("error") or step_result.get("issues"))
