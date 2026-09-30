# Release candidate review: Leica STELLARIS driver (`navigator_expert`)

This review covers the **release candidate** of the Leica driver, version `6.0.0rc1`. The driver is not released yet. This document lists what should be fixed before it is released for unattended use.

- **Code reviewed:** the Leica driver from `thomdehoog/zmart-microscopy`, branch `release-candidate` at commit `decba69`. This is the code in this `zmart-drivers` release candidate.
- **How it was reviewed:** the full review was done on `main` at `00fc8bc`. The `release-candidate` branch adds 7 commits on top of that. In the driver, they change only `zmart_adapter/zmart_adapter.py` and `config/machine.py`: the saved frame origin is now loaded at connect, and `set_origin` became a setup step. The findings in those two files were checked again against `decba69`, all of them still apply, and their line numbers below have been updated.
- **Driver folder:** `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`
- **Date:** 2026-09-30
- **Reviewers:** Claude Code (five parallel reviewers, one per part of the driver, plus checks by the lead session) and an independent Codex review supplied by the user. For each finding, the **Source** line says which review raised it. Where both reviews found the same problem, it appears once and names both.
- **Scope:** an offline review only. Nothing was checked on a physical microscope or on the LAS X simulator, and the review itself changed no driver code. The only change made to the driver alongside this review marks it as a release candidate (its status line and its version number).

All line numbers refer to `navigator_expert/` at `decba69`.

---

## Contents

