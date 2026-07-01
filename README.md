# ZMART Microscopy

**ZMB's Microscopy-Agnostic Research Toolkit (ZMART).**

This toolkit allows programmatic control of a wide range of microscopes with a
simple unified scripting philosophy to empower you to quickly build interoperable
adaptive feedback microscopy workflows.

<p align="center">
  <img src="docs/zmart-architecture.png" alt="ZMART sits between Jupyter notebooks and an AI coding agent above, and vendor drivers - each bound to a microscope - below" width="640">
</p>

## ZMART Controller

The vendor-agnostic API you drive a microscope from — the `zmart` surface, kept
deliberately small: **discover, then apply.** Call a `get_*` to see what the
instrument supports (each option lists its allowed values and the active one),
then pass your choice to the matching call. The same code runs on any microscope
that has a driver.

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
| ZEISS (ZEN) | ZEN API (gRPC) | [`zmart_drivers/zeiss/zenapi/`](zmart_drivers/zeiss/zenapi/README.md) | **Minimum viable product** — full offline suite green; not yet bench-validated (see [Risks](zmart_drivers/zeiss/zenapi/README.md#10-risks--bench-verify)) |
| Nikon (NIS-Elements 6.2) | NIS-Elements macros / NkSocket TCP | [`zmart_drivers/nikon/`](zmart_drivers/nikon/README.md) | **Investigation + spike** — socket round-trip proof landed; no production driver yet (device verbs still to be pinned) |
| Evident FLUOVIEW FV4000 (IX83) | FLUOVIEW RDK (TCP command server) | [`zmart_drivers/evident/`](zmart_drivers/evident/README.md) | **Investigation + planning** — RDK route mapped (Leica-CAM-symmetric); pending Evident developer-program access to the FV RDK command reference |
| mesoSPIM (open-source light-sheet) | mesoSPIM-control (PyQt5; no external API out of the box) | [`zmart_drivers/mesospim/`](zmart_drivers/mesospim/README.md) | **Investigation + planning** — GPL-3.0, driven at arm's length via a resident socket hook (Nikon-symmetric) + MIT client; uniquely offline-testable via `-D` demo mode |

The cross-vendor controller is the intended single surface above the drivers and
is still under construction; today the workflow uses the Leica driver path
directly through local bootstrap modules. As drivers mature they move up from
**Under construction** to **Production-ready**, and workflows move onto the
`zmart` surface.

## Architecture

Four roots, layered from vendor-specific up to vendor-neutral:

- **`zmart_drivers/`** — each driver speaks one microscope's native API and is keyed by
  `<vendor>/<machine>/<api>`. A driver owns its own calibration and limits. New
  microscopes are added here without touching workflows.
- **`shared/`** — vendor-independent utilities: the lab-wide output layout and
  image algorithms (registration, focus) used across drivers and workflows.
- **`zmart_controller/`** — the cross-vendor controller: one small, consistent interface
  a workflow drives, so the same workflow runs on any microscope that has a
  driver. This is the **emerging `zmart` surface** — the vendor-agnostic API the
  rest of the world would import. See its README for the full API and for how to
  register a new driver.
- **`workflows/`** — the smart-microscopy workflows themselves (current:
  `workflows/target_acquisition/`).

## Getting Started

Install the Python environment. We use [conda-forge](https://conda-forge.org) to
avoid licensing issues. Build it in one step, then activate:

```powershell
python build_env.py            # creates the "smart-microscopy" conda-forge env
conda activate smart-microscopy
```

This targets **Python 3.10-3.12** and installs the minimum to drive a microscope
and process its images. Driving a microscope *live* also needs that microscope's
own software installed (e.g. LAS X for the Leica driver); registration, focusing,
and image processing run on any OS. Full setup — dependency rationale, the
conda-forge / PyPI choice, and the typical path through the repo — is in
**[`getting_started/`](getting_started/README.md)**.

## Tests

Every component ships its own **offline** suite that needs no microscope and no
vendor software, and documents how to run it in its own README:

- Controller — [tests](zmart_controller/README.md#tests)
- Target-acquisition workflow — [tests](workflows/target_acquisition/README.md#tests)
- Output layout — [tests](shared/output_layout/README.md#tests)
- Leica driver — [testing](zmart_drivers/leica/stellaris5_y42h93/navigator_expert/README.md#testing) (incl. gated live validation)
- Zeiss driver — [testing](zmart_drivers/zeiss/zenapi/README.md#9-testing)

Live hardware validation is always explicit, gated, and safe by default.
