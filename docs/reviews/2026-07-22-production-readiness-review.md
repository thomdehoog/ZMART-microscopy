# Production readiness: workflow website, adapter, and driver (2026-07-22)

This document records where the three layers of the target-acquisition stack
stand on the road to routine production use, what was double-checked and fixed
in this pass, and the short list of work that is still open. The three layers
are:

- the **workflow website** (`workflows/target_acquisition`, served by
  `run_webapp.py`),
- the **controller and its Leica adapter** (`zmart_controller` +
  `zmart_drivers/leica/.../zmart_adapter`),
- the **Leica Navigator Expert driver** underneath.

## What was checked and fixed in this pass

**The adapter no longer carries driver decisions.** The adapter is meant to be
a thin translator between the controller's vocabulary and the driver. It had
quietly accumulated several tuning decisions of its own: the experiment flush
timeout, the default backlash-correction rounds, the default capture options
(strip scan fields, cleanup, backlash on/off), and which z drive realizes a
move when the workflow does not choose one. Those are decisions about *this
microscope*, so they now live in the driver's config
(`config/profiles.py`, the `ZMART_ADAPTER` profile) next to the rest of the
machine tuning. The adapter reads them fresh on every call; tuning the adapter
now means editing one profile, never adapter code.

**Two stale calibration tests asserted the old reader policy.** The recent
hardening work moved reader-backend choice fully into the state-reader
profile — callers never pin "api" or "log" themselves, and an architecture
guard test enforces that. Two calibration integration tests (and two comments
in `calibration/core/common.py`) still described the old pinned behaviour and
failed. They now guard the new contract instead: calibration reads must leave
the backend choice to the profile.

**The mock adapter validator now selects the fixture's calibration.** The
hermetic mock publishes its two-objective translations as a *named*
calibration set, and named sets are only ever selected explicitly. The
validator never selected it, so the session loaded the placeholder default and
the (correct, fail-closed) objective-swap refusal made the mock run fail. The
mock run now connects with `calibration_name="water_lens_setup"`, and the full
mock validation passes again.

**The website stopped folding sections underneath the operator.** Whenever a
widget mounted mid-run, the page re-fetched the full state snapshot and
re-applied the *boot* layout — folding every completed section (including the
cell explorer the operator was working in) and opening the next one. Section
layout now happens exactly once, when a fresh page catches up on an existing
run; mid-session refreshes and brief stream reconnects leave the operator's
view alone. The end-to-end browser tests caught this once their own masking
bug (a wrong Playwright cleanup call) was fixed; all five now pass.

**Starting the website is now one double-click.** `start_website.bat` (and
`start_website_demo.bat` for the simulated scope) start the server and open
the browser themselves. Each microscope PC keeps its own choices — which
Python environment, where the analysis repository lives — in a small
`start_website.local.bat` next to the launcher, written once per machine and
ignored by git, so pulling updates never overwrites a machine's settings.
From a terminal, `python run_webapp.py --open` does the same.

**Test state after this pass:** Leica driver suite 1364 passed (1 skip needs a
real LAS X installation), workflow + controller suites 344 passed, and the
real-browser click-through of the whole demo run passes.

## Multiple channels: what works today

Multi-channel jobs work through the whole acquisition path. The adapter
returns every saved plane with its time/z/channel index, the workflow refuses
anything that is not a single-timepoint, single-z capture (so channels can
never be confused with a z stack), and the overview map and gallery display
channels as an additive colour overlay with per-channel colour, visibility,
and contrast controls.

One decision is still implicit: **cell segmentation runs on the first channel
only.** The analysis engine receives channel 0 of each overview tile. That is
fine when the structural stain comes first in the job, and wrong otherwise.
Until a channel picker exists, order the overview job so the channel to
segment on is first — or we add "segmentation channel" as an explicit option
(small, well-contained change in `steps.overview_inputs_from_records`).

## Open work before calling it production ready

1. **A run journal for the website.** The notebook tees its console output
   into timestamped per-run log files (`workflow/_log_capture.py`); the
   website currently writes no chronological narrative at all — its step
   notes vanish with the tab. Wiring the same capture into the web flow's
   worker would give every website run the same reconstructable record the
   notebook runs have.
2. **Explorer polish.** The threshold histograms are unlabeled 20-bin bars
   with a fixed pixel scale — enough to see a distribution's shape, not to
   read values from; proper axes/scaling would make gating decisions easier.
   Image zooming is also still uneven: the overview map pans and zooms, the
   gallery has a click-to-enlarge lightbox, but the explorer's hover previews
   and the enlarged views have no zoom of their own.
3. **Per-machine launch settings.** Each microscope PC needs its
   `start_website.local.bat` written once (the ZMB PC's content is recorded
   in `workflows/target_acquisition/MEMORY.md`).
4. **The one owed hardware pass.** The z model assumes the two z drives add
   with the same sign; the arithmetic and readback conventions are validated
   against a live CAM, but the *physical* additivity on a real objective
   still wants one bench pass (park the galvo at a known offset, move z-wide,
   check the focus sum) before trusting large z moves. The acquire/save and
   autofocus phases of `validate_zmart_adapter.py` also only run live —
   the mock rightly skips them.
5. **Segmentation channel choice** — see the channels section above.

## Known design limitations (found in a later critical review)

These are not bugs — the code behaves as written and is tested — but they are
places where a feature promises more than the current data or wiring delivers.
They are recorded here so nobody mistakes the demo for the production story.

1. **Combined gates need per-channel features the real engine may not report.**
   The explorer can gate on any per-cell measurement discovery hands it, and
   selecting double / triple-positive cells specifically needs a per-channel
   intensity (a "marker A" and a "marker B" to require together). Today the
   ONLY producer of per-channel metrics in this repository is the simulated
   engine; the real smart-analysis pipeline must be configured to extract
   per-channel intensities for multi-marker gating to work on a microscope.
   Until that is confirmed, treat the multi-marker gating demo as aspirational:
   the ZMART side is correctly built to consume the features (a generic
   `pick["metrics"]` passthrough) and degrades gracefully to area / eccentricity
   / single intensity, but the production data feeding double-positive gating is
   unverified. This is the first thing to settle before relying on the feature.

2. **The field-of-view preview shows hand-picked cells, not a random sample.**
   The strip under the plot previews the cells picked by hand. The gallery's
   default Acquire draws a RANDOM sample from the gate instead, and those cells
   are not previewed — so "see what will be acquired" only matches reality when
   the operator uses "Acquire selected".

3. **The overview map does not show the discovered cells in the web app.** The
   viewer supports cell marks over the mosaic (`_linked_viewer`), but the web
   flow never links the explorer to the map, so discovery shows a feature-space
   scatter rather than dots on the real image. The intuitive "cells lit on the
   map" view exists in code but is unwired.

4. **Two orchestration paths.** The notebook cells and the web `RunFlow` both
   implement the same run and can drift; several behaviours (the run journal,
   the restart/shutdown guards, the segmentation-channel plumbing) live only in
   the web flow.

5. **The widget JavaScript is only covered by browser tests.** The React apps
   live in Python strings that unit tests never execute, so a JS mistake passes
   pytest and is caught only by the Playwright tests — which are slow and skip
   when Playwright is absent.

## How to re-verify

```bash
python -m pytest zmart_controller workflows -q          # controller + website
python -m pytest zmart_drivers/leica -q                 # full Leica suite
python -m pytest zmart_drivers/mesospim zmart_drivers/zeiss -q
```

(The driver suites must be run per vendor — collecting `zmart_drivers` in one
pytest run trips on same-named test modules across vendors.)
