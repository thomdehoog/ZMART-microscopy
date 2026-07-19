# Leica driver review — structure, limits, and the quirk catalog

**Scope:** the Leica STELLARIS 5 driver only
(`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`).
**Based on:** branch `claude/forfable4-document-11mxsx` (the branch with the
most recent work, 65 commits ahead of `main`).
**Date:** 2026-07-19.

This report has four parts: how the driver is organized today, the design
model we settled on for limits and motion, the plan that follows from it,
and a catalog of the quirks a systematic sweep of the code turned up.

---

## 1. How the driver is organized today

| Folder | What it does | Verdict |
|---|---|---|
| `limits/` | The operator-configured envelope: config loading, `defaults/limits.json`, the set-limits notebook | Good — keep as the pattern |
| `orientation/` | Stage/camera orientation measurement, with defaults and notebook | Good — keep as the pattern |
| `calibration/` | Objective-pair calibration: model, check, adopt, defaults, notebook, tests | Good — keep as the pattern |
| `zmart_adapter/` | The bridge that presents this driver to `zmart_controller` | Good boundary; its main file has quirks (see §4) |
| `acquisition/` | Capturing an image *and* shepherding the files: naming, saving, OME metadata | Good — a genuinely separate concern |
| `readers/` | Everything that *asks* the microscope about its state | Good split against `commands/` |
| `commands/` | Everything that *tells* the microscope to do something, incl. the safety gate | Right concept, messy inside (12 blurry modules, one 58 KB file) |
| `connection/` | Getting and holding a live LAS X session | Fine |
| `config/` | Machine profile and configuration loading | Fine, but has a layer inversion (§4.3) |
| `scanfields/` | Parsing and planning LAS X scan-field templates (LRP files) | Fine |
| `algorithms/` | Pure image math: focus scoring, registration | Clean — no findings |
| `experimental/` | LRP-editing primitives | **Untouched by decision** — observations only |
| `motion/` | Two small files: limit checks + backlash movement | **To be dissolved** (§3) |
| `tests/` | Unit, hardware, and helper tests | Contains 137 committed generated report files that should go |

The conceptual split is good: tell (`commands`), ask (`readers`), capture
(`acquisition`), policy (`limits`), setup (`calibration`, `orientation`),
plumbing (`connection`, `config`). The problems are at the edges: one folder
that should not exist (`motion`), one unsorted pile (`commands`), stray
grab-bag files at the root (`utils.py`, `_file_utils.py`), two competing
test conventions (root `tests/` vs. per-folder tests), and committed run
output (`tests/_report/`).

A guiding rule that came out of this review, worth adopting repo-wide:
**a folder's name should tell you what happens when you call something
inside it.** `readers/` — you learn something, nothing changes. `commands/`
— the microscope does something. `limits/` — you get a rule. A name like
`utils` promises nothing and therefore accumulates everything.

---

## 2. The limits model (decided)

Limits are **not just stage limits**. The limits file covers three families:

1. **Stage envelope** — allowed ranges for `x_um`, `y_um`, `z_galvo_um`,
   `z_wide_um`.
2. **Objective allow-list** — which turret slots may be selected.
3. **Setter allow-lists** — 21 imaging settings (zoom, scan speed and mode,
   z-stack shape, accumulation/averaging, pinhole, detector gain, **laser
   intensity and shutter**, filter wheel). An empty list means unrestricted.

So the definition is: **limits are the operator-configured contract of what
a session may do to the instrument** — positions, objectives, and setting
values. The stage bounds are only the geometric third of it. The third
family is what protects the sample and the detectors, not the motors.

The model, in one sentence:

> `limits/` is the rulebook; `commands/` is the only whistle; nobody above
> the whistle checks limits themselves.

Concretely:

- **`limits/` owns everything about the rule itself**: the stored envelope
  and allow-lists, the notebook that sets them, loading and validation —
  *and the check functions*, the code that answers "is this allowed?"
  Deciding what is in-bounds is limits knowledge.