1. [Summary](#1-summary)
2. [Test and CI status](#2-test-and-ci-status)
3. [High severity: fix before unattended use](#3-high-severity-fix-before-unattended-use)
4. [Medium severity](#4-medium-severity)
5. [Low severity and comment drift](#5-low-severity-and-comment-drift)
6. [Operator-facing documentation (CLAUDE.md audience rules)](#6-operator-facing-documentation-claudemd-audience-rules)
7. [Areas checked and found sound](#7-areas-checked-and-found-sound)
8. [Suggested order of work](#8-suggested-order-of-work)

### How to read the confidence labels

- **Confirmed (reproduced):** a small script or test showed the failure happening.
- **Confirmed (code reading):** following the code path shows the failure, but no script reproduced it.
- **Plausible:** the mechanism is real, but whether it bites on a real microscope depends on LAS X timing or on how the operator works.

---

## 1. Summary

The driver is large (about 25,000 lines of Python), well tested (about 1,300 offline tests), and careful in its core safety design. Every mutating command checks the limits gate before anything is sent to LAS X. Stage moves are also checked against the physical backstop, and none of the reviewers found a way around those checks for stage moves.

The serious problems sit in three places.

1. **A result can say "success" when the microscope did not do what was asked.** An unconfirmed objective change still triggers a compensating stage move, and an acquisition that never started is not raised as an error. Several callers also check only `success` and ignore `confirmed`. Because every command profile treats "sent but not confirmed" as a success, this pattern recurs across the driver.
2. **The recorded positions of images can be wrong.** Plane heights for z-galvo stacks are off by the whole z-wide position. Multichannel stacks lose their per-slice heights. The remembered "where the stage was driven to" goes stale after autofocus, `set_origin`, `zero_z_galvo`, and objective swaps.
3. **The scan-field template handling can destroy the operator's template.** While the stripped copy is loaded, a routine position read can overwrite the operator's real template with the empty one.

In addition, choosing a job silently gets around the "allowed objectives" restriction in `limits.json`, and CI for this driver has been red for several runs because of tests that depend on the author's own PC.

**Counts:** 14 high, 17 medium, and 8 low-severity findings, plus documentation notes.

---

## 2. Test and CI status

Running the offline suites on Linux (Python 3, dependencies from `requirements-dev.txt`) gave the following:

| Suite | Result |
|---|---|
| `pytest` in the driver folder (`tests/`) | 1186 passed, **4 failed**, 1 skipped (the skip needs the LAS X runtime, which is expected) |
| `pytest calibration/tests` | 110 passed, **2 failed** |

Codex, running the unit and calibration suites without `tests/hardware`, reported 1254 passed, 5 failed, 1 skipped. That matches the six failures below: its five are the three AutoSave failures plus the two reader-mode failures.

### T1. Three adapter tests depend on the author's own PC

- **Tests:** `tests/unit/test_zmart_adapter.py::TestAcquire::test_a_plane_says_where_on_the_sample_it_was_taken`, `…::test_the_slices_of_a_stack_are_spread_about_where_the_drive_stands`, and `…::test_a_stack_that_does_not_straddle_the_drive_is_placed_where_it_is`
- **Error:** `RuntimeError: output_root is not set and could not be discovered from LAS X native AutoSave`
- **Cause:** `acquire()` asks `_info.output_root(...)` (`zmart_adapter/zmart_adapter.py:975`) where to save. When the handle has no `output_root`, that function reads the LAS X AutoSave setup file under `%APPDATA%`. The `_capturing()` helper (`tests/unit/test_zmart_adapter.py:575`) does not stand in for this. On a PC with LAS X and AutoSave, the tests pass, and as a side effect they create a real `ZMART-microscopy` folder next to AutoSave. Everywhere else, they fail.
- **History:** the two plane tests have failed since `81a5990` introduced them. The third has failed since `05fd350` introduced it.
- **Fix:** add `patch.object(adapter._info, "output_root", return_value=Path("/tmp/out"))` to `_capturing`. Alternatively, build these handles with `connection={**adapter.CONNECTION, "output_root": "/tmp/out"}`, as the neighbouring tests already do.
- **Source:** Claude and Codex.

### T2. The mock hardware run fails because a test fixture was not updated

- **Test:** `tests/hardware/test_validate_zmart_adapter.py::test_full_mock_run_move_and_acquire`
- **Error:** `select_job('Overview') failed … no calibration translation covers objective slots 3 -> 1`
- **Cause:** commit `661035a` removed the default `calibration_name: "water_lens_setup"` from the adapter's `CONNECTION`, along with the `ZMART_CALIBRATION_NAME` environment fallback. The test fixture `tests/helpers/limits_fixtures.py:96-110` still publishes the mock calibration only under that name. The adapter therefore loads the flat default calibration, whose `objectives` table is empty, and the job switch correctly refuses. This test passes at `a786c3c` and fails from `661035a` onward, on every operating system.
- **Fix:** in `hermetic_mock_machine_root`, publish the calibration as the flat default (drop `calibration_name=`). Alternatively, have the validator's mock connection pass `calibration_name="water_lens_setup"`.
- **Source:** Claude.

### T3. Two calibration tests catch a real bug

- **Tests:** `calibration/tests/integration/test_workflows.py::test_read_job_geometry_pins_api_mode` and `…::test_read_stack_z_positions_pins_api_mode`
- **Error:** `KeyError: 'mode'`
- **Cause:** the tests are right and the code is wrong. See finding **M4**.
- **Source:** Claude and Codex.

### CI

- According to the GitHub Actions history (read by one reviewer, not checked again here), the `navigator-expert.yml` workflow shows **failure** on runs 70 to 77, which cover `main` after PRs #22 and #23 and the PRs since.
- `run_ci.py` treats any pytest failure as fatal, so CI will stay red until T1 to T3 are fixed.
- While CI is red, new regressions are hidden behind the known failures. Fixing T1 and T2 is cheap and worth doing first.

---

## 3. High severity: fix before unattended use

### H1. Choosing a job gets around the "allowed objectives" limit

- **Source:** Codex. Confirmed here by reading the code.
- **Where:** `commands/gate.py:23` (the gate docstring maps `select_job` to "handshake/state gate only") and `commands/commands.py:1620` (`select_job`).
- **What goes wrong:** `set_objective` checks the target slot against `objective_slot.allowed` in `limits.json`. `select_job` does not, although switching to a job also switches to that job's objective.
- **Scenario:** `limits.json` allows only slot 1. `set_objective(client, …, slot=3)` is refused. `select_job(client, "HiRes")`, where HiRes uses slot 3, succeeds and swings the slot-3 lens into place. Codex reproduced this offline.
- **Why it matters:** the README says "objective changes use `objective_slot.allowed`" and that nothing built on top can bypass the command-layer check. A restricted lens (for example, an oil objective on a dry sample) can still be brought in by choosing a job.
- **Fix:** before `select_job` fires, read the target job's objective slot and run it through the same `objective_slot` check that `set_objective` uses.

### H2. An unconfirmed objective change still moves the stage to compensate

- **Source:** Claude and Codex. Both reproduced it with a stubbed client.
- **Where:** `commands/commands.py:702-706` (`set_objective`) and `commands/commands.py:1660` and `1713` (`select_job`).
- **What goes wrong:**
  - Compensation runs whenever `result["success"]` is true. Every command profile has `success_on_unconfirmed=True` (`config/profiles.py:246`), so a change that was never confirmed still counts as a success.
  - `set_objective` passes the *requested* slot as `new_slot`, not a slot it read back.
  - `select_job` uses the target job's configured objective, not the objective that is actually in place.
- **Scenario:** a manual turret shows LAS X's "turn the turret manually" dialog (the README itself warns about this). The objective stays where it is and the readback times out. The driver still moves XY by the calibrated offset, and z-wide by up to hundreds of µm.
  - Claude's reproduction gave `success=True, confirmed=False, moves: [('xy', 1050, 980), ('z', 400.0)]`.
  - Codex's reproduction applied +10 µm in X and −6 µm in Y for a lens that never arrived.
- **Fix:** compensate only when `confirmed is True`, and compute the move from the slot actually read back.

### H3. An acquisition that never starts is not raised as an error

- **Source:** Claude. Reproduced with a stubbed client.
- **Where:** `commands/commands.py:1560-1612` (`acquire`), the ACQUIRE profile in `config/profiles.py`, and `acquisition/capture.py:57`.
- **What goes wrong:** `confirm_acquire` correctly reports a failure when the scan never starts, or when LAS X returns a permanent error. ACQUIRE does not override `success_on_unconfirmed`, so `commands.acquire()` returns `success=True, confirmed=False`. `capture.acquire()` then checks only `success` and does not raise.
- **Contradicts:** the `acquire` docstring ("the result is a failure") and the README, which says three times that acquire "raises on failure".
- **Scenario:** `PyApiAcquireJob` is accepted but the scan never starts. The workflow carries on, and only the freshness check in `save()` stands between it and saving stale data.
- **Fix:** set `success_on_unconfirmed=False` for ACQUIRE, or have `capture.acquire` require `confirmed`.

### H4. A routine position read can overwrite the operator's scan-field template

- **Source:** Claude. Confirmed here by reading the code.
- **Where:** `scanfields/files.py:284-304` (`save_and_read_lrp`). `transaction.py:144` (`apply_lrp_change(TEMPLATE_XML)`) has the same gap.
- **What goes wrong:** `save_and_read_lrp` always saves LAS X's *current* experiment under the operator's template name (`TEMPLATE_XML`), even when LAS X currently has the stripped sidecar loaded.
- **Scenario:**
  1. The adapter strips the template through the sidecar (`_ensure_scan_fields_stripped`). It promises that the original files "stay on disk".
  2. Autofocus (`zmart_adapter.py:1286-1296`), or a position read on a job with a z-stack, calls `_hardware_snapshot`, which calls `z_um_from_settings`, which calls `_z_um_from_saved_experiment`, which calls `save_and_read_lrp`.
  3. That save writes the *empty* stripped experiment over the operator's `.xml`, `.rgn` and `.lrp`.
  4. `restore_template` then counts 0 objects and "succeeds". The operator's scan fields are gone for good, while `get_template_state` still reports "stripped".
- **Why it matters:** this is silent, permanent loss of work the operator drew by hand.
- **Fix:** save to the name of whatever experiment is actually loaded (the stripped sidecar while stripped), or to a dedicated scratch name.

### H5. Restoring the template loads the old acquisition settings, then puts the edited file back

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `scanfields/strip_restore.py:323` (`load_experiment`) and `:373-375` (copy of `.lrp.bak` back into place).
- **What goes wrong:** LAS X loads `TEMPLATE_XML` together with the *original*, unedited `.lrp` and confirm-saves it. Only then is the edited `.lrp.bak` copied over the file on disk.
- **Consequence:** LAS X runs with the original acquisition settings while the file on disk shows the edits. The next save (for example, `save_and_read_lrp`) silently throws the edits away.
- **Fix:** copy the edited LRP back *before* `load_experiment`.

### H6. Plane heights for a z-galvo stack are off by the whole z-wide position

- **Source:** Claude and Codex. Both reproduced it.
- **Where:** `zmart_adapter/zmart_adapter.py:1073-1096` (`_where_the_planes_are`) and `readers/derived.py:66` (`stack_z_wide_um`).
- **What goes wrong:** the stack's `begin` and `end` are always treated as absolute *z-wide* values, and the stack's `zDrive` is ignored. The code then subtracts `driven_to["z_wide_um"]`. For a galvo stack, `begin` and `end` are galvo positions.
- **Scenario:** a galvo stack from −10 to +10 µm with 5 slices, z-wide at 1000 µm, and frame z = 0 is reported at about −1010 … −990 µm instead of −10 … +10 µm. Codex's reproduction expected 90, 100, 110 µm and got −910, −900, −890 µm.
- **Why it matters:** any workflow that takes a focus height from these records (for example, "go to the sharpest plane") would drive to a wildly wrong height.
- **Fix:** read the stack's drive, and subtract the matching anchor (the galvo target for a galvo stack, z-wide for a z-wide stack).

### H7. Multichannel stacks lose their per-slice heights

- **Source:** Codex. Confirmed here by reading the code.
- **Where:** `zmart_adapter/zmart_adapter.py:1035-1047` and `readers/derived.py:93`.
- **What goes wrong:** the plane positions are computed with `count = len(written)`, the total number of saved files. `stack_z_wide_um` refuses when `sections != expected`. With 3 slices × 2 channels, 3 ≠ 6, so the function returns `None` and all six images get the same height. The code also indexes by the file's position in the list (`ordinal`) rather than by the plane's own z index.
- **Fix:** pass the number of distinct z indices, and look up `slices[index.z]` for each plane.

### H8. The remembered "driven to" position goes stale

- **Source:** Claude, and Codex for the `set_origin` case. Confirmed by reading the code.
- **Where:** `handle.driven_to` is set only at `zmart_adapter/zmart_adapter.py:769` (end of a successful `set_xyz`) and is read at `:1085` to label every acquired plane.
- **What goes wrong:** it is never cleared or updated when something else moves the stage or changes the frame:
  - **After autofocus** (`_run_autofocus`, around `:1264`): the next acquisition reports the height from before autofocus. This is exactly what commit `81a5990` meant to prevent.
  - **After `set_origin`** (`:564`): planes are reported in the old frame. `set_origin` is now a setup step that the operator runs on the driver directly, but the same handle keeps working afterwards. For example, `set_xyz(100, 0, 0)`, then `set_origin()`, then `acquire` reports x = 100 where the new frame says 0.
  - **After `zero_z_galvo`:** the z-wide anchor is off by the galvo offset that was moved onto z-wide, so stack slice heights are off by that amount.
  - **After an objective swap inside `acquire`'s `select_job`:** that swap moves the stage to compensate, so slice heights are off by the objective offset.
  - **After a failed `set_xyz`** where the XY move arrived and the z move then failed: the old `driven_to` survives, and later images carry the old position.
- **Fix:** set `driven_to = None` before any move starts, and update or clear it in each of the paths above.

### H9. Every command can wait forever for the scanner to become idle

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `commands/prechecks.py:27-76` (`check_idle`), used by every profile with `timeout=None`.
- **What goes wrong:**
  - A failed status read (`None`, or "Unknown" at `:54`) counts as "not idle".
  - With no timeout, the loop at `:50` never exits. It only writes a heartbeat line to the log every 30 s.
- **Scenario:** a LAS X modal dialog blocks the CAM API, or the connection drops. Every `move_*`, `set_objective`, `select_job` and `acquire` then hangs silently, with no error shown to the operator.
- **Fix:** give the default profiles a finite, generous idle timeout (for example, several minutes). Also count a long run of "Unknown" readings as a failure of its own, separate from "busy".

### H10. Non-square scan fields are planned as squares, leaving gaps

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `scanfields/parsers.py:105-118` (`_tile_size_from_image_size_str`), and its use in `scanfields/planning.py`.
- **What goes wrong:** the X and Y field sizes are averaged into one square tile size.
- **Scenario:** a 290 × 145 µm format becomes a 218 µm "tile". The Y step is then about 207 µm against a real field height of 145 µm, leaving gaps of about 60 µm between rows that are never imaged. Bounding boxes are wrong too.
- **Fix:** keep separate X and Y tile sizes all the way through planning.

### H11. `acquire`, `set_state` and autofocus check only `success` from `select_job`

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `zmart_adapter/zmart_adapter.py:987-990`, `1198-1200` and `1289-1291`.
- **What goes wrong:** an unconfirmed job switch returns `success=True, confirmed=False`, as explained under H2.
- **Scenario:** `acquire` captures under whatever job LAS X still has selected, but the record, the lineage and the stack lookup all name the requested job. The images are then saved with the wrong settings attached. `set_xyz` does check both flags, as the README tells callers to.
- **Fix:** require `confirmed` in these three places.
- **Note:** this shares a root cause with H2 and H3. Reviewing every caller of `success` for whether it should require `confirmed` would close the whole family.

### H12. Setting confirmations can accept a value read before the command was sent

This finding and H13 are both about the "freshness" of what the driver reads back.

- **Source:** Claude.
- **Where:** `commands/confirmations.py:326` (`_confirm_readback`).
- **What goes wrong:** setting confirmations call `_readback` without `observed_after`. The log reader's job-settings path (trusted for up to `job_settings_log_max_age_s` = 2 s) can therefore return a settings dump written *before* the command was sent.
- **Scenario:** this only matters when the older value happens to equal the new target, for example when the same value was set moments before and an unrelated command was confirmed in between. It is rare, but when it happens it is a false "confirmed".
- **Confidence:** plausible, low frequency. It is listed here because it undermines the meaning of `confirmed`, which H2, H3 and H11 all rely on.
- **Fix:** pass `observed_after=<send time>` in setting confirmations, as the move confirmations already do.

### H13. Log timestamps can make old positions look brand new

- **Source:** Claude. Both cases reproduced by importing the real `log_reader`.
- **Where:** `readers/log_reader.py:120-148` (`_fold_disambiguate` / `_parse_ts`) and `:394-401` (`_too_old`).
- **Case 1: the autumn clock change.**
  - When a wall-clock time occurs twice (02:00–03:00 on the last Sunday of October), the code picks whichever of the two readings is closer to "now". That assumes every line is recent, but spotting *old* lines is the reader's whole purpose.
  - Scenario: on 2026-10-25 in Europe/Zurich, a `GetStageHwPosition` line is logged at 02:30:00 during the first 02:xx hour. At 02:30:00.5 in the repeated hour, with no newer line, it is read as 0.5 s old instead of 3600.5 s old.
- **Case 2: the clock steps backwards.**
  - `_too_old` checks `(now − ts) > max_age_s` and never rejects a negative age.
  - Scenario: Windows time sync steps the clock back by 20–30 s. Every log line from the previous 30 s now looks newer than "now", so it counts as fresh.
- **Consequence:** in both cases, `get_xy` and `get_scan_status` return old values as fresh, and those values also pass the `observed_after` check. **A move can be confirmed from an old position.**
- **Fix:** refuse any line stamped more than a small allowance ahead of now. For the repeated hour, prefer the *earlier* reading, or refuse to decide.

### H14. The idle check reads the log first, although its comment says it uses the API

- **Source:** Claude. The mismatch is confirmed; its effect is plausible.
- **Where:** `commands/prechecks.py:54`. `commands/routines.py:134-136` (`correct_backlash`) has the same mismatch.
- **What goes wrong:** the comment says the check is "pinned to the API so a stale log value cannot gate a command". The code calls `_readers.get_scan_status(client)` with no `mode`, so it uses the profile default `scan_status_mode="hybrid"`, which prefers the log.
- **Scenario:** a fresh "idle" line in the log (up to 0.5 s old) lets a command fire while the API still reports scanning.
- **Fix:** pass `mode="api"` as the comment intends, and do the same in `correct_backlash`.

---

## 4. Medium severity

### M1. `select_job` records its "before" position from the wrong job

- **Source:** Claude. Plausible.
- **Where:** `commands/commands.py:1660`.
- **What goes wrong:** `record_before_change` uses `context["api_baseline_name"]`, which comes from the API job list. `profiles.py` and README §10.6 both say that list can name the wrong job for 15 s or more after a switch.
- **Scenario:** switch from job A to B, then soon after switch to C. The old slot and the z-wide starting point are read from A's settings instead of B's. The compensation move is then wrong, or it is skipped entirely because A and C happen to share an objective.
- **Fix:** take the "before" state from the job that is actually selected, using the log reading or the combined reading.

### M2. The re-fire path ignores a failed idle wait and lets errors escape

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `commands/dispatch.py:706-710`.
- **What goes wrong:** before a re-fire, the result of the idle wait is never checked, so the command fires again even when the wait failed. The call is also not wrapped in `try`, unlike step 1 of `_fire_block`, so an exception from the reader escapes `confirm_and_fire` instead of becoming a result dict.

### M3. Plane positions and the canvas ignore the objective offset

- **Source:** Claude. Plausible.
- **Where:** `zmart_adapter/zmart_adapter.py:1443-1455` (`_canvas`).
- **What goes wrong:** frame coordinates are `stage − origin − ΔT`, where ΔT is the calibrated objective offset. The canvas only subtracts the origin. After a lens change with a non-zero offset, the stage limits drawn on the operator page are shifted by ΔT in X and Y.

### M4. Calibration reads image geometry through the log, not the API

- **Source:** Claude and Codex. Confirmed by the two failing tests (T3).
- **Where:** `calibration/core/common.py:119` and `:426`.
- **What goes wrong:** the comment says "use the authoritative API reader", but `drv.get_job_settings(...)` is called without `mode="api"`. It therefore follows the default `job_settings_mode="hybrid"` (`config/profiles.py:91`), which can return a value from the LAS X log.
- **Scenario:** right after a zoom change, the pixel size or z positions come from a log entry the reader still considers fresh. The µm shifts, and so the saved objective translations, are then scaled wrongly.
- **Fix:** pass `mode="api"`. The existing tests then pass.

### M5. Registration "trusts" images that contain no sample

- **Source:** Claude. The mechanism is confirmed; how often it happens on a real microscope is unknown.
- **Where:** `algorithms/registration.py:207-263` (`register_voting`), used by `calibration/core/objective_pair.py:941-975`.
- **What goes wrong:**
  - A vote counts as trusted when any 2 of the 4 methods agree within 3 µm. Two of those methods (`pcc`, `masked_pcc`) are both phase correlation, so they tend to agree with each other.
  - The 3 µm tolerance is fixed in µm, so it is about 30 pixels wide at 0.1 µm pixels.
  - The quality number is not used to decide trust, and it is broken anyway (see L2).
- **Measured:**
  - Two blank fields with the same uneven illumination: trusted 10 out of 10 times, with a shift of about (0.2, −0.2) µm.
  - Two identical flat images: trusted, with a shift of 0.375 µm.
  - Two unrelated noise images: trusted about 5% of the time.
- **Consequence:** in objective-pair calibration, a trusted vote writes the configuration. There is no limit on the size of the correction and no check for featureless images; only `calibration_check` has one.
- **Scenario:** the target image is blank or out of focus. The calibration records a near-zero correction, and the operator can adopt it.
- **Also seen:** plain `pcc` returned about (0, 1.2) when the true shift was (10, −5) on a smooth texture, because it has no edge windowing. The vote hid this.
- **Fix:** add a check for featureless images (low standard deviation or low peak sharpness). Require agreement between *different families* of method (phase correlation versus feature matching versus NCC), and scale the tolerance with the pixel size.

### M6. The calibration check has a built-in centring bias

- **Source:** Claude. Confirmed by simulation.
- **Where:** `calibration/core/calibration_check.py:288-289`.
- **What goes wrong:** the image centre is taken as `H/2` instead of `(H−1)/2`. When the two objectives have different pixel sizes, a *perfect* calibration therefore shows a residual of about `−(coarse_ps − fine_ps)/2` µm per axis.
- **Measured:** with 0.8 vs 0.2 µm pixels, (−0.24, −0.20) µm; with 1.2 vs 0.2 µm pixels, (−0.40, −0.59) µm.
- **Fix:** `rows = (np.arange(h) − (h−1)/2) * scale + (H−1)/2`, and the same for columns.
- **Note:** this affects only the check, not the saved calibration.

### M7. `save()` can pick up the previous acquisition's image

- **Source:** Claude. Plausible.
- **Where:** `acquisition/lasx_native_autosave.py:176-178` together with `acquisition/files.py:118-128`.
- **What goes wrong:** the lookup by relative path accepts any file modified within 2 s *before* `acq.started_at`, and the stability wait (3 × 0.5 s) is shorter than that allowance.
- **Scenario:** during back-to-back saves of small images, LAS X has not yet updated `RelativePathName` when `save()` runs. The previous acquisition's OME-TIFF, written about 1.5 s before this one started, is accepted and saved under the new name. No "several candidates" check runs on this path.
- **Fix:** compare against `finished_at` or require a modification time after `started_at`, and add the "several candidates" check.

### M8. Saving twice overwrites earlier vendor metadata

- **Source:** Codex. Confirmed here by reading the code.
- **Where:** `acquisition/save.py:224-258` (`_persist_vendor_metadata`).
- **What goes wrong:** vendor metadata is written to `<type>/data/metadata/vendor/<exporter>/<source file name>`, with nothing specific to the acquisition in the path. The next capture of the same acquisition type, whose LAS X metadata files share the same names, overwrites the first capture's files.
- **Consequence:** the first capture's recorded `sha256` then points at a file with different contents. Codex reproduced this.
- **Fix:** include the acquisition hash or the naming stem in the vendor metadata path.

### M9. Excitation wavelength is written as emission wavelength

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `acquisition/ome_canonical.py:414-416` and `:437-443`.
- **What goes wrong:** when the vendor's channel has only `ExcitationWavelength`, the canonical plane XML writes it as `EmissionWavelength`, and `summary.json` records it as `wavelength_nm`. The channel metadata is then wrong for anyone reading it later.

### M10. The scan-field template state is judged only by file times

- **Source:** Claude. Plausible.
- **Where:** `scanfields/files.py:89` (`get_template_state`), about `:316`.
- **What goes wrong:** "stripped" is decided only by comparing file modification times, never by what LAS X has loaded or what the sidecar contains.
- **Scenario:** after a strip, the operator reloads the real template in the LAS X window, or draws fields into the loaded stripped template and saves. The state still reads "stripped", so the adapter skips stripping, and LAS X acquires the stored multi-field pattern instead of the current position.

### M11. `parse_lrp` keeps only the first sequential setting of each job

- **Source:** Claude. Confirmed on `tests/data`.
- **Where:** `scanfields/lrp.py:370`.
- **What goes wrong:** the test LRPs have two sequential settings for both Overview and HiRes. The second setting (its detectors, lasers and so on) is silently dropped from `jobs[...]["Sequential"]`.

### M12. Snapshot folders in ProgramData are checked too loosely

- **Source:** Claude. Plausible.
- **Where:** `config/machine.py:86` (`_SNAPSHOT_RE`), `:252-267` and `:536-556`.
- **Problem A:** `_SNAPSHOT_RE` checks only the pattern of digits, not whether the date is real. A folder named like `2026-19-…Z` sorts after every real date, wins as "newest" for good, and then crashes `_next_auto_moment` in `strptime`.
- **Problem B:** `snapshots()` requires the JSON file only for orientation.
  - For calibration, the newest timestamp-named folder *without* `calibration.json` leads `ensure_snapshot` to publish a new snapshot copied from that empty folder. That snapshot uses the bundled placeholder and silently hides the operator's older, real calibration.
  - For limits, it raises "no operator-published limits.json" even though older valid ones exist.
- **Trigger:** calibration session folders live in the same `calibration/` root, and the session id is free text the operator types. A timestamp-style id, or a folder copied by hand, is enough.

### M13. The Connect card says calibration was "found" when it failed

- **Source:** Claude. Confirmed by reading the code.
- **Where:** `zmart_adapter/zmart_adapter.py:1475-1477`.
- **What goes wrong:** `calibration_info` is always a non-empty dict, because an empty-info dict is returned both on failure and when loading is switched off. So `calibration.get("name") or "found" if calibration else "failed…"` always takes the "found" branch.
- **Why it matters:** the operator is told calibration is in place when it is not.
- **Fix:** test `calibration.get("loaded")` instead.

### M14. A half-written log line can give a wrong job ID

- **Source:** Claude. Plausible.
- **Where:** `readers/log_reader.py:91` (`_RE_CURRENT_BLOCK_ID`).
- **What goes wrong:** `BlockID = (\d+)` has no end anchor, so a line that LAS X is still writing can match a shortened number. Every other pattern in the file requires a closing quote or bracket.
- **Scenario:** while `CurrentBlock/BlockID = 12` is being written, the read sees `= 1`. The effect is brief, and the reader usually refuses to decide when two jobs match.

### M15. Job names containing `" '"` are cut short

- **Source:** Claude. Plausible.
- **Where:** `readers/log_reader.py:90` (`_RE_CURRENT_BLOCK_NAME`).
- **What goes wrong:** the lazy match `(.*?)\s+'` stops at the first space followed by a quote. A job named `Tile 'A'` is parsed as `Tile`. In hybrid mode, `get_selected_job` then returns the wrong name as a trusted fresh value.

### M16. The API reader can return the previous reply

- **Source:** Claude. Plausible, low.
- **Where:** `readers/api_reader.py:243-247` and `:314-318`.
- **What goes wrong:** the "clear before read" steps in `get_jobs` and `get_hardware_info` swallow exceptions, and there is no check that the reply belongs to this request.
- **Scenario:** if resetting `Model.Jobs` to `None` fails, the previous job list (including which job is selected) is read straight back as the answer.

### M17. LAS X can read half-written template files

- **Source:** Claude. Plausible, low.
- **Where:** `scanfields/transaction.py:96` (`reorder_jobs`), `experimental/lrp_edits/_primitives.py:86` and `:165`, and the rollback copies in `scanfields/strip_restore.py:339-340` and `:357-358`.
- **What goes wrong:** these write the `.lrp` in place (`write_text`, `copy2`) just before LAS X loads it.
- **Scenario:** an interruption or a file-lock collision midway leaves a truncated template for LAS X to load.
- **Fix:** write to a temporary file, then `os.replace`, the same way the image and JSON writes already do.

---

## 5. Low severity and comment drift

- **L1. `subpixel_peak` refines the focus peak in the wrong direction.**
  - Where: `algorithms/focus.py:32-40`.
  - The denominator `2*(2*y1 − y0 − y2)` has the wrong sign. A parabola that peaks at 2.3 returns 1.7.
  - Nothing in the repository calls it today, and calibration uses its own, correct `_parabolic_peak`. But it is exported, so any new caller would focus on the mirror-image position.
  - Fix the sign, or remove the function.
- **L2. The PCC quality number does not mean what the docstring says.**
  - Where: `algorithms/registration.py:124` and `:141`.
  - `1 − error` comes out as 0.0 on a perfect match, and `masked_pcc` gives NaN, which is reported as `None`. The docstring says "higher is better, matching NCC".
- **L3. A comment claims a limits check that does not exist.**
  - Where: `commands/commands.py:1347-1349`.
  - It says the composed pan "is checked again against the file inside the transaction". Nothing does that: `LeicaLimits.check("move_galvo_to_pixel", …)` returns without checking, and `_edit` compares only against `PAN_LIMIT`. The behaviour matches `gate.py`'s own description, so the comment is what needs fixing.
- **L4. Stale comment about calibrated slots.**
  - Where: `zmart_adapter/zmart_adapter.py:493`.
  - The requirement `measured_slots == slots` is intentional (`objective_pair.py:201`), but this comment still describes the old behaviour.
- **L5. `_fresh_native_tiffs` searches only for `*.ome.tif`.**
  - Where: `acquisition/lasx_native_autosave.py:258`.
  - If AutoSave writes `.ome.tiff`, the "phase B" wait, which has no time limit, never finishes.
- **L6. `_to_um` passes unrecognised units through unchanged.**
  - It should raise an error, so that a new unit name cannot become a silent ×1e6 error.
- **L7. The pytest markers are registered but unused.**
  - Where: `pytest.ini`.
  - `pytest.ini` already says so openly. There is nothing to fix now; the note is here only so no one assumes `-m "not hardware"` filters anything.
- **L8. Registering the driver with the controller by folder path fails.**
  - Where: `zmart_adapter/zmart_adapter.py:83` (`from .. import orientation`), together with the standalone controller's `register_driver`.
  - The controller's README says a driver can be registered by "a folder, a file, or a module name". Passing the `zmart_adapter` folder makes the controller import it as a top-level package, so its imports from the parent `navigator_expert` package fail with `ImportError: attempted relative import beyond top-level package`. Passing the `navigator_expert` folder imports the driver but registers nothing, because the driver only registers when its `zmart_adapter` is imported.
  - What works today: `register_driver("zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter")`, with Python started in the repository root.
  - Fix: let `navigator_expert/__init__.py` offer a `register()` that imports the adapter and registers it, so passing the `navigator_expert` folder works too.
  - Source: Claude, found while preparing this release candidate.

---

## 6. Operator-facing documentation (CLAUDE.md audience rules)

`CLAUDE.md` asks that the setup notebooks, the adapter's session methods and the READMEs be written for biologists who are learning, in full, calm sentences with jargon explained. `calibrate_objective_pair.ipynb` comes closest. The others need a pass.

- **`orientation/notebooks/set_orientation.ipynb`, cell 0:**
  - It says it "compares four rotations with reflection absent or present" but never says *why* orientation matters for the experiment (images and stage moves must point the same way, or tiles and targets land in the wrong place).
  - It does not warn that the stage will move by about 40 µm, or say what to do if the measurement is rejected.
  - The Validate cell asks the operator to "confirm that it follows the stage axes" without saying how to check this by eye.
- **`limits/notebooks/set_limits.ipynb`:**
  - Cell 0 is written in the clipped style CLAUDE.md warns against: "Ranges include both endpoints; an empty list means reviewed and unrestricted."
  - Cell 3 says "saves the XML/RGN/LRP template trio" without explaining what these files are.
  - The `LIMITS` dict lists about 20 raw API names (`set_scan_resonant`, `z_galvo_um`, …) with no word on what each one controls, or why a facility might restrict it.
- **All three notebooks, "Save and Adopt" cells:**
  - "Verifies its measurement and validation outputs, then activates/publishes" is engineering shorthand. It should say plainly what changes on the microscope once the operator adopts, and how to undo it.
- **`calibration/notebooks/calibrate_objective_pair.ipynb`:**
  - This is the best of the three. "Backlash take-up rounds", "Set Focus" and "WEAK VOTE / registration methods" are still only partly explained.
- **README:**
  - The README says three times that acquire "raises on failure". It also says objective changes are bounded by `objective_slot.allowed`. Both claims are currently untrue (see H1 and H3). Either fix the code to match, which is recommended, or correct the text.

---

## 7. Areas checked and found sound

These were looked at deliberately and no problem was found. They are listed so that later work does not need to re-check them from scratch.

- **Safety gate for stage moves:** every native call in `commands/` checks the gate first. `move_xy` and `move_z` also run the envelope and physical-backstop checks. NaN, infinite and numeric-string targets are refused.
- **Unit handling in moves:** the gate and backstop check the µm value, and the native command receives the raw value with the matching Units enum.
- **No double acquisition:** ACQUIRE uses `fire_async` with `max_retries=0` and no re-fire.
- **Retries** only re-send absolute moves or setters, so sending one again is harmless.
- **Limits validation:** NaN, Infinity and min > max are rejected. The backstop is enforced at connect (`commands/gate.py:263`) and in `adopt_limits`. `limits/adaptive.py` rejects non-finite points and zero-area rectangles.
- **Log reader robustness:** decimal commas, `Âµm`, scientific notation and negative numbers make parsing fail cleanly rather than produce a wrong value. Log rotation and truncation are safe, because each read parses the file tail afresh. Router timeouts are bounded.
- **Snapshot ordering:** snapshot names sort in time order (apart from the invalid-date case in M12).
- **Orientation:** all 8 `_STAGE_FROM_ORIENTATION` matrices match `reorient_array` (checked numerically), and the sign convention of the fit is consistent.
- **Registration signs:** PCC, NCC and ORB all use target minus reference, including ORB's (row, col) keypoints.
- **Objective translation direction:** `T[to] − T[from]` is used consistently in `get_xyz`, `set_xyz`, `_scan_field` and `objective_shift`.
- **z-wide / z-galvo split in `set_xyz`:** correct.
- **Calibration adoption:** JSON writes are atomic (temporary file, fsync, `os.replace`), and the newest report wins by `created_at`.
- **Calibration focus fit:** `_parabolic_peak` has the right sign and refuses a peak at the edge of the stack. A flat stack raises an error.
- **OME-TIFF export:** a round trip of a 2×3×2 multichannel image through `_persist_export` gave zero pixel mismatches. Axis order, the swap of pixel sizes on 90° turns, stack units, and RGN metre-to-µm conversion are all correct.
- **Image and JSON writes** are atomic, and image names cannot collide within a single save.
- **Connections:** each connect makes a fresh CAM client, so `disconnect` cannot remove another session's gate.

---

## 8. Suggested order of work

1. **Get CI green (small, mechanical).** Fix the test fixtures for T1 and T2, and make the `mode="api"` fix for M4 (which also fixes T3). A green CI is what will catch regressions from everything below.
2. **Make "success" mean success.** Fix H2 and H3, then review every place that checks `success` without `confirmed` (H11). One way to do this is to set `success_on_unconfirmed=False` for the commands with physical consequences (objective, job selection, acquire) and see which tests react.
3. **Close the objective-limits gap (H1)** in the command layer, so that it holds for every caller.
4. **Protect the operator's scan-field template (H4, H5).** Add a regression test that strips, reads the position on a z-stack job, restores, and checks that the object count survives.
5. **Fix image coordinates (H6, H7, H8).** Tests with a galvo stack, a two-channel stack, and `set_origin` followed by `acquire` would each have caught one of these.
6. **Bound the idle wait (H9)** and **harden log freshness (H13, H14, H12).**
7. **Tiles (H10), then the medium list,** roughly in the order given.
8. **Documentation pass (section 6)** once the behaviour it describes is settled.

Before the first unattended run after these changes, validate on the LAS X simulator and then on the STELLARIS. The work in steps 2 to 5 especially touches what the hardware does, not only what the code reports.
