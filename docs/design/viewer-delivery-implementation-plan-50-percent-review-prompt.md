# Review brief: 50% Viewer delivery implementation plan

Date: 2026-09-01

Please review the implementation plan; do not implement it.

## Read

1. `docs/design/viewer-delivery-implementation-plan-50-percent.md` completely.
2. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` completely.
3. The prior reviews at commits `48f72d64` and `e73aa7f1`.
4. ZMART-microscopy at the commit containing this prompt.
5. ZMART Viewer 0.2.0 at `9ff10b0` or name the newer commit actually inspected.

## Review stance

This is a 50% plan: safe prerequisites should already be implementation-shaped,
while fixture choice, the real preset source, session locking, thresholds, and
compact-view details are intentionally awaiting review. Do not penalise it for
not authorising compact `uint8`; do identify any prerequisite that is still too
vague to implement safely.

## Questions

1. Does the V1 → V2 → M1 → I1 → M2 → M3 order guarantee that no released
   combination reintroduces the camera-range window?
2. Is `positions/<type>/zmart-acquisition.json` the right location, and is the
   proposed schema sufficient without duplicating authority?
3. In the actual Leica/controller path, where should channel key, label, colour,
   numeric range, and optional display window originate? Name the files and
   reject any field the real API does not provide.
4. Is the proposed legacy reconciliation correct: refuse identity mismatch,
   accept full consensus, and omit only disagreeing `start`/`end`?
5. Can Viewer frontend/config paths safely carry `window: null`, or does an
   engine need a different waiting mechanism before the first pixels arrive?
6. Should M2 use package version pinning or explicit capabilities, considering
   the Viewer's optional editable install in `environment.yml`?
7. Is a held file lock plus nonblocking startup sweep safe on both Windows and
   POSIX? Propose the smallest robust alternative if not.
8. Are all scratch/cache roots and byte categories now named? Identify any
   untracked persistent root.
9. Are the 90% coverage definition, cold/warm scopes, 500-ms gates, 20-cycle
   memory proxy, 10% per-run cap, and 5-GiB global cap measurable and hard to
   game?
10. Can the external-run options harness remain read-only with the proposed
    files, or should the real-run trace live entirely in ZMART Viewer?
11. Are the two proposed Playwright tests sufficient to make `z=0` versus
    `z=0.5` reproducible without coupling the test to one engine accident?
12. Does the future whole-picture `uint8` boundary truly preserve one source at
    a time? Confirm that JPEG is now fully absent from the implementation path.

## Requested output

Return:

1. blockers ordered by migration or data-loss risk;
2. corrections to target files, interfaces, tests, and commit order;
3. a final recommended acquisition descriptor schema;
4. a final compatibility/release mechanism;
5. accepted benchmark definitions and thresholds, with replacements where
   needed;
6. a checklist of decisions required for the 80% plan;
7. verdict: ready to refine to 80%, revise the 50% plan first, or stop.

For factual claims, cite files/functions/tests from the inspected commits.
Label proposed design choices separately from verified behaviour.
