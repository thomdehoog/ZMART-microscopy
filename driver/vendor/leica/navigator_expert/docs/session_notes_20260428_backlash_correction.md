# Session notes — 2026-04-28: stage backlash correction

> Historical note: this document describes pre-restructure paths and workflow state.
Following up on open item (4) from `session_notes_20260427_registration.md`:
the iterative stage cookbook hits a 1–2 µm noise floor that is mechanical,
not algorithmic. This session formalises the backlash recipe and adds two
new cookbook variants that apply it consistently.

## What the stage actually does

Backlash is not a random error — it is a position offset that depends on
which side of the leadscrew slack the nut is currently resting on. The
stage has two possible "true positions" for any commanded coordinate:
slack-on-left or slack-on-right. Approach-move discipline forces the
stage into the same slack-state every time, turning a variable offset
into a constant one (which is invisible — everything is shifted by the
same tiny amount).

Sources of total error on this stage, ranked from yesterday's data and
hardware class:

- Backlash: ~3–5 µm (dominant component of the 5–10 µm total error)
- Stiction / first-move-from-rest: ~1–2 µm one-time cost
- Servo settling, controller noise: ~1 µm
- Y is measurably worse than X (asymmetric stage geometry, cable drag,
  mass distribution — see `session_notes_20260427` Phase 1 table)

Approach moves remove backlash but do nothing for the other components.
Floor for this stage without hardware upgrades: ~3 µm.

## The recipe

Coordinate convention: **top-left = (0, 0)**, **bottom-right = max**.
This is the LAS X stage convention with `ImageTransformation = TOPLEFT`.

For any commanded `(target_x, target_y)`:

1. Move to `(target_x − 50, target_y − 50)` — top-left of target
2. Wait 100 ms — lets the controller close out the move and prevents it
   from blending the next command into one curved trajectory
3. Move to `(target_x, target_y)` — final leg is +X and +Y simultaneously

The final 50 µm leg is where the magic happens. Everything before it
(parcentricity shift, joystick jog, prior approach, whatever) does not
count — the slack-state is determined entirely by the last leg of motion.

### Why 50 µm

The overshoot must be larger than the backlash, with margin. Backlash on
this stage is 3–5 µm, so 10× margin gets us 50 µm. Additional reasons:

- Position-dependent backlash variation (some stages have more slack at
  certain points along the screw)
- Time cost is negligible (~100 ms extra per move on this stage)
- Failure mode of an overshoot smaller than the actual backlash is
  silent: the motor reverses but the stage never crosses the slack
  zone, so no slack is taken up

Don't go below 30 µm. 100 µm is fine if a future stage is worse.

### Why 100 ms

Some controllers blend consecutive move commands into one smoothed
trajectory. If they do, the "two distinct moves" become "one curved
move" and you don't get a clean direction reversal — no slack takeup.

A fixed pause guarantees the controller treats them as separate moves.
100 ms works without polling. If `move_xy` already blocks until
the tolerance is met (it does), the pause is technically belt-and-
braces — keep it for safety until verified otherwise.

### Why diagonal, not two single-axis moves

A diagonal final approach handles both axes' backlash with one move
instead of two. Both leadscrews engage their +flanks simultaneously
during the `(+50, +50)` final leg. Sequential X-then-Y would need two
clean approach legs and a settle between them — slower, no accuracy
benefit.

The pre-positioning move itself can be anything — straight, curved,
whatever the controller does. Only the final 50 µm leg from
pre-position to target needs both axes moving in +.

## The catch: source images need the same discipline

The coordinates extracted from a 10× overview are only meaningful in
whatever slack-state the stage was in **when that image was acquired**.
If the source image was grabbed with the stage in slack-state A (came
in from some random direction) and we then drive to that coordinate
using approach moves which put the stage in slack-state B, we have
baked a backlash-sized offset directly into the targeting.

