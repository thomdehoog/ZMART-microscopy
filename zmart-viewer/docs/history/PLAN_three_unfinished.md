# What is left on the canvas, after 3 August 2026

Branch `viewer-plus-scanfields`. Revised four times: written, reviewed twice,
partly executed, reviewed twice again. Each round found something the round
before had asserted confidently and wrongly, including in this document. Read
the corrections as seriously as the instructions.

> **Before anything: most of what follows describes a working tree, not the
> branch.** HEAD is `30dd92f`. The two-column page, the view sync and the removal
> of `viv-inside` from the page exist only as uncommitted edits to `index.html`,
> `src/canvas/engines.js`, `src/main.js`, `src/style.css` and
> `tests/unit/engines.test.js`. Clone the branch and you get the three-column page
> and none of this makes sense. **Commit first.**

---

## How to run anything

Neither the environment nor the commands were in earlier drafts, and both are
traps.

* **Use `zmart-viz`.** It has zarr and Playwright. `zmart-microscopy` has
  neither — it is the env with node, and it is the one the documents still tell
  you to use.
* `zmart-viewer/tests/conftest.py` reads `PLAYWRIGHT_BROWSERS_PATH` and does **not**
  default it, unlike the webapp's config which does. Browsers are at
  `C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright`. Unset, the browser tests
  skip silently — set `ZMART_REQUIRE_BROWSER=1` so a skip fails instead.
* The browser suite spawns `process.env.PYTHON ?? "python"` to write its demo run.
  Plain `python` here has no zarr, so the run never starts and every test that
  needs it times out in `beforeAll`. Point `PYTHON` at `zmart-viz`.
* **Rebuild the harness bundle before every zmart-viewer run.**
  `zmart-viewer/parked/harness/dist/` is gitignored and `run_tests.py` builds it
  *only if it is missing* — there is no staleness check, unlike the one guarding
  `app/page/dist`. Editing either `viewer.js` or the harness and then running the
  suite measures the old bundle and reports confidently wrong numbers. That
  failure has already cost this project a session once.
  `npm --prefix zmart-viewer/parked/harness run build`.
* Commands: `cd zmart-viewer && python run_tests.py` (~20 min);
  `npm test` in `workflows/target_acquisition/webapp-ui` (unit ~0.3 s, browser
  ~8–30 min).

Two roots. Items about the page live in
`workflows/target_acquisition/webapp-ui/`; items about the engines and the
harness live in `zmart-viewer/`.

---

## Done, and what that is actually worth

**`6c54c81` — two real bugs.** `viv-under` asked Viv for a `t` axis on stores
declaring only `z, y, x`, so every read was refused while the page reported
itself content. Both Viv readers took an image's position from the
multiscales-level transform only and ignored the per-dataset one, so a foreign
store drew at the stage's zero and a multi-tile transfer stacked every tile.

**Neither fix has a regression test, and an earlier draft of this document said
they were "verified against a real 120 GB transfer: 5 passed". That was wrong.**
`test_real_mesospim_data.py` contains no reference to `viv-under`, `viv-inside`
or `parked/`; four of its tests read metadata with `json.loads`, and the fifth
drives `window.zmartViewer` — the standalone `zmart-viewer` frontend, a different
viewer. It opens one tile, so it could not detect stacking even in principle.

What the fixes actually rest on: the `Invalid indexer key: t` errors disappearing
from the console and `viv-under` beginning to draw, and the readout moving to the
store's absolute position (`30261, 72034 µm`) from tile-local (`1426, 2534`).
Both observed on real data through the operator page. **Smoke-checked, not
verified.**

**`30dd92f` — the run server answers more than one caller.** `HTTPServer`
serialises; with two viewers on a network drive it starved neuroglancer until it
gave up and looked broken. `ThreadingHTTPServer` is sufficient — `_control()`
returns false, so the demo's one piece of shared state is unreachable. It does
spell threading a second way rather than importing the `Server` class in the file
it says it borrows from; and `live_overview_demo.py` was already threaded, so an
earlier draft's worry about its accept queue was unfounded.

**Uncommitted: the view sync.** `whenShown` now resolves to the canvas handle,
which it did not, so `canvas.view` was always `undefined` and the sync returned
before doing anything. Measured: both columns at 19.50 µm/px, where neuroglancer
sat at 1.10. The once-only state is per column, and a column is recorded **only
once the move has actually landed** — recording it regardless stranded any column
that opened late, which is the single case the mechanism exists for, and that bug
was in this code for an hour.

