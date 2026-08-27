# `object_analysis` workflow

Object-centered analysis for one acquired image tile.

```text
object_analysis.yaml:   detect_objects -> extract_classical_features -> build_object_table
object_detection.yaml:  detect_objects   (persist_only: masks and checkpoint, no features)
```

Every parameter lives in the pipeline YAML with its default, and each can be
overridden per submission — which is how the operator page tunes detection on
one position without registering a pipeline of its own. The step docstrings
are the reference for what each takes and returns.

## Input

Submit one tile at a time:

```python
{
    "image_path": "path/to/position",      # OME-Zarr position or OME-TIFF
    "tile_id": ["R0", 3, 7],
    "tile_stage_xy_um": [10000.0, 15000.0],
    "tile_zwide_um": 2500.0,
    "source_pixel_size_um": [0.65, 0.65],
    "source_image_size_px": [2048, 2048],  # (nx, ny)
    "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
    "channels": None,                      # up to three; [0, 2] to choose
    "gpu": False,
}
```

## Tuning notes

- Prefer `min/max_equivalent_diameter_um` over `min/max_area_px` for size
  bounds that survive a pixel-size change; one kind per side, not both.
- `border_margin_px` rejects objects within a band of each tile edge. Tiles
  overlap, so an edge object is very likely to appear again in the neighbour;
  about half the overlap keeps each object once.
- `segmentation_binning` runs Cellpose at 1/n linear resolution; masks are
  rescaled to full size before features. Choose it from segmentation quality,
  not only speed.
- `cellprob_threshold` lower = larger/more masks; `flow_threshold` is
  Cellpose's flow-consistency QC; `niter` helps very long objects.

## Output

The result lands under `pipeline_data["object_analysis"]` as the object
table: per-object features plus `stage_x_um`/`stage_y_um` (placed via the
tile's own geometry), `tile_name`, and `object_id`.

`detect_objects` also writes `masks.tif`, `raw_masks.tif` and
`detection_checkpoint.json` under `<analysis>/tiles/<short_name>/` — into the
`analysis` folder beside the `data` the image came from, or `output_dir` when
given, or nowhere when the image is outside an acquisition and no
`output_dir` names a place. The checkpoint records the effective parameters,
a hash of the true mask-generation parameters, and content hashes of the
image and masks, so a run is reproducible from what actually ran.