- **`commands/` owns the moment of applying the rule.** The gate and the
  move/set commands ask `limits/` at the right instant and refuse to
  proceed when the answer is no. Verified in code: `commands.move_xy()`
  runs two layers before the native call can fire — the session gate
  (fail-closed if the limits handshake never succeeded) and the envelope
  check (configured envelope plus the hardcoded physical backstop).
- **Everything above** — the ZMART adapter, calibration, notebooks —
  composes commands and never re-implements a check. One rulebook, one
  whistle, and drift becomes structurally impossible rather than merely
  discouraged.

One refinement, discovered during verification: the adapter's `set_xyz`
carries a deliberate "whole-move pre-flight" — it checks the XY *and* Z
legs before any motion starts, so a move can never be left half-done (XY
moved, Z refused). That protection is worth keeping, but as a **question
the adapter asks `limits/`** (one exposed "would this whole move be
allowed?" function), not as the current re-implementation through private
`_check_*` internals. Asking the rulebook from anywhere is fine; there is
still only one copy of the rules.

---

## 3. The plan: dissolve `motion/`, single-source the limits

The `motion/` folder holds two small files, and its existence creates the
confusing situation of two different things called "limits"
(`limits/` the package and `motion/limits.py` the checks). The folder also
imports from `commands/` — a lower-sounding layer reaching upward.

### Decisions

1. **Dissolve `motion/`** — the folder disappears.
2. **`motion/limits.py` → `limits/checks.py`.** The check functions, the
   physical backstop constant, and the currently-applied envelope move into
   `limits/`. Everything named "limits" then lives in one folder.
3. **`move_xy_with_backlash` → deleted.** It fused acquisition policy
   (overshoot-then-approach choreography with baked-in 50 µm / 100 ms
   constants) into the driver. The choreography is three lines of plain
   `move_xy` calls; the adapter's acquisition routine composes it itself.
   Every leg still passes through the checked `move_xy` door, so nothing
   composed above can escape the limits.
4. **`correct_backlash` → `commands/routines.py`.** This is the one block
   that legitimately encodes stage physics (this STELLARIS has 3–5 µm of
   leadscrew slack; 50 µm overshoot is 10× margin). It stays in the driver
   — but in `commands/`, because it moves the stage, and folders must tell
   the truth. Explicitly **not** in utils: a function with physical
   side effects must not live in a folder that promises harmlessness.
5. **The adapter's duplicate limit checks are removed**, replaced by the
   single whole-move pre-flight question exposed by `limits/` (see §2).
6. **Backlash takeup is ordered from above** — by the acquisition routine
   in the adapter or by the calibration notebook — never spontaneously by
   the driver. The driver is building blocks; composition is the caller's
   job.

*(Background for readers new to the term: "backlash" is the few micrometres
of slack in the stage leadscrews. When the stage reverses direction, the
slack means the final position depends on which direction it came from.
The fix is to always finish a move from the same direction, so positions
are repeatable across an experiment.)*

### Phases

- **Phase 1 — relocate (zero behavior change).** Move the two files to
  their new homes, update the six import sites, delete the folder. Gate:
  full unit suite green with no test edits beyond import paths.
- **Phase 2 — single-source (the behavior change).** Delete
  `move_xy_with_backlash`; the adapter composes arrival itself. Remove the
  adapter's private checks; add the `limits/` whole-move pre-flight
  function. Gate: an adversarial test proving out-of-bounds targets are
  refused with no caller-side checks anywhere.
- **Phase 3 — make drift impossible.** Extract the objective and setter
  allow-list *decisions* out of the gate into `limits/checks.py` (the gate
  keeps only the refusal moment). Add a guard test that fails if any module
  outside `commands/` issues stage motion or if check functions are called
  from anywhere but `commands/`. Update the README and docstrings to state
  the model plainly.

Each phase is one commit, independently revertible. Risk concentrates in
Phase 2 and is strictly in the "legitimate move gets refused" direction,
which the existing adversarial limit tests should catch.

### Open questions attached to this plan

- `correct_backlash`: add an optional `at=(x, y)` argument so callers that
  just commanded a move can skip the position read in the hot path?
- The 3-pass default of `correct_backlash` (6 stage moves): worth a bench
  measurement; one pass may give the same guarantee after a fresh arrival.
- Near the envelope's lower edge, an overshoot waypoint (target − 50 µm)
  can be out of bounds even when the target is legal. Policy choice: clamp
  the takeup near the edge (recommended), or accept a ~50 µm strip of the
  legal area that cannot be reached with compensation.

---

## 4. The quirk catalog

A systematic sweep of the driver (two independent scans, key claims
verified by hand against the code) found that the `move_xy_with_backlash`
pattern — policy fused into mechanism — is not an isolated case. Findings
are grouped by family, most important first.

### 4.0 Headline: a physics constant that is known-wrong for this microscope

`utils.py` hardcodes `GALVO_FIELD_FRACTION = 0.667` and
`PAN_LIMIT = 0.00775`, which drive galvo-pan targeting. The comment above
them says the committed value **was measured on the ZMB STELLARIS 8, while
this driver targets the STELLARIS 5**. Unlike orientation and limits —
which are measured per machine and stored in that machine's config tree —
this scope-specific constant lives as a source literal, correctable only by
editing code. This is a correctness item, not tidiness: it belongs next to
`orientation.json` and `limits.json` as a measured, per-instrument value,
independent of any reorganization.

### 4.1 Policy fused into mechanism (the backlash family)

1. **`set_objective` and `select_job` secretly move the stage.** After the
   change, the wrapper silently fires additional `move_xy` + `move_z`
   commands to compensate parcentricity/parfocality (the small XY/Z offset
   between objectives). Record → change → compensate is welded into the
   setter; callers cannot take it apart. (`commands/commands.py:660`,
   `1644`; `commands/objective_shift.py:174`)
2. **That compensation policy is implemented twice** — once in the driver
   (`objective_shift`) and once in the adapter's per-move compensation. The
   docstring admits correctness depends on the two staying "perfectly in
   sync." This is the limits-drift structure realized in a second
   subsystem, and the most dangerous structural finding.
3. **The adapter's `set_xyz` is a god-function**: frame math, an invented
   two-leg Z plan, limit pre-flight, and the backlash call fused into one
   atomic operation. (`zmart_adapter.py:565–667`)
4. **The driver decides experiment defaults**: `get_acquisition_options`
   hardcodes `backlash_correction: True` and `strip_scan_fields: True` —
   answers that belong to the acquisition routine above.
   (`zmart_adapter.py:696`)
5. **"Success" does not mean success.** Every command profile sets
   `success_on_unconfirmed=True`, so `success: True` means "the command was
   accepted," not "it took effect." Every caller must know to also check
   `confirmed`. A workflow-continuation policy is wired into every
   primitive's return contract. (`config/profiles.py:222`,
   `commands/dispatch.py:767`)
