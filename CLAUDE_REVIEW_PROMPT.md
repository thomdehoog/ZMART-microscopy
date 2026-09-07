# Review: Neuroglancer between the operator's plan and annotations

Repository: https://github.com/thomdehoog/ZMART-microscopy
Branch: `codex/transparent-operator-layers`
Base: `1860b1f4` on `claude/smart-operator-workflow-review-ehw3c5`.
Review `git diff 1860b1f4...HEAD`. No PR has been opened.
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

## What to challenge

Review for short, professional, maintainable code at the right abstraction level.
Flag unnecessary fallback paths, dead compatibility code, duplicate placement
logic, misleading comments, hard-coded test assumptions, or a smaller correct
implementation. Do not equate passing tests with a sound design.

Specifically check layer stacking contexts and hit-testing; heatmap versus marker
placement; initial empty viewer lifecycle and disconnect races; first-source
installation; channel mixing and zero pixels; growing C/Z/T extents; and source
replacement. Check generic canvas behaviour and JPEG fallback, not just NG.

One remaining inherited boundary deserves scrutiny: adding a different
acquisition/channel shape still takes the existing reopen path. Only first-source
installation and appended sources on stable rows preserve the viewer instance.
This branch does not claim seamless scene replacement across arbitrary types.

## Evidence and reproduction

`docs/transparency-proof/` contains unmodified browser screenshots of step 4,
step 5 and a diagnostic three-surface stack. Magenta is beneath the image; the
orange label is above. The test compares the screenshot with imagery hidden to
ensure it counted real image pixels, not UI decorations.

The application build passed, 481 Vitest tests passed (15 skipped), and all 17
viewer-service Python tests passed. The real mock-bridge browser walk passed
repeatedly: it checks empty Connect state, retained first viewer at step 4,
ground enabled and no cut-outs at steps 4/5, plus screenshot pixels on all levels.
The viewer repository separately passes its 47 targeted Python/browser tests.
All four targeted operator browser tests pass, including JPEG registration
during pan/zoom and opaque lower-background behaviour. The automatic cut-out
path and its notifications have been removed, not kept as no-op compatibility.
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
    npx playwright test transparent-middle.spec.js the-scan-under-the-plan.spec.js

From the root:

    python -m pytest application/parts/storage/test_viewer_service.py -q

Keep unrelated dirty files intact. Never use conda defaults or touch either
Leica driver folder. Report findings as severity, file:line, a concrete failure
scenario and the smallest principled correction. No fixes, commits, pushes or PRs.
