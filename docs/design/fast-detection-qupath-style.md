# Fast detection: a QuPath-style watershed beside Cellpose

Design note, 2026-09-02. Nothing here is implemented. The operator's ask: in Discover
Targets, a dropdown above "Test object detection" with **fast** and **accurate**, where
accurate is Cellpose and fast is what QuPath does. This note says what QuPath does
(from its source), how to do the same in Python without torch, how fast that is on this
PC, how it fits the `detect_objects` contract, and where the switch should live.

## 1. Why

Measured on this PC (review, section 11): Cellpose on the T400 takes **about 48 s per
1024 x 1024 field including the checkpoint** (nine fields in 7 min 14 s, three runs
alike); when the model falls back to the CPU it is **about ten minutes a field**
(`docs/reviews/2026-09-02-smart-operator-workflow-review.md`, "Observed, not changed"
under section 11 and MEDIUM-14). A nine-field overview is a seven-minute wait on a good
day. The step's job on the page is to find nuclei in a DAPI-like channel and hand them,
with their pixels, to `extract_classical_features`; for that job a classical detector is
one to two seconds a field.

## 2. What QuPath's cell detection does, from the source

Source read: `qupath-core-processing/src/main/java/qupath/imagej/detect/cells/WatershedCellDetection.java`
at commit `67cbf619` (main, 2026-09-01), fetched from
https://github.com/qupath/qupath/blob/main/qupath-core-processing/src/main/java/qupath/imagej/detect/cells/WatershedCellDetection.java
(the task named `qupath-extension-processing/...`; that path no longer exists on main).
The watershed itself is `qupath-core-processing/src/main/java/qupath/imagej/processing/Watershed.java`.
Line numbers below are from that commit. The published description is Bankhead et al.,
"QuPath: Open source software for digital pathology image analysis", Sci. Rep. 7, 16878
(2017), https://doi.org/10.1038/s41598-017-17204-5.

**It is not a Difference of Gaussians.** The comment says "Laplacian of Gaussian"
(line 730) and the code is a Gaussian blur followed by a 3 x 3 negative Laplacian
kernel (lines 776-778):

```java
fpLoG.blurGaussian(sigma);
fpLoG.convolve(new float[]{0, -1, 0, -1, 4, -1, 0, -1, 0}, 3, 3);
```

That is a discrete LoG approximation on a background-subtracted image, then an
intensity-constrained watershed seeded at the LoG's regional maxima. A DoG is a close
cousin of a LoG, so "DoG" is a fair recollection, but the faithful port is
Gaussian + Laplacian. The whole `doDetection()` (lines 715-1010), in order:

1. **Median filter** (optional, radius `medianRadius`; lines 736-737). Default off.
2. **Background estimate and subtraction** (lines 762-766, `estimateBackground`
   lines 665-711): a minimum filter of radius `backgroundRadius` (line 675), then
   either **opening by reconstruction** -- morphological reconstruction of the eroded
   image under the original (line 702, the default) -- or a plain maximum filter, i.e.
   a simple opening (line 707, option since v0.4.0). The estimate is subtracted from
   the image (line 765). The background-subtracted image is also what every intensity
   check below measures on (`ipToMeasure`, line 766). `maxBackground` masks out
   regions whose background exceeds it (lines 679-697), but it is passed as
   `NEGATIVE_INFINITY` for anything that is not brightfield (line 562), so for
   fluorescence it does nothing.
3. **LoG** as above (lines 777-778).
4. **Foreground = LoG > 0** (line 785). No intensity threshold yet: the zero crossing
   of the LoG is the blob boundary.
5. **Seeds = regional maxima of the LoG** (line 789, `findRegionalMaxima(fpLoG, 0.001f)`),
   labelled (line 790).
6. **Watershed** on the LoG image from those seeds, 4-connected, not allowed below 0
   (line 791, `Watershed.doWatershed(fpLoG, ipNucleusLabels, 0, false)`). This is a
   priority-queue flooding (`Watershed.java` lines 75-104); the comment on line 731
   says the result "will be a dramatic over-segmentation".
7. **Mean-intensity check** per watershed region on the background-subtracted image:
   regions whose mean is `<= threshold` are dropped (lines 805-811); brightfield only,
   regions on a masked background are dropped too (lines 813-816).
