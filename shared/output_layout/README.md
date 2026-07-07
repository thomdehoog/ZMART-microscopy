# output_layout

Lab-wide canonical **naming and directory layout** for zmart-microscopy outputs.
Vendor-independent: drivers and workflows across the repo write their acquisition
products through this one module so every run lands in the same, sortable shape.

```text
<output_root>/<acquisition_type>/<acquisition_type>_<hash6>_<position_label>_c<cc>_z<zzzzz>.ome.tiff
```

The image layout is **flat**: one folder per acquisition type, one 2-D plane
per file, keyed only by channel (`c`) and z-slice (`z`). There is **no sidecar
`.ome.xml`** — the machine/software state at export time is embedded directly
in each plane's OME-XML. `hash6` is minted **per acquisition** and is base36
seconds-since-2026-01-01 UTC — chronologically meaningful and lexicographically
sortable. `position_label` is sanitized to `[A-Za-z0-9_-]` and length-capped.

Pure functions plus the frozen `Naming` / `LayoutPlan` dataclasses; only
`build_layout` does I/O (creates the run directory). Key entry points:
`Naming`, `run_hash`, `build_image_name`, `acquisition_dir`, `build_layout`,
`parse_image_name`. (`build_xml_name` / `build_position_analysis_name` remain
for the not-yet-migrated per-position analysis workflow.)

## Tests

Offline, pure-function unit tests (no microscope, no vendor software). Run from
the repo root:

```powershell
python -m pytest -q shared/output_layout/tests
```

## Author

Thom de Hoog — Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com). MIT License.
