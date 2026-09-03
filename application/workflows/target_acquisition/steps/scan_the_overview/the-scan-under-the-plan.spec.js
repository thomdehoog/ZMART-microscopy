/**
 * The scan drawn beneath the plan, and the one thing that has to be true of it.
 *
 * The operator's drawing and the acquired picture are drawn by different code
 * on different surfaces. The only thing that makes them one picture is that
 * they agree about where things are on the sample — and a disagreement of a few
 * pixels does not announce itself. It looks like a slightly soft scan, and it
 * is a run pointed at the wrong place. That is what most of this checks.
 *
 * The scan here is served by the test rather than made by a microscope: a
 * `tiles.json` saying where a handful of fields belong, and one small picture
 * standing in for all of them. That is exactly what the viewer is given in
 * earnest — it never opens a microscope's own files, because a picture that had
 * to read ten thousand large files to find out where to put something would be
 * back to the problem the small pictures exist to solve.
 */

import { expect, test } from "@playwright/test";

/**
 * How long one of these may take.
 *
 * They walk a whole run twice — once to find out where the plan puts things,
 * and again with a scan built to match — and a run is not quick. Generous
 * rather than the default, because what would otherwise fail here is the
 * walking, which is not what is being checked.
 *
 * Set inside each test rather than once for the file. `test.describe.configure`
 * at the top of a file settles it for whatever suite is being loaded at that
 * moment, and when several spec files are given to one run that turns out to be
 * the *next* file rather than this one — which fails it at load with a message
 * about `beforeEach` being in the wrong place, nowhere near the cause. Running
 * this file on its own hides that completely.
 */
const A_RUN_TAKES_A_WHILE = 120_000;

/** One small picture, standing in for every field. */
const A_SMALL_PICTURE = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/wAALCAAQABABAREA/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/API/hN8OJ/irda9dXmvS2lzbPHJLLLAbl53lMhLMS6nOUJJOc5qL4yfC/wD4Vv8A2R/xN/7S/tDzv+XbyfL8vZ/ttnO/26UfBv4of8K3/tf/AIlH9pf2h5P/AC8+T5fl7/8AYbOd/t0o+MnxQ/4WR/ZH/Eo/s3+z/O/5efO8zzNn+wuMbPfrX//Z", "base64");

/* Where the six-well plate's plan lands, which the page works out for itself.
   The scan is built from whatever it says, so the two cannot drift apart. */
const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

async function recordSlot(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  /* Some slots take a name and some do not — where what is read names itself,
     the bar is only a button. Naming one that has no field to name it in is
     the test insisting on a control the operator never sees. */
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(650);
}

async function runStep(page, ms = 1000) {
  await page.locator(".panel.on button.step-run").click();
  await page.waitForTimeout(ms);
}

/** Serve a scan whose fields are exactly where the page's plan will put them. */
async function serveAScanMatching(page, plan) {
  const tiles = plan.map((position, index) => ({
    label: `P${index}`,
    src: `P${index}.jpg`,
    x0: position.x - position.frameUm / 2,
    y0: position.y - position.frameUm / 2,
    w: position.frameUm,
    h: position.frameUm,
    grey: 90,
  }));
  await page.route("**/mock-scan/tiles.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ units: "um", tiles }) }));
  await page.route("**/mock-scan/*.jpg", (route) =>
    route.fulfill({ contentType: "image/jpeg", body: A_SMALL_PICTURE }));
}

/**
 * Walk only as far as having a plan.
 *
 * Enough to ask the page where it means to send the stage, which is what the
 * scan has to be built from. Stopping here rather than scanning as well keeps
 * the first of the two walks short.
 */
async function throughToAPlan(page) {
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(300);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(400);
  return page.evaluate(() => window.__theStageCanvas.plan());
}

/** Walk far enough to have a plan and a finished scan. */
async function throughToAScannedPlate(page) {
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(300);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(400);
  await gotoStep(page, "Focus strategy");
  await recordSlot(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await runStep(page, 2000);
  await gotoStep(page, "Scan the overview");
  await runStep(page, 6500);
}

/** The furthest any planned position is from where the scan puts it, in pixels. */
const howFarApart = (page) => page.evaluate(() => {
  const plan = window.__theStageCanvas.plan();
  const where = window.__thePicture.whereThingsAreDrawn();
  let worst = 0;
  for (const position of plan) {
    const planSays = window.__theStageCanvas.project(position.x, position.y);
    const scanSays = where.project(position.x, position.y);
    worst = Math.max(worst, Math.hypot(planSays[0] - scanSays.x, planSays[1] - scanSays.y));
  }
  return worst;
});

/** How much of the plan's surface has been cut away, so the scan shows through. */
const howMuchIsOpen = (page) => page.evaluate(() => {
  /* The plan is drawn on the topmost of the surfaces the engine builds inside
     the box — it used to be a canvas of the page's own, and asking the box for
     a 2D context now gets nothing. The last one is the one drawn over the
     picture; see `drawOver` in the engine contract. */
  const surfaces = [...document.querySelectorAll("#stage-canvas canvas")];
  const cv = surfaces.at(-1);
  if (!cv) throw new Error("the plan has no surface to read");
  const seen = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
  let clear = 0;
  for (let i = 3; i < seen.length; i += 4) if (seen[i] < 8) clear += 1;
  return clear / (seen.length / 4);
});

test("is not opened at all unless the page was pointed at one", async ({ page }) => {
  /* An engine is a large thing to fetch, and a page nobody pointed at a scan
     has no use for one. */
  await page.goto("/?backend=pretend");
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => window.__thePicture)).toBeFalsy();
});