8. **Merge and split by shape** (lines 826-836, `mergeAll` is always true, line 622):
   the surviving regions are dilated by one pixel (`MAX` filter), ANDed with the LoG > 0
   mask, filled, and -- if "Split by shape" is on -- split with ImageJ's binary
   **EDM watershed** (`new EDM().toWatershed(bp)`, line 835). So a clump of nuclei that
   the LoG merged is split again on the distance transform.
9. **Boundary refinement** (lines 854-861, `refineBoundary` fixed to true, line 606):
   when sigma > 1.5 px, a LoG with sigma 1 is thresholded, ANDed with the mask, and the
   mask eroded by one pixel then ORed back -- corrects boundaries that the larger blur
   pushed out by a pixel.
10. **Area and intensity filter** (lines 876-890): each nucleus's pixel count must be
    within `[minArea, maxArea]` and its mean on the subtracted image `>= threshold`.
11. **Smooth boundaries** (lines 926-936): polygon interpolation and smoothing of the
    ROI outlines, a vector operation with no label-image equivalent.
12. **Cell expansion** (lines 966-975): the Euclidean distance map of the nucleus mask
    is negated and the nucleus labels are flooded outwards by watershed, stopped at
    `-cellExpansion` (line 974). Nuclei grow by a fixed distance without merging.
    Cytoplasm is cell minus nucleus (lines 988-991).

**Every parameter the dialog exposes** (`buildParameterList`, lines 175-272), with the
default and the help text from the source:

| Group | Name (key) | Default | Unit | Help text (source) |
|---|---|---|---|---|
| Setup | Detection channel (`detectionImage`) | first channel named like dapi/hoechst/nucleus/... (lines 165-166, 202) | -- | "Choose the channel that should be used for nucleus detection (e.g. DAPI)" |
| Setup | Detection image (`detectionImageBrightfield`) | Hematoxylin OD (line 204) | -- | brightfield only |
| Setup | Requested pixel size (`requestedPixelSizeMicrons`) | 0.5 (line 207) | um | image is downsampled to this before detection (lines 402-410, 430) |
| Nucleus | Background radius (`backgroundRadiusMicrons` / `backgroundRadius`) | 8 um / 15 px (lines 212, 233) | um or px | "Radius for background estimation, should be > the largest nucleus radius, or <= 0 to turn off background subtraction" |
| Nucleus | Use opening by reconstruction (`backgroundByReconstruction`) | true (line 216) | -- | "tends to give a 'better' background estimate ... in some cases (e.g. images with prominent folds ...) this can cause problems, with the background estimate varying substantially between tiles" |
| Nucleus | Median filter radius (`medianRadiusMicrons` / `medianRadius`) | 0 / 0 (lines 224, 235) | um or px | "Radius of median filter used to reduce image texture (optional)" |
| Nucleus | Sigma (`sigmaMicrons` / `sigma`) | 1.5 um / 3 px (lines 226, 237) | um or px | "Sigma value for Gaussian filter used to reduce noise; increasing the value stops nuclei being fragmented, but may reduce the accuracy of boundaries" |
| Nucleus | Minimum area (`minAreaMicrons` / `minArea`) | 10 um^2 / 10 px^2 (lines 228, 239) | um^2 or px^2 | |
| Nucleus | Maximum area (`maxAreaMicrons` / `maxArea`) | 400 um^2 / 1000 px^2 (lines 230, 241) | um^2 or px^2 | |
| Intensity | Threshold (`threshold`) | 0.1 (line 245); reset for fluorescence to **100** for > 8-bit, 25 for 8-bit (lines 336-341, "this is a complete guess, we don't know the pixel values!") | image units | "detected nuclei must have a mean intensity >= threshold" |
| Intensity | Max background intensity (`maxBackground`) | 2 (line 248) | OD | brightfield only (line 562) |
| Intensity | Split by shape (`watershedPostProcess`) | true (line 251) | -- | the EDM watershed of step 8 |
| Intensity | Exclude DAB (`excludeDAB`) | false (line 253) | -- | brightfield only |
| Cell | Cell expansion (`cellExpansionMicrons` / `cellExpansion`) | 5 um (0..25) / 5 px (lines 259, 261) | um or px | step 12 |
| Cell | Include cell nucleus (`includeNuclei`) | true (line 264) | -- | |
| General | Smooth boundaries (`smoothBoundaries`) | true (line 269) | -- | "Smooth the detected nucleus/cell boundaries" |
| General | Make measurements (`makeMeasurements`) | true (line 271) | -- | |