6. **Baked policy constants inside mechanisms**: retry cadence
   `(2, 4, 8, 16)` in the LRP transaction backbone
   (`scanfields/transaction.py`); save timeouts `(120, 120, 180, 240)` in
   template restore (`scanfields/strip_restore.py`);
   `idle_streak_required = 2` inside acquire confirmation
   (`commands/confirmations.py:1097`); file-stability polling defaults in
   `_file_utils.py`; OME read timeouts plus a spawned thread inside
   metadata generation (`acquisition/ome_canonical.py`).

### 4.2 Duplicated checks (drift generators)

7. The adapter's XY+Z limit pre-flight duplicates the gate (deliberate;
   resolution decided in §2 — keep the protection, single-source the
   implementation).
8. `move_xy`/`move_z` run **two overlapping limit mechanisms** with two
   different failure styles: the gate refusal returns a result dict, the
   envelope check raises an exception. (`commands/commands.py:1242`, `1490`)
9. `set_objective` invokes the limits gate **twice** per call with
   different payloads (slot not yet resolved on the first pass).
   (`commands/commands.py:609`, `647`)
10. **OME handling overlaps itself**: TIFF tag-270 parsing is owned by both
    `ome.py` and `ome_canonical.py` (the latter reaching into the former's
    privates); `extract_embedded_ome_xml` exists in two files; z-stack
    parameters are re-derived two ways. (`acquisition/`)

