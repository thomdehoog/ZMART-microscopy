# Review: Neuroglancer between the operator's plan and annotations

Repository: https://github.com/thomdehoog/ZMART-microscopy
Branch: `codex/transparent-operator-layers`
Base: `170d9494` on `claude/smart-operator-workflow-review-ehw3c5`.
Review `git diff 170d9494...HEAD`. No PR has been opened.
The original review clone's unrelated uncommitted changes are not in this branch.
The rebuilt tracked page under `application/framework/window/static` is included
for built deployments. Review source first; the browser walk tests the built page.

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
The bridge alone decides which acquisitions are dense, so the image adapter
can use constant alpha within those sources. It must not apply this rule to a sparse
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
slices without lost points, the acquired record, and viewer identity at steps 4/5.
It captures a stable one-field overview; the separate nine-step walk tests the
full UI-driven scan. A second scan replaces sources rather than appending them.
It isolates both the mock configuration and instrument state, and explicitly
chooses the Overview/Focussing jobs. Other tests can change either shared default.
The nine-step upstream walk additionally checks viewer identity through target
acquisition; keep its Z/T assertions intact and report any baseline failures.
The automatic cut-out path, obsolete inspection API and their assertions are gone.
`THE_STACK` has one `picture` marker, and the drawing engine owns its middle slot.
The image caller passes one transparency flag without inspecting the engine name.
The upstream completed-plan hiding condition was removed: with images above the
plan it is unnecessary, and it referenced deleted cut-out state after the merge.

Round-three qualification on 2026-09-07: build passed; 501 Vitest tests passed
(15 skipped); 17 service tests passed. The built nine-step acquisition walk
passed, including loaded target rows, unchanged viewer identity, the original
Z/T assertions and upstream's new mask-strip assertions. The companion viewer
at `39ff048` passed 78 targeted tests and changed-file lint, including dense bounds growth
without a transparent frame. An independent coding agent reviewed the changes.
Long viewer replay/benchmark suites were not rerun.
The built partial-overview proof passed twice (52.2 seconds combined), and the
three JPEG/placement checks plus built-versus-development appearance check
passed. The full walk passed again in 2.5 minutes and explicitly validates every overview record and
storage error; those checks moved out of the focused one-field proof.

The older simulated `framework/operator-page.spec.js` whole-run test fails at
line 1447: expected first field `1 / 864`, received last field `864 / 864`.
Independent history inspection confirmed upstream `ae842123f` deliberately
removed the post-scan selection reset before `8dbbf768`; the September 4 test
still expects it. This unrelated assertion remains unchanged. Do not report
the entire operator browser suite as passing.

Fresh local artifacts are under
`C:\ProgramData\MinicondaZMB\home\t.de\round3-fullwalk-final`
and `C:\ProgramData\MinicondaZMB\home\t.de\round3-fullwalk-final-proof`.
The repeatable partial-view and three-layer screenshots are under
`C:\ProgramData\MinicondaZMB\home\t.de\round3-partial-final`.
No physical Leica acquisition or Firefox/Edge qualification is claimed.

The root review prompt is retained because the user explicitly requested a
pushed Claude hand-off. The isolated test-port override prevents another clone's
running Vite from silently supplying the tested page. Watched viewer rows still
use coverage; the constant-alpha optimization applies only where the source
contract guarantees dense bounds. These deliberate choices are not claimed fixed.

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
Also set `ACQUISITION_BRIDGE_PORT` to an unused port for the nine-step walk; another
clone's bridge was already listening on its default 8833 during this review.
`ZMART_TEST_BUILT=1` runs the focused transparency spec against the built page.

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