**Uncommitted: `viv-inside` off the page.** Five files, not the four an earlier
draft claimed. Functionally clean; editorially half-done — see item 4.

---

## The order, and why the previous one was wrong

An earlier draft put `imagedBounds` first, on the grounds that it is small and
needs no decisions, and worried it would move the specs' thresholds.

**Both were wrong, for one reason: `src/canvas/panel.js:396` passes
`coverage: null`.** Both engines gate on `boundToCoverage && coverage?.regions?.length`,
so `imagedBounds` is never called on the operator page. It cannot move a spec
threshold, and it cannot help the page. It is a harness-only fix and it goes last.

What actually moves the thresholds is the page's shape — two columns at half
width, neuroglancer opening twenty times further out — plus the decisions below.
Those are the real predecessors of the spec rework.

0. **Commit the working tree.**
1. **Settle the decisions and make the page-shape edits.**
2. **The specs** — rewritten once, thresholds measured once. The only red-to-green
   on the page this plan is about.
3. **The stale prose**, in the same pass, or the line numbers drift under it.
4. **The foreign store** — separate tree, rebuild the bundle first.
5. **Brightness.**
6. **`imagedBounds`.**

---

## 1. Decisions, which block everything else

1. **The `file://` heading.** Off the disk, neuroglancer is not offered,
   `panel.js` falls back to `built[0]`, and the column heading is hard-coded — so
   a built page opened by double-clicking shows two identical viv-under pictures,
   one headed `neuroglancer-under`. Either the heading follows what the column
   opened with, or the column says the engine it was asked for is unavailable.
2. **Generate the columns from `enginesOnOffer()`?** The engine list lives in four
   places and `engines.js` still promises "adding an engine is one line".
3. **Delete the hidden chooser markup?** Still built on every open. Keeping
   `changeTo` on the handle is defensible — it belongs to the interface — but dead
   markup is what tempts a test into counting buttons no operator can reach.
   (Deleting it frees no CSS: the rule is the generic `.seg[hidden]`.)
4. **What `?engine=` means now.** It currently overrides *both* columns at once,
   which destroys the point of the layout. Both specs use it as their only way to
   choose an engine, and `viewer-built.spec.js` needs it to produce the "was asked
   for and is not here" note. Kill it, make it per-column, or keep it as a
   both-columns override. **This blocks the specs as hard as decision 1.**
5. **Brightness** — see item 5.
6. **`harness.square`: one field with a flag, or `imagedSquare` +
   `declaredSquare`.** Two is better, but note it is not only about the guard:
   four sites must each be told which they want, and the answers differ —
   `fitTheImagedGround` wants declared-or-imaged, the two margin drawings want
   imaged, and a test reads `window.harness.square` from the browser.
7. **Retire `viv-inside` in `zmart-viewer` too, or leave it?** It is out of the
   page. `EVERY_OPTION` still parametrises three, so every foreign-store run costs
   three options rather than two. If retired, keep its `parked/RESULTS.md` column with a
   note — those measurements are the evidence for the choice being made.

## 2. The specs

Both are stale, and this is a **rewrite, not a re-selection**. Four tests do not
survive: the one clicking `data-engine="viv-inside"`; the one asserting three
chooser buttons; `untilTheEngineIsDrawing`, which waits on `aria-checked` on that
chooser and is the wait mechanism for *every* test in the file; and
`viewer-built.spec.js`'s serial engine loop, which has no meaning once columns are
fixed.

Wait on the column's own note for `` `${engine} — ` ``. **Not** on the engine's
description alone — viv-under's sentence is a strict prefix of neuroglancer's.

Re-measure `THE_WASH_IS_THERE`, `THE_LATTICE_IS_THERE`, `A_LAYER_IS_ABSENT`.
Halved box width and a 20× zoom change move all three.

Consolidate or the suite is unusable: `workers: 1`, `fullyParallel: false`, every
test now opens two engines, and `fullestPictureOf` photographs each box every
700 ms for ten seconds. "Both engines' Beneath in one photograph" *is* the two
layer tests merged.

**Add the test the newest code does not have.** `theViewTheyShare` /
`alreadyPutOnIt` and the failure path were measured by hand and by nothing else.
Two readout reads pin the shared view; one case where a column fails to open and
the other still gets a view pins the bug that was in it for an hour. Cheapest real
gain here.

