# What should be in the instrument state

Status: reference / working note. Describes the intended contents of the
Leica driver's `get_state` and the acquisition export state, where each value
comes from, and the gaps between what is captured today and what the readers
can supply.

## The two states, and why they differ

There are two related snapshots, and it helps to keep them apart:

- **`get_state(handle)`** — the controller-facing instrument state. Two
  halves: `changeable` (what `set_state` will reapply — today just the
  selected job) and `observed` (a read-only report of identity and
  condition). This is what a workflow reads to know what it is driving.
- **The acquisition export state** (`_export_state`) — a per-image snapshot
  embedded in every saved OME-TIFF, so each file records the exact machine
  and software condition it was captured under. Best-effort: any missing
  reader degrades to `None` rather than failing the save.

Both are assembled from the **readers**, and both should draw on the same
underlying facts.

## Where the values come from: the reader families

Every observed value has a source, and the driver has three:

- **API readers** (`readers/api_reader.py`) — live calls into the LAS X CAM
  API. Authoritative and current, but each one costs a round-trip and can
  block if LAS X is busy.
- **Log readers** (`readers/log_reader.py`) — parse the LAS X log files
  (`lcs`, `msgbox`) on disk locally. No round-trip, survive a busy or
  momentarily unresponsive LAS X, but only as fresh as the last line written,
  so each reading carries an age.
- **The router** (`readers/router.py`) — the `mode` selector (`api`, `log`,
  or the default hybrid) that decides, per datum, whether to trust the API,
  fall back to the log, or race them. The state should name its `mode` per
  value where it matters, not silently assume one.

A state field's entry below lists which family can supply it. "Both" means
the hybrid router already covers it; "API only" or "log only" flags a value
that has a single source today.

## The state contract — everything that should be present

### Identity (who this instrument is)

| Field | Source | In state today |
|---|---|---|
| vendor | connection dict | yes |
| microscope id | connection dict | yes |
| api name | connection dict | export only |
| serial number | API (hardware info) | yes |
| system type (real vs simulator) | API (hardware info) | yes |
| stand / microscope name | API (hardware info) | yes |
| driver version | package | export only |
| client kind (PythonClient…) | connection dict | export only |

Identity is stable for a connection; reading it once at connect and caching
would be legitimate, but it must be present in both states so a saved image
can be traced to the exact instrument and driver build.

### Objective turret (which lenses, which one is active)

| Field | Source | In state today |
|---|---|---|
| turret map (slot → objectiveNumber) | API (hardware info) | yes |
| active objective (slot, name, magnification, NA) | API (job settings) | yes |
| per-slot objective names | API (hardware info) | partial |

The objective is the field that changed most this session: it can move via a
direct objective change *or* via a job change that carries a different lens.
The state's active-objective read must always come from the currently
selected job's settings (it does), so a job switch is reflected immediately.

### Selected job and job catalog (the unit of configuration)

| Field | Source | In state today |
|---|---|---|
| selected job name (`changeable`) | Both | yes |
| full selected-job record | Both | yes |
| normal job catalog | Both | yes |
| autofocus job catalog (separate category) | Both | yes |
| current block / element within a matrix job | log | partial |

The job is deliberately the whole `changeable` promise: reapplying the
selection restores the configuration. The catalog belongs in `observed` so a
workflow can see what else is selectable without a second call.

### Imaging geometry (how pixels map to the stage)

| Field | Source | In state today |
|---|---|---|
| image format (W × H) | API (job settings) | via job |
| pixel size x/y (µm) | API (job settings) | yes |
| field of view (µm) | Both (`get_fov`) | derivable |
| base FOV (zoom 1) | Both (`get_base_fov`) | derivable |
| zoom | API (job settings) | via job |
| scan field rotation | API (job settings) | via job |

Geometry is what turns a found cell into a stage move, so it must be
self-consistent with the orientation and the objective. Pixel size is
surfaced directly; the rest ride inside the job record but deserve to be
first-class if a consumer other than the widget needs them.

### Position (where the stage and focus are)