### 4.3 Tangled layers and lying names

11. `config/profiles.py` imports confirmation callables from `commands/`,
    while `commands/` imports `config/profiles` back — config, conceptually
    a leaf, participates in an import cycle.
12. `readers/derived.py` imports its job-settings parser from
    `commands/settings.py` — a reader concern living in commands, closing
    another cycle. Natural owner: `readers/`.
13. **`utils.py`'s docstring is false.** It claims "no domain knowledge …
    no knowledge of LAS X, microscopes, or API objects," while containing
    galvo physics (including the §4.0 constants), a LAS X encoding-repair
    parser, tile-geometry parsing, command timeout constants, and command
    result-envelope builders. Every function has an obvious home elsewhere;
    dissolving `utils.py` entirely is feasible and worthwhile.
14. The three `confirm*` modules split confirmation policy in a way the
    names cannot explain: a 380-line api/log/hybrid evidence engine hides
    in `confirm_select_job.py` while trivial confirms and the dual-leg
    arbiter live in `confirmations.py`.
15. `get_info` — nominally a read — first flushes the live experiment to
    disk (with a magic 60 s timeout). A read that writes.
    (`zmart_adapter.py:1105`)
16. *(Observation only — `experimental/` is untouched by maintainer
    decision.)* `commands/` and `scanfields/` are bidirectionally entangled
    with `experimental/lrp_edits/`; `scanfields/parsers.py` re-exports a
    parser specifically so `experimental/` can keep importing it, and the
    README concedes the experimental code is load-bearing.

### 4.4 Hidden state

17. **Four separate module-global registries** — the gate state, session
    state, the reader router's in-flight marker, and the applied stage
    envelope — each keyed by `id(client)`, each independently assuming one
    instrument per process, plus a single-writer assumption in command
    dispatch. Fine today; any multi-instrument future must touch all of
    them at once, and nothing currently ties them together.
18. Acquisition naming has second-resolution timestamps, so two
    acquisitions in the same second collide by construction; the adapter
    works around it with a collision loop in a different layer than the
    cause. (`acquisition/naming.py`, `zmart_adapter.py:719`)

### Clean bill of health

`algorithms/` (focus, registration) and `calibration/core` came back clean:
well-layered, hardware-free, named constants. The
limits/orientation/calibration pattern — defaults + notebook + code + tests
per concern — is the good half of this driver and the template the rest
should converge on.

---

## 5. Recommended order of work

1. **Correctness first, no reorganization needed:** move the galvo
   constants (§4.0) into per-machine config.
2. **Trivial hygiene:** delete the 137 committed files in `tests/_report/`
   (already gitignored; the scripts regenerate them and create the
   directory themselves).
3. **The motion/limits plan (§3), phases 1–3.** This establishes the
   one-rulebook / one-whistle architecture and the guard test that keeps
   it.
4. **Kill the double-implemented objective compensation (§4.1.2)** — pick
   one layer (the driver's `objective_shift` is the natural owner since the
   setters already invoke it), make the adapter defer to it, and write the
   same style of guard as for limits.
5. **Dissolve `utils.py`** (§4.3.13) — each function to its natural owner.
6. **Then, opportunistically:** the `commands/` internal grouping, the
   confirm-module split, OME deduplication, and the constants-in-mechanism
   list — each is small and local once the architecture above is in place.

Items 1–2 are an afternoon. Item 3 is the structural core. Items 4–6
follow the same principle each time: one implementation per fact, policy
above, mechanism below, folders that tell the truth.