## 3. Prose that is now false

Name sections, not line numbers — they drift. Includes text an operator reads
(`steps.js`'s `why`: the engines "draw the same scene in turn"), the document a
human follows at the microscope (`TESTING_ON_REAL_HARDWARE.md`, wrong about the
chooser *and* about the environment), `webapp-ui/README.md` (false well beyond
the two-steps section — also the three-engines comparison, the "92% of the box",
"two of the three engines"), `docs/how_it_works/ARCHITECTURE.md`, `panel.js`, `workflows/index.js`,
`engines.js` ("all three engines are offered"), and a unit test still *titled*
"carries all three engines" while asserting two. `zmart-viewer/TESTING.md` names a
conda env that does not exist — fix it in the same pass as the other environment
correction.

## 4. The foreign store, committed red

Two independent defects.

**The harness refuses a store with no imaged regions**, though `parked/contract.md`
permits `coverage: null`. Scope the guard by **where the hole comes from**, not by
`draw=`: `carrier` and any unrecognised value take it from `coverage.regions` and
are genuinely broken; `margin` — *the default when `draw=` is absent* — takes it
from `harness.square` and is fine once that has a source; `none` and
`threeLayers` cut no holes.

`harness.square` needs the declared extent: add it to `/api/coverage`, as a **box**
`{x0,y0,x1,y1}`, shape from the first dataset's `.zarray`, mapped by axis name.
Server-side, because `origin_um` there already composes both transform levels.
**But note `voxel_size_um` beside it reads only the inner scale and returns `{}`
when axes declare no unit — an extent built on it inherits both gaps.** The
`foreign` store happens not to hit either, so this would ship green and silent.

Mapping `recorded:false → null` **fixes nothing** — every engine already gates on
`regions?.length`. And the guard also fires for `recorded:true, regions:[]`, one
of *our* runs before its first tile lands.

**The threshold is unreachable**: `> 0.2` against an opening fit that spans 245 px
of a 900×700 window ≈ 9.5%. Lower it, or fill the window — but **test-locally with
`harness.setView`**; changing `fitTheImagedGround` moves the starting view of
every measurement in `parked/RESULTS.md`.

The store is filled solid, so the range read returns null — you cannot range a
constant — and falls back to 0–4095, which is why it is visible at all. "Fixing"
that ternary turns it black.

## 5. Brightness

`viv-under` reads the range from the smallest copy when nobody said anything.
`neuroglancer-under` cannot: no Viv loader, and its `normalized` control defaults
to the *data type's* range, so omitting it on uint16 gives 0–65535 — worse.

This ranks above `imagedBounds` because it changes what an operator sees on a
foreign store; `imagedBounds` changes nothing on the page.

Options: the page supplies the window (one mechanism, both engines, ~15 lines —
an earlier attempt was reverted for passing a colour as a hex string where three
numbers are required, which is a warning about care, not about the approach); or
a real contrast control; or a third reader inside neuroglancer, which duplicates
what Viv already does and is argued against. **An earlier draft cited
`docs/how_it_works/CONTROLS.md` for the contrast control; that file does not mention contrast. The
real statements are in `parked/contract.md` and `docs/open/NEXT_STEPS.md`.**

## 6. `imagedBounds` ignores the origin

`neuroglancer-under` and `viv-under` multiply coverage regions by voxel size and
never add `origin_um`; the harness's `imagedRegions` does. Both work in stage
micrometres, so they disagree. `viv-inside` was immune — it worked in the store's
own voxel frame.

**Never reached on the operator page** (`coverage: null`). Only two stores declare
a non-zero origin and both are opened `bounded="0"`, so **no existing test and no
row of `parked/RESULTS.md` changes when this is fixed** — it needs a new check
(`store=detail` alone, bounding at default) or an explicit "read-verified only".

Not as local as it looks: `imagedBounds` feeds `fitTheEngineToItsPatch` →
`engineRect` → `howFarThePatchIsOffCentre` → the reported centre and every
projected shape. And both files state the rule in the code being edited — these
five helpers are word-for-word shared, so **change both in the same commit**.

Adjacent and unaddressed: the harness hands the engine **one** coverage record
while computing `harness.square` across both acquisitions, so with survey+detail
and bounding on, the patch still excludes the detail scan after this is fixed.
Decide whether that is in scope.
