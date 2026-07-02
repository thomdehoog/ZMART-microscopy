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

The loop closes with a single write path: **moving IS writing actuators**.
``set_xyz`` means "change the actuators such that the frame reads the target" —
intent in frame space, action in actuator space, truth by fresh read, history in
the journal. There is no other way anything changes, which is why the model
cannot drift.

Two compressions of the whole design (operator's words, 2026-07-02):

- **"Everything becomes a relative movement in an absolute system."** The frame
  carries relative *meaning* (µm from your zero; A→B); execution is always
  absolute *positions*. Relative meaning is what you think in; absolute
  execution is what makes it drift-proof. The mirror image — absolute meaning
  realized by relative moves — is dead reckoning, which this design bans.
- **"The base might just change — and that is what objectives do."** Exactly two
  base events exist: ``set_origin`` (the operator *chooses* the base) and an
  objective swap (physics *shifts* the base). ΔT is the change-of-base term;
  frame values of fixed sample points survive it because the transform absorbs
  the shift.
- **"On an objective change, XY and z-wide just change — not the absolute
  system."** Three layers, only the middle one jumps at a swap: the absolute
  coordinate system (stage encoders) never changes and is the bedrock that makes
  absolute execution drift-proof; the actuator *values* within it jump (the
  firmware's shift, XY + z-wide only — the galvo is orthogonal to the objective
  story); the frame's *base* (sample↔absolute mapping) shifts by the optical
  offset, and ΔT re-anchors it.

The complete taxonomy of change — three event kinds, each touching a different
layer:

1. **Commanded move** — exactly one actuator (the actuator of interest) absorbs
   one delta, computed fresh (`target − current`) and commanded as an absolute
   position: relative in meaning, absolute in execution. Other actuators held by
   construction.
2. **Objective swap** — XY + z-wide values jump (firmware); the frame base
   shifts; ΔT re-anchors; frame values of sample points survive.
3. **True absolute-system change** (stage re-home / re-initialization) — the one
   event the design cannot absorb: all absolute references die, the persisted
   origin is meaningless, the operator must re-run ``set_origin``. It is
   detectable (next connect: position/objective wildly inconsistent with the
   last journaled state ⇒ warn "re-home suspected"), so it fails loud, not
   wrong.

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
   on the LAS X simulator + scope. Must also confirm: an objective change acts on
   XY + z-wide ONLY — the galvo is orthogonal to the objective story — but since
   z-galvo is read through job settings and objective changes ride on job
   selection, verify a job swap does not carry its own galvo setpoint; if it
   does, the bracket must compare focus terms accordingly.)
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
  `get_xyz`,
- **bracketed swap measurements** (uncommanded delta vs. recorded motor_shift) —
  accumulated across sessions this dataset answers open question 2
  (reproducibility/tolerance of the firmware shift),
- out-of-session change detections (objective/position differs from the last
  session's final state).

**Line schema — every line records both sides of the invariant** (the
sample-space coordinate AND its realization), plus the origin the frame values
are measured against (frame values are meaningless across a ``set_origin``
without it):

```json
{"ts": "...", "session": "09dumk", "event": "set_xyz",
 "frame":     {"x": 25.0, "y": 25.0, "z": 2.0},
 "hardware":  {"x_um": 63585.0, "y_um": 41345.0,
               "z_wide_um": -7200.0, "z_galvo_um": 2.0},
 "objective": {"name": "HC PL APO CS 10x/0.40 DRY", "slotIndex": 0},
 "origin_ref": 1751467200.0,
 "target": {"...": "..."}, "confirmed": true}
```

The adapter already produces the frame + hardware + objective triple on every
call; the journal appends that plus ``ts`` / ``session`` / ``event`` /
``origin_ref`` (the origin's ``captured_at``) and event-specific extras.

The driver already produces the raw material (structured command envelopes with
timing/logs; validator JSONL records); the journal is a thin appender, not new
machinery. Run provenance stays with the run (`save()` lineage) — the journal is
the machine's diary.

## Sequencing

The galvo pre-flight + `rebase_galvo` (guards, no calibration dependency) are
separable and can land before the review verdict, as can the journal (pure
observation, no behavior change). The frame arithmetic + schema addition + swap
gate land together, after review.
