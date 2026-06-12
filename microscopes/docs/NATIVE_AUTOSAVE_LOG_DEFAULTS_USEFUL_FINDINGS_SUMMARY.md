# Native AutoSave + Log Defaults: Useful Findings Summary

Date: 2026-06-05

Branch: `defaults/native-autosave-log`

## Setup / Environment

- Repo: `smart-microscopy`.
- Original planned env `smart_lasx_pf_only_fresh` did not exist on this machine.
- New env `smart_lasx_runtime` was created and works:
  - Python 3.12
  - `pythonnet` / `clr` import OK
  - `numpy`, `tifffile`, `imagecodecs`, `ome-types`, `pytest`
- The driver loads the Leica CAM runtime from Program Files, not from copied DLLs in the env.
- LAS X Api Server must be listening on `127.0.0.1:8896`.
- Registered client name `PythonClient` is correct.

## Connection Finding

- Initial connection failures were not Python/env/DLL problems.
- LAS X was running, but the Api Server socket was not listening.
- After restarting/enabling LAS X Api Server, port `8896` was owned by `NavigatorExpert` and connection worked.

## Validator Results

- API read-only validator worked:
  - `pass=9 warn=0 fail=0 skip=0`
- Strict log-mode read-only validator failed on job resolution:
  - `pass=7 warn=0 fail=1 skip=0`
  - Failure: no jobs returned under strict log freshness gates.
- Pure log with temporarily relaxed age gates passed, proving parser/log content can work when stale data is allowed.
- Native AutoSave save tests were not completed yet.
- Full acquisition/save tests are still open.

## Log Format / Parser Findings

- LAS X log format did not appear fundamentally broken.
- Existing markers still matched:
  - `GetStageHwPosition`
  - `ATL_GetBlockApiInfoAsJsonString`
  - `GetConfocalHardwareInfoAsJson`
  - `SetCurrentSelectedElementID`
  - `AcquisitionState`
  - `CurrentBlock/Name`
  - `CurrentBlock/BlockID`
  - `GetMatrixCollectionPatternInfo`
- Old job-list parser source was weak:
  - It inferred jobs from `ATL_GetBlockApiInfoAsJsonString`.
  - That source is partial because LAS X only logs settings for jobs that were queried.
- Better full job-list source:
  - `GetMatrixCollectionPatternInfo`
  - It listed all jobs: `AF Job`, `Overview`, `HiRes`.

## Selected Job Finding

- `CurrentBlock/Name` and `CurrentBlock/BlockID` in `MatrixScreener.log` matched the actual UI.
- `SetCurrentSelectedElementID` is command intent, not proof of applied state.
- API selected-job readback is wrong on this hardware:
  - Switched to `AF Job`.
  - Log/UI confirmed switch in about `0.138s`.
  - API still reported `Overview` for 60 seconds.
  - Restore to `Overview` was confirmed by log in about `0.13s`.
- Conclusion: API selected-job readback is persistently stale here, not merely slow.

## Job Switching / Movement

- Selecting a job does not move the stage.
- It changes the active Matrix Screener block/job.
- XY/Z movement and acquisition are separate phases, which were skipped in the narrow job-switch tests.
- That explains why physical movement was not visible during job switching.

## Side-by-Side Harness Findings

- The side-by-side API-vs-log script had a branch-specific harness issue:
  - It labeled one column "API" but called readers without `mode="api"`.
  - Since this branch defaults passive readers to log, it could compare gated-log vs ungated-log instead of API vs log.
- Once API was pinned correctly, most parity was good:
  - full job list matched
  - settings matched
  - FOV matched
  - Z-wide matched
- Main mismatch remained selected job:
  - API said `Overview`
  - log/UI showed the actual active job.

## Hardware Info Finding

- Hardware-info parser did return data, but the harness assumed a top-level `"Microscope"` key.
- This microscope's JSON shape used keys like:
  - `FilterWheels`
  - `LightSinks`
  - `DetectionUnits`
- So the harness should not assume `hw["Microscope"]["name"]`.

## Freshness / Age Gate Findings

- Log age gates are very strict:
  - XY around `1s`
  - jobs/settings/hardware around `2s`
  - scan status around `0.5s`
- LAS X may stop writing state logs when idle.
- `Socket.log` can remain live while `lcsCommand.log` / `MatrixScreener.log` state entries are stale.
- Therefore strict log mode can correctly fail closed on an idle scope.
- Do not fix this by globally inflating age gates.

## Design Conclusion

- Treat API readers and log readers as separate reader families.
- A state decision should use one explicit source policy:
  - `api`
  - `log`
  - or explicit experimental `both`
- Do not mix API and log inside one decision unless `both` is deliberately selected and conflict-reporting is implemented.
- For selected job on this hardware:
  - log `CurrentBlock` is the reliable applied-state source.
  - API selected-job readback is unreliable.
- `both` should not be a silent fallback; it should report source, freshness, and conflicts.

## Implementation Caution

- Exploratory edits were made but not committed.
- The current dirty worktree should not be treated as final.
- Best clean path:
  1. Save or discard the exploratory diff.
  2. Reset to a clean baseline.
  3. Re-land small changes in order:
     - parser only: `GetMatrixCollectionPatternInfo` + `CurrentBlock`
     - selected-job reader contract
     - command policy, only if agreed
- The science/result is solid; the implementation should be redone cleanly.
