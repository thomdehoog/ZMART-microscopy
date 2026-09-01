/**
 * Step 5, photographed as it fills in, on real tissue.
 *
 * This is the evidence gate for the Smart Viewer integration: a nine-field
 * scan of one tileset, watched through the operator's own window while the
 * fields land, and then judged three ways — that every planned field carries
 * picture, that hiding the focussing leaves the whole overview behind, and
 * that what is drawn is microscopy texture rather than a flat shape.
 *
 * A slide rather than a plate, so that nine fields are one tileset and each of
 * them is a good many screen pixels rather than a speck. The mock microscope
 * draws its sample from a real micrograph of mouse kidney, which is what makes
 * the close-up worth looking at: a flat colour and a picture both fill a
 * square, and only one of them has cells in it.
 *
 * Nothing here is staged. The scan is started with Step 5's own Run button and
 * the pictures are taken as the bridge reports fields landing, so the counts in
 * the file names are what had actually been imaged at the moment of the
 * photograph — recorded rather than assumed, because a scan does not pause to
 * be looked at.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  rest, startTheBridge,
} from "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "./workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "step-five-kidney");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8812);

/** A whole run is a run: connecting, focussing and scanning all take time. */
const A_WHOLE_RUN = 900_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/**
 * How much of one field's square on screen carries picture, and how varied it
 * is.
 *
 * Two numbers, because they answer two different doubts. `covered` is the
 * share of the square that differs from the page's own colour — that is enough
 * to say a field was drawn at all. `shades` is how many distinct grey levels
 * are in it, which is what tells a photograph of tissue from a flat rectangle
 * of the right size in the right place. A drawing fault that paints every
 * field one solid colour passes the first and fails the second.
 *
 * Measured a little inside the field's edge, so that a neighbouring field
 * bleeding over the boundary cannot be mistaken for this one.
 */
function whatIsInside(pixels, box) {
  const { data, width, height, channels } = pixels;
  const corner = [data[0], data[1], data[2]];
  const inset = 0.25;
  const left = Math.max(0, Math.round(box.left + (box.right - box.left) * inset));
  const right = Math.min(width - 1, Math.round(box.right - (box.right - box.left) * inset));
  const top = Math.max(0, Math.round(box.top + (box.bottom - box.top) * inset));
  const bottom = Math.min(height - 1, Math.round(box.bottom - (box.bottom - box.top) * inset));
  if (right <= left || bottom <= top) return null;  // off screen
  let drawn = 0;
  let looked = 0;
  const seen = new Set();
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const at = (y * width + x) * channels;
      looked += 1;
      if (Math.abs(data[at] - corner[0]) > 10
        || Math.abs(data[at + 1] - corner[1]) > 10
        || Math.abs(data[at + 2] - corner[2]) > 10) drawn += 1;
      seen.add(data[at] >> 2);
    }
  }
  return looked ? { covered: drawn / looked, shades: seen.size } : null;
}

/** Where each planned field sits on the photograph, as the plan itself says. */
async function theFieldsOnScreen(page) {
  return page.evaluate(() => {
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    return window.__theStageCanvas.plan().map((at, index) => {
      const half = at.frameUm / 2;
      const middle = window.__theStageCanvas.project(at.x, at.y);
      const edge = window.__theStageCanvas.project(at.x + half, at.y + half);
      const across = Math.abs(edge.x - middle.x);
      const down = Math.abs(edge.y - middle.y);
      return {
        index,
        left: box.left + middle.x - across,
        right: box.left + middle.x + across,
        top: box.top + middle.y - down,
        bottom: box.top + middle.y + down,
      };
    });
  });
}

