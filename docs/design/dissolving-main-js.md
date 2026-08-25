# Dissolving `main.js`: the frame keeps the engine, the workflow keeps the run

Status: plan, 2026-08-25. Nothing below is started. Branch
`claude/layered-view-operator-next-gcqxuu`, page at
`workflows/target_acquisition/webapp-ui/`.

## Where it stands

`frame/window/main.js` is 4,483 lines and runs the whole page. Read section
by section, about 70 % of it is the target-acquisition run — focus, detection,
gating, the gallery, the session card, the stage picture and the synthetic
sample — and about 30 % is the engine the folders say the frame is: run state,
the rail, the chooser, tabs, the action bar, the channel and its divider, the
mount lifecycle. The two are interleaved in one module scope: `state`,
`sample`, `view`, `stageCv` and `backend` are module-level singletons that
every section reaches for, and `drawStage` has ~30 call sites.

Three facts are written more than once. The synthetic sample lives in
`main.js` 61–141 **and** in `microscope/pretend-sample/sample.js` (same seeds,
same laws, never imported by the page). Its focus tilt exists a third time in
`microscope/mock.js` 42. `AREA_LO/HI` and `labelColour` are each in two places.

What a step *does* is not `step.run(ctx)` but seven `if`s inside `runStep`
(443–561) keyed on `mode`, and ten more `mode` guards elsewhere (action-bar
hints 422/425, layer visibility 2134/2328/2368/2398, focus pointer
3285–3437, anchors 3464, detect 3477, the Delete key 3978).

`index.html` carries four parked blocks of one workflow's controls
(`#focus-controls`, `#detect-controls`, `#analysis-controls`,
`#gallery-controls`); widgets *move* them into the channel on mount, so
every renderer guards with `isConnected`.

`ARCHITECTURE.md` says all of this in its own words and calls the sample a
live hazard. `docs/design/prototypes/HANDOFF.md` § "The state of the code"
describes a layout (`src/main.js`, `lib/`, `widgets/`) that no longer exists.

## The end state

- `frame/` holds only what runs *any* workflow: run bookkeeping (`wf`,
  `activeIdx`, `done`, `ran`, `running`, `notes`, `tabs`, `tab`, `locked`,
  `failed`, `sideMounted`), the rail, the chooser, tabs, the action bar, the
  channel + divider, the mount lifecycle, backend resolution, the generic
  layer-chip bar. It imports nothing from `workflows/`. Its tests live in
  `frame/tests/`.
- `workflows/target_acquisition/` owns everything else. Each step's controls
  are built by its own `steps/<n>/widget.js` (the carrier and scan-area
  widgets are the pattern: handed a value and a callback, know nothing of run
  state, redraw themselves, export `drawOn`). What several steps share sits in
  `shared/` (the stage picture and its projection, the scale bar). The sample
  sits behind the seam in `microscope/`. Its tests live in
  `workflows/target_acquisition/tests/`.
- The three target-acquisition workflows stay: `_prototype` (pretend
  backend, in the browser), `_mock` (bridge → controller → mock driver),
  `_real` (bridge → controller → Leica). They keep differing only in the
  backend line of `flow.js`.
- `index.html` is the frame's markup and nothing else.
- Each fact has one owner. The page asks the backend what it imaged; it does
  not generate cells itself.

## Rules for every step

1. One extraction per commit, suites green, screenshot looked at.
2. **Tests move with what they test.** A test of frame rules goes to
   `frame/tests/`; a test of a workflow goes into that workflow's `tests/`.
   No new file lands in the top-level `tests/`.
3. A widget redraws itself; never rebuild a panel on input (this defect has
   been produced twice).
4. Something extracted contributes a *layer* to the stage picture; it does
   not draw on `#stage-canvas` directly.
5. If a constant or rule would have to exist twice, stop and merge instead.
6. No `waitForTimeout` in a test touched along the way — wait on the thing
   itself. Untouched stopwatch waits are out of scope.

