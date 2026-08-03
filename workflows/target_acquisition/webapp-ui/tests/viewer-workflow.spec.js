import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { colourSpread, fractionLit, fractionNear, photograph } from "./pixels.js";
import { SHOTS, rest, startDemoRun } from "./live-run.js";
import {
  THE_COLOUR_ABOVE, THE_COLOUR_BENEATH,
} from "../src/canvas/demonstration-drawings.js";

/* Does the canvas really draw, and do its three layers really behave, inside the
 * real operator window?
 *
 * The canvas is the picture of a run that an operator pans and zooms. It is
 * being built separately, once for each of several drawing engines, all behind
 * one small interface, and the workflow these tests drive is where it is put
 * inside the operator window and watched: two steps, one drawing with Viv and
 * one with neuroglancer, each with a button for the layer beneath the picture,
 * the picture itself, and the layer above it.
 *
 * The question worth asking about a picture is a question about pixels, so that
 * is what is measured here. The box is photographed and the photograph is
 * measured — how much of it is showing specimen rather than nothing, how much
 * variety there is in it, and how much of it is each of the two colours the
 * page's own layers are drawn in. Nothing else is asserted. Not that a button
 * exists, not that it reports itself pressed, not that a loader resolved. A
 * viewer that reports itself perfectly loaded while drawing nothing has happened
 * in this project more than once, and every one of those checks passed while it
 * did.
 *
 * The colours the layers are drawn in come from the page's own declaration of
 * them rather than being written out again here, so a colour that changed on
 * screen cannot leave a test quietly passing against the old one.
 *
 * The run being drawn is written by the project's own writer; see `live-run.js`.
 *
 * ## The one thing these tests found that is worth more than the tests
 *
 * Turning the picture off means opening the canvas with no acquisitions at all,
 * which is what an operator sees before a run has started. Two of the three
 * engines do it in a fraction of a second. Neuroglancer never finishes opening
 * at all — measured below, from the page, not from a reading of the code. That
 * is a gap in the interface rather than a fault of this page, so the test here
 * pins the behaviour an operator meets: the page waits, gives up, says plainly
 * what happened, and puts the working picture back.
 *
 * ## Making sure it can fail
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

/* What counts as a layer being on screen, and what counts as it being absent.
   The two drawings cover very different amounts of the box, so they are given
   their own numbers rather than one that suits neither: the layer beneath is a
   flat wash over everything the picture does not cover, and the layer above is
   a lattice of thin lines that comes to a few per cent. Measured, they are about
   90% and about 4%, and a layer that is off measures nothing at all. Every one
   of these sits a long way from what is actually measured, so a result landing
   between them would be something to look at by hand rather than something these
   numbers should be tuned to. */
const THE_WASH_IS_THERE = 0.3;
const THE_LATTICE_IS_THERE = 0.015;
const A_LAYER_IS_ABSENT = 0.002;

/** Which panel belongs to each of the two steps, and what that step is called. */
const STEPS = {
  viv: { at: 0, engine: "viv-under", title: /drawn by Viv/ },
  neuroglancer: { at: 1, engine: "neuroglancer-under", title: /drawn by neuroglancer/ },
};

const boxOf = (which) => `#viewer-${which}-box`;
const layerButton = (which, layer) => `#viewer-${which}-layers button[data-layer="${layer}"]`;

let run = null;

test.beforeAll(async () => { run = await startDemoRun({ port: PORT }); });
test.afterAll(() => { run?.stop(); });

/**
 * Open the page on the run and stand on one of the demonstration's two steps.
 *
 * The step is reached by clicking it in the rail, exactly as an operator would,
 * rather than by asking the page to show a panel. That matters for the second
 * step: nothing has been done in the first one, so if the two steps were not
 * genuinely independent the second would be greyed out and this would fail here.
 */
async function standOn(page, which, { engine = null } = {}) {
  const asked = new URLSearchParams({ overview: run.store });
  if (engine) asked.set("engine", engine);
  await page.goto(`/?${asked}`);
  await page.selectOption("#wf-select", "canvas_layers");
  await page.locator(".step").nth(STEPS[which].at).click();
  // The engine is fetched when a step is first opened rather than on load, so
  // there is a moment here before anything can be drawn.
  await expect(page.locator(`#panel-viewer-${which}`)).toHaveClass(/\bon\b/);
}