So: the source image must also be acquired with the stage in the +X+Y
slack state. The cookbook scripts handle this by doing a takeup move at
the source position before acquiring — read current XY, move to
`(x − 50, y − 50)`, wait, move back to `(x, y)`, acquire. The stage
ends up at the same physical position but in a known slack-state.

## What was shipped

| Commit | Subject |
|---|---|
| _pending_ | Add backlash-corrected stage cookbook variants |

Two new cookbook scripts under
`driver/vendor/leica/cookbook/motorized_stage/`:

- `single_target_stage_one_shot_backlash_correction.py` — one-shot variant
- `single_target_stage_iterative_backlash_correction.py` — iterative variant

Both differ from their non-backlash siblings only in:

- New `_move_xy_backlash` helper that does pre-position → pause →
  final move
- Every `drv.move_xy` call routed through the helper
- Source-image takeup move added before the source acquisition
- New CLI flags: `--backlash-overshoot-um` (default 50),
  `--backlash-settle-ms` (default 100)
- Output dir, logger name, and `summary.json["method"]` get the
  `_backlash_correction` suffix
- `summary.json` now records `backlash_overshoot_um` and
  `backlash_settle_ms` so runs are reproducible

## Expected behaviour

- One-shot: should drop landing from ~3 µm to ~1–2 µm if backlash is
  the dominant remaining component on a clean +X +Y move.
- Iterative: should break through the 1–2 µm noise floor reported in
  yesterday's notes. Theoretical floor is the non-backlash residual
  (stiction, servo noise) — likely ~0.5–1 µm if the model holds.

If iterative still hits ~1–2 µm with backlash correction on, the floor
is one of: stiction recovery between iterations (mitigation: more
warm-up moves at session start), thermal drift over the iteration
period, or sub-pixel registration noise dominating real stage motion.
At that point hardware (linear encoder retrofit) is the next step, not
software.

## Open items carried forward

### 1. Tile overviews (when they exist) need the same discipline
Yet to be implemented, but flagging it now: any future tiled-overview
acquisition must approach each tile position with the same backlash
discipline, otherwise tiles register inconsistently relative to each
other and downstream coordinates carry that inconsistency.

### 2. Session-init "wake up" routine
Stiction and lubricant redistribution mean the first move from a
fully-rested stage is less accurate than subsequent moves. Standard
mitigation: drive corner-to-corner a couple of times at session start,
then approach the working area from top-left. Cheap insurance, also
serves as the slack-state reset.

Not implemented yet. Worth adding if first-move-of-session targeting
turns out to be measurably worse than steady-state.

### 3. Open items from yesterday still apply
- Parfocal dZ in cookbooks (highest leverage)
- `measure_objective_offsets.py` Phase 1 backlash compensation (item 2
  of `session_notes_20260427`) — same recipe, different script
- D4 residual guard in the calibration script
- Migrate galvo cookbook to use `registration.py`

## How to verify next session

1. Run `single_target_stage_one_shot_backlash_correction.py` on the
   same sample/objectives as yesterday's one-shot validation (~3 µm
   landing). New version should land tighter.
2. Run `single_target_stage_iterative_backlash_correction.py` and
   check whether it converges below 1 µm. If yes, the noise-floor
   diagnosis was correct. If no, look at the iteration log — is each
   correction smaller than the last (real progress) or are they
   bouncing (something else is dominant)?
3. Both scripts log `backlash_overshoot_um` and `backlash_settle_ms`
   in `summary.json` — keep these constant across runs for fair
   comparison.

## Files to know about

- `driver/vendor/leica/cookbook/motorized_stage/single_target_stage_one_shot.py` — original one-shot
- `driver/vendor/leica/cookbook/motorized_stage/single_target_stage_iterative.py` — original iterative
- `driver/vendor/leica/cookbook/motorized_stage/single_target_stage_one_shot_backlash_correction.py` — new
- `driver/vendor/leica/cookbook/motorized_stage/single_target_stage_iterative_backlash_correction.py` — new
- `driver/vendor/leica/docs/session_notes_20260427_registration.md` — yesterday's notes (open items 2 and 4 are what this session addresses)
