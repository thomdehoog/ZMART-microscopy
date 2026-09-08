# The black overview tile: a focus stack with a negative z step

Written 2026-09-08 on branch `claude/smart-operator-workflow-review-ehw3c5`,
from run `E:\Experiments\ZMART-microscopy\target-acquisition_aa5b05`.

## The complaint

Step 5 scanned one field. LAS X showed a bright field of nuclei. The
operator page drew the tile as a solid black square, and the acquisition
chip bar that stands at the canvas's top right once a picture is open was
missing.

## What was ruled out

- **The data.** `positions/overview/overview_K00_M000014_G000001_P000000_V00.ome.zarr`
  is a 1024x1024, two-channel, uint16 store with signal (histogram up to
  ~5700 of a 0..9242 window). The bridge's viewer service serves it with
  `Access-Control-Allow-Origin: *`.
- **The engine.** `engine-look.spec.js` pointed at the overview store alone,
  centred on the stage position (`ZV_CENTRE=12433,10688`), draws the field
  perfectly.
- **The page.** The operator walk on the mock (`the-operator-walk.spec.js`,
  with two stale expectations relaxed, see below) scans and draws its fields
  at the plan's places.
- **The native window.** WebGL2 is available inside pywebview/WebView2
  (ANGLE on the RTX A4000), and the neuroglancer worker bundles were built.
- **Disconnect / reconnect.** Disconnect wipes the display settings on
  purpose (`thePicture.reset()` -> `closePicture({ forgetVisibility: true })`).
  That is a separate matter and plays no part here.

## The reproduction

`engine-look.spec.js` with **both** of the run's stores:

    ZV_SOURCE="<overview>|zarr3: <focussing>|zarr3:" ZV_CENTRE=12433,10688 ZV_ZOOM=2

draws nothing at all. `layersForMeasurement()` reports for the focussing layer:

    Error parsing "scale" property: Expected positive finite floating-point
    number, but received: -1.2998051948052307.

and the scene's navigation z is `null`.

The focussing store's transform:

    scale:       [1.0, 1.0, -1.2998, 4.61, 4.61]
    translation: [0.0, 0.0, 200.17, 10540.69, 12286.10]
    shape:       [1, 1, 155, 64, 64]

## Root cause

**The sweep's direction is encoded as the sign of the voxel spacing.**

The driver reports the focus sweep as it happened: 155 planes from z=200 um
downwards, so the plane spacing is negative. The position writer
(`application/parts/storage/zarr_positions.py`, `dz` at lines ~118 and ~509)
copies that signed spacing straight into the OME-Zarr `scale` for z. But
`scale` is a voxel size, not a direction: OME-NGFF and neuroglancer both
require it to be positive. The store is invalid whenever the sweep runs
top-down. Nothing checks this at write time.

Two things made it invisible until now:

1. The mock only ever sweeps bottom-up, so its spacing is positive and every
   test passes.
2. neuroglancer nulls the *shared* z navigation when one layer fails to load,
   which blanks every other layer in the scene. The valid overview was taken
   down by the invalid focus stack beside it. The canvas still cut its window
   over the scanned tile, and what showed through was the picture host's
   near-black background (`THE_COLOUR_BEHIND_THE_PICTURE`, `#05070d`).

## The fix

**Done 2026-09-08**, see `ABSOLUTE_Z_PLAN.md` for what was changed and what
was found on the way.

- **Writer:** keep `scale` positive (absolute spacing) and put the direction
  into the data: either reorder the planes ascending on write, or keep the
  order and express the start height through the translation.
- **Coverage:** a unit test on the writer with a negative spacing, and/or a
  top-down stack in the mock, so the case stays covered.
- **Defence in the page (optional):** `layersForMeasurement()` already
  surfaces the layer error; the page could show it instead of a black tile.

## Side findings

- `the-operator-walk.spec.js` is stale against last night's canvas changes:
  it expects the focussing eye on (`data-on="1"`) at the scan step, and
  expects fewer than 20 drawn pixels before the scan, but the new acquisition
  chip bar draws ~2500. Both need updating.
- The bridge log for this run also warned "the job said nothing usable about
  its stack; 2 planes are stamped at the drive's height" for every capture.
