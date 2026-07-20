# Prompt: build the env, run, and evaluate the Leica hardware validation

Copy everything below this line into the agent that will run this eval on the
LAS X PC. It is self-contained; the agent needs no other context.

---

You are setting up from scratch (or verifying an existing setup) and then
running and evaluating the hardware validation of the ZMART Leica Stellaris5
driver, on the LAS X PC, against the real instrument (or the LAS X simulator —
detect which and say so in your report).

## Context

- Repo: ZMART-microscopy, branch `claude/smart-drivers-code-review-ky4phc`.
  Verify `git log -1` — the expected state is commit `fa94125` or a
  descendant. If the checkout is older, `git pull` first; if it still looks
  materially older (missing the commits named below), STOP and report — do
  not run stale code on hardware.
- Working dir for everything below:
  `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`
- The runbook is `tests/hardware/README.md` — read it first and follow its
  prerequisites exactly (LAS X running, ≥2-job template loaded, stage clear
  and inside the calibrated envelope, no modal dialogs).
- **Recent changes you are validating** (all landed and bench-verified once
  already on ZMB-LASX-PC; this eval is confirming they hold on this machine,
  or catching anything machine-specific):
  - `set_procedure` renamed to `run_procedure` across the controller and both
    adapters (`c4cdfa2`). **Breaking change:** the limits gate requires the
    machine-local `limits.json` `functions` block to match
    `commands/gate.py:FUNCTION_LIMIT_KEYS` exactly. A `limits.json` adopted
    before this rename still carries the old `set_procedure` key and will
    refuse **every** gated move. If the connect handshake fails naming a
    missing/unknown function key, re-run
    `limits/notebooks/set_limits.ipynb` before doing anything else.
  - Backlash wired into the `backlash_correction` acquisition option and
    tested at all three tiers (`3ea9dec`) — `acquire(options={"backlash_correction": True})`
    should run `correct_backlash` before capture and report
    `settle == "backlash-corrected"`.
  - CAM teardown on disconnect (`f35843d`): `disconnect()` now drops the
    commands-layer gate state via `gate.uninstall()`. No behavior change you
    should notice; just shouldn't regress.
  - `require_canonical_scan_orientation` was **removed** (not wired in) —
    don't look for it, it's gone. Separately, if you want to sanity-check:
    ZMB-LASX-PC's live `ImageTransformation` was found to be `RIGHTTOP`, not
    `TOPLEFT`, on the LAS X version installed at the time — the maintainer's
    call was that the next LAS X version doesn't have this transform, so it
    is not tracked as an open item. Not something to fix; just don't be
    surprised if pixel↔stage ROI math looks off on this specific version.
  - **Acquire's idle-confirmation wait has no deadline, and that is
    intentional** (`MAINTAINER_DECISIONS.md` §6, decided 2026-07-06): if
    `check_idle`/`confirm_acquire` blocks for a long time, that is the
    designed behavior (a real acquisition can legitimately take a long
    time), not a bug to report or a hang to kill. Only report it as a finding
    if LAS X is verifiably dead (unresponsive to a fresh `ping` in a second,
    unrelated session) and the wait never returns even then.
  - Three offline-only fixes (`fa94125`): a missing `"AF Job"` mock catalog
    entry, a headless matplotlib backend for calibration tests, and a
    log-reader hermeticity fix (`--mock` validators no longer read this
    machine's real LAS X log history). None of these should be visible in a
    live run; mentioned in case you also run the offline suite and want
    context for why it's now green.

## Safety rules (hard)

- Never edit stage or function limits, and never pass wider limits than the
  machine config provides.
- Use only the documented run_ci/validator invocations. Nothing under
  `experimental/` touches hardware.
- `run_ci.py --hardware` includes acquire smoke checks. Do not enable
  `--allow-objective` in a direct validator run unless the operator explicitly
  says so in this session.
- **Never kill a process mid-acquire or mid-capture.** If a step is slow,
  let it run — see the idle-gate note above. If you must bound your own
  patience for tooling reasons, use a long timeout (5+ minutes) and let the
  process finish naturally; do not send a kill/interrupt to something that
  may be capturing.
- If the driver hangs with no log progress AND you have independently
  verified LAS X itself is dead (see the idle-gate note above), note the
  exact time and report — do not retry blindly.
- Do not push to `main`. Commit run artifacts to the working branch only.

## Step 0: Build the environment (skip if already built and activated)

```powershell
cd <repo-root>
python build_env.py --name zmart-microscopy   # creates the conda-forge env; ~2-5 min
conda activate zmart-microscopy
```

`build_env.py` builds the full conda-forge env from `environment.yml` (runtime
plus the test/lint tools `run_ci.py` needs — `pytest`, `pytest-cov`,
`matplotlib`, `ipython`, `ruff`), verifies core imports, and asserts every
package came from conda-forge (never `defaults`). No separate `pip install` is
required; `requirements-dev.txt` is the dependency list for the non-conda
GitHub CI matrix. A missing test toolchain still fails the first CI step closed
("No module named pytest"), so a broken env can never let a hardware run start.

## Step 1: Stage limits

The driver reads limits from ProgramData. If ProgramData is empty, repo defaults
are copied there so CI can connect; on the rig, run once to replace those
defaults with measured stage limits:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_limits.ipynb
```

The pre-filled values are this machine's known-good envelope — adjust only
if you have better numbers for *this specific* stage.

## Run

```powershell
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py              # mock/offline gate: no LAS X
python run_ci.py --hardware   # live validators + acquire smoke
```

The hardware command starts with the mock limits self-check before any live
validator runs. It does not pass `--allow-missing-lasx`; missing LAS X is a
hardware-run failure, not a skip.

Reports land in `tests/_report/hardware_run_report_*.md` (paths are printed
at the end), each with a companion `driver_log_*.log`. Keep every report and
log, including from failed runs.

## Evaluate

Work from the CI summary, the Markdown run reports, and the companion
`driver_log_*.log` files. Answer each question with evidence (quote the
report rows/log lines):

1. **Overall CI result:** offline suite pass/fail counts and coverage; which
   of the 7 live steps (limits self-check, passive readers, reader parity,
   zmart adapter, and the api/log/hybrid end-to-end validators) passed?
2. **Backlash acquisition option, live:** if you need the specific direct
   validator check, run
   `validate_zmart_adapter.py --yes --allow-move --allow-state --allow-acquire`
   (real capture — do not interrupt it) and confirm `settle` reads
   `"backlash-corrected"` in the record, with the sequence select → backlash
   → capture visible in the driver log.
3. **Reader-mode comparison:** from the per-reader-mode timing table and the
   `read[datum] mode=...` rows — for each datum: do api, log, and hybrid
   agree on values? Does the log leg ever deliver, or is it always
   SKIP/absent on this machine? Any surprises versus the api-only `jobs`
   datum (expected to always be api-only — that's by design, not a finding).
4. **Confirmation health:** Confirmed/Unconfirmed columns and the
   unconfirmed-actions table — which changes went unconfirmed, after how
   many attempts, on which reader route? Unconfirmed after 3 attempts is
   reported-and-continue by policy, not a failure — but cluster it: one
   setting, one route, or systemic?
5. **Restore verification:** does every `Mutates scope: YES` row have a
   matching restore row, and did the final state match the initial (job
   selection, settings, XY/Z position, objective)?
6. **Anything machine-specific:** does this machine's `ImageTransformation`
   differ from `TOPLEFT` (see the orientation note above)? Does the stage
   envelope in the freshly-adopted `limits.json` look sane for this
   physical stage? Anything about this scope that doesn't match what was
   seen on ZMB-LASX-PC?

## Deliver

1. Commit the report and driver-log files to the branch — `tests/_report/`
   is gitignored, so force-add the run artifacts:
   `git add -f tests/_report && git commit && git push -u origin <branch>`.
2. Write `tests/_report/BENCH_EVAL_<date>.md`: a verdict per question above
   (with quoted evidence), an overall PASS / PASS-WITH-FINDINGS / FAIL call,
   and a ranked list of follow-up actions any findings justify. Where a
   finding maps to a known open item (stale-response correlation for
   `get_xy`/`get_jobs`/`get_hardware_info`, the abandoned-race-leg residue
   CF-05, or a maintainer-decision-needed item), name it — the open list
   lives in `docs/reviews/archive/PROGRESS_2026-07-05.md` §6 and
   `docs/reviews/MAINTAINER_DECISIONS.md`.
3. Commit and push that file too, then give the operator a ≤10-line spoken
   summary: overall verdict, whether the backlash option behaved correctly,
   which reader leg is winning on this scope and at what latency,
   confirmation health, and the single most important follow-up.
