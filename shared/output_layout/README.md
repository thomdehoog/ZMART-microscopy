# output_layout

Lab-wide canonical **naming and directory layout** for smart-microscopy outputs.
Vendor-independent: drivers and workflows across the repo write their acquisition
products through this one module so every run lands in the same, sortable shape.

```text
media_path/smart/<experiment>_<hash6>/<acquisition-type>/{data,analysis,feedback}/
```

Filenames carry eight zero-padded dimensional slots (`k, m, g, p, t, v, c, z`);
the XML companion omits `c` and `z` (one per position, describing the c×z grid).
`hash6` is base36 seconds-since-2026-01-01 UTC — chronologically meaningful and
lexicographically sortable.

Pure functions plus the frozen `Naming` / `LayoutPlan` dataclasses; only
`build_layout` does I/O (creates the run directory). Key entry points:
`Naming`, `run_hash`, `build_image_name`, `build_xml_name`, `acquisition_data_dir`,
`build_layout`, `parse_image_name`.

## Tests

Offline, pure-function unit tests (no microscope, no vendor software). Run from
the repo root:

```powershell
python -m pytest -q shared/output_layout/tests
```

## Author

Thom de Hoog — Center for Microscopy and Image Analysis (ZMB), University of
Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com). MIT License.
