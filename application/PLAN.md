# The plan from here (2026-08-29)

Two phases, in this order. The first makes the mock run the whole workflow for
real; the second makes the code read as if one person wrote it. Not the other
way round: refactoring code that is still moving is work done twice.

## Where we stand

Steps 1–5 — connect, carrier, scan area, focus map, overview — go through the
bridge to the mock driver for real: images in `<type>/data/`, state in
`data/metadata/`, JPEGs in `view/`, analysis via the warm engine. Nothing on
that path pretends except the mock driver, which is a real driver.

Steps 6–8 do not touch the backend:

- **6 Discover targets** — detection runs on the page over pretend cells, not
  on the overview tiles just scanned.
- **7 Refine targets** — the gate works, on those pretend cells.
- **8 Acquire targets** — the gallery pairs come from `pretend-sample/rng.js`;
  nothing is acquired.

## Phase 1 — the mock to the end of the workflow

The rule that made steps 4–5 real applies unchanged: the page asks, the driver
captures, the analysis measures, the viewer shows.

0. **The mock's sample becomes a real micrograph.** scikit-image's `kidney`
   (mouse kidney, 16 z-planes × 512×512 × 3 channels: nuclei, glomeruli,
   tubules; fetched once with pooch into
   `C:\ProgramData\MinicondaZMB\home\t.de\skimage-data`, `SKIMAGE_DATADIR`)
   replaces the synthetic tissue. Every frame the mock writes is a crop of it
   at the asked position; sharpness still follows the mock's height model and
   debris. Then the full pipeline, cellpose included, has real cells to find.
1. **Discover** = `object_analysis` in `zmart_analysis` on the overview tiles,
   through the same warm engine the focus map uses. Detections come back with
   stage coordinates and land on the canvas as they arrive — one position at a
   time, like the focus points. The mock's overview tiles carry objects to
   find, drawn by the mock driver the way it draws focus curves today.
2. **Refine** = the gate on the real detections. The gate already reads what it
   is given; little to build.
3. **Acquire** = `acquire` with acquisition type `targets` at each gated
   position, through the bridge → `targets/data/`, JPEGs in `view/`, the
   gallery shows the real pictures. The verdicts stay on the page: they are the
   operator's.
4. One operator walk of all eight steps on the mock, in the window. Then the
   browser test that does the same, and the full suite exactly once.

In parallel, driver only, parked until LAS X can be reached again: **the
simulator homes at connect.** In `zmart_adapter.connect()`, after the limits
handshake and before the handle is returned, when the hardware identity says
simulator, drive to the CI's known-safe position (x 63500, y 41500, z-wide 0,
z-galvo 0); the constant moves from the CI script into the adapter so the two
cannot drift. Refused → connect raises. The real scope never moves at connect.
Own branch off `main`, PR, then merged in.

## Phase 2 — the refactor

1. **An audit first, no edits.** One document, per folder: what is here, does
   it belong here, what would a newcomer expect to find and where. Judged by
   the rules already written down: the framework knows no workflow; parts are
   what a step reaches for; a step is one folder, `run` plus its helpers
   below; tests beside what they test; the mock is a real driver. The audit
   goes to Codex for review before anything is touched.
2. **Then the moves**, one folder per commit, tests green after each, nothing
   new built while moving.
3. **Then the reading pass:** docstrings carry the why, no comment blocks
   above statements, no filler; names in operator terms.
4. **Done when** someone who has never seen the code opens `application/` and
   finds a step, its backend verb and its test in under a minute, from the
   folder names alone.
