/**
 * The whole operator walk, on the real bridge, up to a scanned overview.
 *
 * Every other test here drives one join and stands the rest in. This one
 * drives none of them: it presses the page's own buttons, in order, from
 * Connect to a finished overview, against `application/framework/bridge.py`
 * running the mock microscope through the controller. Nothing is passed on a
 * query string -- not the instrument, not the scan, not where the pictures
 * are. If the page cannot find its own run, this fails.
 *
 * What it asserts at the end is pixels: the acquired sample, drawn on the
 * canvas, in the place the plan said the stage would go.
 *
 * Making sure it can fail: `LIVE_WALK_SABOTAGE=unscanned` walks the whole run
 * but never presses Scan. Everything else still happens -- the page connects,
 * plans, focuses and stands on the step -- and the picture stays empty, which
 * is what makes the rise afterwards mean the scan and not the walking.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { rest, startTheBridge } from "./live-bridge.js";
import { fractionNear, photograph } from "./pixels.js";

const SHOTS = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)), "..", "test-results", "the-operator-walk",
);
const PORT = Number(process.env.LIVE_WALK_PORT ?? 8803);

/** A whole run, one step at a time, on a microscope that really captures. */
const A_WHOLE_RUN = 600_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

/** Wait until a folder holds acquisitions, and say how many planes landed. */
async function capturedUnder(folder, patience) {
  const until = Date.now() + patience;
  do {
    const planes = fs.existsSync(folder)
      ? fs.readdirSync(folder).filter((name) => name.endsWith(".ome.tiff")).length
      : 0;
    if (planes) return planes;
    await rest(1000);
  } while (Date.now() < until);
  return 0;
}

/** Take the reading a step will not proceed without, and name it. */
async function record(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(800);
}

/** How many pixels of the picture are covered by acquired fields. */
function coveredPixels(pixels) {
  const corner = [pixels.data[0], pixels.data[1], pixels.data[2]];
  return Math.round(
    (1 - fractionNear(pixels, corner)) * pixels.width * pixels.height,
  );
}

async function fullestOf(page, name, { seconds = 12 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const covered = coveredPixels(await photograph(page, "#picture-host", 1));
    if (!best || covered > best.covered) {
      best = { covered, shot: await page.locator("#picture-host").screenshot() };
    }
    await rest(700);
  } while (Date.now() < until);
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), best.shot);
  return { covered: best.covered };
}