## The steps, in order

### 0. The tests go home (mechanical, first)

The top-level `tests/` dissolves into three places:

| today | goes to |
|---|---|
| `tests/unit/steps.test.js` (frame rules half) | `frame/tests/steps.test.js` |
| `tests/unit/steps.test.js` (the target-acquisition step assertions) | `workflows/target_acquisition/tests/steps.test.js` |
| `tests/unit/{carriers,plan,scanfields,recordings,surface,sweep,engines,layers-above}.test.js` | `workflows/target_acquisition/tests/` |
| `tests/unit/{brightness,opening-view,planes,what-a-reader-refuses,where-the-specimen-is}.test.js` — these test `viz_studio/options/*.js`, not this page | `viz_studio/options/tests/`, run from the harness there (**decision to confirm**; the alternative is a vitest include that reaches up out of the page) |
| `tests/operator-page.spec.js` tests 1, 2, 13, 14 (rail, chooser, ordering, canvas-and-channel) | `frame/tests/operator-page.spec.js` |
| `tests/operator-page.spec.js` the other 30, `the-scan-under-the-plan`, `live-overview*`, `viewer-*`, `canvas-layers`, helpers `live-run.js`, `pixels.js` | `workflows/target_acquisition/tests/` |

`vitest.config.js` folds into `vite.config.js` with
`include: ["frame/tests/**/*.test.js", "workflows/*/tests/**/*.test.js"]`;
`playwright.config.js` gets `testDir: "."`, `testMatch: "**/tests/**/*.spec.js"`,
`testIgnore: "**/node_modules/**"`, and `outputDir` out of the root.
The browser test that reads the workflow folders keeps doing so from its new
place. *Measured by:* the same counts as before the move — 227 unit, 62
browser.

### 1. `step.run(ctx)` replaces the `mode` arms (frame, no UI change)

Each `steps/<n>/step.js` gains `run(ctx)` holding its arm from `runStep`
(connect 462–491, scan 493–512 + 537–540, focus 523–533, detect 541–546,
select 547, targets 548–553). `runStep` becomes: readiness, `running`,
`await step.run(ctx)`, `done`, note, re-render. `ctx` is
`{ state, actions, backend }` as `ARCHITECTURE.md` already promises. The ten
outlying `mode` guards stay for now and move with their sections in 3–8;
each gets a `// moves with <section>` marker so none is forgotten.
*Measured by:* `frame/tests/steps.test.js` (a step with `run` is called
once, with `ctx`, and `done` follows) + the whole-run walk.

### 2. Run state splits (frame, no UI change)

`state` (223–274) becomes the frame's eleven fields plus `state.run`, an
object the workflow owns: `the-run.js` exports `freshRun()` and the frame
calls it on reset. `resetRun` (314–333) resets the frame's half itself and
calls `freshRun()` for the rest. `rebuildSample`'s side effect of writing
`state.plan` / `window.__plan` becomes an explicit action.
*Measured by:* `frame/tests/steps.test.js` (reset leaves only frame keys) +
"walking back to the carrier takes the plan off the canvas".

### 3. Gallery → `steps/8_acquire_targets/widget.js`

Lines 4368–4459, the widget object 1253–1267, the `targets` arm. Fewest
dependencies: `run.acquired/verdicts`, the cells, `makeRng`; no canvas, no
projection. The widget builds its own markup; `#gallery-controls` leaves
`index.html`. *Measured by:* "one walk of the whole run".

### 4. Gating → `steps/7_refine_targets/widget.js`

Lines 4195–4366, widget 1228–1240, the `select` arm, hint 425. Owns its
scatter canvas and `AREA_LO/HI` (which then has one owner). Its only outward
call is "redraw the stage", which becomes an action. `#analysis-controls`
leaves `index.html`. Add the one missing unit test: the gate predicate.
*Measured by:* the whole-run walk + the new test.

### 5. Detection → `steps/6_discover_targets/widget.js`

