import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { colourSpread, fractionLit, photograph } from "./pixels.js";
import { SHOTS, rest, startDemoRun } from "./live-run.js";

/* Does the canvas really draw, inside the real operator window?
 *
 * The canvas is the picture of a run that an operator pans and zooms. It is
 * being built separately, once for each of several drawing engines, all behind
 * one small interface, and the workflow these tests drive is the first place it
 * is put inside the operator window: one workflow, one step, nothing else in it.
 *
 * The question worth asking about a picture is a question about pixels, so that
 * is what is measured here. The box the canvas draws in is photographed and the
 * photograph is measured — how much of it is showing specimen rather than
 * nothing, and how much variety there is in it. Nothing else is asserted. Not
 * that a canvas element exists, not that a loader resolved, not that the console
 * stayed quiet. A viewer that reports itself perfectly loaded while drawing
 * nothing has happened in this project more than once, and every one of those
 * checks passed while it did.
 *
 * The run being drawn is written by the project's own writer; see `live-run.js`.
 *
 * Making sure it can fail
 * -----------------------
 *
 * A test that cannot go red is worse than no test. Set
 * `LIVE_OVERVIEW_SABOTAGE=stalled` and the demo writes no tile at all, which is
 * what an acquisition that never started looks like from here: the page still
 * opens the run, the box is still there, the engine still reports itself
 * content, and the picture stays black. The measurements below then fail, which
 * is the proof that they are reading the picture rather than the plumbing.
 */

const PORT = Number(process.env.VIEWER_WORKFLOW_PORT ?? 8791);

/* What the numbers have to reach. They sit a long way below what a drawn picture
   actually measures — around 0.99 lit, some two hundred distinct colours — and a
   long way above what an empty box measures, which is nothing lit, one colour,
   and no spread at all. Being far from both is what stops them from being fussy
   about the exact shade an engine happens to draw. */
const ENOUGH_OF_IT_LIT = 0.5;
const ENOUGH_DIFFERENT_COLOURS = 50;
const NOT_ALL_ONE_COLOUR = 0.2;

let run = null;

test.beforeAll(async () => { run = await startDemoRun({ port: PORT }); });
test.afterAll(() => { run?.stop(); });

/** Open the page on the run, and choose the workflow that is only the canvas. */
async function standOnTheViewerStep(page, { engine = null } = {}) {
  const asked = new URLSearchParams({ overview: run.store });
  if (engine) asked.set("engine", engine);
  await page.goto(`/?${asked}`);
  await page.selectOption("#wf-select", "viewer_only");
  // The engine is fetched when this step is first opened rather than on load, so
  // there is a moment here before anything can be drawn.
  await expect(page.locator("#panel-viewer")).toHaveClass(/\bon\b/);
}

/**
 * Watch the box for a few seconds and keep the fullest photograph of it.
 *
 * A single photograph is not a fair measure: a picture part way through fetching
 * its pieces is honestly half drawn. The fault only goes one way, though — there
 * is nothing on screen that was not read from the run — so the fullest of
 * several moments is the honest answer to "is it drawing", and it cannot flatter
 * an engine that draws nothing, because the fullest of several blank photographs
 * is still blank.
 */
async function fullestPictureOf(page, name, { seconds = 10 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const pixels = await photograph(page, "#viewer-box", 0.5);
    const lit = fractionLit(pixels);
    if (!best || lit > best.lit) {
      best = { lit, ...colourSpread(pixels) };
      best.shot = await page.locator("#viewer-box").screenshot();
    }
    await rest(700);
  } while (Date.now() < until);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), best.shot);
  delete best.shot;
  return best;
}

/** What a photograph has to show before we will call it a picture. */
function itIsReallyDrawing(measured, whichEngine) {
  expect(measured.lit, `${whichEngine}: share of the box showing picture`)
    .toBeGreaterThan(ENOUGH_OF_IT_LIT);
  expect(measured.distinct, `${whichEngine}: how many different colours are in it`)
    .toBeGreaterThan(ENOUGH_DIFFERENT_COLOURS);
  expect(measured.dominantFraction, `${whichEngine}: share taken by one flat colour`)
    .toBeLessThan(NOT_ALL_ONE_COLOUR);
}

test("the canvas draws the run, and a photograph of it says so", async ({ page }) => {
  test.setTimeout(180_000);

  await standOnTheViewerStep(page);
  await run.acquire(25);

  const measured = await fullestPictureOf(page, "viewer-workflow-viv-under");
  console.log(
    `the canvas drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours, spread ${measured.spread.toFixed(1)}`,
  );
  itIsReallyDrawing(measured, "viv-under");
});

