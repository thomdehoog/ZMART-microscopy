# Instrument state — field list

Working checklist of every field that should be in the instrument state.
Prose background lives in `state-contract.md`; this file is the flat list we
enrich with the concrete API/log mapping.

Columns:
- **Field** — the state key.
- **In state** — present in `get_state` today? (yes / export-only / no / partial)
- **API reader** — the LAS X CAM call that supplies it. _(to enrich)_
- **Log reader** — the log-parse source, if any. _(to enrich)_
- **Mode** — preferred read mode (api / log / hybrid). _(to enrich)_
- **Notes**

## Identity

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| vendor | yes | — | — | — | from connection dict |
| microscope_id | yes | — | — | — | from connection dict |
| api | export-only | — | — | — | from connection dict |
| serial_number | yes | | | | stable per connection |
| system_type | yes | | | | real vs simulator |
| stand | yes | | | | microscope name |
| driver_version | export-only | — | — | — | from package |
| client | export-only | — | — | — | from connection dict |

## Objective turret

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| turret_map (slot → objectiveNumber) | yes | | | | |
| active_objective (slot/name/mag/NA) | yes | | | | from selected job settings |
| objective_names (slot → name) | partial | | | | full map wanted |

## Selected job & catalog

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| selected_job (changeable) | yes | | | | the set_state promise |
| selected_job_record | yes | | | | full record |
| jobs (normal catalog) | yes | | | | |
| autofocus_jobs | yes | | | | separate category |
| current_block / element | partial | | | | matrix-job position (log) |

## Imaging geometry

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| image_format (W × H) | via job | | | | |
| pixel_size_x/y (µm) | yes | | | | |
| fov_um | derivable | | | | get_fov |
| base_fov_um (zoom 1) | derivable | | | | get_base_fov |
| zoom | via job | | | | |
| scan_field_rotation | via job | | | | |

## Position

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| stage_xy_um (motoric) | export-only | | | | via get_xyz |
| z_wide_um | export-only | | | | |
| z_galvo_um | export-only | | | | |
| focus_sum / frame_z_um | export-only | — | — | — | derived |
| frame_xyz (compensated) | export-only | — | — | — | adapter frame math |

## Scan / acquisition condition

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| scan_status (idle/running) | no | | | | **gap — add to observed** |
| pending_dialog (blocking modal) | no | | | | **gap — add to observed** |
| scan_speed / resonant | via job | | | | |
| z_stack_definition | via job | | | | begin/end/step/sections |
| frame/line accumulation & average | via job | | | | |
| pinhole_airy | via job | | | | |
| detector_gain | via job | | | | |
| laser_intensity / shutter | via job | | | | |
| filter_wheel slot / spectrum | via job | | | | |

## Machine configuration (setup-notebook outputs)

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| limits (path/source/is_fallback) | yes | — | — | — | commands gate |
| orientation (turn/mirror/measured) | via setup | — | — | — | ProgramData, loaded at connect |
| calibration_readiness | via setup | — | — | — | measured vs placeholder slots |
| origin (frame zero + objective) | export-only | — | — | — | handle |
| setup.ready + issues | yes | — | — | — | adapter verdict |

## Provenance (export state only)

| Field | In state | API reader | Log reader | Mode | Notes |
|---|---|---|---|---|---|
| session_hash6 | export-only | — | — | — | |
| acquisition_hash | export-only | — | — | — | |
| acquisition_type | export-only | — | — | — | |
| position_label | export-only | — | — | — | |
| exported_at | export-only | — | — | — | UTC timestamp |

## Gaps to act on

1. Add **scan_status** and **pending_dialog** to `observed` — readers supply
   both.
2. Decide whether **position** belongs in `get_state` (currently export-only).
3. Promote **geometry** (fov, base_fov, zoom, rotation) to first-class fields
   rather than leaving them inside the raw job record.
4. Make the **read mode** explicit per field (fresh API where staleness
   matters; log/cache where it does not).
5. Populate the full **objective_names** slot→name map.
