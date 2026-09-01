/**
 * A 96-well plate, nine fields in every well, all of them acquired and drawn.
 *
 * Eight hundred and sixty-four fields is the scale this arrangement is meant
 * for, and it is a different question from the six-well walk beside it. Six
 * wells fit comfortably in one picture; ninety-six do not, so this is where
 * the zoomed-out end of the picture has to earn its keep as well as the
 * zoomed-in end.
 *
 * The focussing is hidden throughout — its eyes read closed in every
 * photograph, checked rather than assumed — so what is on screen is the
 * acquired overview and nothing else.
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
const SHOTS = path.join(HERE, "test-results", "96-well");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8809);

/** Eight hundred and sixty-four captures is not a quick thing to ask for. */
const A_PLATE_TAKES_A_WHILE = 3_600_000;

/** How many wells to look at one by one. All of them, unless asked otherwise. */
const WELLS_TO_LOOK_AT = Number(process.env.ZV_WELLS ?? "96");

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/** How much of one field's square carries picture. See every-tile-is-filled. */
function drawnWithin(pixels, box) {
  const { data, width, height, channels } = pixels;
  const corner = [data[0], data[1], data[2]];
  const inset = 0.25;
  const left = Math.max(0, Math.round(box.left + (box.right - box.left) * inset));
  const right = Math.min(width - 1, Math.round(box.right - (box.right - box.left) * inset));
  const top = Math.max(0, Math.round(box.top + (box.bottom - box.top) * inset));
  const bottom = Math.min(height - 1, Math.round(box.bottom - (box.bottom - box.top) * inset));
  if (right <= left || bottom <= top) return null;
  let drawn = 0;
  let looked = 0;
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const at = (y * width + x) * channels;
      looked += 1;
      if (Math.abs(data[at] - corner[0]) > 10
        || Math.abs(data[at + 1] - corner[1]) > 10
        || Math.abs(data[at + 2] - corner[2]) > 10) drawn += 1;
    }
  }
  return looked ? drawn / looked : null;
}

