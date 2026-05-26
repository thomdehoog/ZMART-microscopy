# Driver Import Migration Guide

The driver package has been restructured from a flat layout (25+ modules)
into layered subpackages. This document maps old import paths to new
canonical paths.

## Rule

New code should use **canonical paths** (the subpackage imports).
Old flat paths still work via compatibility shims but are deprecated.

## Canonical import paths

| Subpackage | Modules | Example |
|------------|---------|---------|
| `driver.api` | core, commands, readers, confirmations, prechecks, profiles, settings, errors, utils, session | `from navigator_expert.driver.api.commands import set_zoom` |
| `driver.templates` | files, strip_restore, parsers, transaction | `from navigator_expert.driver.templates.files import TEMPLATE_XML` |
| `driver.templates.edits` | read | `from navigator_expert.driver.templates.edits.read import lrp_get_pan` |
| `driver.output` | ome, lasx_files, acquire, acquisition | `from navigator_expert.driver.output.ome import fix_ome_tiff` |
| `driver.motion` | limits, stage, config | `from navigator_expert.driver.motion.limits import set_stage_limits` |
| `driver.experimental.lrp_edits` | general, scan, z, roi, focus, _primitives | `from navigator_expert.driver.experimental.lrp_edits.scan import lrp_set_zoom` |

## Facade

`import navigator_expert.driver as drv` continues to work and re-exports
~190 symbols. The facade is frozen at its current symbol set.

## Shim paths (deprecated)

These flat-level files exist for backward compatibility:

```
driver/utils.py          -> driver/api/utils.py
driver/errors.py         -> driver/api/errors.py
driver/core.py           -> driver/api/core.py
driver/commands.py       -> driver/api/commands.py
driver/readers.py        -> driver/api/readers.py
driver/confirmations.py  -> driver/api/confirmations.py
driver/prechecks.py      -> driver/api/prechecks.py
driver/profiles.py       -> driver/api/profiles.py
driver/settings.py       -> driver/api/settings.py
driver/session.py        -> driver/api/session.py
driver/limits.py         -> driver/motion/limits.py
driver/stage_motion.py   -> driver/motion/stage.py
driver/stage_config.py   -> driver/motion/config.py
driver/ome_tiff.py       -> driver/output/ome.py
driver/file_confirmation.py -> driver/output/lasx_files.py
driver/acquire.py        -> driver/output/acquire.py
driver/acquisition.py    -> driver/output/acquisition.py
driver/scanning_templates.py -> driver/templates/{files,strip_restore,transaction}.py
driver/scanning_template_parsers.py -> driver/templates/parsers.py
driver/scanning_template_editors.py -> driver/experimental/lrp_edits/general.py
driver/scanning_template_editors_scan.py -> driver/experimental/lrp_edits/scan.py
driver/scanning_template_editors_z.py -> driver/experimental/lrp_edits/z.py
driver/scanning_template_editors_roi.py -> driver/experimental/lrp_edits/roi.py
driver/scanning_template_editors_focus.py -> driver/experimental/lrp_edits/focus.py
```
