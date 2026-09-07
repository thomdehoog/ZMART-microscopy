# Review: Neuroglancer between the operator's plan and annotations

Repository: https://github.com/thomdehoog/ZMART-microscopy
Branch: `codex/transparent-operator-layers`
Base: `8dbbf768` on `claude/smart-operator-workflow-review-ehw3c5`.
Review `git diff 8dbbf768...HEAD`. No PR has been opened.
The original review clone's unrelated uncommitted changes are not in this branch.
Generated files under `application/framework/window/static` are excluded.

Companion viewer 0.2.0 change:
https://github.com/thomdehoog/zmart-viewer/tree/codex/transparent-2d-footprints

## Contract and boundaries

Bottom to top: background/carrier/focus heatmap/overview plan; acquisition viewer;
scan markers, masks, focus markers, editing handles, stage crosshair and scale.
The empty transparent viewer opens after Connect and receives the first focusing
images in step 4, without replacing that initial viewer. Step 5 fills the overview.
Image alpha does not depend on intensity: real black pixels are opaque.
Acquisition must not cut holes in, fade, or hide other application layers.

The existing lightweight canvas owns navigation and its two drawing slots. Its
middle slot hosts the separate image viewer. `THE_STACK` in `shared/stage.js`
owns the semantic layer order. The server boundary still uses the separately
installed ZMART-viewer 0.2.0, not the historical in-repository backend copy.
The microscopy writer publishes dense individual position stores, so its adapter
can use constant alpha within a source. It must not apply this rule to a sparse
composed bounding box. That case needs the viewer repository's geometry coverage.
Resolved target display mosaics keep their existing explicit encoding (zero is
a gap, acquired values are at least one; raw frames are kept separately). The
bridge disables dense opacity for these mosaics. This patch does not change
their writer or substitute a dense bounding box for their coverage.

## What to challenge

Review for short, professional, maintainable code at the right abstraction level.
Flag unnecessary fallback paths, dead compatibility code, duplicate placement
logic, misleading comments, hard-coded test assumptions, or a smaller correct
implementation. Do not equate passing tests with a sound design.

Specifically check layer stacking contexts and hit-testing; heatmap versus marker
placement; initial empty viewer lifecycle and disconnect races; first-source
installation; channel mixing and zero pixels; growing C/Z/T extents; and source
replacement. Check generic canvas behaviour and JPEG fallback, not just NG.

New acquisition/channel rows append to the existing viewer, preserving its
loaded layers. Their display panel is remounted only when row shape changes,
retaining requested settings and cancelling old indexed measurements first.
Removing or replacing existing source addresses still requires a scene reopen.
Session generations reject stale opening/growth results after disconnect.
An unavailable source response is not interpreted as an empty scene. Spatial
axes are selected before alignment corrections, including early source callbacks.

## Evidence and reproduction

`docs/transparency-proof/README.md` explains the generated browser artifacts.
Screenshots are test outputs, not tracked fixtures. Magenta is beneath the image;
the orange label is above. Differential screenshots measure actual imagery for
both the NG and JPEG paths, not only the background canvas's alpha.

The corrected mock walk checks successful focus and overview responses, captured
slices without lost points, all planned records, and viewer identity at steps 4/5.
It uses a fresh mock configuration: reusing a configuration whose origin was
changed by another test reproduced the review's out-of-envelope errors.
The nine-step upstream walk additionally checks viewer identity through target
acquisition; keep its Z/T assertions intact and report any baseline failures.
The automatic cut-out path and its notifications have been removed, not retained
as no-op compatibility.

Final qualification on 2026-09-07: fresh dependency installation and build passed;
501 Vitest tests passed (15 skipped); 17 service tests passed; all five browser
tests passed in 4.1 minutes, including the full nine-step acquisition walk,
loaded target rows, unchanged viewer identity, and the original Z/T assertions.
The companion viewer at `b5b3d27` passed 52 targeted tests and changed-file lint.
An independent subagent reviewed the corrections and also ran the unpatched
`8dbbf768` nine-step baseline successfully. No assertions were relaxed to qualify
our branch. Long viewer replay/benchmark suites were not rerun.

Fresh local artifacts are under
`C:\ProgramData\MinicondaZMB\home\t.de\operator-review-final-browser-20260907`
and `C:\ProgramData\MinicondaZMB\home\t.de\operator-review-final-proof-20260907`.
No physical Leica acquisition or Firefox/Edge qualification is claimed.

Worktree: `C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-transparency-20260907`.
Put `C:\ProgramData\MinicondaZMB\envs\zmart-microscopy` and its `Scripts` and
`Library\bin` on PATH. Set `CONDA_EXE=C:\ProgramData\MinicondaZMB\Scripts\conda.exe`,
`CONDA_PREFIX` to that env, `CONDA_DEFAULT_ENV=zmart-microscopy`, `CONDA_SHLVL=1`.
Set `PYTHONPATH` to the companion viewer worktree to test its 0.2.0 source.
Set `PLAYWRIGHT_CHROMIUM` to the installed `chromium-1234\chrome-win64\chrome.exe`
under `C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright`.
Set `ZMART_TEST_PORT=5187` so an already-running Vite from another clone cannot
silently supply the wrong code. Set `ZMART_MOCK_MACHINE` to an isolated temporary
folder; keep TEMP, TMP and npm cache under the whitelisted ProgramData tree.

From `application`:

    npm ci
    npm run build
    npx vitest run
    npx playwright test workflows/target_acquisition/walk.spec.js transparent-middle.spec.js the-scan-under-the-plan.spec.js

From the root:

    python -m pytest application/parts/storage/test_viewer_service.py -q

Keep unrelated dirty files intact. Never use conda defaults or touch either
Leica driver folder. Report findings as severity, file:line, a concrete failure
scenario and the smallest principled correction. No fixes, commits, pushes or PRs.