test("a 96-well plate, nine fields a well, every one of them drawn", async ({ page }) => {
  test.setTimeout(A_PLATE_TAKES_A_WHILE);
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
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 120_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "96-well · Greiner SensoPlate" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(SHOTS, "1-the-plate.png") });

  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(SHOTS, "2-tiled.png") });

  const plan = await page.evaluate(() => window.__theStageCanvas.plan());
  console.log(`the plan holds ${plan.length} fields`);
  expect(plan.length, "nine fields in each of ninety-six wells").toBe(864);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(600);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 900_000 });
  await page.screenshot({ path: path.join(SHOTS, "3-focussed.png") });

  await gotoStep("Scan the overview");
  await page.locator(".panel.on button.step-run").click();
  const began = Date.now();
  /* Waiting for "not running" alone is not waiting for the scan: asked the
     instant the button is pressed, before the worker has taken its first
     step, the answer is already "not running" and the whole plate is
     declared finished without a single field having been imaged. So what is
     waited for is every field being accounted for. */
  await expect
    .poll(async () => page.evaluate(async (port) => {
      const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
      return { done: scan.done ?? 0, of: scan.of ?? 0, running: !!scan.running };
    }, PORT), {
      timeout: 2_400_000,
      intervals: [5000],
      message: "the scan never got through its fields",
    })
    .toEqual({ done: 864, of: 864, running: false });
  console.log(`the scan took ${Math.round((Date.now() - began) / 1000)} s`);
  await rest(45_000);

  /* Only the overview. The panel is told nothing: it hears from the viewer. */
  await page.evaluate(() => {
    window.__thePicture.layersForMeasurement().forEach((row, at) => {
      if (row.name.startsWith("focussing")) {
        window.__thePicture.setChannel(at, { visible: false });
      }
    });
    window.__theStageCanvas.fadeTo(0);
  });
  await rest(5000);

  const eyes = await page.evaluate(() =>
    [...window.__viewerPanel.querySelectorAll("button[data-shown]")].map((eye) => ({
      of: eye.title.replace(/^(Hide|Show) this /, ""),
      shown: eye.dataset.shown === "1",
    })));
  console.log("eyes:", JSON.stringify(eyes));
  expect(eyes[0].shown, "the focussing acquisition's eye is closed").toBe(false);
  expect(eyes[1].shown, "the focussing channel's eye is closed").toBe(false);

  /* The whole plate, as an operator would frame it. */
  await page.evaluate(() => {
    const held = window.__theStageCanvas.plan();
    const xs = held.map((at) => at.x);
    const ys = held.map((at) => at.y);
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    const wide = (Math.max(...xs) - Math.min(...xs)) + 2 * held[0].frameUm;
    const tall = (Math.max(...ys) - Math.min(...ys)) + 2 * held[0].frameUm;
    window.__theStageCanvas.lookAt({
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      y: (Math.min(...ys) + Math.max(...ys)) / 2,
      zoom: 1.1 * Math.max(wide / box.width, tall / box.height),
    });
  });
  await rest(60_000);
  await page.screenshot({ path: path.join(SHOTS, "4-the-whole-plate.png") });

  /* And then well by well, so "all of them" is measured rather than admired. */
  const wells = await page.evaluate(() => {
    const gathered = new Map();
    for (const at of window.__theStageCanvas.plan()) {
      const key = `${Math.round(at.x / 4500)},${Math.round(at.y / 4500)}`;
      const held = gathered.get(key) ?? [];
      held.push(at);
      gathered.set(key, held);
    }
    return [...gathered.entries()].map(([well, fields]) => ({ well, fields }));
  });
  console.log(`the plan falls into ${wells.length} wells`);

  const missing = [];
  let counted = 0;
  const looking = wells.slice(0, WELLS_TO_LOOK_AT);

  for (const [which, { well, fields }] of looking.entries()) {
    await page.evaluate(({ fields: held }) => {
      const xs = held.map((at) => at.x);
      const ys = held.map((at) => at.y);
      const frame = held[0].frameUm;
      const box = document.querySelector("#stage-canvas").getBoundingClientRect();
      const wide = (Math.max(...xs) - Math.min(...xs)) + 2 * frame;
      const tall = (Math.max(...ys) - Math.min(...ys)) + 2 * frame;
      window.__theStageCanvas.lookAt({
        x: (Math.min(...xs) + Math.max(...xs)) / 2,
        y: (Math.min(...ys) + Math.max(...ys)) / 2,
        zoom: Math.max(wide / box.width, tall / box.height),
      });
    }, { fields });
    await rest(9000);

    const boxes = await page.evaluate(({ fields: held }) => {
      const host = document.querySelector("#stage-canvas").getBoundingClientRect();
      const where = (x, y) => {
        const put = window.__theStageCanvas.project(x, y);
        const at = Array.isArray(put) ? { x: put[0], y: put[1] } : put;
        return { x: at.x + host.left, y: at.y + host.top };
      };
      return held.map((at) => {
        const half = at.frameUm / 2;
        const a = where(at.x - half, at.y - half);
        const b = where(at.x + half, at.y + half);
        return {
          x: at.x, y: at.y,
          left: Math.min(a.x, b.x), right: Math.max(a.x, b.x),
          top: Math.min(a.y, b.y), bottom: Math.max(a.y, b.y),
        };
      });
    }, { fields });

    /* A photograph of every well would be ninety-six pictures; a handful,
       spread across the plate, is enough to look at. All of them are still
       measured. */
    const worthKeeping = which < 3 || which === looking.length - 1
      || which === Math.floor(looking.length / 2);
    const shot = path.join(SHOTS, `well-${well.replace(",", "x")}.png`);
    if (worthKeeping) await page.screenshot({ path: shot });
    const pixels = readPng(
      worthKeeping ? fs.readFileSync(shot) : await page.screenshot(),
    );

    for (const box of boxes) {
      counted += 1;
      const share = drawnWithin(pixels, box);
      if (share === null || share < 0.5) missing.push({ well, x: box.x, y: box.y, share });
    }
    if ((which + 1) % 12 === 0) {
      console.log(`looked at ${which + 1} wells, ${counted} fields, ${missing.length} not drawn`);
    }
  }

  console.log(`looked at ${counted} fields in ${looking.length} wells; `
    + `${missing.length} not drawn`);
  if (missing.length) console.log("not drawn:", JSON.stringify(missing.slice(0, 20)));
  expect(missing, `${missing.length} of ${counted} fields were not drawn`).toEqual([]);
});
