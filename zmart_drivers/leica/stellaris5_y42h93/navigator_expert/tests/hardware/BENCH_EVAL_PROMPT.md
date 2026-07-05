# Prompt: run and evaluate the Leica hardware validation

Copy everything below this line into the agent that will run tonight's eval on the
LAS X PC. It is self-contained; the agent needs no other context.

---

You are running and evaluating the hardware validation of the ZMART Leica
Stellaris5 driver, on the LAS X PC, against the real instrument (or the LAS X
simulator — detect which and say so in your report).

## Context

- Repo: ZMART-microscopy, branch `claude/smart-drivers-code-review-ky4phc`.
  Verify `git log -1` — the expected state is commit `75f3f29` or a descendant.
  If the checkout is older, STOP and report; do not run stale code on hardware.
- Working dir for everything below:
  `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`
- The runbook is `tests/hardware/README.md` — read it first and follow its
  prerequisites exactly (LAS X running, ≥2-job template loaded, stage clear and
  inside the calibrated envelope, no modal dialogs).
- Recent relevant changes you are validating: routed state reads now default to
  `hybrid` mode; the hybrid confirmation race's API-leg deadlock (finding CF-01)
  was fixed and tonight is its first hardware exercise; the side-by-side
  validator (FD-12 crash) runs live for the first time ever.

## Safety rules (hard)

- Never edit stage or function limits, and never pass wider limits than the
  machine config provides.
- Use only the documented run_ci/validator invocations. Nothing under
  `experimental/` touches hardware.
- Do not enable `--allow-objective` or `--allow-acquire` unless the operator
  explicitly says so in this session.
- If the driver hangs >5 minutes with no log progress, or the stage does
  anything unexpected, stop the process, note the exact time, and report —
  do not retry blindly.
- Do not push to `main`. Commit run artifacts to the working branch only.

## Run

```powershell
python run_ci.py online                # read-only pass first (~2–5 min)
# Only if the read-only report looks sane (see Evaluate step 1):
python run_ci.py online --live-writes  # full validation (~15–30 min)
```

Reports land in `tests/_report/hardware_run_report_*.md` (paths are printed at
the end). Keep every report, including from failed runs.

## Evaluate

Work from the Markdown run reports plus the driver log. Answer each question
with evidence (quote the report rows/log lines):

1. **Read-only sanity (gate for --live-writes):** did all readers return values?
   Any FAIL rows, API timeouts/hangs, or `CRASHED` line? If yes → do not
   proceed to live writes; report.
2. **Reader-mode comparison (the core question):** from the per-reader-mode
   timing table and the `read[datum] mode=...` rows — for each datum: do api,
   log, and hybrid agree on values? What are the per-mode latencies and reading
   ages? Does the log leg ever deliver (age present) or is it always SKIP?
   Does hybrid ever lose to plain api on latency by more than ~2×?
3. **CF-01 fix on hardware:** in the select_job round-trips — which leg
   confirmed each switch (`confirmed by log leg` / `confirmed by api leg`) and
   how fast? MUST be absent: any `api read not started: another read in flight`
   during select_job confirmation, and any
   `confirmation race budget exhausted; still pending: api`. If either appears,
   the fix regressed on hardware — capture the full log section.
4. **Confirmation health:** from the summary's Confirmed/Unconfirmed columns
   and the unconfirmed-actions table — which changes went unconfirmed, after
   how many attempts, on which reader route? Per current policy, unconfirmed
   after 3 attempts is reported-and-continue, so unconfirmed rows are data,
   not failures — but cluster them: is it one setting, one route, or systemic?
5. **Timing profile:** slowest actions table — anything anomalous vs the
   documented expectations (setting writes dominated by ≤3×3 s confirm
   windows)? Note the median command round-trip and time-to-confirmation.
6. **Stale-API quirk:** any evidence of the historical 15 s+ stale API
   readbacks (large reading ages on api-mode reads, especially selected_job)?
   This calibrates how much the hybrid/log side matters on this scope.
7. **Restore verification:** does every `Mutates scope: YES` row have its
   matching restore row, and did the final state match the initial (job
   selection, settings, XY/Z position)?

## Deliver

1. Commit the report files to the branch
   (`git add tests/_report && git commit && git push -u origin <branch>`).
2. Write `tests/_report/BENCH_EVAL_<date>.md`: a verdict per question above
   (with quoted evidence), an overall PASS / PASS-WITH-FINDINGS / FAIL call,
   and a ranked list of follow-up actions the findings justify. Where a
   finding maps to a known open item (backlash wiring, acquire-idle
   confirmation, unbounded waits CF-02/CF-03, teardown gap, stale-response
   correlation), name it — the open list lives in
   `docs/reviews/COMPLETE_REVIEW.md` (status addendum) and
   `docs/reviews/MAINTAINER_DECISIONS.md`.
3. Commit and push that file too, then give the operator a ≤10-line spoken
   summary: overall verdict, which reader leg is winning on this scope and at
   what latency, confirmation health, and the single most important follow-up.
