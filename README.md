# ZMART Microscopy

**ZMB's Microscopy-Agnostic Research Toolkit.** ZMART Microscopy puts microscopes
under programmatic control and runs workflows that analyze data and make acquisition
decisions live during an experiment. The design is **vendor-neutral**: a
workflow targets one small controller interface — the emerging `zmart` surface —
and any microscope with a driver behind that interface can run it.

> **The name is the point.** `zmart` is meant to be the vendor-agnostic API that
> workflows and users import; the vendor drivers (`leica`, `zeiss`, `nikon`,
> `evident`) plug in *underneath*. That is how the toolkit — and ZMB's name —
> travels to other institutes: every `import zmart` in someone else's code
> carries it. See **[`docs/ZMART.md`](docs/ZMART.md)** for the identity and the
> rebrand sequencing. (Name: **ZMART Microscopy**, repo `ZMART-microscopy`. The
> code packages — `navigator_expert`, and `controller` → `zmart` — and the conda
> env are renamed on the deliberate code pass, once the agnostic API is worth
> branding.)

## Architecture

Four roots, layered from vendor-specific up to vendor-neutral:

```text
drivers/                                        vendor microscope drivers
  <vendor>/<machine>/<api>/                     one driver per (vendor, machine, API)
  leica/stellaris5_y42h93/navigator_expert/     Leica LAS X Navigator Expert driver
    calibration/                                calibration notebooks and code
    limits/                                     safety-limit data and helpers
shared/                                         vendor-independent utilities (output layout, algorithms)
controller/                                     cross-vendor controller (single workflow-facing surface)
workflows/                                      smart-microscopy workflows
  target_acquisition/                           operator notebook, pipeline, tests
```

- **`drivers/`** — each driver speaks one microscope's native API and is keyed by
  `<vendor>/<machine>/<api>`. A driver owns its own calibration and limits. New
  microscopes are added here without touching workflows.
- **`shared/`** — vendor-independent utilities: the lab-wide output layout and
  image algorithms (registration, focus) used across drivers and workflows.
- **`controller/`** — the cross-vendor controller: one small, consistent interface
  a workflow drives, so the same workflow runs on any microscope that has a
  driver. This is the **emerging `zmart` surface** — the vendor-agnostic API the
  rest of the world would import. See its README for the full API and for how to
  register a new driver.
- **`workflows/`** — the smart-microscopy workflows themselves (current:
  `workflows/target_acquisition/`).

## ZMART Controller

The vendor-agnostic API you drive a microscope from — the `zmart` surface, kept
deliberately small: **discover, then apply.** Call a `get_*` to see what the
instrument supports (each option lists its allowed values and the active one),
then pass your choice to the matching call. The same code runs on any microscope
that has a driver.

Full API and per-call docs: **[ZMART Controller »](controller/README.md)**

```python
import controller   # the ZMART Controller (renamed to `zmart` on the code pass)

controller.get_instruments()
controller.set_instrument(instrument=connection)   # pick a scope
controller.set_origin()                            # current position -> (0, 0, 0)
controller.set_xyz(x, y, z)
controller.acquire(acquisition_type="overview", position_label="A1", options=opts)
controller.disconnect()
```

## Drivers

Drivers live under `drivers/<vendor>/<machine>/<api>/` and are registered with
the controller through its registry (see the controller README), so adding a
vendor, microscope, or API is an additive change. Each driver documents its own
command model, state handling, and gotchas in its own README.

| Microscope | API | Driver | Status |
|---|---|---|---|
| Leica STELLARIS 5 | LAS X CAM / Navigator Expert | [`drivers/leica/stellaris5_y42h93/navigator_expert/`](drivers/leica/stellaris5_y42h93/navigator_expert/README.md) | **Production-tested** — LAS X simulator + real STELLARIS |
| ZEISS (ZEN) | ZEN API (gRPC) | [`drivers/zeiss/zenapi/`](drivers/zeiss/zenapi/README.md) | **Minimum viable product** — full offline suite green; not yet bench-validated (see [Risks](drivers/zeiss/zenapi/README.md#10-risks--bench-verify)) |
| Nikon (NIS-Elements 6.2) | NIS-Elements macros / NkSocket TCP | [`drivers/nikon/`](drivers/nikon/README.md) | **Investigation + spike** — socket round-trip proof landed; no production driver yet (device verbs still to be pinned) |
| Evident FLUOVIEW FV4000 (IX83) | FLUOVIEW RDK (TCP command server) | [`drivers/evident/`](drivers/evident/README.md) | **Investigation + planning** — RDK route mapped (Leica-CAM-symmetric); pending Evident developer-program access to the FV RDK command reference |

The cross-vendor controller is the intended single surface above the drivers and
is still under construction; today the workflow uses the Leica driver path
directly through local bootstrap modules. As more drivers land, this table grows
and workflows move onto the controller surface.

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

- Controller — [tests](controller/README.md#tests)
- Target-acquisition workflow — [tests](workflows/target_acquisition/README.md#tests)
- Output layout — [tests](shared/output_layout/README.md#tests)
- Leica driver — [testing](drivers/leica/stellaris5_y42h93/navigator_expert/README.md#testing) (incl. gated live validation)
- Zeiss driver — [testing](drivers/zeiss/zenapi/README.md#9-testing)

Live hardware validation is always explicit, gated, and safe by default.
