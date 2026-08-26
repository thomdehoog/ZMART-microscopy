# Finding: grown slab windows went negative — CLOSED 2026-08-19

> Found by the timepoint-landing instrument on 2026-08-19, bisected the
> same night, and run fully to ground the next session. Fixed in
> `governed.py`; pinned by `test_two_runs_share_one_process.py`.

## The symptom

Serving a grown (t, c) live run of 64 positions in a process that had
already served a 16-position run of the same name, some coarse pieces
answered **503 forever**: `composer._read_from` computed
`np.empty(high - low)` with a negative extent, and the composer's warm
thread died on the same error. The page never painted.

## The mechanism, caught red-handed

Not a race at all, in the end — the "race" was scheduling noise around a
deterministic poisoning. `TheWorldFrame` (the governed run's mosaic,
whose geometry is the layout's) remembered its origin and per-level
extent in **class-level caches keyed by (run_id, layout revision,
profile)** — on the assumption that the triple names one layout. It does
not: a viewer process outlives one acquisition, and the same script run
again into a fresh folder carries the same run name, the same sealed
profile, and a layout starting from the same revision number.

The second run then read the FIRST run's remembered frame. The probe
caught the inconsistency whole: a mosaic whose index placed 64 tiles out
to x = 1152 while its cached shape said 672 — the 16-position run's
extent. Every tile beyond the remembered frame clamps its slab window to
`to < from`: the negative dimension, the dead warm, the eternal 503s.
The loud crash was the RIGHT behaviour — the same poisoning with extents
that happened to fit would have placed tiles silently wrong.

## The fix

The run's **folder** — the identity that actually distinguishes two runs
— is now part of both remembered keys (`_origins` and `_shapes` in
`TheWorldFrame`). Within one folder the layout revision genuinely names
the layout, so the caches keep the per-commit saving they exist for.

## The gates

- `test_two_runs_share_one_process.py`: two grown runs, same name, same
  profile, small first — every placement of the second must sit inside
  its own frame at every level, and every coarse piece must compose. Red
  before the fix with the poisoned numbers (a tile reaching 1664 in a
  frame remembered as 1344); green after.
- `measure_a_timepoint_landing.py` multi-rung is the end-to-end
  regression: every rung reuses one process and one run name by design.

## The bisect ledger that led here (kept for the method)

| sequence (one process) | outcome |
|---|---|
| 16 alone / 64 alone / 16→16 / 64→64 | fine |
| 16 → 64 | second run never paints |
| 16 → 64, first folder kept (no inode reuse) | still fails |
| 64-run, warm run synchronously, fresh composer | clean |
| 64-run after 16, probe dumping state at the crash | index at x≤1152, shape 672: the smoking gun |
