# Handover: the linked scene loads, serves, and draws nothing

**State at handover (2026-09-01, ~02:00):** branch `claude/viewer-layer-020`,
worktree `C:\ProgramData\MinicondaZMB\home\t.de\zmart-viewer-layer`. One open
bug stands between the operator canvas and the finished viewer integration,
and it is precisely characterised — the next agent should be able to close it
in one sitting. Read `.claude` memory `project_viewer_layer_020` for the whole
project; this file is only the open bug and the trail to it.

## The outcome wanted

The operator's words: *"seeing the image appear in the right coordinate
system with right zoom and pan, so it aligns with the canvas."* Concretely:
after a 6-tile overview scan, the canvas's bottom layer (engine
`neuroglancer-under`) shows all six tiles as one picture, registered under
the plan, together with the focussing source.

## What already works (do not re-debug)

- Autosave OME-TIFF → OME-Zarr 0.5 t/c/z/y/x position stores, one per
  capture, in `<run>/positions/<type>/` — proven, tested, real pixels
  (`application/parts/storage/zarr_positions.py`).
- The ZMART-viewer server runs beside the bridge (`viewer_service.py`),
  serves with CORS + OPTIONS preflight, opens each type's folder, announces
  landings. **A folder that opened at one store is closed and reopened when
  the second store lands, and then links into one scene** — proven by
  `scratchpad/prove_scene_growth.py` (single store → `overview.zmartview.zarr`).
- The engine draws a SINGLE position store perfectly (windowed tissue) —
  proven repeatedly with `application/engine-look.spec.js`.
- The scene itself serves REAL bytes: level-0 chunk decodes to uint16 max
  4089, 75% nonzero. Chunks are whole-level (`chunk_shape [1,1,1,512,512]`),
  codecs plain `bytes,zstd`. The engine fetches them with 200s and no
  console error.
- The page: `thePicture` opens viewer sources with `neuroglancer-under`,
  reopens when sources change; the viewer-dress left panel (histogram,
  min/max/opacity, eyes, colours, fold) works against the live server.

## The open bug

**A linked scene's layer is invisible because its z is never re-based.**
The `layersForMeasurement()` dump (new debug accessor on the engine handle)
from the failing case:

```
dims  [t, c', z, y, x]
lower [-0.5, -0.5, 10.51, 4039.08, 4637.35]
upper [ 0.5,  2.5, 11.51, 4551.08, 5149.35]
nav   [t, z, y, x] = [0, 0.5, 4295.5, 4893.75]
```

x/y are RIGHT (nav inside bounds — pan/zoom "not linked" was an illusion;
the picture is loaded and positioned, and invisible 10 µm away in z). The
layer's z spans 10.51..11.51 while navigation z stands at 0.5: a slice one
voxel thick never intersects it. `everyHeightBeginsAtNought()` (in
`viz_studio/options/neuroglancer-under/viewer.js`) is supposed to zero every
layer's z translation; for the scene it does not take, even after the
500 ms settling clock was added (commit pending in this one).

## Prime suspect (check this FIRST)

The translation write index. `everyHeightBeginsAtNought` copies the
corner-shift idiom:

```js
const moved = Float64Array.from(placed.transform);
moved[rank * (rank + 1) + heightAxis] = 0;   // rank=5 → index 30+2=32
```

If `placed.transform` has only 30 entries (5×6 row-major, translation at
`row*(rank+1)+rank`), index 32 is out of bounds and **a typed array drops
out-of-bounds writes silently** — the function then "succeeds" and changes
nothing. The corner-shift (`countFromTheCornerOfTheVoxelRatherThanItsMiddle`)
uses the same formula and ships — so either the matrix is (rank+1)×(rank+1)=36
(then translation for axis i is at `i*(rank+1)+rank`, i.e. z at 17, and BOTH
functions write into the dead homogeneous row today), or it is 30 long and
the right z index is `2*(rank+1)+rank = 17` anyway. **The accessor now dumps
`matrix` — run the spec once and arithmetic settles it:**

```powershell
$env:PATH="C:\ProgramData\MinicondaZMB\envs\zmart-microscopy;$env:PATH"
# serve a grown scene (adjust run folder if needed):
#   scratchpad/prove_scene_growth.py builds prove-growth/ then a one-liner
#   in the session log serves it and prints SOURCE= and CENTRE=
$env:ZV_SOURCE='http://127.0.0.1:<port>/data/0/overview.zmartview.zarr/|zarr3:'
$env:ZV_CENTRE='<x>,<y>'; $env:ZV_ZOOM='3'
cd application; npx playwright test engine-look.spec.js
# read test-results/engine-look.png and the printed "layers:" dump
```

If the index was wrong, note that positions may never have been zeroed
either — the earlier two-store probe that "drew both" may have done so by
z-coincidence. After fixing the index, re-verify BOTH cases (single position,
scene) and check registration under the plan in the live window.

## Fallbacks if the matrix write is a dead end

1. Drive navigation z to the layer's own z instead of re-basing (works only
   for one acquisition at a time — not the wanted outcome).
2. Make z layer-local (`z'`) — first attempt via a source-spec `transform`
   drew nothing (spec shape likely wrong; reverted). The viewer app never
   passes source transforms, so there is no working reference in-repo.
3. Zero the z translation at WRITE time for flat captures (converter writes
   translation z=0 into `positions/` stores; stacks keep 0-based z). Loses
   z provenance in the store metadata (still in the record/TIFFs) but kills
   the whole problem class — the viewer app would show them coplanar too.

## How to reproduce everything

- Dev window: `npm run dev` in `application/` (port 5174), then
  `python zmart-interface.py` (env `zmart-microscopy`). Connect the MOCK
  instrument; scan → 6 tiles; watch the canvas.
- Bridge answers `/api/viewer` (find the port via the ZMART window's PID →
  `Get-NetTCPConnection`). The viewer server port is inside that answer.
- Diagnostics: `application/engine-look.spec.js` (engine alone on any served
  store; console + network + `layersForMeasurement` dumped; screenshots to
  `test-results/engine-look.png`), `application/viewer-panel-look.spec.js`
  (panel layout photograph), `scratchpad/prove_scene_growth.py`.
- Suites: pytest `application/parts/storage/test_zarr_positions.py` and
  `.../microscope/test_detection.py` (zmart-microscopy env), `npx vitest run`.

## Also open, smaller

- The live window needs a restart to pick up the `viewer_service.py`
  scene-growth fix (Python is not hot-reloaded; the page half is).
- The `2026-09-01` scan session's viewer still holds the stale single-store
  source until that restart.
- Panel: LUTs, × close, Z/T overlay sliders with play, histogram axis
  pan/zoom still unported (map in memory `project_viewer_layer_020`).
