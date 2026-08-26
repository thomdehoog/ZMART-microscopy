# Prompt: measure the ladder on this machine, and go further

You are picking up a measured optimization campaign on a fresh machine.
The full story so far — what was changed, what each change did to each
metric, what was tried and reverted, and why — is in
`docs/measured/MEASURED_the_ladder_of_surveys.md` in this folder. Read it first. The
numbers there came from a small software-rendering container; this
machine is the first with real cores and a real disk, so your job is to
establish the real numbers, then push on the recorded open threads.

## Ground rules, from the campaign you are joining

- **Measure before and after everything.** No change ships on the
  strength of an argument; the harness's columns are the only verdict.
- **Zero transients, or it does not ship.** The churn's recorder counts
  frames where tiles dip dark and return. A speed-up that flickers was
  already caught and reverted once this campaign; the gate wins.
- **Byte-equality is what "correct" means** for the baked picture: a
  patched bake equals a from-scratch bake, a warmed slab equals a
  composed one. The tests pin this; keep them green.
- **Write findings down** in `docs/measured/MEASURED_the_ladder_of_surveys.md` as you
  go — including the failures, with their evidence. Commit results
  (`ladder_results.json` snapshots) as they land, not at the end.

## First: prove the machine

1. Set up: `pip install -r requirements.txt playwright pillow pytest`,
   `python -m playwright install chromium`, then
   `cd zmart-viewer/app/page && npm install && npm run build`, and the
   options harness too: `npm --prefix zmart-viewer/parked/harness
   install && npm --prefix zmart-viewer/parked/harness run build` —
   without it the suite's pixel-reading tests skip quietly.
2. Run the guard tests:
   `python -m pytest zmart_live/tests zmart-viewer/tests -q`
   (browser-based picture tests need the Chromium just installed; set
   `ZMART_REQUIRE_BROWSER=1` so a missing browser fails loudly instead
   of skipping).
3. Run the ladder's quick half and compare shapes with the recorded
   tables:
   `python zmart-viewer/app/picture/measure_a_ladder_of_surveys.py
   --powers 6-12 --fixtures <somewhere with room>`
   (~33 GB keeps every fixture for cheap re-runs; `--tidy` if tight.)
4. If the shapes hold, run `--powers 6-15` for the full record. The
   runner resumes from its own `ladder_results.json`; nothing is
   repeated.

## Then: the open threads, in order of value

1. **The bake worker count.** `_BAKE_PROCESSES` in `declare.py` is
   capped at 4 for a four-core container. Raise it toward this
   machine's core count and measure the bake column at 2^12 and above —
   the factor grew with scale on four cores and should grow again here.
2. **The reverted parallel-decode prefill.** Find the commit titled
   "The prefill decodes without the loop, several blocks at once" and
   its revert. It made the warm's block prefill genuinely parallel and
   byte-identical — and produced thirty-two on-screen transients in one
   rung, all in the landing row, reproducible, one-commit bisect. The
   mechanism was never run to ground. Reinstate it on a branch,
   reproduce the flicker (`--powers 7-7` sufficed), and instrument until
   the mechanism is understood — suspicion fell on the per-commit
   re-warm's decode threads racing the patcher, not on the decoded
   bytes. Only a version with zero transients at every rung may land.
3. **The warm-race at the top rung.** With the prefill fixed, the warm
   should finally fit inside the harness's five-minute head start at
   32,761, and that row should fall onto the trend line. That is the
   campaign's remaining headline claim; measure it.
4. **Smaller recorded items**: the derive's residual slope (plain-Python
   snapshot walks, ~ms per thousand positions), hard-linking unchanged
   moments on replacement instead of copying, and threading the
   writer's per-level read-back for real 2048-pixel camera frames.

## What good looks like

A `MEASURED_...` table from this machine alongside the container's, the
bake and warm columns transformed at the top rungs, the 32,761 row
ordinary, zero transients everywhere — and every experiment that failed
written down with its evidence, because the failures taught this
campaign as much as the wins.
