# Top plane index, absolute Slice, and mock stack jobs

Paired changes on `codex/operator-named-views-simulator` and viewer
`codex/operator-embedding`. Viewer revision `90e0350` is published and pinned
by this operator increment; no rig/main branch changes.

## Behavior

- Top aligns every stack's first/lowest plane at index zero, displayed as Plane 1.
  The range is the maximum plane count. Unequal thicknesses and step sizes work;
  shorter stacks hold their final plane. Single images remain visible.
- Slice uses absolute specimen coordinates, including single images. It uses the
  smallest native step in the acquisition and nearest-plane resampling, with at
  most half an output step of origin quantization. Coverage and pixels use the
  same source-plane selection. Originals remain separate and unchanged.
- MIP remains a per-position maximum projection, without a depth slider.
- The operator dropdown changes all acquisitions together, including acquisitions
  arriving later. This fixes the misleading mixed case where the dropdown said
  Slice for overview while targets were still held in Top. Mode changes do not
  carry physical micrometres into plane indices.
- The shared publisher owns placement and the versioned recipe. Old relative-Z
  products rebuild once on re-publication, even with unchanged source revisions.
  Subsequent identical announcements remain idle. Opening old products alone does
  not migrate them. False-Z legacy originals need correct specimen metadata.

## Mock jobs

`Overview stack`: 7 planes, 2 µm step, three channels.
`Target stack`: 11 planes, 1 µm step, three channels.
Original single-plane jobs remain available. The unknown-job failure was a stale
backend process; the first restart loaded the new definitions. A read-only check
of the user's resulting overview confirmed TCZYX shape `[1,3,7,20000,30000]`.
The final view-mode changes need another restart; an active target run was left
undisturbed rather than interrupted for that restart.

## Verification

- 16 mock driver/instrument tests passed, including real multi-plane captures and
  switching back to single-plane jobs.
- 525 operator JS unit tests passed, 15 skipped. New tests cover one-based Plane,
  physical Slice units and canvas-wide mode propagation to later acquisitions.
- 133 viewer regression tests passed; a final 25-test targeted rerun also passed,
  including a new one-time migration test. Coverage includes C/T, unequal steps,
  unequal depths, sparse planes, black pixels, reopen, growth/shrink, and bakes
  compared with an independent cold composer. Scaling remains capped at 100.
- Four operator rendered fixtures passed, both arrival orders and bake on/off.
  Distinct-plane pixels prove Slice placement and Top boundary holding. One-pixel
  detail matches Top/MIP at four zooms; no MIP resolution loss reproduced.
  Each fixture reports zero idle image refetches.
- Two standalone rendered overlap/coverage tests passed, including Plane labels
  and physical-Z readouts.
- Full baked Connect → detection → target-acquisition walk passed in 2.9 minutes:
  538 image requests, zero idle refetches; mask/image offset 0 px at four zooms.
- Both frontend builds passed. The old opacity explanation was corrected: the
  operator uses acquired coverage, not rectangular holes in its drawing layer.
  Generic drawing-window APIs remain for their other tested clients.

This verifies settled pixel alignment, not a universal latency guarantee during
continuous zooming. Cold chunk fetch/decoding still takes time. No speculative
rendering timeout or quality reduction was added for the reported sluggishness.

Evidence is under `C:/ProgramData/MinicondaZMB/home/t.de/_op050/plane-walk/`,
`plane-mode-browser/`, and `mip-detail-results/`.
See `MICROSCOPE_INSTALL_HANDOVER_2026-09-10.md` for the matching viewer source build,
environment setup and real-microscope preflight checks.
