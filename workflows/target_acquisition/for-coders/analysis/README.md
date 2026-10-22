# Analysis of the target acquisition workflow for coders

Finds the objects in an overview image, measures each one, and returns a table with one row per object. It plugs into the [ZMART analysis](https://github.com/ZMB-UZH/ZMART-analysis) engine, which runs each step in the environment the step names.

## The pipeline

`pipelines/object_analysis_watershed.yaml`: `read_images` → `segment_watershed` → `measure_objects` → `build_object_table`. A watershed that needs no GPU. Every parameter is in the pipeline, with its default; the docstring of each step, in `steps/`, says what it takes and returns. `segment_cellpose.py` is there for the helpers two steps use.

## Input

```python
{"image_path": "path/to/image.ome.zarr"}
```

An OME-Zarr image is enough: the pixel size and where the image lies on the stage come from its metadata. A TIFF also needs `tile_stage_xy_um` and `source_pixel_size_um`.

## Output

The object table, under `["object_analysis"]["objects"]["properties"]`: one list per column, one entry per object, with its features (such as `intensity_cv` and `eccentricity`) and its stage position, `stage_x_um` and `stage_y_um`.

## Environment

The steps run in `ZMART--target_acquisition_for_coders--classical`, built from the lock file `environments/classical.txt`, so every package is at one version:

```bash
python environments/setup_env.py --step classical
```

`environments/clean_env.py` removes it again. To move to newer packages, build with `--unpinned`, check it, and write a new lock file with `pip freeze`.

## Tests

```bash
pip install pytest
python -m pytest tests
```