| Field | Source | In state today |
|---|---|---|
| stage XY (motoric, µm) | Both (`get_xy`) | export (via get_xyz) |
| z-wide (µm) | Both (`read_zwide_um`) | export (via get_xyz) |
| z-galvo (µm) | API (job settings) | export (via get_xyz) |
| focus sum / frame z | derived | export |
| objective-compensated frame XYZ | adapter (frame math) | export (get_xyz) |

Position is in the export state (embedded per image) but **not** in
`get_state`'s `observed` block today. That is a deliberate scope line — the
controller reads position through `get_xyz`, not `get_state` — but worth
confirming it is intentional, since a workflow inspecting state cannot see
where the stage is without a separate call.

### Scan / acquisition condition

| Field | Source | In state today |
|---|---|---|
| scan status (idle / running) | Both (`get_scan_status`) | no |
| pending LAS X dialog (blocking modal) | log (`get_pending_dialog`) | no |
| scan speed / resonant flag | API (job settings) | via job |
| z-stack definition (begin/end/step/sections) | API (job settings) | via job |
| frame/line accumulation & averaging | API (job settings) | via job |
| pinhole (Airy) | API (job settings) | via job |
| detector gain, laser intensity/shutter | API (job settings) | via job |
| filter wheel slot / spectrum | API (job settings) | via job |

`scan_status` and `pending_dialog` are the two condition signals the readers
can supply that the state does **not** surface today, and they are exactly
what a workflow wants before it fires the next step (is the scanner idle? is
a modal blocking LAS X?). Strong candidates to add to `observed`.

### Machine configuration (the setup-notebook outputs)

| Field | Source | In state today |
|---|---|---|
| limits provenance (path, source, is_fallback) | commands gate | yes |
| orientation (turn, mirror, measured flag) | ProgramData / session | via `setup` |
| calibration readiness (measured vs placeholder slots) | ProgramData / session | via `setup` |
| origin (frame zero, objective it was set under) | handle | export (via get_xyz) |
| readiness verdict (`setup.ready` + issues) | adapter | yes |

These come not from LAS X but from the machine-local ProgramData snapshots
the setup notebooks publish, loaded once at connect. The `setup` readiness
block folds them into one driver-owned verdict the workflow can gate on.

### Provenance (only in the export state)

Session hash, acquisition hash, acquisition type, position label, selected
job, and `exported_at` timestamp — the lineage that lets a saved file be
traced back to the run that produced it. Correct that this lives only in the
export state, not in `get_state`.

## Gaps and decisions (the actionable part)

1. **Add scan status and pending-dialog to `observed`.** Both readers supply
   them; a workflow should be able to see "scanner busy" or "a modal is
   blocking LAS X" from the state rather than discovering it when a command
   stalls.
2. **Decide whether position belongs in `get_state`.** It is in the export
   state and reachable via `get_xyz`, but absent from `observed`. If the
   intent is "state is configuration, position is a separate axis", say so;
   otherwise surface at least the frame XYZ.
3. **Promote geometry to first-class fields.** FOV, base FOV, zoom, and scan
   rotation are all derivable and all consumed by the pixel→stage chain;
   burying them inside the raw job record makes every consumer re-parse.
4. **Name the read `mode` per value where staleness matters.** Position and
   scan status want fresh API reads; identity and the catalog tolerate log or
   cache. The state assembles from a mix, and the mix should be explicit, not
   incidental.
5. **Confirm identity caching.** Serial, system type, stand, and turret map
   are stable per connection; reading them once at connect (like limits,
   orientation, and calibration already are) would cut per-call cost without
   changing correctness — as long as they still appear in every snapshot.
6. **Per-slot objective names are only partially populated.** The hardware
   info carries names for occupied slots; the state should carry the full
   slot→name map so a saved image records the lens by name, not just number.

## One-line summary

The state should carry, from the readers: **identity**, the **turret and
active objective**, the **selected job and catalog**, **imaging geometry**,
**position**, **scan/acquisition condition**, and the **machine-config
readiness** — each annotated with its reader source and freshness. Today it
carries identity, turret, job, geometry (partially), and readiness well;
the clear gaps are scan status, pending dialogs, position in `observed`,
and making geometry first-class.
