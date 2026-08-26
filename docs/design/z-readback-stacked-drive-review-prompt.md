# Review prompt: Z readback on a stacked drive

Paste to an external reviewer with `docs/design/z-readback-stacked-drive.md`
and read access to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`
— in particular `readers/z_readback.py`, `tests/unit/test_z_readback.py`,
`readers/derived.py`, `readers/router.py`, `commands/confirmations.py`
(`confirm_move_z`, `_readback`), `commands/commands.py` (`move_z`,
`_dispatch`), `config/profiles.py` (`MOVE_Z`, `CommandProfile`),
`scanfields/files.py` (`save_experiment`, `save_and_read_lrp`).

---

You are reviewing a small new reader and a plan to wire it into a microscope
driver. The instrument's API reports no Z position; the field the driver
used as one freezes for whichever drive carries the job's z-stack. The new
reader falls back to saving the experiment and reading the position from
the saved file — a value that is current but is the last *command*, not a
hardware reading. Read the design note first, then the code. Answer with
line numbers.

1. **Is the reader's decision actually free on the free path?** Trace
   `read_z` for a drive that carries no stack: count CAM calls, parses,
   allocations. Compare with `router.read_zwide_um` today. Any extra cost
   is a defect against a stated requirement.

2. **Can `read_z` return a stale number?** Enumerate every path that
   returns a `ZReading` and say what evidence each rests on. Pay attention
   to `save_and_read_lrp` returning a parse of a file that the save did not
   actually rewrite (its mtime/size confirmation), and to the log-reader
   leg (`mode="log"`), whose settings snapshot may be older than the move.

3. **The `.lrp` is per-job setpoint memory.** Under what job selection and
   move-issuing conditions would `z_um_from_lrp` return a value for
   `job_name` that does not reflect the last move on that drive? (Hint: a
   move issued through a different job name.) Should `read_z` require that
   the move and the read go through the same job, and how would it know?

4. **Step 2 of the plan (`confirm_move_z`).** Show precisely where the
   `MOVE_Z` profile's re-fire happens (`_dispatch` → `confirm_and_fire` →
   `refire_on_unconfirmed` / `max_confirm_attempts`) and whether returning
   early from `confirm_move_z` is enough to suppress it, or whether the
   profile needs a per-call override. Which is the smaller, cleaner change?

5. **Decision A.** Argue for one of the three meanings of `confirmed` on the
   stack drive, from the point of view of the callers that exist
   (`zmart_adapter`, the validator, calibration). Say which callers treat
   `None` as a failure today.

6. **One owner per fact.** `LRP_Z_USE_MODES` in the reader duplicates
   `Z_USE_MODES` in `experimental/lrp_edits/z.py`. Where should the single
   copy live, given the experimental package must not be imported by core?

7. **The gate.** `save_experiment` is refused until the limits handshake
   has run for the session. Under which entry points (adapter connect,
   `connect_microscope`, tests) could `read_z` reach the save without a
   handshake, and what should it do then — refuse loudly, or fall back to
   the frozen settings value with `source="settings-stale"`?

8. **What did the plan miss?** Anything that persists or compares
   `zPosition` that the plan's step 3 does not name (grep `zPosition`,
   `zwide_um`, `z-galvo` across the driver and `zmart_adapter`).

Findings that change the design first; naming and style last. Do not
propose GUI-based readouts; they are excluded by decision.