test("the same run, drawn by the other engine, from the same view", async ({ page }) => {
  test.setTimeout(180_000);

  await standOnTheViewerStep(page);
  await run.acquire(25);
  await fullestPictureOf(page, "viewer-workflow-before-the-change", { seconds: 6 });

  const before = await page.locator("#viewer-readout").textContent();
  await page.locator('#viewer-engine button[data-engine="viv-inside"]').click();
  await expect(page.locator('#viewer-engine button[data-engine="viv-inside"]'))
    .toHaveAttribute("aria-checked", "true");

  const measured = await fullestPictureOf(page, "viewer-workflow-viv-inside");
  console.log(
    `the other engine drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours`,
  );
  itIsReallyDrawing(measured, "viv-inside");

  /* Changing engine has to keep the view. Two ways of drawing the same thing can
     only be compared if the second one is looked at from where the first one
     was; a difference of half a pixel is invisible if reaching the second
     picture means finding your way back. */
  expect(await page.locator("#viewer-readout").textContent()).toBe(before);
});

test("the same run again, drawn by neuroglancer, from the same view", async ({ page }) => {
  test.setTimeout(180_000);

  /* The third engine is the one this project is most likely to ship, and it is
     also the one that cannot live inside the page: it hands the fetching and
     unpacking of image pieces to background programs, which a browser will only
     start from files of their own. `src/canvas/engines.js` explains what that
     costs. What matters here is only the question a photograph can answer —
     given a page served the way an operator will be served it, does the third
     engine put a picture on the screen? The built page is checked separately, in
     `viewer-built.spec.js`, because how the page is delivered is exactly what
     this engine is sensitive to. */
  await standOnTheViewerStep(page);
  await run.acquire(25);
  await fullestPictureOf(page, "viewer-workflow-before-neuroglancer", { seconds: 6 });

  const before = await page.locator("#viewer-readout").textContent();
  await page.locator('#viewer-engine button[data-engine="neuroglancer-under"]').click();
  /* A generous wait, and it is not papering over anything. The button is marked
     as the chosen one once the engine has actually opened, not when it is
     pressed — so this is waiting for neuroglancer to load. It is a large engine,
     and the development server hands a page its pieces one file at a time, so
     the first time it is asked for it can take the better part of a minute. The
     built page, where everything arrives in one piece, does it in a couple of
     seconds; `viewer-built.spec.js` waits the ordinary amount and passes. */
  await expect(page.locator('#viewer-engine button[data-engine="neuroglancer-under"]'))
    .toHaveAttribute("aria-checked", "true", { timeout: 90_000 });

  const measured = await fullestPictureOf(page, "viewer-workflow-neuroglancer-under");
  console.log(
    `neuroglancer drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours`,
  );
  itIsReallyDrawing(measured, "neuroglancer-under");

  // The view has to survive the change, the same as it does between the other two.
  expect(await page.locator("#viewer-readout").textContent()).toBe(before);
});

test("the chooser offers every engine the page was built with, and no others", async ({ page }) => {
  /* Served over HTTP, which is how an operator meets the page, all three can
     draw and all three are offered. The point of this test is the "no others"
     half: a button for an engine the page cannot open would draw nothing, and a
     box that never fills looks exactly like one that is still loading. The same
     rule is checked from the other side, without a browser, in
     `tests/unit/engines.test.js`. */
  await standOnTheViewerStep(page);

  const offered = await page.locator("#viewer-engine button").allTextContents();
  expect(offered).toEqual(["viv-under", "viv-inside", "neuroglancer-under"]);
});

test("the step gives the whole window to the picture", async ({ page }) => {
  await standOnTheViewerStep(page);

  // One module, so one tab, and it is the picture.
  await expect(page.locator("#tabs .tab")).toHaveCount(1);
  await expect(page.locator("#tabs .tab")).toHaveText("Viewer");
  // Nothing docked down the right-hand side, and nothing to press.
  await expect(page.locator("#canvas-side")).toBeHidden();
  await expect(page.locator("#panel-viewer button.step-run")).toHaveCount(0);
  // One step in the rail, and the workflow is named in plain words.
  await expect(page.locator(".step")).toHaveCount(1);
  await expect(page.locator(".step")).toContainText("Look at the run");
});