test("nine fields of kidney fill the plan, photographed as they land", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };
  const shot = async (name) => {
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
    console.log("photographed", name);
  };
  /** What the bridge says has actually been imaged. */
  const imagedSoFar = () => page.evaluate(async (port) => {
    const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
    return { done: scan.done ?? 0, of: scan.of ?? 0, running: !!scan.running };
  }, PORT);

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  /* A slide, so the nine fields are one tileset rather than nine wells' worth
     spread across a plate. */
  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);

  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);

  const planned = await page.evaluate(() => window.__theStageCanvas.plan().length);
  console.log("the plan holds", planned, "positions");
  expect(planned, "a three by three tileset").toBe(9);

  /* The focus map is run because the overview-only photograph needs something
     to hide: without a focussing acquisition there is nothing to prove was put
     away while the overview stayed. */
  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });
  await rest(2000);

  await gotoStep("Scan the overview");
  await rest(1500);
  await shot("0-of-9");
  const atTheStart = await imagedSoFar();
  expect(atTheStart.done, "nothing is imaged before Start is pressed").toBe(0);

  /* Step 5's own Run button. The photographs below are taken as the bridge
     reports fields landing — a scan does not pause to be looked at, so what is
     recorded is the count at the moment of the photograph rather than a count
     asked for in advance. */
  await page.locator(".panel.on button.step-run").click();

  const wanted = [3, 6, 9];
  const taken = [];
  for (const count of wanted) {
    await expect
      .poll(async () => (await imagedSoFar()).done, {
        timeout: 400_000, intervals: [150],
        message: `the scan never reached ${count} fields`,
      })
      .toBeGreaterThanOrEqual(count);
    /* A moment for the field that has just landed to be drawn. */
    await rest(1200);
    const now = await imagedSoFar();
    taken.push(now.done);
    await shot(`${now.done}-of-9`);
  }

  await expect
    .poll(async () => !(await imagedSoFar()).running,
      { timeout: 400_000, message: "the scan never finished" })
    .toBe(true);
  await rest(20_000);
  const finished = await imagedSoFar();
  console.log("the scan imaged", finished.done, "of", finished.of);
  expect(finished.done, "every planned field was imaged").toBe(9);
  console.log("photographs were taken at", taken.join(", "), "fields");

  /* ---- the overview alone ------------------------------------------------
     The focussing is put away through the engine, and both the engine and the
     panel are then asked what they say about it. An eye that reads closed over
     a channel still being drawn would make every photograph below worthless. */
  await page.evaluate(() => {
    window.__thePicture.layersForMeasurement().forEach((row, at) => {
      if (row.name.startsWith("focussing")) {
        window.__thePicture.setChannel(at, { visible: false });
      }
    });
    window.__theStageCanvas.fadeTo(0);
  });
  await rest(6000);

  const asDrawn = await page.evaluate(() =>
    window.__thePicture.layersForMeasurement()
      .map((row) => ({ name: row.name, shown: row.visible !== false })));
  const eyes = await page.evaluate(() => {
    const panel = window.__viewerPanel;
    return [...(panel?.querySelectorAll("button[data-shown]") ?? [])].map((eye) => ({
      of: eye.title.replace(/^(Hide|Show) this /, ""),
      shown: eye.dataset.shown === "1",
    }));
  });
  console.log("as drawn:", JSON.stringify(asDrawn));
  console.log("eyes:", JSON.stringify(eyes));
  for (const row of asDrawn) {
    expect(row.shown, `${row.name} while only the overview is wanted`)
      .toBe(!row.name.startsWith("focussing"));
  }
  await shot("overview-only");

  /* ---- every field, measured separately ---------------------------------
     A scan of nine fields that drew four looks, from far enough away, exactly
     like one that drew all nine. */
  const fields = await theFieldsOnScreen(page);
  const pixels = readPng(await page.screenshot());
  const thin = [];
  const flat = [];
  for (const field of fields) {
    const inside = whatIsInside(pixels, field);
    if (!inside) continue;
    console.log(`field ${field.index}: ${(inside.covered * 100).toFixed(1)}% drawn,`,
      `${inside.shades} shades`);
    if (inside.covered < 0.9) thin.push(`${field.index} (${(inside.covered * 100).toFixed(1)}%)`);
    if (inside.shades < 8) flat.push(`${field.index} (${inside.shades} shades)`);
  }
  expect(thin, "every planned field carries picture").toEqual([]);
  expect(flat, "and every one of them is textured, not a flat shape").toEqual([]);

  /* ---- the whole carrier, and one field close enough to judge ---------- */
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
  await page.locator("#fit-btn").click();
  await rest(8000);
  await shot("whole-plate");

  await page.evaluate(() => {
    const first = window.__theStageCanvas.plan()[0];
    window.__theStageCanvas.lookAt({ x: first.x, y: first.y, zoom: 0.9 });
  });
  await rest(12_000);
  await shot("close-up");
});
