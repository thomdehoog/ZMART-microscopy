# Shared acquisition rendering in the operator

Integration base: `claude/smart-operator-workflow-review-ehw3c5` at `a0fafdc0`.
The rig's plane sorting, frame/stamp fixes, gamma controls and target rerun work
remain in the merge. This branch adds no absolute-Z viewing mode.

Viewer dependency: `codex/mixed-acquisition-depth` at
`b33a21cb8ff9c3edb6a49c75e46ee5e72790818b` (0.2.1 baseline).
Install that separate checkout as described in the root README; the service
checks acquisition-rendering capability rather than silently accepting the old
release's per-position path.

## Ownership

- Every completed capture is a separate, complete OME-Zarr position store,
  including targets. The old full-resolution resolved-target store is gone.
- The bridge reports completed revisions and explicit bottom-to-top order.
  Raising a target changes order within its flat/stack kind, not its original
  pixels. Stacks always render above flats; cross-kind raises are not supported.
- A coalesced background publisher calls the shared viewer. Acquisition callbacks
  and bridge status requests perform no viewer I/O. Failed publication retains
  the last picture for that acquisition and reports the error, without hiding
  other acquisitions. Temporary failures retry; rejected input waits for a change.
- The viewer serves at most two sources per acquisition: persistent flats and
  relative-Z stacks. Channel controls address both internal blocks together.
  Original-store count never becomes engine source count.
- Source revisions trigger one effective whole-source refresh. An unchanged
  poll does not invalidate chunks. The stable viewer survives new acquisition
  rows and either depth kind arriving later.

At Connect, **Bake coarse images (experimental)** selects the A/B mode for the
session, default off. Both modes aggregate over the full specimen canvas. Bake
off computes coarse chunks on demand; bake on materializes affected coarse chunks.
Fine data stays in the separate originals. The image occupies the middle canvas
slot, above overview-plan ground and below operator marks. No ground cut-out is
needed during acquisition.

Complete-source footprints are authoritative coverage, independent of brightness
and absent zero-filled Zarr chunks. The shared viewer also supports explicit
sparse regions for other producers. Empty regions stay transparent; acquired
black covers lower imagery.

Stacks use the recorded specimen focus/reference height, falling back to the
lowest stored plane when no reference exists. The relative slider includes
negative coordinates. Flat aggregates use one private display Z and remain
visible through navigation. The rig writer's flat-Z/provenance convention is
preserved; no existing original is migrated or rewritten.

## Geometry limits

Flat and stack outputs share a channel count; their time lengths may differ.
Each aggregate requires compatible C/T, native pyramid layout and sampling,
and a common relative Z lattice. Canvas and published stack Z domain stay fixed;
a later stack extending that domain is explicitly refused and needs a new
acquisition. Fractional XY origins use nearest-neighbour raster placement with
at most half a finest-pixel shift per axis, consistently at every level and in
coverage. No subpixel interpolation or absolute-Z option is included.

Auto samples the logical channel across both common-canvas sources. As before,
this excludes zero-valued samples and is not an exact current-plane/occlusion
histogram. It never supplies image coverage or controls whether black is opaque.

## Verification

From the repository root, with the pinned viewer importable:

```text
python -m pytest application/framework/test_operator_bridge.py application/parts/storage/test_viewer_service.py application/parts/storage/test_zarr_positions.py
npm --prefix application run test:unit
```

From `application`:

```text
npm run build
npm run test:ui -- parts/canvas/aggregate-depth.spec.js parts/canvas/acquired-coverage.spec.js parts/canvas/source-refresh.spec.js workflows/target_acquisition/steps/scan_the_overview/transparent-middle.spec.js workflows/target_acquisition/steps/scan_the_overview/the-scan-under-the-plan.spec.js workflows/target_acquisition/walk.spec.js
```

The mixed-depth cases use the real shared server and original arrays in both
arrival orders and baking modes. They assert exact rendered colors, transparent
gaps, opaque black, fine/coarse views, slider limits, retained hidden-channel
state, aggregate-only requests and zero idle requests. The walk exercises all
nine workflow steps in both baking modes, checks publication errors and source
count, and measures mask alignment plus idle requests. Service scaling stops at
100 positions; no long benchmark ladder is part of this check.

Screenshots are generated test artifacts, not committed golden images. Set
`OPERATOR_EVIDENCE_DIR` to retain full-workflow screenshots elsewhere.