test("an operator walks from Connect to a scanned overview", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const complaints = [];
  page.on("pageerror", (e) => complaints.push(e.message));

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);

  // 1. Connect. The instrument list is the controller's own, and the page
  //    lands on the mock because it is the one this bridge registered.
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });

  // 2. A plate to scan.
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);

  // 3. Where to scan it. The tileset needs the instrument's own optics first:
  //    how much sample a frame covers decides how many frames a well takes.
  await gotoStep(page, "Define scan area");
  await record(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);
  const plan = await page.evaluate(() => window.__theStageCanvas.plan());
  expect(plan.length, "the plate was tiled").toBeGreaterThan(0);

  // 4. Focus. Every point drives, captures a stack, and has ZMART_analysis
  //    score it -- no vendor autofocus anywhere in this.
  await gotoStep(page, "Focus strategy");
  await record(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  /* The reticles stand above the plan. The stack order is the draw order,
     and the points were once part of a layer early enough that the plan's
     grid painted over the very thing the operator was placing. They also
     survive the shared fade: fading the plan to see the picture is not a
     request to lose the focus points too. */
  const stack = await page.evaluate(() => window.__theStageCanvas.layers());
  const order = stack.map((l) => l.key);
  expect(order.indexOf("focusPoints"), "the points are a layer above the plan")
    .toBeGreaterThan(order.indexOf("plan"));
  expect(stack.find((l) => l.key === "focusPoints")?.staysSolid,
    "the points survive the shared fade").toBe(true);
  await page.locator(".panel.on button.step-run").click();
  /* Watched on disk rather than on screen. What has to be true of this step is
     that the instrument really captured stacks and something really scored
     them -- a page that drew a heatmap over nothing would satisfy any check
     made through the page itself. */
  const stacks = await capturedUnder(
    path.join(bridge.currentRun(), "focussing", "data"),
    300_000,
  );
  expect(stacks, "no focussing stack was captured").toBeGreaterThan(0);

  /* The stage was driven in its own frame, not the carrier's. The map lays
     points on the carrier; where the carrier sits on the stage is the origin
     alignment measures, and unaligned it is centred in the travel -- so the
     two frames never agree, even here. Every point went out unconverted for
     as long as the mock's picture happened to line up anyway; on an aligned
     Leica each one drove to the wrong place. */
  const [ox, oy] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());
  expect(Math.hypot(ox, oy), "the carrier stands off the stage's zero").toBeGreaterThan(1000);
  const asked = await page.evaluate(() => window.__theFocusPoints());
  await expect.poll(async () => {
    /* The page's own Connect opened a fresh run; what it captured is there,
       not in the run this harness's connect made. */
    const where = path.join(bridge.currentRun(), "focussing", "analysis");
    if (!fs.existsSync(where)) return false;  // nothing scored yet
    const kept = fs.readdirSync(where)
      .map((name) => JSON.parse(fs.readFileSync(path.join(where, name), "utf8")));
    return kept.some((m) => Math.abs(m.x_um - (asked.x + ox)) < 1 && Math.abs(m.y_um - (asked.y + oy)) < 1);
  }, { message: "no capture was taken where the stage should have gone", timeout: 60_000 }).toBe(true);

  /* The run finishes when its promise does, and the rail refuses to move
     while a step is working. The done badge is no signal -- recording a
     focus preset settles the step before anything has driven -- so what the
     walk waits for is what the operator watches: the button coming back.
     Waited for here, before the preview is read: while the map is being
     measured the selected point is the one under measurement, which has no
     slices yet, so a preview asked for mid-run was hidden by design. */
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 180_000 });

  /* The slice at the black line. The box beside the plot shows the real
     captured plane nearest the chosen height, and dragging the height walks
     the stack -- so the two ends of the plot must show two different
     slices, fetched from the bridge, not drawn from anything invented. */
  await expect(page.locator("#zpreview")).toBeVisible();
  /* The preview above pushed the plot below the fold, and a mouse press at
     an off-screen coordinate scrubs nothing -- it clicked whatever was at
     the clamped spot and the line never moved. */
  await page.locator("#trace-canvas").scrollIntoViewIfNeeded();
  const plotBox = await page.locator("#trace-canvas").boundingBox();
  const scrubTo = async (x) => {
    await page.mouse.move(plotBox.x + x, plotBox.y + plotBox.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(200);
    return page.evaluate(() => window.__theSliceShown());
  };
  const lowSlice = await scrubTo(45);
  const highSlice = await scrubTo(plotBox.width - 60);
  expect(lowSlice, "a slice of the stack is on show").toBeTruthy();
  expect(highSlice, "the line's height picks the slice").not.toBe(lowSlice);

  /* The stack seen from the side, beside the slice: one column per height,
     so the tissue's place in the sweep is visible at a glance. It fills as
     the slices arrive, so it is polled rather than glanced at once. */
  await expect.poll(() => page.evaluate(() => {
    const cv = document.getElementById("zortho-canvas");
    if (!cv || !cv.width) return 0;
    const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    let lit = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 10 || d[i + 1] > 10) lit += 1;
    return lit / (d.length / 4);
  }), { message: "the orthogonal view never filled", timeout: 30_000 })
    .toBeGreaterThan(0.05);

  /* The cut is the operator's: drag the green line across the slice and the
     side view is re-cut along it. Held as a weighted sum of the side view's
     pixels, which moves when the columns it is built from do. */
  const orthoInk = () => page.evaluate(() => {
    const cv = document.getElementById("zortho-canvas");
    const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += d[i] * (((i >> 2) % 997) + 1);
    return sum;
  });
  /* Settled first, or the assertion is a coin toss: the side view fills as
     slices arrive, so two samples differ on their own until it is whole --
     and this test once passed with no feature behind it exactly that way. */
  let cutBefore = await orthoInk();
  await expect.poll(async () => {
    const now = await orthoInk();
    const same = now === cutBefore && now !== 0;
    cutBefore = now;
    return same;
  }, { message: "the side view never settled", timeout: 30_000 }).toBe(true);
  await page.locator("#zcut-slider").evaluate((slider) => {
    slider.value = "200";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForTimeout(300);
  expect(await orthoInk(), "dragging the cut re-cuts the side view").not.toBe(cutBefore);

  // 5. Scan. Nothing tells the page where the pictures will be: it asks its
  //    own backend, which is the join this walk exists to prove.
  await gotoStep(page, "Scan the overview");
  /* Focussing is a real acquisition too, and the preceding step has already
     written it. It is therefore legitimate for those fields to be visible
     before the overview starts. Hide that acquisition through the operator's
     own control so the pixel rise below belongs specifically to overview;
     acquisition order and shared display Z must not be used as visibility. */
  const focussingEye = page.locator(
    '.viewer-panel button[data-acquisition="focussing"]',
  );
  await expect(focussingEye).toHaveAttribute("data-on", "1", { timeout: 30_000 });
  await focussingEye.click();
  await expect(focussingEye).toHaveAttribute("data-on", "0");
  await expect.poll(() => page.evaluate(() => window.__thePicture
    .layersForMeasurement()
    .filter(({ name }) => name.startsWith("focussing"))
    .every(({ visible }) => !visible)), {
    message: "the panel did not hide the focussing acquisition",
  }).toBe(true);
  await page.addStyleTag({ content: ".stagecv { visibility: hidden !important; }" });
  const empty = await fullestOf(page, "1-before-the-scan", { seconds: 4 });
  expect(empty.covered, `something was drawn before the scan ran: ${empty.covered}px`)
    .toBeLessThan(20);

  if (process.env.LIVE_WALK_SABOTAGE !== "unscanned") {
    await page.locator(".panel.on button.step-run").click();
  }
  const scanned = await fullestOf(page, "2-after-the-scan", { seconds: 30 });

  expect(scanned.covered, `the overview never reached the screen: ${scanned.covered}px`)
    .toBeGreaterThan(empty.covered + 40);

  /* Where the picture stands, asked of the picture itself: the first planned
     field, driven through the under-viewer's own projection, must be lit
     tissue on screen. Coverage alone let a misplaced picture pass -- there
     was tissue somewhere, just not under the plan. */
  const placed = await page.evaluate(() => {
    const where = window.__thePicture.whereThingsAreDrawn();
    const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
    const tile = window.__theStageCanvas.plan()[0];
    const at = where.project(tile.x + ox, tile.y + oy);
    return { x: at.x, y: at.y, w: where.width, h: where.height };
  });
  expect(placed.x, "the first field is on screen").toBeGreaterThan(0);
  expect(placed.y, "the first field is on screen").toBeGreaterThan(0);
  const shot = await photograph(page, "#picture-host", 1);
  const px = (x, y) => {
    const i = (Math.round(y) * shot.width + Math.round(x)) * 4;
    return [shot.data[i], shot.data[i + 1], shot.data[i + 2]];
  };
  const corner = px(1, 1);
  /* The tissue nearest the projected first field must be within a tile's
     reach of it. A knife-edge sample lost to a few pixels of border slop
     between the host and the engine's canvas; a real misplacement -- an
     origin's worth -- is tens of pixels and still fails this. */
  const cx = placed.x * (shot.width / placed.w);
  const cy = placed.y * (shot.height / placed.h);
  let nearest = Infinity;
  for (let y = 0; y < shot.height; y += 2) {
    for (let x = 0; x < shot.width; x += 2) {
      const there = px(x, y);
      if (corner.some((c, i) => Math.abs(c - there[i]) > 12)) {
        nearest = Math.min(nearest, Math.hypot(x - cx, y - cy));
      }
    }
  }
  expect(nearest, `the nearest tissue is ${nearest.toFixed(0)}px from the ` +
    `projected first field at ${JSON.stringify(placed)}`).toBeLessThan(40);
  console.log(`covered: ${empty.covered}px -> ${scanned.covered}px, ${plan.length} positions`);
  expect(complaints, "the page complained while walking").toEqual([]);
});
