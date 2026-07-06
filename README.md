# ZMART Microscopy

**ZMB's Microscopy-Agnostic Research Toolkit (ZMART).**

This toolkit gives you programmatic control of a wide range of microscopes
through a simple, unified scripting philosophy, so you can quickly build
interoperable, adaptive feedback microscopy workflows. It is developed at the
Center for Microscopy and Image Analysis (ZMB), University of Zurich.

<br/>

<p align="center">
  <img src="docs/zmart-architecture.png" alt="ZMART sits between Jupyter notebooks and an AI coding agent above, and vendor drivers - each bound to a microscope - below" width="100%">
</p>

<br/>

## ZMART Controller

The vendor-agnostic API for driving a microscope — small, consistent, and the
same for every vendor. The pattern is always **discover, then apply**. Call a
`get_*` to see what the instrument supports; each option lists its allowed values
and the one that's active. Then pass your choice to the matching call. Write it
once, and it runs on any microscope that has a driver.

Full API and per-call docs: **[ZMART Controller »](zmart_controller/README.md)**

```python
import zmart_controller

# 1) Get the available instruments and connect to one
zmart_controller.get_instruments()
zmart_controller.set_instrument(instrument=Dict)

# 2) Set the origin point of the frame (current position becomes 0, 0, 0)
zmart_controller.set_origin()

# 3) Discover actuators, then read or move the position in the frame
zmart_controller.get_actuators()
zmart_controller.get_xyz()
zmart_controller.set_xyz(x, y, z, with_actuators=Dict)

# 4) Capture and reapply instrument state
zmart_controller.get_state()
zmart_controller.set_state(Dict)

# 5) Acquire data (captures and saves) with the current state and position
zmart_controller.get_acquisition_options()
zmart_controller.acquire(acquisition_type=String, position_label=String, options=Dict)

# 6) Run a procedure specific to the microscope (e.g. hardware autofocus)
zmart_controller.get_procedures()
zmart_controller.set_procedure(Dict)

# 7) Get additional context the driver provides (e.g. initial positions)
zmart_controller.get_context()

# 8) Close the session
zmart_controller.disconnect()
```

## ZMART Drivers

Drivers live under `zmart_drivers/<vendor>/<machine>/<api>/` and are registered with
the controller through its registry (see the controller README), so adding a
vendor, microscope, or API is an additive change. Each driver documents its own
command model, state handling, and gotchas in its own README.

### Production-ready

| Microscope | API | Driver | Status |
|---|---|---|---|
| Leica STELLARIS 5 | LAS X CAM / Navigator Expert | [`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/README.md) | **Production-tested** — LAS X simulator + real STELLARIS |

### Under construction

| Microscope | API | Driver | Status |
|---|---|---|---|
| mesoSPIM (open-source light-sheet) | mesoSPIM-control (PyQt5; resident socket hook) | [`zmart_drivers/mesospim/`](zmart_drivers/mesospim/README.md) | **Demo-validated — near production** — the full round-trip **incl. `acquire`** passes against a live mesoSPIM `-D` demo (real software, simulated hardware); 111 offline + headless-Qt + live-demo tests green, `run_ci.py` runs offline/online/both. GPL app driven at arm's length via a resident hook + MIT client. Pending real-hardware validation |
| ZEISS (ZEN) | ZEN API (gRPC) | [`zmart_drivers/zeiss/zenapi/`](zmart_drivers/zeiss/zenapi/README.md) | **Minimum viable product** — full offline suite green; not yet bench-validated (see [Risks](zmart_drivers/zeiss/zenapi/README.md#10-risks--bench-verify)) |
| Nikon (NIS-Elements 6.2) | NIS-Elements macros / NkSocket TCP | [`zmart_drivers/nikon/`](zmart_drivers/nikon/README.md) | **Investigation + spike** — socket round-trip proof landed; no production driver yet (device verbs still to be pinned) |
| Evident FLUOVIEW FV4000 (IX83) | FLUOVIEW RDK (TCP command server) | [`zmart_drivers/evident/`](zmart_drivers/evident/README.md) | **Investigation + planning** — RDK route mapped (Leica-CAM-symmetric); pending Evident developer-program access to the FV RDK command reference |

The ZMART Controller is meant to be the single surface every workflow drives, but
it is still under construction — so today's workflows call the Leica driver
directly. As each driver matures it graduates from **Under construction** to
**Production-ready**, and workflows move onto the controller.

## Architecture

The top-level layout — vendor-specific drivers up to vendor-neutral workflows,
plus setup and docs:

- **`zmart_drivers/`** — each driver speaks one microscope's native API and is keyed by
  `<vendor>/<machine>/<api>`. A driver owns its own calibration and limits. New
  microscopes are added here without touching workflows.
- **`zmart_controller/`** — the cross-vendor controller: one small, consistent interface
  a workflow drives, so the same workflow runs on any microscope that has a
  driver. This is the **emerging `zmart` surface** — the vendor-agnostic API the
  rest of the world would import. See its README for the full API and for how to
  register a new driver.
- **`shared/`** — vendor-independent utilities: the lab-wide output layout and
  image algorithms (registration, focus) used across drivers and workflows.
- **`workflows/`** — the zmart-microscopy workflows themselves (current:
  `workflows/target_acquisition/`).
- **`getting_started/`** — setup and orientation: the one-step environment build,
  the conda-forge / PyPI rationale, and the typical path through the repo.
- **`docs/`** — project docs: the ZMART identity and architecture
  (`docs/ZMART.md`), the diagram, and design notes.

## Getting Started

Three steps to go from a clone to driving the microscope (full detail in
**[`getting_started/`](getting_started/README.md)**).

**1. Install the environment** — conda-forge, built in one step, then activate:

```powershell
python build_env.py            # creates the "zmart-microscopy" conda-forge env
conda activate zmart-microscopy
```

Targets **Python 3.10-3.12**. Live control needs the microscope's own software
installed (e.g. LAS X for the Leica driver); registration/focusing run on any OS.

**2. Set the stage limits** — the driver refuses to move until machine-local
limits exist (no bundled fallback). Run
`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_stage_limits.ipynb`
once; it publishes a single `limits.json` for this machine.

**3. Run it** — from the Leica driver dir, `python run_ci.py online` (read-only),
then `python run_ci.py online --live-writes` for the full bench validation. Each
driver's README documents its own run steps.

