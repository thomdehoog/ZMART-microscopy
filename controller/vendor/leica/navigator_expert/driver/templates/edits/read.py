"""
Read-only LRP helpers.
========================
Functions that *read* attributes from LAS X scanning template ``.lrp``
files without modifying them.

These are pure readers with no side effects. Mutation helpers live under
``experimental/lrp_edits/`` until they have live-state verification.

Dependency direction:
    - Imports: stdlib only.
    - Imported by: editor modules that need current values for
      relative edits (e.g. ``lrp_set_pan`` callers that compose deltas).
"""

import xml.etree.ElementTree as ET
from pathlib import Path


def lrp_get_pan(lrp_path, job_name):
    """Read ``(PanFirstDim, PanSecondDim)`` for a job from the LRP.

    Used by relative-pan callers that need the current pan to compose a
    delta. Returns ``(0.0, 0.0)`` if the job or attributes are absent --
    that matches LAS X's "no pan written yet" state.
    """
    root = ET.parse(Path(lrp_path)).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is None or seq.get("BlockName") != job_name:
            continue
        for el in b.findall(".//ATLConfocalSettingDefinition"):
            px = el.get("PanFirstDim")
            py = el.get("PanSecondDim")
            if px is not None and py is not None:
                return float(px), float(py)
    return 0.0, 0.0
