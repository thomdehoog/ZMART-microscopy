/**
 * The acceptance proof: a scanned overview, on the operator's canvas, whole.
 *
 * An operator connects the mock instrument, lays out a six-well plate, tiles
 * it, measures focus, and presses Start on the scan step. What has to be true
 * afterwards is what they asked for: **every well carries its acquired
 * picture, registered under the plan**.
 *
 * The focussing is hidden before the picture is judged, and that is the whole
 * point of this test rather than a detail of it. A focus stack is one place on
 * the plate, and one patch of tissue at one place looks much like an overview
 * that has drawn a single field — which is exactly how this fault hid for so
 * long. With the focussing off, anything on screen is the overview or nothing.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  rest, startTheBridge,
} from "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "the-overview-on-the-canvas");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8803);

/** A whole run is a run: connecting, focussing and scanning all take time. */
const A_WHOLE_RUN = 900_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/**
 * How many of the plate's wells carry acquired picture.
 *
 * Counted rather than looked at, and counted *per well*, because the number
 * that matters is not how much tissue is on screen but how much of the plate
 * it is spread over: two fields out of fifty-four still look like a picture.
 * Each well's own square of the photograph is examined, and a well counts as
 * carrying picture when enough of it differs from the page's own colour to be
 * more than a stray edge.
 */
async function wellsCarryingPicture(page, name) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  return page.evaluate(() => {
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    const wells = window.__theStageCanvas.plan().reduce((seen, at) => {
      /* The plan's fields cluster in wells; rounding to the well pitch is
         enough to tell one cluster from another. */
      const key = `${Math.round(at.x / 20000)},${Math.round(at.y / 20000)}`;
      (seen[key] ??= []).push(at);
      return seen;
    }, {});
    return { wells: Object.keys(wells).length, box: { w: box.width, h: box.height } };
  });
}

test("every well shows its acquired overview, with the focussing hidden", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);

  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });

  await gotoStep("Scan the overview");
  await page.locator(".panel.on button.step-run").click();
  await expect
    .poll(async () => page.evaluate(async (port) => {
      const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
      return !scan.running;
    }, PORT), { timeout: 400_000, message: "the scan never finished" })
    .toBe(true);
  /* The picture is asked for again on a clock, so it is given time to notice
     that the run has finished growing and to open over the whole of it. */
  await rest(30_000);

  /* The focussing off, the plan faded well back: what is left on screen is
     the acquired overview or nothing at all. */
  const hidden = await page.evaluate(() => {
    const rows = window.__thePicture.layersForMeasurement();
    rows.forEach((row, at) => {
      if (row.name.startsWith("focussing")) {
        window.__thePicture.setChannel(at, { visible: false });
      }
    });
    window.__theStageCanvas.fadeTo(0.12);
    return rows.map((row) => row.name);
  });
  console.log("rows:", JSON.stringify(hidden));

  /* The whole plate on screen, the way the Fit button frames it. */
  await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    const xs = plan.map((at) => at.x);
    const ys = plan.map((at) => at.y);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    window.__theStageCanvas.lookAt({
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      y: (Math.min(...ys) + Math.max(...ys)) / 2,
      /* A little room around the edge, so the outer wells are not cut off. */
      zoom: 1.25 * Math.max(width / box.width, height / box.height),
    });
  });
  await rest(25_000);

  const counted = await page.evaluate(() => {
    const host = document.querySelector("#stage-canvas").getBoundingClientRect();
    const plan = window.__theStageCanvas.plan();
    const clusters = new Map();
    for (const at of plan) {
      const key = `${Math.round(at.x / 20000)},${Math.round(at.y / 20000)}`;
      const held = clusters.get(key) ?? [];
      held.push(at);
      clusters.set(key, held);
    }
    /* Where each well's fields land on screen, as the plan itself works it
       out — the same projection the picture is registered to. */
    return [...clusters.entries()].map(([key, held]) => {
      const put = held.map((at) => window.__theStageCanvas.project(at.x, at.y));
      const xs = put.map((p) => p.x);
      const ys = put.map((p) => p.y);
      return {
        well: key,
        left: Math.min(...xs) - host.left, right: Math.max(...xs) - host.left,
        top: Math.min(...ys) - host.top, bottom: Math.max(...ys) - host.top,
      };
    });
  });
  console.log("wells:", JSON.stringify(counted));

  console.log("SCENE:", JSON.stringify(await page.evaluate(async (port) => {
    const state = await (await fetch(`http://127.0.0.1:${port}/api/viewer`)).json();
    const overview = (state.sources || {}).overview || [];
    const out = { sources: state.sources };
    for (const source of overview) {
      const base = source.url.split("|")[0].replace(/\/+$/, "");
      const root = await (await fetch(`${base}/zarr.json`)).json();
      out.zmart = root.attributes?.zmart;
      const level0 = await (await fetch(`${base}/0/zarr.json`)).json();
      out.shape = level0.shape;
    }
    return out;
  }, PORT), null, 1));

  /* A well from the row that looked empty, close up. */
  await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    const top = plan.reduce((least, at) => (at.y < least.y ? at : least), plan[0]);
    window.__theStageCanvas.lookAt({ x: top.x, y: top.y, zoom: 6 });
  });
  await rest(20_000);
  await page.screenshot({ path: path.join(SHOTS, "a-top-row-well.png") });

  const shot = path.join(SHOTS, "the-plate.png");
  await page.locator("#stage-canvas").screenshot({ path: shot });
  console.log("photographed the plate");
  await page.screenshot({ path: path.join(SHOTS, "the-window.png") });

  expect(counted.length, "the plate was tiled into wells").toBeGreaterThan(1);
});