test("lands exactly where the plan says, at every zoom and after panning",
  async ({ page }) => {
    test.setTimeout(A_RUN_TAKES_A_WHILE);
    await page.goto("/?backend=pretend");
    await page.waitForTimeout(800);
    await serveAScanMatching(page, await throughToAPlan(page));
    await page.goto("/?picture=/mock-scan&backend=pretend");
    await page.waitForTimeout(800);
    await throughToAScannedPlate(page);
    await page.waitForFunction(() => !!window.__thePicture, null, { timeout: 20_000 });

    /* Exactly, not nearly. The two projections are the same arithmetic written
       twice, so any difference at all means one of them has drifted. */
    expect(await howFarApart(page), "the scan is not where the plan says").toBeLessThan(0.001);

    const box = await page.locator("#stage-canvas").boundingBox();
    for (let i = 0; i < 8; i += 1) {
      await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.4);
      await page.mouse.wheel(0, -120);
      await page.waitForTimeout(70);
    }
    await page.waitForTimeout(400);
    expect(await howFarApart(page), "zooming pulled the two apart").toBeLessThan(0.001);

    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.5 - 200, box.y + box.height * 0.5 + 120, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(400);
    expect(await howFarApart(page), "panning pulled the two apart").toBeLessThan(0.001);
  });

test("shows only where the drawing above it has been opened up", async ({ page }) => {
  test.setTimeout(A_RUN_TAKES_A_WHILE);
  await page.goto("/?backend=pretend");
  await page.waitForTimeout(800);
  await serveAScanMatching(page, await throughToAPlan(page));
  await page.goto("/?picture=/mock-scan&backend=pretend");
  await page.waitForTimeout(800);
  await throughToAScannedPlate(page);
  await page.waitForFunction(() => !!window.__thePicture, null, { timeout: 20_000 });

  /* The run opened its own ground: the scan already shows through the fields
     it imaged, and nowhere else. The fields are 20x frames, 676 µm against
     wells of 6.6 mm, so the open ground is small on the canvas: a fraction
     of a percent open is the whole plan showing. */
  await page.waitForTimeout(400);
  expect(await howMuchIsOpen(page), "the scan does not show through what it imaged")
    .toBeGreaterThan(0.0004);

  /* Closed by hand, the surface covers everything again — what an operator
     sees before they ask for the picture. */
  await page.evaluate(() => window.__theStageCanvas.closeTheGround());
  await page.waitForTimeout(400);
  expect(await howMuchIsOpen(page), "the scan was showing with the ground closed").toBeLessThan(0.0002);

  await page.evaluate(() => window.__theStageCanvas.openScannedGround());
  await page.waitForTimeout(500);
  const throughTheWindow = await howMuchIsOpen(page);
  expect(throughTheWindow, "the window did not reach the scan").toBeGreaterThan(0.0004);
  expect(throughTheWindow, "the window opened far more than the fields it named")
    .toBeLessThan(0.5);

  await page.evaluate(() => window.__theStageCanvas.closeTheGround());
  await page.waitForTimeout(400);
  expect(await howMuchIsOpen(page), "closing the windows left the scan showing")
    .toBeLessThan(0.0002);

  /* And the blunt way: turn the bottom layer off and the scan is simply there.
     A window is for looking at part of it; this is for looking at all of it.

     Asked of the canvas rather than pressed on a button, because the strip of
     controls that held those buttons has been taken off the screen while a
     better home for it is decided. What is being checked here is the canvas,
     not the button — and a test that could only reach the canvas through a
     control somebody was still designing would have to be rewritten every time
     the design moved. */
  await page.evaluate(() => window.__theStageCanvas.showLayer("ground", false));
  await page.waitForTimeout(500);
  expect(await howMuchIsOpen(page), "turning the background off did not show the scan")
    .toBeGreaterThan(0.4);
});
