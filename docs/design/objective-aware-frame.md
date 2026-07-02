# Objective-aware coordinate frame — design (not yet implemented)

- **Status:** proposed 2026-07-02 · awaiting external review · nothing below is built
  except where marked BUILT.
- **Scope:** `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/`
  (frame math), `calibration/` (schema addition), driver motion guards.
- **Owner:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch ·
  thomdehoog@gmail.com

## The invariant

**Frame coordinates live in sample space: the same surface point reads the same
frame value regardless of how the actuators realize it.** Actuator positions are
how a coordinate is *realized*, never what it *means*: frame z is computed from
the focus sum (`z_wide + z_galvo`), so it is invariant under re-decomposition
between the drives (including `rebase_galvo`); `with_actuators` selects how a
move is executed, never what a coordinate denotes; and — once this design lands —
an objective change re-anchors the mapping via ΔT without moving the frame value
of a fixed sample point. Actuator state matters in exactly two places, both
consumed inside `set_xyz` and never leaking into the coordinate: decomposition
(the other drive's current position) and feasibility (the galvo range
pre-flight). Position truth is always a fresh hardware read; the frame transform
is stateless math on that measurement, never bookkeeping.

## Problem

A frame coordinate must mean the *same sample location* under any objective. Today
the adapter's frame is anchored to the origin set by `set_origin` (BUILT: persisted
machine-locally as `origin.json` in the newest machine snapshot, restored at
`connect`, records XY + both z drives + focus sum + **the objective it was set
under**) — but the frame math ignores objectives entirely; an objective change only
logs a warning. A target picked under 10x therefore does not land on the same
sample point under 63x.

## Facts the design rests on

- All stage moves are **absolute** (`RelativePosition=False` everywhere).
- Objectives change only via LAS X **job selection** (jobs own objective state).
  On a swap the **firmware itself shifts the stage** (its parcentricity/parfocality
  compensation) — an uncommanded move.
- The calibration stores, per objective, a total
  `translation_um = motor_shift + correction`, where `motor_shift` is the
  firmware's automatic swap-shift and `correction` the optical residual. Today only
  the **total** is canonical; the split lives in per-session reports.
- Z model: `focus = z_wide + z_galvo`; z-galvo is physically a ±offset riding on
  z-wide (short range); a move targets exactly ONE drive, decomposed using the
  other drive's current position. Objective z-translations are measured in z-wide
  µm but a focus µm is drive-independent (question 3 below).

## Design

### 1. Frame arithmetic (get_xyz / set_xyz) — needs only the CURRENT objective

```
ΔT       = T[current_objective] − T[origin.objective]     # calibration, XY µm + z µm
abs_xy   = origin.xy_ref    + F.xy + ΔT.xy
focus    = origin.focus_ref + F.z  + ΔT.z
→ decompose focus onto the CHOSEN z drive (other drive's current position)
```

Stateless per call: the hardware snapshot already carries the current objective and
`origin.json` carries the anchor objective. **No-double-counting claim:** because
every commanded move is absolute, the *total* translation subsumes whatever the
firmware did at swap time; the motor_shift/correction split is NOT needed for
target computation. Side effect: after a swap with no commanded move, an
objective-aware `get_xyz` reads the residual truthfully (perfect firmware
compensation ⇒ frame value unchanged; otherwise the frame shows −correction).

### 2. Calibration schema addition — the split, for VERIFICATION not arithmetic

Store `motor_shift` / `correction` per objective pair in the canonical
`calibration.json` (today report-only). At use time, when the adapter itself
performs a swap (its `select_job` paths in `acquire`/`set_state`), it **brackets**
it: read position+objective → swap → read again. The uncommanded delta is the
firmware's *current* motor_shift; a mismatch vs. the recorded value beyond
tolerance ⇒ **fail closed** ("LAS X compensation tables changed since calibration —
re-run the objective-pair session"). Same record-then-verify pattern as the
existing `image_to_stage_hash` gate.

Swaps happening OUTSIDE the session (operator in the LAS X GUI between adapter
calls) are **detectable** (handle tracks last-seen objective) but **not
attributable** (other moves may have occurred) ⇒ warn, don't fail (question 4).

### 3. Guards

- **Galvo pre-flight:** validate the z decomposition *before* the XY leg, so a
  galvo target outside its physical range refuses the WHOLE move with an
  actionable message ("focus target needs the galvo at +312 µm (range ±200): move
  with z-wide instead, or rebase the galvo") — instead of today's order (XY moves,
  then z fails, stage left at new XY with old focus).
- **Missing calibration entry** for either objective ⇒ refuse cross-objective
  moves.
- **`rebase_galvo` procedure** (via `get_procedures`): z-wide absorbs the current
  galvo offset, galvo returns to 0, net focus unchanged. A deliberate operator
  action — never implicit — resolving "the galvo needs to be reset sometime"
  without breaking the invariant that a galvo move never moves the motor.

## Open questions (for external review)

1. Is the no-double-counting claim (absolute moves ⇒ total subsumes firmware
   swap-shift) airtight? What breaks it — any relative-move path, or firmware
   compensation applied to *reads* rather than positions?
2. Is bracketed-swap measurement sound, and is the firmware shift reproducible
   enough per objective pair to gate on? What tolerance? (Planned: validation pass
   on the LAS X simulator + scope.)
3. Any optical reason a galvo-realized µm ≠ z-wide-realized µm that breaks
   applying the z translation in focus-sum space?
4. Warn-don't-fail for out-of-session swaps: acceptable, or should the frame
   refuse moves until re-verified by a bracketed re-swap?
5. Schema: decomposition as new per-pair fields WITHOUT a calibration schema-version
   bump (unknown fields tolerated; verified-when-present, like `image_to_stage_hash`)
   vs. required-with-bump?

## Journal — evidence, not truth

The frame does NOT depend on tracked state to know the current position: the
hardware is the only position truth (fresh snapshot per call, readback-confirmed
moves, nothing dead-reckoned). A log that became the position truth would drift
from reality at the first unwitnessed event (GUI action, crash) — the classic
mutable-shared-state trap. What IS missing is an **append-only machine-local
journal** (JSONL, `…/<vendor>/<microscope>/<api>/journal/YYYY-MM-DD.jsonl`, session
hash on every line) recording what *happened*:

- `connect` (+ which persisted origin was restored, its age/objective),
- `set_origin` (full reference), `set_xyz` (target + confirmed readback),
- **bracketed swap measurements** (uncommanded delta vs. recorded motor_shift) —
  accumulated across sessions this dataset answers open question 2
  (reproducibility/tolerance of the firmware shift),
- out-of-session change detections (objective/position differs from the last
  session's final state).

The driver already produces the raw material (structured command envelopes with
timing/logs; validator JSONL records); the journal is a thin appender, not new
machinery. Run provenance stays with the run (`save()` lineage) — the journal is
the machine's diary.

## Sequencing

The galvo pre-flight + `rebase_galvo` (guards, no calibration dependency) are
separable and can land before the review verdict, as can the journal (pure
observation, no behavior change). The frame arithmetic + schema addition + swap
gate land together, after review.
