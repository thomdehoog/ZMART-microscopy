# Review prompt: dissolving `main.js`

Paste to an external reviewer together with `docs/design/dissolving-main-js.md`,
`application/ARCHITECTURE.md`, and read access to
`application/framework/window/main.js` (4,483 lines).

---

You are reviewing a refactoring plan for a browser page that drives a
microscope. The page has an engine (`frame/`) meant to run any workflow, and
one workflow (`application/workflows/target_acquisition/`) that today mostly lives inside
the engine's 4,483-line `main.js`. The plan moves the workflow out in eleven
commits. Read the plan, then `main.js`, and answer these — cite line numbers.

1. **Is the frame/workflow line drawn in the right place?** For each section
   the plan calls FRAME, say whether a second workflow (an analysis workflow
   that never touches a microscope) would need it. For each it calls
   WORKFLOW, say whether anything generic is being buried in the workflow.
   The stage picture (step 7 → `shared/stage/`) and the recordings UI
   (789–1035, unassigned) are the two you should argue hardest about.

2. **Does step 1 (`step.run(ctx)`) hold?** The plan leaves ten `mode` guards
   in place to move later. Find any guard whose section is extracted in a
   *later* step than the one that would break it — i.e. an order bug.

3. **Does step 2 (state split) break a test?** The browser tests reach into
   `window.__plan` and `window.__theStageCanvas`. Which tests, and does the
   plan say what happens to those hooks?

4. **Is the extraction order right?** The plan goes gallery → gating →
   detection → session → stage → focus → live picture → sample. Give a
   counter-order with a reason, or say why this one stands. In particular:
   should the stage (7) come *before* the cheap widgets (3–5), since 4 and 5
   each contribute a layer to it?

5. **Where would a fact end up written twice?** The plan claims one owner
   each for the sample, its tilt, `AREA_LO/HI`, `labelColour`. Check
   `microscope/pretend-sample/sample.js`, `microscope/mock.js` and `main.js`
   and say whether step 10 actually closes all four, and what the prototype
   backend's `detect`/`acquire` must return for the page to stop generating
   cells itself.

6. **The two decisions marked "to confirm":** (a) the five unit tests of
   `viz_studio/options/*.js` moving out of this page's tree; (b) renaming
   `microscope/mock.js` → `pretend.js`. Recommend, with one reason each.

7. **What is missing?** Anything in `main.js` the plan does not assign
   (say the lines), and anything the plan assigns that is not actually in
   `main.js`.

Answer as a numbered list. Findings that would change the order or the
boundary first; style last. Do not propose additional features.
