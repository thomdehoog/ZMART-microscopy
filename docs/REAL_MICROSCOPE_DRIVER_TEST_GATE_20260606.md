# Real Microscope Driver Test Gate - 2026-06-06

## Goal

Validate the production-candidate driver branch on the real microscope before
running the target-acquisition workflow.

Branch intent:

- LAS X native AutoSave is the production save path.
- Passive state readers should use the API path.
- Log readers remain experimental and should not be part of the first real
  workflow baseline.

Do not start the full target-acquisition workflow until the driver checks below
pass.

## Local Baseline Already Run

These checks passed before the real-scope gate:

```text
Focused driver unit suite: 293 passed, 56 subtests passed
Mock hardware validator: pass=63 warn=0 fail=0 skip=5
```

The focused unit suite covered the high-risk branch areas:

- API/profile state-reader defaults
- native AutoSave collection/materialization
- LAS X runtime loading
- acquisition/save contract
- core driver command behavior

## Real Microscope Commands

Use the LAS X driver environment:

```powershell
$py = 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe'
cd 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy'
```

### 1. Basic Read-Only Health Check

This checks that the driver can connect and read the core API-backed state
without moving the microscope or acquiring.

```powershell
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --read-only `
  --state-reader-mode api `
  --output C:\Users\t.de\lasx_probes\smart\real_validate_readonly_api.jsonl
```

Pass criteria:

- zero `FAIL`
- no missing jobs/hardware/XY reads

### 2. Reversible Hardware Validator

This checks the command spine with reversible writes and small motion/acquire
operations. The first real run should keep objective switching disabled.

```powershell
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --state-reader-mode api `
  --allow-xy `
  --allow-z `
  --allow-acquire `
  --strict-confirmation `
  --output C:\Users\t.de\lasx_probes\smart\real_validate_hardware_api.jsonl
```

Pass criteria:

- zero `FAIL`
- preferably zero `WARN`
- acquire confirms cleanly
- XY and Z restore to their starting positions

Only add objective switching after this passes and the microscope setup is
ready for objective changes:

```powershell
--allow-objective
```

### 3. Two-Tile Acquire/Save Smoke

This is the most important branch-specific smoke test. It exercises the native
AutoSave production path and the workflow-style file contract without running
the full target workflow.

```powershell
& $py driver/vendor/leica/navigator_expert/tests/hardware/smoke_two_tile_save.py `
  --yes `
  --allow-xy `
  --output-root C:\Users\t.de\lasx_probes\smart\real_two_tile_smoke `
  --report C:\Users\t.de\lasx_probes\smart\real_two_tile_smoke_report.json
```

This test verifies:

- active save exporter resolves from the driver profile
- native AutoSave discovers its own source root
- two acquisitions are saved into canonical SMART output
- job switching works between tile 0 and tile 1
- one job setting is changed and restored
- optional XY movement is restored
- TIFF/XML files exist and are readable
- `summary.json` contains p=0 and p=1 records
- source references resolve back to LAS X native AutoSave files

Pass criteria:

- report status is `PASS`
- two canonical OME-TIFF outputs exist
- two canonical OME-XML companions exist
- `summary.json` has both p indices
- no unresolved source refs

If this fails at job selection, stop before the full workflow. That means the
API selected-job readback/confirmation path is not reliable enough for the
workflow baseline yet.

## Notebook Environment Note

This note is about the `smart_microscopy_v3.2.ipynb` notebook kernel, not the
ELMI/smart-analysis worker environment.

Before using the 3.2 notebook on the microscope, make sure the notebook kernel
is:

```text
lasxapi_extended
```

Do not run the microscope notebook from the temporary DINO test environment
used during simulator probing (`dino3_test`, sometimes written as
`dinov3_test` in notes).

Reason:

- the LAS X driver/API stack is set up in `lasxapi_extended`
- on the microscope, `lasxapi_extended` is expected to contain Cellpose and
  scikit-image as well
- using the known microscope notebook environment avoids adding another
  variable during the real-scope driver/workflow test

After changing the notebook kernel, restart the kernel and rerun the workflow
setup/preflight cells. An old notebook kernel can keep stale imports, a stale
`ctx`, or a previously registered analysis engine.

The smart-analysis worker environment is a separate layer. Handle that only
when testing or changing the ELMI/analysis pipeline itself.

## Stop Conditions

Stop before the full target workflow if any of these happen:

- read-only validator has any `FAIL`
- reversible validator has any `FAIL`
- `--strict-confirmation` turns a command confirmation warning into a non-zero
  exit
- two-tile smoke cannot find native AutoSave output
- two-tile smoke writes canonical files but summary/source refs do not resolve
- selected-job readback is wrong after a job switch
- any restore operation fails

If all three gates pass, the driver is a reasonable baseline for:

1. opening the workflow notebook,
2. rerunning preflight,
3. acquiring the overview,
4. checking fresh Cellpose analysis outputs,
5. then proceeding to target acquisition.
