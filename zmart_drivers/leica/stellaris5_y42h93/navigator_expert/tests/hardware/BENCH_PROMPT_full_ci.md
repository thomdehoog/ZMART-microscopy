# Bench prompt: run the entire driver CI on the microscope and evaluate it

Hand everything below this line to a bench agent (or follow it yourself) on the
LAS X PC. It is self-contained: run the **full** Navigator Expert CI — the
offline gate, the live LAS X validators (read-only then reversible writes across
all three reader routes), and one real capture+save — against the real STELLARIS
(or the LAS X simulator; detect which and say so), then report a verdict.

---

## Context

- Repo: ZMART-microscopy, branch `claude/smart-drivers-code-review-ky4phc`
  (== `main`). Verify `git log -1` shows `ac77e60` or a descendant; if the
  checkout looks materially older, `git pull` first, and if it is still missing
  the commits named below, STOP and report — do not run stale code on hardware.
- Working dir for everything below:
  `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`
- Runbook: `tests/hardware/README.md` — read it and follow its prerequisites
  (LAS X running, a ≥2-job template loaded, stage clear and inside the
  calibrated envelope, no modal dialog open — a dialog blocks the whole CAM API).
- The single self-contained CI entry point is `run_ci.py`; the individual
  `validate_*.py` scripts stay runnable for debugging.

### Recent changes this run validates

- **Save path is native-AutoSave-only** — the `navigator_expert` exporter was
  removed; `acquire` finds and validates its output via LAS X native AutoSave
  (base folder read from the active StartUp `.lcf` `AutoSaveBaseFolder`).
- **Two-phase AutoSave collector** (`ac77e60`): after a capture, if **no**
  project folder or OME-TIFF appears within the detection window (60 s), the save
  fails with an actionable *"native AutoSave is most likely disabled in the
  running LAS X session — enable it and re-run"* (not a generic "no file found").
  Once a project appears, it waits **without a deadline** for the file to flush
  (a slow/large save is healthy, not a failure).
- The acquire idle-confirmation wait is deadline-free **by design**
  (`MAINTAINER_DECISIONS.md §6`): a long acquisition legitimately blocks; that is
  not a hang to kill.

## Safety rules (hard)

- Never edit stage or function limits, and never pass wider limits than the
  machine config provides.
- Use only the documented `run_ci`/validator invocations. Nothing under
  `experimental/` touches hardware.
- **Never kill a process mid-acquire or mid-capture.** If a step is slow, let it
  finish. If you must bound your patience for tooling reasons, use a long timeout
  (5+ min) and let the process end naturally.
- Only report a hang as a finding if LAS X is **independently** verified dead
  (unresponsive to a fresh `ping` in a second, unrelated session) and the wait
  never returns even then — note the exact time.
- Do **not** push to `main`. Commit run artifacts to the working branch only.

## Step 0 — build the environment (skip if already built and activated)

```powershell
cd <repo-root>
python build_env.py --name zmart-microscopy      # conda-forge env; ~2-5 min
conda activate zmart-microscopy
pip install -r zmart_drivers/leica/stellaris5_y42h93/navigator_expert/requirements-dev.txt
```

`build_env.py` asserts every package came from conda-forge (never `defaults`).
The `pip install` adds the test/lint deps `run_ci.py` needs — without it the
first CI step fails closed with "No module named pytest".

## Step 1 — machine-local stage limits

The driver refuses every move until a machine-local `limits.json` exists (no
bundled fallback). If this machine has never been provisioned, or the connect
handshake fails naming a missing/unknown function key, run once:

```
zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_stage_limits.ipynb
```

The pre-filled values are this machine's known-good envelope; adjust only if you
have better numbers for *this* stage.

## Step 2 — confirm AutoSave

Confirm LAS X native AutoSave is **enabled in the running session** and note its
`AutoSaveBaseFolder` (that is where captures land). The static StartUp `.lcf` can
report it enabled while the live session has it off — the acquire step below is
what actually proves the live state.

