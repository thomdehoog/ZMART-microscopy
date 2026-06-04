# Minimal LAS X Python Environments

Date: 2026-06-04

This repo no longer vendors Leica CAM API DLLs. The driver loads the LAS X CAM
API runtime from the licensed LAS X install:

```text
C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert
```

The Python environment only needs the Python packages. Leica files do not need
to be copied into the conda environment.

## Minimal API / Hardware Validator Env

Use this for connecting to LAS X, reading state, moving, switching jobs, and
running `validate_hardware.py` without saving images.

```powershell
conda create -n smart_lasx_min python=3.12 pip -y
conda activate smart_lasx_min
python -m pip install pythonnet
```

Connection/read-only smoke test:

```powershell
cd Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy

python driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --read-only `
  --state-reader-mode api
```

Expected key line:

```text
runtime=C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert
version=1.0.108.0
api_delay_ms=250
```

## Minimal Full Driver Save Env

Use this for acquire + native AutoSave + canonical SMART OME-TIFF output.

```powershell
conda create -n smart_lasx_save python=3.12 pip -y
conda activate smart_lasx_save
python -m pip install pythonnet numpy tifffile imagecodecs
```

This is the smallest practical env for the normal driver path that persists
images.

## Validation / Metadata Comparison Env

Use this for unit tests and hardware metadata comparison tools that parse OME.

```powershell
conda create -n smart_lasx_validate python=3.12 pip -y
conda activate smart_lasx_validate
python -m pip install pythonnet numpy tifffile imagecodecs ome-types pytest
```

Example checks:

```powershell
python -m pytest driver/vendor/leica/navigator_expert/tests/unit/test_lasx_runtime.py -q

python driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --read-only

python driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py `
  --read-only
```

## Recommended Microscope Env

For the microscope workstation, use one small env that covers connection,
hardware validation, native AutoSave output, and API-vs-log comparison:

```powershell
conda create -n smart_lasx_runtime python=3.12 pip -y
conda activate smart_lasx_runtime
python -m pip install pythonnet numpy tifffile imagecodecs ome-types pytest
```

This does not install or copy Leica DLLs into the env. The driver loads them
from Program Files at runtime.

## Notes

- `pythonnet` is still required. It is the Python-to-.NET bridge.
- `numpy`, `tifffile`, and `imagecodecs` are needed for image read/write paths.
- `ome-types` is needed by metadata comparison/validation tools, not by the
  simplest connection smoke test.
- `pytest` is only needed for running tests.
- LAS X must be installed and the CAM Api Server must be listening on
  `127.0.0.1:8896` before hardware validation can connect.
