# Review: operator integration with ZMART-viewer 0.2.1

Branch: `codex/operator-viewer-0.2.1-ehw3c5`.
Base: `2dd0ba66842283b1aa5cef4da73540773d7dbbb4` on
`claude/smart-operator-workflow-review-ehw3c5`.
Review `git diff 2dd0ba66...HEAD`. This merges the previously reviewed
`codex/transparent-operator-layers` branch onto the latest workflow branch.
The separate viewer release is `v0.2.1`, commit
`18bd328267922eeca878f7839d4d66bce0d11bfb`.

## Contract and review priorities

Bottom to top: background/carrier/focus heatmap/overview plan; acquisition
viewer; scan markers, masks, editing handles, stage crosshair and scale.
The empty viewer opens at Connect, receives focus images in step 4, overview
images in step 5, and target rows without replacing that viewer.
Empty image areas are transparent; acquired black pixels remain opaque.
Acquisition does not cut holes in or automatically fade application layers.

Challenge simplicity, clarity, efficiency and abstraction boundaries. Prefer
contained fixes over duplicated state, engine-specific caller knowledge,
fallback chains or additional machinery. Report severity, file:line, failure
scenario and the smallest principled correction. Review only; do not edit,
commit, push or merge without a new request.

Check the canvas-owned middle slot, layer order and pointer handling; retained
rows and disconnect races; channel mixing and C/Z/T bounds; source replacement;
and JPEG fallback. The merge keeps upstream's frames-before-cells order and
stage tracking, focus-error isolation, mask controls and step-9 colour restoration.
The generated page conflict was resolved by rebuilding, not hand-merging output.

The bridge alone decides dense opacity. Resolved target mosaics retain their
existing encoding (zero means gap, acquired values are at least one; raw frames
are separate). They must not receive the dense-bounds optimization. Sparse
composed sources require geometry coverage in the viewer. The Neuroglancer
alpha edits remain in the operator patch-package file and the viewer's anchored
script, cross-referenced; this integration does not consolidate those repositories.

## Qualification — 2026-09-08

- Fresh npm installation and build passed; final tracked built page is included.
- Vitest: 501 passed, 15 skipped.
- Python storage, bridge, capture, focus and warm-worker checks: 142 passed.
- Six browser integration checks passed, including the full nine-step built-page
  acquisition, partial overview, three-layer proof, JPEG placement/fallback and
  built-versus-development appearance. The final walk leaves layer opacity at
  100%, keeps the background enabled and retains the Connect viewer through
  target acquisition. It checks overview and target storage errors.
- Broader operator-page suite: 32 passed, four failed. All four reproduced
  unchanged on untouched base 2dd0ba66:
  - line 276: sidebar handle is 18px; assertion requires at least 28px.
  - line 1011: toolbar intercepts a click at canvas coordinate (5, 5).
  - line 1071: returned carrier screenshot is not byte-identical.
  - line 1447: expected first field 1/864, received last field 864/864.
  These failures are not silenced or counted as passes.
- Initial Python run: 93 passed, one failed writing a long nested Windows path.
  A shorter temporary root passed all 94 unchanged tests, then the expanded
  142-test group passed. Storage implementation is unchanged from the base.
- npm reports 26 dependency advisories on both base and integration branches.
  No dependency audit fixes were attempted. npm also warns about the installed
  Node 26 alpha version. No physical Leica or live Firefox/Edge qualification.

## Reproduction and evidence

Follow README.md to install the separate viewer at the release commit. The
runtime version check now requires 0.2.1 and tests reject older/unproved versions.
The local test venv uses the existing conda packages plus an isolated editable
viewer release, without updating the microscope's shared environment.

From application:

    npm ci
    npm run build
    npx vitest run
    npx playwright test workflows/target_acquisition/walk.spec.js transparent-middle.spec.js the-scan-under-the-plan.spec.js framework/the-built-page.spec.js
    npx playwright test framework/operator-page.spec.js

From the root:

    python -m pytest application/parts/storage application/framework/test_operator_bridge.py application/parts/microscope/test_capture_run.py application/parts/microscope/test_focus_run.py application/parts/analysis/test_warm.py -q

Use isolated test/bridge ports, mock machine/state and a short temporary path.
All executables, caches and data must remain under the whitelisted ProgramData
tree. Set the conda worker variables and use conda-forge only; do not touch
either Leica driver folder or another clone's dirty files.

Local environment setup:
`C:\ProgramData\MinicondaZMB\home\t.de\operator-021-test-settings.ps1`.
Invoke it with PowerShell's call operator, not dot-sourcing.
Evidence is outside Git under the same home:
`operator-021-final-browser-results`, `operator-021-final-proof`,
`operator-021-page-results`, `operator-021-base-results`,
`operator-021-base-plan-results`, and `operator-021-python-final.xml`.
`operator-021-demo/index.html` presents recorded evidence in a pywebview window,
not a live microscope session. Screenshots are not committed fixtures.
