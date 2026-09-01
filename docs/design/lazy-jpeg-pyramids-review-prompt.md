# Review brief: lightweight JPEG pyramids for the ZMART viewer

Date: 2026-09-01

Please review the design; do not implement it yet.

## What to read

Read these completely before reaching a verdict:

1. `CLAUDE.md`
2. `docs/design/lazy-jpeg-pyramids-for-the-viewer.md`
3. `docs/reviews/2026-09-01-review-of-the-smart-viewer-integration-plan.md`
4. `docs/reviews/2026-09-01-why-the-acquired-overview-never-appeared.md`
5. `application/PLAN.md`, especially “Found on the way”
6. `viz_studio/backend/jpeg_tiles.py`
7. `viz_studio/options/jpeg-under/viewer.js`
8. `viz_studio/options/contract.md`
9. `application/framework/bridge.py`, specifically `view_of`,
   `_the_view_of`, and `_send_a_picture`
10. `application/parts/storage/viewer_service.py`
11. `application/parts/canvas/engines.js`
12. `application/workflows/target_acquisition/steps/scan_the_overview/watching-the-run.js`

Also inspect the actual current ZMART Viewer repository/version 0.2 if it is
available. Do not infer its behaviour from the older `viz_studio/backend/`
copy. Name the viewer commit you inspected.

## Product goal

ZMART needs a fast, low-friction two-dimensional view of microscopy data in an
ordinary browser or PyWebView. Work and transfer for a settled view should
follow viewport size rather than the number of microscope fields. The TIFFs
remain authoritative and JPEGs are display-only.

The persistent display cache must be partial, bounded per acquisition by source
size, and bounded across all cached runs by one absolute limit. The proposal
starts with:

```text
per-acquisition soft target = 5% of source bytes
per-acquisition hard ceiling = 10% of source bytes
all-runs cache-root soft target = 5 GiB
all-runs cache-root hard ceiling = 10 GiB
```

The numbers are provisional. The rule that a huge dataset cannot produce a
huge cache merely because its percentage is small is not provisional.

## How to review

Lead with blocking findings, ordered by consequence. For every factual claim,
name the file, function, experiment, standard, or official library behaviour
that supports it. Separate:

- facts verified in the repositories;
- inferences;
- decisions that require measurements on real ZMART images or the microscope
  PC.

Do not reward the plan for being detailed. Look for a smaller design that meets
the same goal and for work Smart Viewer 0.2 already does. In particular, reject
any arrangement that quietly creates a second large persistent dataset or a
second independent production viewer backend.

## Questions that need an answer

1. Does a global JPEG tile pyramid actually remove the measured 8,400-field
   fetch-queue problem, or is there a cheaper correction to the existing
   OME-Zarr/Smart Viewer path?
2. Is the proposed stable channel-wide 16-bit-to-8-bit encoding truthful and
   useful for ZMART fluorescence? What real data would disprove it?
3. Can area downsampling preserve sparse puncta well enough, or should max or
   another display-only reducer be tested? Name the visual failure each option
   risks.
4. Is the live algorithm sound? Specifically, can a bounded transient lossless
   RAM tile prevent both O(total fields) rebuilds and cumulative JPEG damage
   without becoming necessary persistent state?
5. Is a partial LRU disk cache operationally acceptable? Challenge the proposed
   5 GiB soft and 10 GiB hard defaults.
6. Is one deck.gl TileLayer per channel, with a BitmapLayer shader extension,
   the smallest reliable renderer under `viz_studio/options/contract.md`?
   Verify the exact installed deck.gl/luma.gl versions rather than current docs
   alone.
7. Does the proposal preserve physical placement, pixel-edge convention,
   orientation, live extent, z/time selection, retakes, and acquired-black
   versus unimaged ground without guessing?
8. Can the same route work in the supported PyWebView engine on the microscope
   PC? State what must be measured or installed, especially WebView2/WebGL2.
9. Where should production generation and serving live: ZMART Viewer or
   ZMART-microscopy? Give a concrete ownership boundary and identify any plan
   step that violates it.
10. Does explicitly selecting JPEG for flat display avoid the old silent-
    fallback failure, or can the proposed integration still conceal a broken
    source path?
11. Are the phase gates capable of killing the idea early, or do any merely
    confirm that work was completed?
12. What concurrency, cache-corruption, path-validation, or source-change
    failure is missing?
13. Review the Z model specifically. Is it correct to map every source's
    explicit anchor-plane voxel centre to shared display z=0 in 2-D, preserve
    acquisition Z separately, and apply calibrated physical placement only in
    a 3-D scene? Identify any half-voxel, stack-anchor, layer/source double
    translation, or navigation-state ambiguity that remains.
14. In 2-D, should a one-plane source stay pinned to its anchor while another
    source's stack is navigated, or does the existing viewer contract require a
    different explicit per-source selection model?

## Requested output

Return:

1. blocking findings;
2. important non-blocking corrections;
3. claims you verified and agree with;
4. a simpler alternative, if one exists;
5. recommended changes to the phase order and gates;
6. a clear verdict: proceed to phase 0 only, proceed to a static spike, revise
   before measuring, or stop.

Please do not write implementation code. Small calculations, manifest examples,
or pseudocode are welcome only when they expose a design fault or make a
correction precise.
