# Follow-up review brief: Viewer delivery after the JPEG review

Date: 2026-09-01

Status: answered at commit `e73aa7f1` in
`docs/reviews/2026-09-01-review-of-the-revised-viewer-delivery-plan.md`.
The next review should use
`docs/design/viewer-delivery-implementation-plan-50-percent-review-prompt.md`.

Please review the revised decision and plan; do not implement it.

## Context

The first JPEG-pyramid proposal was reviewed on branch
`claude/lazy-jpeg-pyramids-review-fhz6te` at commit `48f72d64`. That review
found that the motivating 8,400-field request cost belonged to the retired
`jpeg-under` engine, while ZMART Viewer 0.2 already composes viewport pieces on
demand. It also found missing acquisition-wide display-window metadata, a
downsampling-coordinate mismatch, incomplete cache arithmetic, and no gate
proving a second format worthwhile.

The revised plan accepts the architectural verdict. It stops the separate JPEG
viewer and makes JPEG only a conditional representation of the existing Viewer
piece route.

## Read

1. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` completely.
2. Your first review at commit `48f72d64`.
3. The current files cited by the revised plan in ZMART-microscopy.
4. ZMART Viewer 0.2.0 at commit `9ff10b0`, especially:
   - `zmart_viewer/compose.py`;
   - `zmart_viewer/contrast.py`;
   - `zmart_viewer/building.py`;
   - `zmart_viewer/pieces.py`;
   - `docs/measured/MEASURED_the_ladder_of_surveys.md`;
   - `docs/open/MEASURED_the_four_ways_of_serving.md`;
   - `docs/open/PLAN_one_door_one_source.md`;
   - `docs/open/PLAN_two_viewers_one_contract.md`.

Name the commits actually inspected.

## Questions

1. Does the revision fully remove the second viewer/grid/manifest/invalidation
   path, or does one remain under a different name?
2. Is acquisition-level metadata the correct authority for one display window
   per channel? Correct the proposed precedence and legacy behaviour where
   needed.
3. Is omitting per-position `start`/`end` when no acquisition-wide window
   exists compatible with the current composed and linked paths?
4. Does the proposed storage accounting distinguish authoritative,
   scientific-working, baked, cached, browser, and memory bytes correctly?
5. Challenge the proposed limits: 2 seconds to first useful picture, 500 ms
   p95 navigation and live landing, fivefold fewer bytes, 10% per run, and a
   5-GiB all-runs automatic-cache ceiling.
6. Is the smallest response-size experiment 8-bit through the existing codec,
   JPEG through the same piece address, or something Viewer 0.2 already does?
7. Can either encoded response actually reuse the current frontend source, or
   would it necessarily create a second source/renderer and therefore fail the
   plan's own gate?
8. Is the qualification about area reduction correct: it can be registered
   only with an explicit per-level translation, while the existing scale-only
   convention is tied to decimation?
9. Does the revised Z section now distinguish verified repository facts from
   the reported but not yet committed `z=0`/`z=0.5` trace?
10. What is the smallest concrete phase-0 patch, and which repository owns
    each changed file?

## Requested output

Lead with remaining blockers. Then give:

1. corrections to the revised architecture;
2. a proposed final display-window schema and authority chain;
3. exact phase-0 measurements and existing harnesses to reuse;
4. any gate that is arbitrary, impossible to measure, or easy to game;
5. a verdict: accept the stop decision, revise again, or retain a separate
   JPEG experiment now.

Do not write implementation code. Cite files, tests, measurements, or standards
for factual claims and label inferences as such.