/** Wait until the picture has opened and the engine has said which it is. */
async function untilTheEngineIsDrawing(page, which, name, { timeout = 90_000 } = {}) {
  await expect(page.locator(`#viewer-${which}-engine button[data-engine="${name}"]`))
    .toHaveAttribute("aria-checked", "true", { timeout });
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
async function fullestPictureOf(page, which, name, { seconds = 10 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const pixels = await photograph(page, boxOf(which), 0.5);
    const lit = fractionLit(pixels);
    if (!best || lit > best.lit) {
      best = { lit, ...colourSpread(pixels) };
      best.shot = await page.locator(boxOf(which)).screenshot();
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

/**
 * How much of the box is one of the page's own layer colours, right now.
 *
 * Kept to a couple of seconds and to the fullest of a few moments, for the same
 * reason as above: a layer is repainted in step with the picture, so a
 * photograph taken between two frames can catch it half drawn.
 */
async function howMuchOfTheBoxIs(page, which, colour, { seconds = 3 } = {}) {
  const until = Date.now() + seconds * 1000;
  let most = 0;
  do {
    most = Math.max(most, fractionNear(await photograph(page, boxOf(which), 0.5), colour));
    await rest(400);
  } while (Date.now() < until);
  return most;
}

/** Keep a photograph of the box, so a failure can be looked at rather than read. */
async function keep(page, which, name) {
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), await page.locator(boxOf(which)).screenshot());
}

/**
 * Zoom out until the picture is a small thing in the middle of the box.
 *
 * The layer beneath the picture is only ever seen where the picture is not, and
 * a canvas opened on a run is framed to fill itself with the run — so at the
 * magnification it opens on there is nothing for a layer beneath to show
 * through. Zooming out is what makes room to see it, which is exactly what an
 * operator does, and it is done here with the wheel rather than by asking the
 * page to move: the wheel is the gesture the operator has, and using it means
 * these measurements also depend on it still working.
 */
async function zoomOutABitWithTheWheel(page, which, notches = 5) {
  const box = await page.locator(boxOf(which)).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < notches; i += 1) {
    await page.mouse.wheel(0, 300);
    await rest(120);
  }
  await rest(900);
}

test("the first step opens with Viv, and a photograph says it drew the run", async ({ page }) => {
  test.setTimeout(180_000);

  await standOn(page, "viv");
  await untilTheEngineIsDrawing(page, "viv", STEPS.viv.engine);
  await run.acquire(25);

  const measured = await fullestPictureOf(page, "viv", "canvas-layers-viv-under");
  console.log(
    `the Viv step drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours, spread ${measured.spread.toFixed(1)}`,
  );
  itIsReallyDrawing(measured, "viv-under");
});

test("the second step opens with neuroglancer, without the first having been touched",
  async ({ page }) => {
    test.setTimeout(180_000);

    /* Straight to the second step, having done nothing in the first. The two
       steps produce nothing, so neither can be waiting on the other, and an
       operator may open either one first. If that rule were lost the click below
       would land on a disabled step and this would fail before a pixel was
       measured. */
    await standOn(page, "neuroglancer");
    await untilTheEngineIsDrawing(page, "neuroglancer", STEPS.neuroglancer.engine);
    await run.acquire(25);

    // The first step's picture was never opened, so its box is still empty.
    expect(await page.locator("#viewer-viv-box canvas").count()).toBe(0);

    const measured = await fullestPictureOf(
      page, "neuroglancer", "canvas-layers-neuroglancer-under");
    console.log(
      `the neuroglancer step drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
        `${measured.distinct} distinct colours`,
    );
    itIsReallyDrawing(measured, "neuroglancer-under");
  });

test("the layer above the picture comes and goes with its button", async ({ page }) => {
  test.setTimeout(180_000);

  await standOn(page, "viv");
  await untilTheEngineIsDrawing(page, "viv", STEPS.viv.engine);
  await run.acquire(25);

  const before = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_ABOVE);
  await page.locator(layerButton("viv", "above")).click();
  const during = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_ABOVE);
  await keep(page, "viv", "canvas-layers-above-on");
  await page.locator(layerButton("viv", "above")).click();
  const after = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_ABOVE);

  console.log(
    `the layer above: ${(before * 100).toFixed(2)}% of the box before, ` +
      `${(during * 100).toFixed(2)}% while on, ${(after * 100).toFixed(2)}% after`,
  );
  expect(before, "the layer above, before its button was pressed").toBeLessThan(A_LAYER_IS_ABSENT);
  expect(during, "the layer above, while its button was on")
    .toBeGreaterThan(THE_LATTICE_IS_THERE);
  expect(after, "the layer above, after its button was pressed again")
    .toBeLessThan(A_LAYER_IS_ABSENT);
});

test("the layer beneath the picture appears under Viv", async ({ page }) => {
  test.setTimeout(180_000);

  await standOn(page, "viv");
  await untilTheEngineIsDrawing(page, "viv", STEPS.viv.engine);
  await run.acquire(25);
  await zoomOutABitWithTheWheel(page, "viv");

  const before = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_BENEATH);
  await page.locator(layerButton("viv", "beneath")).click();
  const during = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_BENEATH);
  await keep(page, "viv", "canvas-layers-beneath-under-viv");

  console.log(
    `the layer beneath, under Viv: ${(before * 100).toFixed(2)}% of the box before, ` +
      `${(during * 100).toFixed(2)}% while on`,
  );
  expect(before, "the layer beneath, before its button was pressed")
    .toBeLessThan(A_LAYER_IS_ABSENT);
  expect(during, "the layer beneath, while its button was on")
    .toBeGreaterThan(THE_WASH_IS_THERE);

  // And the page does not warn about something that is working perfectly well.
  expect(await page.locator("#viewer-viv-why").textContent()).not.toMatch(/cannot/);
});

test("the layer beneath the picture does not appear under neuroglancer, and the page says why",
  async ({ page }) => {
    test.setTimeout(180_000);

    /* This is the one real difference between the three engines, and the whole
       reason the demonstration has two steps. Neuroglancer forces its canvas
       opaque at the end of every frame, so a drawing placed behind it is never
       seen. It is not hidden and it is not worked around — the drawing is handed
       to the slot it belongs in, the engine covers it, and the page puts the
       engine's own sentence about it beside the button. */
    await standOn(page, "neuroglancer");
    await untilTheEngineIsDrawing(page, "neuroglancer", STEPS.neuroglancer.engine);
    await run.acquire(25);
    await zoomOutABitWithTheWheel(page, "neuroglancer");

    await page.locator(layerButton("neuroglancer", "beneath")).click();
    await expect(page.locator(layerButton("neuroglancer", "beneath")))
      .toHaveAttribute("aria-pressed", "true");
    const during = await howMuchOfTheBoxIs(page, "neuroglancer", THE_COLOUR_BENEATH);
    await keep(page, "neuroglancer", "canvas-layers-beneath-under-neuroglancer");

    console.log(
      `the layer beneath, under neuroglancer: ${(during * 100).toFixed(2)}% of the box ` +
        "while on",
    );
    expect(during, "the layer beneath, under an engine that cannot show it")
      .toBeLessThan(A_LAYER_IS_ABSENT);

    /* And an operator is told why, in the engine's own words, next to the button
       they just pressed. A button that appears to do nothing teaches somebody
       that the page is broken; a reason beside it teaches them something true
       about the engine. */
    const said = await page.locator("#viewer-neuroglancer-why").textContent();
    console.log(`the page said: ${said}`);
    expect(said).toMatch(/cannot|will not/);
    // The engine's own words, not a sentence this page made up about a name it
    // recognised. These are the two phrases the engine uses to say what it does.
    expect(said).toMatch(/forces the whole of its canvas opaque/);
    expect(said).toMatch(/nothing placed behind it is ever seen/);

    // The layer above works on this engine, which is what makes the one above a
    // statement about the bottom slot rather than about drawing in general.
    await page.locator(layerButton("neuroglancer", "above")).click();
    const above = await howMuchOfTheBoxIs(page, "neuroglancer", THE_COLOUR_ABOVE);
    console.log(`the layer above, under neuroglancer: ${(above * 100).toFixed(2)}%`);
    expect(above, "the layer above, under neuroglancer").toBeGreaterThan(THE_LATTICE_IS_THERE);
  });

test("turning the picture off leaves the operator's own drawing on screen", async ({ page }) => {
  test.setTimeout(180_000);

  /* Opening the canvas with no acquisition at all is what an operator sees
     before a run has started, laying positions out on an empty plate. What has
     to survive it is the operator's own drawing: the picture goes, and the
     things the operator put above and below it stay exactly where they were. */
  await standOn(page, "viv");
  await untilTheEngineIsDrawing(page, "viv", STEPS.viv.engine);
  await run.acquire(25);

  await page.locator(layerButton("viv", "above")).click();
  await page.locator(layerButton("viv", "beneath")).click();

  const withThePicture = await fullestPictureOf(
    page, "viv", "canvas-layers-picture-on", { seconds: 3 });

  await page.locator(layerButton("viv", "picture")).click();
  await expect(page.locator(layerButton("viv", "picture")))
    .toHaveAttribute("aria-pressed", "false", { timeout: 40_000 });
  await rest(1500);

  const above = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_ABOVE);
  const beneath = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_BENEATH);
  const withoutIt = await fullestPictureOf(
    page, "viv", "canvas-layers-picture-off", { seconds: 3 });

  console.log(
    `with no acquisition: the layer above covers ${(above * 100).toFixed(2)}% and the ` +
      `layer beneath ${(beneath * 100).toFixed(1)}% of the box; the box holds ` +
      `${withoutIt.distinct} distinct colours, against ${withThePicture.distinct} with ` +
      "the acquisition open",
  );

  // Both of the operator's own layers are still there, drawn by an engine that
  // has no acquisition open at all.
  expect(above, "the layer above, with no acquisition open")
    .toBeGreaterThan(THE_LATTICE_IS_THERE);
  expect(beneath, "the layer beneath, with no acquisition open")
    .toBeGreaterThan(THE_WASH_IS_THERE);

  /* And the acquisition really has gone. A flat wash and a lattice hold a
     handful of colours; a picture of a specimen holds hundreds, so the variety
     collapsing is the acquisition leaving rather than the box going dark — which
     is what the wash covering most of the box already rules out. */
  expect(withoutIt.distinct, "colours left with no acquisition open")
    .toBeLessThan(withThePicture.distinct / 4);

  // Said on the page too, so nobody has to wonder where the picture went.
  expect(await page.locator("#viewer-viv-note").textContent())
    .toMatch(/opened with no acquisition/);
});

test("neuroglancer cannot open with no acquisition, and the page says so rather than hanging",
  async ({ page }) => {
    test.setTimeout(240_000);

    /* The gap this demonstration found. Asked to open with no acquisitions at
       all, neuroglancer's `openViewer` never finishes — it waits for the engine
       to say what space the picture lives in, and with no layers to read that
       from it never does. Measured from this page: the two Viv engines open with
       no acquisition in under a quarter of a second, and this one is still not
       ready after twenty-five.

       Nothing here works around that. What is checked is what an operator meets:
       the page waits, gives up out loud, and puts the picture that was working
       back rather than leaving a box that will never fill. */
    await standOn(page, "neuroglancer");
    await untilTheEngineIsDrawing(page, "neuroglancer", STEPS.neuroglancer.engine);
    await run.acquire(25);
    await page.locator(layerButton("neuroglancer", "above")).click();

    await page.locator(layerButton("neuroglancer", "picture")).click();

    // The page says what it is doing while it waits, rather than looking frozen.
    await expect(page.locator("#viewer-neuroglancer-note"))
      .toContainText("opening with no acquisition", { timeout: 10_000 });

    /* And then gives up and says so. The wait is deliberately generous, so this
       is the one place a test here waits a long time on purpose. */
    await expect(page.locator("#viewer-neuroglancer-note"))
      .toContainText("never finished opening", { timeout: 90_000 });

    const said = await page.locator("#viewer-neuroglancer-note").textContent();
    console.log(`the page said: ${said}`);
    expect(said).toMatch(/no acquisition/);
    expect(said).toMatch(/drawing as it was/);

    // The button went back to on, because the layer it names never went off.
    await expect(page.locator(layerButton("neuroglancer", "picture")))
      .toHaveAttribute("aria-pressed", "true");

    /* And the picture that was working is working still. Giving up on an engine
       that will not open must not cost the operator the one that had. */
    const measured = await fullestPictureOf(
      page, "neuroglancer", "canvas-layers-neuroglancer-recovered");
    console.log(
      `after giving up, neuroglancer still drew: ${(measured.lit * 100).toFixed(1)}% ` +
        `of the box lit, ${measured.distinct} distinct colours`,
    );
    itIsReallyDrawing(measured, "neuroglancer-under after giving up");
  });

test("the same run, drawn by another engine, from the same view", async ({ page }) => {
  test.setTimeout(180_000);

  await standOn(page, "viv");
  await untilTheEngineIsDrawing(page, "viv", STEPS.viv.engine);
  await run.acquire(25);
  await fullestPictureOf(page, "viv", "canvas-layers-before-the-change", { seconds: 6 });

  const before = await page.locator("#viewer-viv-readout").textContent();
  await page.locator('#viewer-viv-engine button[data-engine="viv-inside"]').click();
  await untilTheEngineIsDrawing(page, "viv", "viv-inside");

  const measured = await fullestPictureOf(page, "viv", "canvas-layers-viv-inside");
  console.log(
    `the other engine drew: ${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours`,
  );
  itIsReallyDrawing(measured, "viv-inside");

  /* Changing engine has to keep the view. Two ways of drawing the same thing can
     only be compared if the second one is looked at from where the first one
     was; a difference of half a pixel is invisible if reaching the second
     picture means finding your way back. */
  expect(await page.locator("#viewer-viv-readout").textContent()).toBe(before);

  /* And the layers work on this engine too, which is the third of the three and
     the only one that draws all three of them in a single pass rather than as
     surfaces stacked in the page. The page's drawing code is identical for all
     three — that is the whole point of the interface — so this is asking whether
     the third engine really carries it out. */
  await page.locator(layerButton("viv", "above")).click();
  const above = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_ABOVE);
  await zoomOutABitWithTheWheel(page, "viv");
  await page.locator(layerButton("viv", "beneath")).click();
  const beneath = await howMuchOfTheBoxIs(page, "viv", THE_COLOUR_BENEATH);
  await keep(page, "viv", "canvas-layers-viv-inside-both-layers");

  console.log(
    `on viv-inside the layer above covers ${(above * 100).toFixed(2)}% and the ` +
      `layer beneath ${(beneath * 100).toFixed(1)}% of the box`,
  );
  expect(above, "the layer above, on viv-inside").toBeGreaterThan(THE_LATTICE_IS_THERE);
  expect(beneath, "the layer beneath, on viv-inside").toBeGreaterThan(THE_WASH_IS_THERE);
});

test("either step offers every engine the page was built with, and no others", async ({ page }) => {
  /* Served over HTTP, which is how an operator meets the page, all three can
     draw and all three are offered. The point of this test is the "no others"
     half: a button for an engine the page cannot open would draw nothing, and a
     box that never fills looks exactly like one that is still loading. The same
     rule is checked from the other side, without a browser, in
     `tests/unit/engines.test.js`.

     Both steps are asked, because the row of engines is what makes the
     comparison possible from wherever you happen to be standing. */
  const three = ["viv-under", "viv-inside", "neuroglancer-under"];

  /* The row is built when the step is first opened rather than when the page
     loads, because building it means fetching the engine, so each row is waited
     for rather than read the instant the step is clicked. */
  await standOn(page, "viv");
  await expect(page.locator("#viewer-viv-engine button")).toHaveCount(three.length);
  expect(await page.locator("#viewer-viv-engine button").allTextContents()).toEqual(three);

  await page.locator(".step").nth(STEPS.neuroglancer.at).click();
  await expect(page.locator("#viewer-neuroglancer-engine button")).toHaveCount(three.length);
  expect(await page.locator("#viewer-neuroglancer-engine button").allTextContents())
    .toEqual(three);
});

test("each step gives the whole window to the picture, and says it is a demonstration",
  async ({ page }) => {
    await standOn(page, "viv");

    // One module, so one tab, and it is the picture.
    await expect(page.locator("#tabs .tab")).toHaveCount(1);
    await expect(page.locator("#tabs .tab")).toHaveText("Viv");
    // Nothing docked down the right-hand side, and nothing to press.
    await expect(page.locator("#canvas-side")).toBeHidden();
    await expect(page.locator("#panel-viewer-viv button.step-run")).toHaveCount(0);

    // Two steps in the rail, each naming the engine it opens with.
    await expect(page.locator(".step")).toHaveCount(2);
    await expect(page.locator(".step").nth(0)).toContainText(STEPS.viv.title);
    await expect(page.locator(".step").nth(1)).toContainText(STEPS.neuroglancer.title);
    // Neither is greyed out, because neither is waiting for the other.
    await expect(page.locator(".step.locked")).toHaveCount(0);

    /* And it is named as what it is. Somebody choosing it in a month should not
       have to open it to find out that no microscope moves. */
    const chosen = page.locator("#wf-select option[value='canvas_layers']");
    await expect(chosen).toContainText(/demonstration/i);
    await expect(chosen).toHaveAttribute("title", /not a run/i);

    /* And naming it did not push anything else off the rail. The chooser sits
       beside the Restart button in a column of fixed width, and a workflow name
       a few words longer than the others used to make the dropdown as wide as
       itself and shove the button under the panel next door — where it was
       plainly visible, reported itself perfectly enabled, and could not be
       pressed. So this asks the page what is actually at the middle of that
       button rather than whether the button is there. */
    const reachable = await page.evaluate(() => {
      const button = document.getElementById("restart-btn");
      const at = button.getBoundingClientRect();
      const under = document.elementFromPoint(at.x + at.width / 2, at.y + at.height / 2);
      return under === button;
    });
    expect(reachable, "the Restart button is what is at the middle of itself").toBe(true);

    // The three layer buttons, named from the bottom of the stack upwards.
    await expect(page.locator("#viewer-viv-layers button")).toHaveCount(3);
    expect(await page.locator("#viewer-viv-layers button").allTextContents())
      .toEqual(["Beneath", "Picture", "Above"]);
  });
