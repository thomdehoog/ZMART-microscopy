# Bench prompt: validate the native-AutoSave-only save path

Hand this to a bench agent (or follow it yourself) on the LAS X PC to try the
latest changes on the real STELLARIS. It is scoped to **one question**: does
`acquire` now find and validate its output on its own, via LAS X native
AutoSave, with the `navigator_expert` exporter gone?

## What changed since the last bench run

- **The `navigator_expert` save exporter was removed entirely.** `lasx_native_autosave`
  is now the *only* save path. It reads the output folder from the active LAS X
  StartUp `.lcf` (`AutoSaveBaseFolder`) and does its own OME-TIFF discovery +
  validation. There is no longer an `exporter` acquire option, no `--exporter`
  flag, and no `media_path` selection — so the earlier "ran a full capture then
  failed with *No Navigator Expert OME-TIFF files found*" hiccup should be gone.
- A dead-code / docstring / README cleanup sweep followed (no behaviour change).
- Relevant commits on branch `claude/smart-drivers-code-review-ky4phc`:
  `07ac3b5` (exporter removal) and `3d83bf7` (cleanup). Confirm the tip with
  `git log -1` after pulling.

## Setup

Follow **Steps 0–1 of `BENCH_EVAL_PROMPT.md`** (build the env, provision
machine-local stage limits). Two things to double-check first:

1. **Regenerate `limits.json` if this machine was provisioned before the
   `set_procedure → run_procedure` rename.** The limits gate requires the
   `functions` block to match exactly; an old file still carrying `set_procedure`
   will refuse *every* gated move. If in doubt, re-run
   `limits/notebooks/set_limits.ipynb` once.
2. **Confirm LAS X native AutoSave is enabled** in the active StartUp
   configuration and note its `AutoSaveBaseFolder` — that is where captures land.

## Run

From `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`:

1. `python run_ci.py` — offline gate. Expect `RESULT: PASSED` (the reference on
   Linux is 914 passed, `ruff check` clean; `ruff format --check` WARN is
   non-fatal).
2. `python run_ci.py --hardware` — full live validation, incl. acquire smoke.

## The one thing to verify: acquire finds + validates its output

From the `--hardware` run and its `tests/_report/hardware_run_report_*.md`
(and the companion `driver_log_*.log`), confirm the full save round-trip:

- The driver resolved the AutoSave base folder from the `.lcf` (it should match
  the `AutoSaveBaseFolder` you noted) — **no** path-not-found error, **no**
  "No … OME-TIFF files found".
- The capture produced OME-TIFF(s) that the collector located and validated
  (grid/stability/OME checks pass), and the saved product landed in the ZMART
  output layout under the machine's output root.
- `get_acquisition_options` no longer offers an `exporter` key; passing
  `options={"exporter": …}` should raise `unknown acquisition option`.

## Known / expected — do NOT file these as new failures

- **Stale api job-select readback (F2, known):** the end-to-end **[api]** reader
  step may still show the ~15 s stale `IsSelected` lag (job-select unconfirmed on
  the api-only route). Production defaults to **hybrid**, which degrades
  gracefully; log/hybrid steps pass. Not introduced by this change.
- **XY/Z outside the envelope → SKIP, not FAIL.** If the stage/sim isn't parked
  inside the calibrated envelope, those phases skip with an actionable message.
  Park it in-envelope to actually exercise the moves.

## Deliver

- The `tests/_report/` run reports + driver logs (force-add them as evidence, as
  prior bench runs did).
- A short verdict: **did `acquire` find and validate its output end-to-end via
  native AutoSave?** Call out anything that regressed from the exporter removal
  or the cleanup, and separate it from the known items above.
