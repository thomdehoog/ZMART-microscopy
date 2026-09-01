# Smart Viewer Step 5 failing coordinate trace

**Captured:** 2026-09-01 14:00 UTC  
**Microscopy:** `codex/smart-viewer-integration-cleanup` at `0389df1e`  
**Smart Viewer:** 0.2.0 at `9ff10b0`, imported from the separate
`/Users/thomdehoog/ZMART-viewer` checkout  
**Workflow:** actual Step 5 Run button, actual mock kidney, 9/9 stores landed

This is the pre-production-change trace required by the canonical integration
plan. The repaired evidence test projected and examined exactly nine planned
ROIs. None was skipped for being off-screen. The run failed because 0/9 ROIs
met the texture requirement, so it cannot produce a false positive with zero
examined regions.

The complete machine-readable record is in
`2026-09-01-smart-viewer-failing-coordinate-trace.json`.

## Coordinate boundaries

Every `x, y` pair below is named in its own frame. Store translations and
engine bounds are shown as physical `x, y` values even though OME-Zarr carries
spatial axes in `y, x` order.

| Boundary | Position 0 | Position 8 | Relationship |
| --- | ---: | ---: | --- |
| Plan centre, carrier-local µm | `(35476, 10476)` | `(37524, 12524)` | Read from `__theStageCanvas.plan()`; each frame is 1024 µm square |
| Carrier origin, absolute-stage µm | `(23500, 28500)` | `(23500, 28500)` | Read from `carrierOriginUm()` |
| Acquisition centre, absolute-stage µm | `(58976, 38976)` | `(61024, 41024)` | Plan plus origin, exactly once |
| OME-Zarr level-0 scale `(y, x)`, µm | `(4, 4)` | `(4, 4)` | Read from each position store's `zarr.json` |
| OME-Zarr level-0 translation `(y, x)`, µm | `(38464, 58464)` | `(40512, 60512)` | Absolute-stage top-left |
| OME-Zarr derived centre, absolute-stage µm | `(58976, 38976)` | `(61024, 41024)` | Translation plus half the 256 x 256 level-0 frame |
| Engine loaded bounds `(x0, y0, x1, y1)`, µm | `(58464, 38464, 59488, 39488)` | `(60510, 40510, 61534, 41534)` | Contains the same physical centre; the second reports half-voxel bounds |
| Stage projection, CSS px | `(183.846, 222.179)` | `(194.154, 232.487)` | Carrier-local point through the carrier-owned view |
| Engine projection, CSS px | `(183.846, 222.250)` | `(194.154, 232.558)` | Matching absolute-stage point |
| Projection error, CSS px | `0.0703` | `0.0703` | Below the plan's 1 px tolerance |

Smart Viewer reported two acquisitions: focussing with one logical channel and
one source, and overview dataset 1 with three logical channel rows and nine
position sources behind every row. No engine layer reported a loading error.

## Finding

There is no divergent **x/y** coordinate boundary on this cleanup branch. The
carrier origin is already applied exactly once before writing; the OME-Zarr
x/y placements and engine bounds describe those same absolute-stage points;
and both screen projections agree. Subtracting the carrier origin would
introduce the offset that this trace disproves.

The trace does expose an earlier visibility divergence along z. Position 0's
flat overview store carries a level-0 z translation of 15.9358 µm; the engine
reports its loaded z bounds around 13.6198–14.5022 while the shared map plane is
z = 0.5. Measured focus height belongs in the acquisition record, not in the
geometry of a flat overview. The first boundary to correct is therefore the
position writer's z translation: all flat positions begin at z zero while real
stacks retain their planes and spacing from that common origin.

Two independent failures remain visible and are not coordinate fixes:

- image arrival replaced the earlier whole-plate Fit;
- one run caught a late Neuroglancer worker message for a source the adapter
  had already deleted, producing `Cannot read properties of undefined (reading
  'chunkManager')`.

They are handled at their own view-ownership and source-lifecycle boundaries.
