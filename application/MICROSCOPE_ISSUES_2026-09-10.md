# Microscope operator issues observed on 2026-09-10

The installed named-views operator has missing previews, incomplete-looking target rendering, and slow store preparation and viewer updates. These observations were reported during use on the microscope workstation. All issues below remain open for later investigation; no fixes or root-cause diagnoses have been made.

## Installation under observation

- Operator branch: `codex/operator-named-views-simulator`.
- Operator revision: `53667bbecfa1c87160e19fcbce736e0225b8f470`.
- Viewer: `0.5.0.dev0`, built from `90e0350777a2852ee19dee7b5fe48846aa5bcf14` in `thomdehoog/ZMART-viewer`.
- Conda environment: `C:\ProgramData\MinicondaZMB\envs\zmart-operator-named-views`.
- Launch command: `python application/zmart-interface.py --built`, without simulator pixels.
- Installation instructions: [microscope installation handover](MICROSCOPE_INSTALL_HANDOVER_2026-09-10.md).

Both frontend builds and dependency checks passed. Preflight results were 525 unit tests passed, 15 skipped, and all four named-view browser tests passed with generated image fixtures. These checks did not establish correct preview behavior or performance during microscope use.

## Open issues

### 1. Focusing image previews are black

In step 4, Focus strategy, four black image squares appear at the focus points. Focus coordinates, Z results, and the focus plot are visible. The screenshot shows the focussing acquisition in Top view at Plane 1 of 201.

Expected: focusing images should be inspectable at the selected plane, with empty/out-of-range states clearly distinguished from a failed preview.

### 2. Object detection sidebar preview is black

In step 6, Detect objects, the Configure object detection preview on the right is black, although the main overview displays image data. Fast detection is selected, with tile 4 of 4 outlined on the canvas and Grey preview mode shown.

Expected: the sidebar displays the selected tile for configuring and testing detection.

### 3. Overview / Target scan sidebar comparison is black

In step 9, Acquire Targets, both halves of the sidebar comparison are black while image data is visible on the main canvas. The screenshot shows MIP mode, targets selected, and acquisition progress at 9 of 20.

Expected: the comparison displays the corresponding overview and available target image, or clearly reports pending data.

### 4. Large dark blocks cover the target image area

A later screenshot shows Top view at Plane 10 of 21 with target 9 selected (`overview_r001_c000_obj02101`, 21.43, 21.09 mm). Large dark rectangles cover the target area while surrounding image data remains visible. The sidebar comparison is also black.

The viewer reports `targets: 9/20 stores available (preparing)`. Rerun current, Rerun all, and Make it look good controls are visible. This records the display state; it does not establish whether acquisition/publication has finished or whether the dark blocks represent missing, stale, out-of-range, or genuinely dark pixels.

### 5. Store generation and delivery to the viewer are slow

The user reports that generating stores and pushing them to the viewer is generally slow. No timings or confirmed bottlenecks have been collected.

### 6. Possible cache update or loading problem

The user suspects that cache updating or loading is also faulty. The exact mechanism and its relationship to slow publication, black previews, and dark target blocks remain unconfirmed.

## Hypotheses and investigation work

The user suspects the right-side previews may read different data from the main canvas, explaining why those previews remain black. Treat this as a hypothesis to test, not an established cause.

- Compare sidebar and main-canvas source paths, acquisition/target selection, channels, planes/projections, and data revisions across focusing, detection, and target acquisition.
- Inspect failed or empty preview requests and distinguish pending data from valid dark pixels or an out-of-range plane.
- Trace store publication and viewer availability, including cache refresh/invalidation and subsequent reads.
- Measure store creation, publication, viewer loading, preview generation, and time to visible pixels separately.

The general requirement is to improve overall performance and responsiveness across store generation, viewer delivery, caching, previews, and rendering. Establish timings and verify improvements with the same recorded dataset. Schedule investigation separately from ongoing acquisition.

## Screenshot evidence

Screenshots were supplied in the session and remain on the microscope workstation under `C:\Users\t.de\Desktop`. They are not embedded in this Markdown report.

| Observation | Local screenshot filename |
| --- | --- |
| Focusing previews | `{4AF82A90-C0B0-4210-9AD4-30888A623A35}.png` |
| Detection preview | `{624F7086-BA8D-41E5-9B60-D37FB931BF71}.png` |
| Acquisition sidebar comparison | `{015E93D6-81F1-4FE2-BF74-92FA9C5476C3}.png` |
| Dark target blocks / preparing stores | `{37A273BD-1480-476A-A0F6-EA5D31CC55E1}.png` |
