# Legacy scripts

These scripts pre-date `controller/vendor/leica/navigator_expert/examples/`
and import via the deprecated `lasx` test-shim
(`from LasxApi import PYLICamApiConnector as lasx_api`).

| File | Purpose |
|------|---------|
| `acquire_hires.py` | Quick high-resolution acquire spike (~21 lines). |
| `explore_export_paths.py` | Debugging probe for LAS X export-drive path resolution. |
| `test_file_confirmation.py` | Early file-confirmation experiments; predates `driver/file_confirmation.py`. |
| `test_grid_acquisition.py` | Grid acquisition spike. |

**Status:** kept rather than deleted in case any of these workflows
are still useful for one-off lab tasks. **Not part of the supported
example surface** — that's `controller/vendor/leica/navigator_expert/examples/`.
New work goes there.

The `lasx` shim these scripts rely on lives in
`controller/vendor/leica/navigator_expert/test/conftest.py`. When that
shim is retired (planned in a later cleanup wave), these scripts will
need their imports updated to `from navigator_expert.driver import ...`
or be deleted alongside the shim.
