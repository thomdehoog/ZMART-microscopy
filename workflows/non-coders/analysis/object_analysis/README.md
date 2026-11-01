# `object_analysis` workflow

Finds the objects in an image, measures each one, and returns a table with
one row per object. It works on one *tile* at a time. A tile is one image of
a larger field, submitted as soon as it is acquired.

## The pipelines

| Pipeline | Steps |
|---|---|
| `object_analysis_cellpose.yaml` | `read_images` → `segment_cellpose` → `measure_objects` → `build_object_table`. The operator page calls it "robust". |
| `object_analysis_watershed.yaml` | The same, with `segment_watershed`: a watershed that needs no GPU. It leaves out the texture features that need a crop of every object (`glrlm`, `lbp`, `fft`). The operator page calls it "fast". |
| `reduce_dimensions.yaml` | `reduce_dimensions`: a PCA or UMAP of a detected population, made on request. |

`read_images` opens the image; no step after it opens a file. Both tile
pipelines put the table under `pipeline_data["object_analysis"]`.

Every parameter is in the pipeline, with its default. The docstring of each
step, in `steps/`, says exactly what the step takes and returns.

## Input

Submit one tile at a time:

```python
{
    "image_path": "path/to/position",      # OME-Zarr position or OME-TIFF
    "tile_id": ["R0", 3, 7],
    "tile_stage_xy_um": [10000.0, 15000.0],
    "tile_z_um": 2500.0,                   # capture height; optional
    "source_pixel_size_um": [0.65, 0.65],
    "source_image_size_px": [2048, 2048],  # (nx, ny)
    "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
    "channels": None,                      # up to three; [0, 2] to choose
    "gpu": False,
}
```

These keys are optional. The operator page in
[ZMART Interface](https://github.com/ZMB-UZH/ZMART-interface) sends them
when it has them:

| Key | What it is |
|---|---|
| `z_selection` | Which plane of a z-stack to detect on: an index, `"mid"` (the default), or `"max"` / `"mean"` for a projection. |
| `extra_channel_paths` | The other channels, for a frame that is stored as one file per plane. The features are measured in every colour. |
| `extra_channel_indices` | The same for a frame that is stored as one position: the indices of the channels to read from it. |
| `synthetic_pixels` | For images from a mock microscope: how the pixels were made. It is copied into the checkpoint for the record. |
| `output_dir` | Where to write the masks and the checkpoint. The default is the `analysis` folder next to the `data` folder the image came from. |

You can also give any detection setting of the pipeline here, such as
`diameter`, `cellprob_threshold` or `border_margin_px`. It then replaces
the pipeline's value for this one image. This is how the operator page tunes
detection on one position.

## Output

The result is the object table, under `pipeline_data["object_analysis"]`.
Each row holds the features of one object, its `object_id`, its `tile_name`,
and its position on the stage as `stage_x_um` and `stage_y_um`. The position
is worked out from the geometry of the tile. Beside the table stands the
segmentation's record, under `segment_cellpose` or `segment_watershed`; its
`detector_params` say which device it ran on.

The segmentation step also writes three files to
`<analysis>/tiles/<short_name>/`: `masks.tif`, `raw_masks.tif` and
`detection_checkpoint.json`. Where `<analysis>` is depends on the input:

- With `output_dir` given, the files go there.
- Otherwise they go to the `analysis` folder next to the `data` folder the
  image came from.
- If the image is not part of an acquisition and no `output_dir` is given,
  nothing is written.

The checkpoint records the parameters that were actually used, a hash of
the parameters that shaped the masks, and hashes of the image and the
masks. With it, a run can be reproduced from what really ran.

## The population plot

`reduce_dimensions.yaml` is the one pipeline here that does not run per
tile. When a whole overview has been detected and its object table is
written, the operator can ask for a plot of that population: the first two
principal components, or a UMAP made from the first fifty.

Objects that are alike end up close together in the plot, whichever mix of
features makes them alike. So you can select objects by the structure of
the population, not only by single features. A UMAP of half a million
objects takes minutes, which is why it is made on request and never during
detection.

## Environments

| Environment | Holds | Used by |
|---|---|---|
| `ZMART--object_analysis--classical` | scipy, scikit-image and the image readers | `read_images`, `segment_watershed`, `measure_objects`, `build_object_table` |
| `ZMART--object_analysis--cellpose` | PyTorch and Cellpose | `segment_cellpose` |
| `ZMART--object_analysis--umap` | pandas, scikit-learn and umap-learn | `reduce_dimensions` |

Create each one from its file in `environments/`, for example
`conda env create -f environments/classical.yml`. The classical and UMAP
environments come from lock files, every package at one version. Cellpose's
has none yet: conda-forge's `pytorch` takes the CUDA build by itself when the
computer has an NVIDIA GPU, so that build differs between computers. Its
version is pinned to one that also has builds for CUDA 12, because the newest
PyTorch's builds may all need a newer NVIDIA driver than a microscope PC has,
and a computer with a GPU would then get the CPU build without a word.

Each step file names its own environment, so a pipeline only starts the
workers it needs. The watershed pipeline never loads PyTorch.

### Why they are split this way

A model environment holds one model and nothing else: `read_images` and the
features run in the classical one. Each model insists on its own versions: Cellpose needs one
PyTorch, StarDist needs TensorFlow, and the next model will need yet another
CUDA. Kept apart, an upgrade of one model can only break its own worker.

The watershed and the features share an environment on purpose. Both are
built on scipy and scikit-image, and splitting them would only copy every
image between two workers.

The `umap` environment has no image readers and no PyTorch, because
`reduce_dimensions` reads the object table and not the images. It is kept
apart because umap-learn brings the numba compiler, which the other steps
do not need.

### Add a model

1. Write a step `segment_<model>.py` like `segment_watershed.py`: its `run`
   hands its own `find_objects` to `segment` in `segment_cellpose.py`, which
   does the binning, the filters and the record. Import the model inside the
   function that uses it.
2. Give it its own environment: a file in `environments/`, with its lock file.
3. Write a pipeline that runs it after `read_images`.

## Tuning notes

- **Size limits.** Prefer `min_equivalent_diameter_um` and
  `max_equivalent_diameter_um` over `min_area_px` and `max_area_px`. A limit
  in micrometres stays right when the pixel size changes. Use one kind per
  side, not both.
- **`border_margin_px`** rejects objects within this distance of a tile's
  edge. Tiles overlap, so an object at the edge very likely appears again
  in the neighbouring tile. A margin of about half the overlap keeps each
  object once.
- **`segmentation_binning`** runs Cellpose on an image that is `n` times
  smaller in each direction. The masks are scaled back to full size before
  the features are measured. Choose it by the quality of the segmentation,
  not only by speed.
- **`cellprob_threshold`**: a lower value gives larger masks and more of
  them.
- **`flow_threshold`** is Cellpose's own quality check on its masks.
- **`niter`**: a higher value helps with very long objects.

## The Cellpose model

Cellpose downloads its model (about 1.2 GB) the first time it runs, into
`.cellpose` in your home folder. To keep it somewhere else, for example
when a Windows profile has a size limit, set `CELLPOSE_LOCAL_MODELS_PATH`
to that folder before the first run.