Lines 4026–4193, `detectPressed` 3476–3489, the cells layer 2363–2378, the
`detect` arm. `labelColour` gets one owner here. `#detect-controls` leaves
`index.html`. *Measured by:* the whole-run walk; a unit test for `detects`
over a known tile.

### 6. Session → `steps/1_connect/widget.js`

Lines 614–788, `SETUP_CARDS` 1498–1500, the connect arm. Self-contained
markup already; `run.checks` and `run.session` come with it. `answerCheck`
stops reaching rows by `querySelectorAll(".check-row")[k]` and keeps its
row handles. *Measured by:* the five session tests + "the api offered follows
the microscope chosen".

### 7. The stage picture → `shared/stage/`

Lines 1933–2927 minus the focus/detect presses: the view, `carrierOriginUm`,
`fitView`, `toScreen/toWorld`, `drawStageLimits`, the stage mark, the scale
bar (2741–2776), the layer stack and `drawStage`. It exposes: open on a
carrier, add/remove a layer, fit, an `onPress` others subscribe to. Fix the
missing `#stage-layers` host here (the layer bar has never rendered). The
generic layer-chip renderer (2525–2619) stays in the frame.
*Measured by:* tests 16, 19–31 (grid, positions, regions, copy/paste) +
`canvas-layers.spec.js`; a screenshot compared against one taken before.

### 8. Focus → `steps/4_focus_strategy/widget.js`

The largest: 143–176, the focus half of 1037–1116, 1129–1176, 2928–3252,
3254–3458, 3491–4024, layer 2320–2339. It subscribes to the stage's
`onPress` instead of owning the pointer. `PREVIOUS_SURFACES`, the trace and
the z-preview come with it. `#focus-controls` leaves `index.html`, which is
now frame-only. *Measured by:* `surface`, `sweep`, `scanfields` (sharePoints)
unit tests + tests 32–33 + a screenshot of the trace.

### 9. The scan step's live picture → `steps/5_scan_the_overview/`

Lines 1610–1847 (`thePicture`, `liveOverview`, the `?overview/targets/…`
URL switches) join `overview.js`. *Measured by:* `live-overview*.spec.js`,
`the-scan-under-the-plan.spec.js`.

### 10. The sample goes behind the seam (last — 4, 5, 8 all read it)

`main.js` 61–141 + `trueZ` 2938 merge into `microscope/pretend-sample/`;
`mock.js` stops re-deriving the tilt. The prototype workflow's backend
becomes `microscope/mock.js` — which is then misnamed, since "mock" is also
the workflow that goes through the bridge to the controller's mock driver.
**Rename `microscope/mock.js` → `microscope/pretend.js`** to match
`backend: { kind: "pretend" }` (**decision to confirm**). After this the
page never generates a cell; it asks `backend.detect` / `backend.acquire`.
*Measured by:* `plan`, `carriers`, `scanfields` unit tests +
`the-scan-under-the-plan.spec.js` + the whole-run walk.

### 11. The documents describe the tree that exists

`ARCHITECTURE.md` § "Where this stands" table and the sample paragraph;
`HANDOFF.md` § "The state of the code" rewritten from scratch (it describes
a layout three renames ago); `workflows/README.md` gains the tests rule.

## What is deliberately not in this plan

- Replacing every stopwatch wait in the browser suite (rule 6 covers only
  tests touched on the way).
- Register Carrier, the acquisition preset question, `STAGE_LIMITS_MM`, the
  prefilled password — the handoff's open questions; none of them moves.
- `frame/window/main.js` staying as a file: after 10 it should be a few
  hundred lines of engine and can keep its name.

## Order, in one line

Tests home → `run(ctx)` → state split → gallery → gating → detection →
session → stage → focus → live picture → sample → docs. The two frame steps
go first because they are contained and touch no UI (the handoff's own
advice); the widgets go smallest-dependencies first so the pattern is
proven on the cheap ones before the focus step, which is the only one that
shares a pointer with the stage.