## Run

From `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`:

```powershell
python run_ci.py                       # 1. offline gate (portable; no LAS X)
python run_ci.py online                # 2. live read-only pass (~2-5 min)
python run_ci.py online --live-writes  # 3. full live validation, reversible (~15-30 min)
```

(`python run_ci.py both --live-writes` runs the offline suite and the live
validators in one shot if you prefer a single command.)

Then the one thing `run_ci` does **not** do (acquisitions are opt-in) — one real
capture+save through the controller:

```powershell
python tests/hardware/validate_zmart_adapter.py --yes --allow-move --allow-state --allow-acquire --allow-missing-lasx
```

Reports land in `tests/_report/hardware_run_report_*.md` (paths printed at the
end) with companion `driver_log_*.log`. Keep every report and log, including
from failed runs.

## Evaluate

Answer each with evidence (quote report rows / log lines):

1. **Offline gate:** `RESULT: PASSED`? pass count and coverage; `ruff check`
   clean (a `ruff format --check` WARN on the known pre-existing files is
   non-fatal).
2. **Live steps:** which of the 7 passed — limits mock self-check, passive
   readers (api/log/hybrid), reader parity + routed modes, zmart-adapter
   round-trip, and the end-to-end validator once per `--state-reader-mode`
   (api/log/hybrid)? Any API timeouts/hangs (should be 0)?
3. **Reader routes:** for each datum, do api/log/hybrid agree? Does the `log`
   leg ever deliver or is it SKIP/absent on this machine (fail-closed on a
   stale/absent log is expected, not a failure)? `jobs` is api-only by design.
4. **Confirmation health:** which changes went unconfirmed, after how many
   attempts, on which route? Unconfirmed-after-3 is reported-and-continue by
   policy — cluster it (one setting / one route / systemic).
5. **Restore verification:** does every `Mutates scope: YES` row have a matching
   restore, and did the final state match the initial (job, settings, XY/Z,
   objective)?
6. **Acquire + save (the headline):** did `acquire` find and validate its
   OME-TIFF via native AutoSave and materialise it into the SMART layout under
   the output root? Is `settle == "backlash-corrected"`? Confirm
   `get_acquisition_options` no longer offers an `exporter` key.
7. **AutoSave-off diagnostic (optional but valuable):** turn native AutoSave
   **off** in the live session, re-run the acquire command, and confirm it fails
   with the actionable *"most likely disabled in the running LAS X session"*
   message (not a generic error, not a hang) at ~the 60 s detection window — then
   turn AutoSave back on. **Watch for:** if it *hangs* instead of failing, LAS X
   created an empty project shell even with AutoSave off, which the collector's
   project-detection heuristic would mis-read as "engaged" — report that.

## Known / expected — do NOT file these as new failures

- **Stale api job-select readback (F2, known):** the `[api]` route may show a
  ~15 s stale `IsSelected` lag; production defaults to hybrid.
- **XY/Z outside the envelope → SKIP, not FAIL:** the simulator commonly homes at
  0,0. Park the stage inside the calibrated envelope to actually exercise moves.
- **A single transient `could not determine the selected LAS X job`** on one read
  is a known reader hiccup, not a regression.
- **`ImageTransformation = RIGHTTOP`** on this LAS X version (not `TOPLEFT`) is a
  known version quirk, not an open item.

## Deliver

1. Force-add the run artifacts (they are gitignored) and commit to the working
   branch: `git add -f tests/_report && git commit && git push -u origin <branch>`.
2. Write `tests/_report/BENCH_FULL_CI_<date>.md`: a verdict per question above
   with quoted evidence, an overall **PASS / PASS-WITH-FINDINGS / FAIL**, and a
   ranked follow-up list. Name any finding that maps to a known open item.
3. Give the operator a ≤10-line spoken summary: overall verdict, whether acquire
   saved end-to-end, which reader leg wins and at what latency, confirmation
   health, and the single most important follow-up.
