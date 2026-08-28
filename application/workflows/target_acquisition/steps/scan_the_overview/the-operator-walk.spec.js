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
  await page.locator(".panel.on button.step-run").click();
  /* Watched on disk rather than on screen. What has to be true of this step is
     that the instrument really captured stacks and something really scored
     them -- a page that drew a heatmap over nothing would satisfy any check
     made through the page itself. */
  const stacks = await capturedUnder(path.join(bridge.folder, "focussing", "data"), 300_000);
  expect(stacks, "no focussing stack was captured").toBeGreaterThan(0);

  // 5. Scan. Nothing tells the page where the pictures will be: it asks its
  //    own backend, which is the join this walk exists to prove.
  await gotoStep(page, "Scan the overview");
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
  console.log(`covered: ${empty.covered}px -> ${scanned.covered}px, ${plan.length} positions`);
  expect(complaints, "the page complained while walking").toEqual([]);
});