Micrometre parameters are divided by the (requested) pixel size once (lines 545-550);
the pixel variants are used when the image has no calibration.

## 3. The same thing in Python, scikit-image and scipy only

The classical environment already has what is needed: `ZMART--object_analysis--classical`
carries numpy 2.4.6, scipy 1.17.1, scikit-image 0.26.0 (checked). Nothing to install.
Stage by stage:

| QuPath stage | Python |
|---|---|
| median filter | `scipy.ndimage.median_filter(f, footprint=skimage.morphology.disk(r))` -- off by default |
| minimum filter, radius r | `skimage.morphology.erosion(f, disk(r, decomposition="sequence"))` -- the decomposed disk is 4-10x faster than `scipy.ndimage.grey_erosion` with a full disk and differs by about one noise sigma (measured, section 4) |
| opening by reconstruction | `skimage.morphology.reconstruction(seed=eroded, mask=f, method="dilation")`; subtract from `f`. (Simple opening: `scipy.ndimage.grey_opening`.) |
| Gaussian + 3x3 Laplacian | `skimage.filters.gaussian(f, sigma, preserve_range=True)` then `scipy.ndimage.convolve(., [[0,-1,0],[-1,4,-1],[0,-1,0]])`. Mind the sign: `scipy.ndimage.laplace` is the negative of QuPath's kernel. `skimage.filters.difference_of_gaussians` would be the DoG stand-in; not needed |
| foreground LoG > 0 | `above = log > 0` |
| regional maxima | `skimage.morphology.local_maxima(log) & above`, then `skimage.measure.label(., connectivity=1)` |
| intensity-constrained watershed | `skimage.segmentation.watershed(-log, markers, mask=above, connectivity=1)` -- the mask is QuPath's "not below 0" |
| mean-intensity check | `scipy.ndimage.mean(subtracted, labels, index)` > threshold, keep those labels |
| merge and split by shape | `scipy.ndimage.binary_dilation(kept, 3x3) & above`; `scipy.ndimage.distance_transform_edt`; seeds `skimage.morphology.h_maxima(dist, 0.5)` (ImageJ's EDM watershed finds maxima with tolerance 0.5); `watershed(-dist, seeds, mask, watershed_line=True)` |
| boundary refinement | optional; same LoG with sigma 1, `binary_erosion` then OR. Can be left out for the page |
| area filter | the step's own `filter_masks_by_area` (bincount + relabel), unchanged |
| smooth boundaries | no label-image equivalent; skip |
| cell expansion | `skimage.segmentation.expand_labels(masks, distance)` -- nearest-label growth capped at a distance, the same ordering as QuPath's watershed on the negated EDM |

Converting QuPath's micrometre defaults to the page: the bridge already knows the pixel
size (`application/parts/microscope/detection.py`, `pixel_um`, from the instrument's
observed `pixel_size.x`; 1.0 um/px on the mock kidney overview, 1024 um frame at
1024 px) and already converts the page's Diameter to pixels the same way
(`given["diameter"] = settings["diameter"] / pixel_um`, line 85). QuPath's defaults
(8 um background radius, 1.5 um sigma, 10 and 400 um^2 areas) were chosen for
nuclei about 8-10 um across; expressed as ratios of the diameter D they are:

- background radius = D (QuPath: 8 um for ~8-10 um nuclei; its help text demands "> the
  largest nucleus radius", so the diameter is the safe choice);
- sigma = D / 8 (1.5 um on ~10 um nuclei; with the page's default D = 30 um at 1 um/px
  that is 3.75 px, close to QuPath's 3 px pixel default);
- min area = A / 8 and max area = 5 A with A = pi (D/2)^2 (10 and 400 um^2 against
  A ~ 80 um^2). With D = 30 um: 88 and 3534 um^2;
- median radius 0, cell expansion 0 (the segmentation channel is the nuclear one and
  Cellpose on it also returns nuclei, so the two modes measure the same thing);
- threshold: **no honest default exists**; QuPath itself guesses 100 counts for a
  > 8-bit image. It is a mean over the background-subtracted nucleus in raw counts,
  so it depends on exposure and must be tuned per acquisition setting -- the reason
  the test tile exists.

Which existing fields map where:

| Page field | accurate (Cellpose) | fast (watershed) |
|---|---|---|
| Diameter (um) | `diameter` px to Cellpose | drives background radius, sigma, min/max area as above |
| Cell prob. | `cellprob_threshold` | not applicable; hidden in fast mode |
| Border (um) | `border_margin_px`, after detection | identical, same code |
| Binning | segment on a smaller copy, masks scaled back | identical, same code; the pixel parameters above are divided by the binning as well |

New field the fast mode needs: **Threshold** (counts, default 100). Sigma and
background radius should start derived from Diameter rather than as fields: the ask is a
two-way dropdown, not a second dialog, and every extra row costs a message to remove. If
real tissue shows the ratios are wrong, "Sigma" and "Background radius" (um) are the two
rows to add, in that order.

## 4. Speed, measured

Method: the recipe of section 3 (opening by reconstruction with the decomposed disk,
LoG, seeded watershed, intensity check, EDM split with `h_maxima(0.5)`, area filter),
run in `ZMART--object_analysis--classical` on this PC (AMD, 24 logical CPUs; these
scipy/skimage calls are single-threaded) on synthetic 1024 x 1024 uint16 fields:
Gaussian blobs on a sloped background with Gaussian noise sigma 60 counts. Warm
process, best of three. Scripts in this session's scratchpad (`bench_final.py`,
`bench_bg.py`, `bench_qupath2.py`); they are not part of the repository.

| Field | Diameter | Time | Objects | Breakdown |
|---|---|---|---|---|
| 1024 x 1024, 600 nuclei r 8-14 px | 30 px | **1.35 s** | 501 | background 0.57, LoG + watershed 0.23, intensity + shape split 0.70, filters 0.01 |
| 1024 x 1024, 300 nuclei r 12-18 px | 30 px | **0.96 s** | 259 | background 0.44, LoG + watershed 0.11, split 0.40 |
| 512 x 512 (the page's binning 2), 150 nuclei r 4-7 px | 15 px | **0.16 s** | 319 (over-split, see section 6) | |

The background estimate is the cost centre and the footprint decides it: erosion with
a full disk of radius 20 takes 1.27 s and radius 30 takes 2.92 s, against 0.19 s and
0.30 s with `disk(r, decomposition="sequence")` (largest difference on the noisy
field about 100 counts, one noise sigma). The reconstruction itself is 0.23-0.29 s
regardless of radius. Without the decomposition the recipe is 2-4 s a field; with it
about one second. Plain opening instead of reconstruction is not a shortcut: at any
radius it leaves a residual of roughly two noise sigmas across the whole background,
the 100-count threshold then passes noise, and the field came back with about 10,000
"objects". QuPath's default (reconstruction) is the one to port.

Against Cellpose on this PC: **about 48 s a field on the T400 including the checkpoint,
about 600 s on the CPU**, so the fast mode is 35-50x faster than the GPU path and
several hundred times faster than the CPU fallback. The nine-field overview of section
11 would spend about 12 s detecting instead of 7 min 14 s; the checkpoint write
(masks, raw masks, a sha256 over the position store) and feature extraction then set
the pace, and those were not measured here.

Cold costs, measured as whole processes with `Measure-Command`: `conda run -n <env>
python -c pass` 2.0-2.2 s in either environment; interpreter plus numpy, scipy.ndimage,
tifffile 0.9 s; the scikit-image modules another 1.0 s; `import torch` plus
`cellpose.models` 4.9 s in the vision environment, before the 1.2 GB weights are read.
The fast path never pays the last two.

## 5. Contract fit and where the switch lives

What `detect_objects` returns today and what downstream reads
(`zmart_analysis/workflows/object_analysis/steps/detect_objects.py`):

- `pipeline_data["detect_objects"]`: `image`, `image_2d`, `masks` (int32 label image,
  relabelled from 1), `n_objects`, `n_raw_objects`, `dropped_labels`, `area_filter`,
  `border_filter`, `cellpose_params` (with `device`), `segmentation_resize`,
  `image_size_px`, `segmentation_params`, `segmentation_params_hash`, `artifacts`;
- `pipeline_data["preprocess"]["image"]` and `pipeline_data["segment"]["masks"|"n_cells"]`
  for `extract_classical_features` (lines 67-68 of that step);
- `build_object_table` reads `pipeline_data["detect_objects"]` by that name (lines 44,
  138); the bridge reads `result["detect_objects"]["cellpose_params"]["device"]` for the
  "on the GPU / on the CPU" readout (`application/parts/microscope/detection.py`,
  line 148);
- the checkpoint (`tiles/<frame>/masks.tif`, `raw_masks.tif`,
  `detection_checkpoint.json`) is written by `_write_detection_checkpoint` from that
  record and is what the page paints masks from.

Everything in that list except the raw masks is shared plumbing: loading the plane,
binning, resizing back, the border and area filters, the hash, the checkpoint. Only
`model.eval(...)` (lines 436-459) is Cellpose. So the fast detector is a second way to
produce `raw_masks` from `seg_eval`, and nothing downstream changes if it is inserted
there.

**Recommendation: a `method: "fast" | "accurate"` parameter on the one `detect_objects`
step, a branch inside `segment_position`, environment unchanged.** Concretely:

- `segment_position` takes `method`; `"accurate"` calls the Cellpose block as today,
  `"fast"` calls a `_watershed_masks(seg_eval, ...)` written below it in the same file,
  importing scipy and skimage inside the function and nothing from torch or cellpose.
  `_load_cellpose_model` is already a lazy import (line 557), so a fast run never
  imports torch.
- `cellpose_params` becomes `detector_params`: `{"method", "device", ...}` with the
  Cellpose keys for accurate and `threshold`, `sigma_px`, `background_radius_px`,
  `min_area_px`, `max_area_px`, `split_by_shape` for fast; `method` and the fast keys
  join `SEGMENTATION_IDENTITY_KEYS` so the hash tells the modes apart. The bridge's
  device lookup, the checkpoint key and the tests that pin `cellpose_params`
  (`tests/test_segmentation.py` lines 387-664) are renamed in the same change.
- the YAML gains `method: accurate` and `threshold: 100`; the bridge's
  `what_was_captured` passes `given["method"]` from `settings.algo` and
  `given["threshold"]` when fast; the panel re-enables the parked picker (`ALGOS` in
  `detection.js`, and `algo: "cellpose"` already sits in the page's settings in
  `main.js` line 156) as the dropdown above the test card, and shows Cell prob. or
  Threshold according to the choice.
- the vision profile in `environments/setup_env.py` adds `scikit-image>=0.23`; it is
  not there today (`import skimage` fails in `ZMART--object_analysis--vision`, checked),
  and scikit-image pulls no torch.

Why the branch and not a second step file (`detect_objects_fast.py` with
`environment: "ZMART--object_analysis--classical"`):

1. A step file declares one environment, bound at registration
   (`engine/_pipeline.py` lines 186-196), and the YAML cannot skip a step -- there is
   no conditional in the engine. A second step therefore means a second pipeline YAML
   and a change to `warm.py`'s rule that a pipeline lives at
   `<name>/pipelines/<name>.yaml` (`application/parts/analysis/warm.py` lines 31-40).
2. The classical worker is spawned in both designs, because
   `extract_classical_features` runs there on every field. The only worker the second
   file saves is the vision one: about 2 s of `conda run` and 1 s of imports, once per
   session (idle workers are reaped after 300 s, `_pipeline.py` line 123). The
   expensive parts of that worker -- torch, cellpose, the weights, the card memory --
   are only paid when accurate is chosen, in either design.
3. The loaders, filters and checkpoint writer are the step's own helpers; a second file
   would either import them across step files, which the self-contained-step rule
   forbids, or copy some 400 lines.
4. `build_object_table` and the bridge key on the name `detect_objects`.

One thing to decide inside the branch: an operator who tests accurate, then switches to
fast, leaves the warm Cellpose model in the worker's `state`, holding card memory until
the worker is reaped. Popping `state["model"]` when a fast run arrives frees it at the
cost of a reload if they switch back; leaving it is simpler. Either is defensible;
the note recommends leaving it, since the reaper frees it within five minutes of the
last field.

`max_workers: 1` stays: nine fields at ~1.4 s are 13 s in series, and the step's
concurrency is per file, not per method.

## 6. Where the fast mode will be worse, and how to word the choice

- **Touching nuclei.** The LoG watershed separates two nuclei only where the blur
  leaves an intensity saddle between them; the EDM split then separates by shape.
  Round nuclei in a pair split well; a clump of three or more with no saddle and a
  convex outline comes back as one object. Large, textured nuclei can also go the
  other way: the synthetic 512 x 512 run above returned 319 objects for 150 nuclei,
  the shape split with tolerance 0.5 breaking small blobs at every ripple. Cellpose's
  flow field handles both without a tolerance to tune.
- **Anything that is not a nuclear blob.** The detector assumes bright compact blobs
  on a darker ground (QuPath's own note, line 444: "it requires low values in the
  background, high values within nuclei"). Cytoplasmic or membrane stains, elongated
  or irregular cells, and dark nuclei on a bright ground are outside it. Cellpose
  segments whatever the channel shows.
- **Uneven background and debris.** Opening by reconstruction removes smooth gradients
  and structures smaller than the background radius; bright debris or folds larger
  than the radius survive as "objects", and QuPath's help text warns the estimate can
  "vary substantially between tiles". Cellpose is largely exposure- and
  background-invariant because it normalises each image; the fast mode's threshold is
  in raw counts and must be re-tuned when exposure or laser power changes.
- **Dim and out-of-focus nuclei.** Below the threshold they are gone; out of focus, the
  LoG > 0 regions swell and merge. Cellpose degrades more gracefully.
- **Binning.** Both modes segment on the binned copy; the fast mode's pixel parameters
  scale with it (they are derived from Diameter in pixels), so binning 2 costs
  boundary precision, not detection.

Wording for the dropdown, in the page's voice:

- **fast · watershed on the nuclear channel (QuPath-style)** -- "Finds bright, compact
  nuclei in about a second a field. Threshold is the mean brightness a nucleus must have
  above its background."
- **accurate · Cellpose** -- "A learned segmenter, about a minute a field on the GPU.
  Diameter is the size it looks for; cell probability is how sure it has to be."

The "Cellpose segmentation" subhead becomes the chosen method's name, and the readout's
"· on the CPU" -- today a warning that something fell back -- should say nothing for the
fast mode, where the CPU is the plan.

## 7. What I did not verify

- The recipe was timed on synthetic fields only. It was not run on real pixels (the mock
  kidney overview or the datasets on D:), and no accuracy comparison against Cellpose
  was made; the object counts above are counts, not correctness.
- The per-field fixed cost under the engine -- reading the OME-Zarr plane, the sha256
  over the whole position store in the checkpoint, the mask TIFFs, and feature
  extraction -- was not measured. The 48 s Cellpose figure includes it; the 1.35 s
  figure does not.
- The cold worker spawn was measured as `conda run ... python -c pass` from a shell,
  not through the engine's `Worker` with its connect-back.
- ImageJ's `EDM().toWatershed` internals were not read; the tolerance 0.5 used for the
  Python `h_maxima` is taken from ImageJ's `MaximumFinder` default as remembered, and
  scikit-image's `reconstruction` is assumed equivalent to QuPath's hybrid
  reconstruction (`MorphologicalReconstruction.java`) in result, not in speed.
- QuPath's documentation page for the dialog was not reached with a parameter table;
  the defaults and help texts above are from the source, which is the authority anyway.
  The Bankhead 2017 reference is from memory and was not re-fetched.
- Whether the accurate path rescales `diameter` for the binned copy was not checked:
  `segment_position` passes `diameter` to `model.eval` unchanged after
  `_downsample_for_segmentation` (lines 417-428, 872-888). The fast path must divide
  its pixel parameters by the binning; the accurate path may or may not need the same.
- The mock kidney's overview pixel size of 1.0 um/px is inferred from the review's
  "1024 um frame" at 1024 px, not read from the record.
- GPU memory behaviour when switching modes inside one session (section 5, last
  paragraph) is reasoned from the code, not observed.
