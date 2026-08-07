# The decisions: writing OME-Zarr for smart microscopy

One page. Every decision that is genuinely yours to make, what was chosen, and
what it affects. Everything not listed here is worked out by the software from
the frame shape and the overlap you asked for.

Detail lives in [`ome-zarr-checklist.md`](ome-zarr-checklist.md), the arrangement
in [`zmart-ome-zarr-recipe.md`](zmart-ome-zarr-recipe.md), and the measurements in
[`ome-zarr-for-analysis-and-neuroglancer.md`](ome-zarr-for-analysis-and-neuroglancer.md).

---

## Decided once, for the whole project

| # | decision | chosen | why it matters |
| --- | --- | --- | --- |
| 1 | **Which version of the format** | **0.5** | 0.4 cannot bundle files, and a five-terabyte run then means 153 million of them |
| 2 | **What holds the pixels** | **the tiles**, whole, exactly as acquired | the only complete record; a stitcher can always go back to it |
| 3 | **How the viewer gets one image** | **a view that points at the tiles**, copying nothing | copying costs 1.98× the acquisition; stitching on the fly costs 647 ms a chunk against 4.6 |
| 4 | **Where analysis results go** | **inside the tile** — `labels`, `tables` | where ngio, napari and Fiji look; our viewer already finds them |
| 5 | **Where our own bookkeeping goes** | **beside the images**, never inside | a stray file inside makes zarr warn whoever opens it |
| 6 | **Plate layout for screening runs** | **no, on any instrument** | well and field become columns of the run table; one arrangement everywhere |
| 7 | **What ngio is for** | **reading, checking and analysing — never writing** | its version ceiling would otherwise become ours |
| 8 | **Whether the overlap is trimmed from the pixels** | **no** — it is accounted for in the viewer and in the analysis | the overlap is the only evidence of where the stage really went |

---

## Decided once per microscope

| # | decision | how to answer |
| --- | --- | --- |
| 9 | **Does this instrument need 0.6?** | Only if it acquires something 0.5 cannot describe — a light-sheet deskew, or rotations between views. Confocal and widefield: no. |
| 10 | **Snappy viewing, or cheap imaging?** | Sets which chunk gets chosen. On a 2048 sensor: chunk 204 at 20% overlap fills a screen in 209 requests; chunk 128 at 12.5% takes 527. |
| 11 | **What overlap does this stage really need?** | Measure it rather than believe it. The tiles are kept whole, so a stitcher can report how far each really moved. Offsets of a few voxels against a 204-voxel overlap mean you are paying for ten times what you need. |

---

## Decided per run — only two

| # | decision | options |
| --- | --- | --- |
| 12 | **What kind of scan is this?** | `overview`, `targetscan`, … — it names the folder and separates acquisition types |
| 13 | **How much overlap?** | **none** (a survey you will never stitch, 1.0×) · **modest** (ordinary mosaics, ~1.3×) · **generous** (sparse specimens, light-sheet, ~1.6×) |

Give an **intent**, never a percentage. `modest` resolves to 10% on a 2048 or 2304
sensor and 12.5% on a 1024 scan — a literal 10% written into a workflow is
impossible on a 1024 frame and the run would be refused or silently written twice.

---

## Still to decide

| # | decision | the trade |
| --- | --- | --- |
| 14 | **Adopt chunk-aligned seams?** | Puts the join between two tiles exactly on a chunk edge, so the viewer can *skip* the shared strip instead of the writer *cutting* it. Removes the second copy from every overlapping run — 1.98× down to about 1.3×. **Deletes nothing:** the tiles stay whole. Costs a slightly stricter overlap grid. **Recommended.** |
| 15 | **HTTP/2 for the viewer?** | Takes a screen fill from ~440 ms of round trips to ~26 ms, but browsers speak it only over TLS, so a certificate on every microscope PC. **Take the bigger chunk first — it is free — then measure.** |
| 16 | **When to adopt scenes (0.6, RFC-5)?** | They describe our workflow exactly and would make the view stop being ours. But Neuroglancer has no notion of a scene and ngio cannot read 0.6 at all. **Wait for `ngio.NgffVersions` to gain `"0.6"`.** |
| 17 | **Fix the no-copy path for a drifting stage?** | It currently refuses runs whose tiles miss an exact grid, so an ordinary run falls back to copying. |

---

## One thing that does discard voxels, and it is your choice

Everything above keeps every voxel the camera recorded. There is exactly one
exception, and it should not be confused with the chunk-aligned seam above:

**Frame fitting.** To make a frame divide into whole chunks, the writer may store
2300 columns of a 2304 sensor — and those four columns are *never written*. It is
0.35% of the field, taken from the sensor's worst edge, and it is what allows an
overlap of exactly ten per cent rather than 12.5%.

It is capped at 1%, reported at setup in voxels and per cent, and refused rather
than exceeded. **And it is optional**: forbid it and nothing is discarded, at the
cost of taking 12.5% overlap on a 2048 sensor instead of 10%.

---

## Not decisions — the software settles these

Chunk size · how many voxels to trim from the frame · bundle size · how many
smaller copies · where the position is written in the metadata · the axes · file
and folder naming · whether a run is pointed at or copied.

All of them follow from the frame shape and the overlap intent. **Rigid where a
person chooses, derived where arithmetic does better than a person.**

---

## Before any of it: two things are blocking

1. **The per-dataset translation.** What we write today is invalid against the
   official schema, so ngio refuses our tiles and `ngff-zarr` stacks them all at
   the origin. The fix is written on `claude/ngff-translation-per-dataset`.
2. **Reading a bundle index in the viewer's server.** Without it there is no
   bundling, and without bundling a five-terabyte run cannot be copied.
