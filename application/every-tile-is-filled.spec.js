/**
 * Every field the scan took, on the canvas — all of them, one by one.
 *
 * "The picture is there" is not the check this needs, and neither is "the
 * wells have something in them". A scan of fifty-four fields that draws
 * twenty of them looks, from far enough away, exactly like a scan that drew
 * all fifty-four: the wells are in the right places and there is tissue in
 * them. So this walks the plate well by well, puts each well's own block of
 * fields across the canvas, and asks of **each field separately** whether
 * anything was drawn where the plan says that field is.
 *
 * The focussing is hidden throughout and the plan faded away, so what is
 * measured is the acquired overview and nothing else.
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
const SHOTS = path.join(HERE, "test-results", "every-tile");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8808);

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/**
 * How much of one field's square on screen carries picture.
 *
 * Measured against the photograph's own corner rather than a colour written
 * down here, because what the page paints behind the picture belongs to the
 * stylesheet. A little inside the field's edge, so that a neighbouring field
 * bleeding over the boundary cannot be mistaken for this one.
 */
function drawnWithin(pixels, box) {
  const { data, width, height, channels } = pixels;
  const corner = [data[0], data[1], data[2]];
  const edges = [box.left, box.right, box.top, box.bottom];
  if (!edges.every(Number.isFinite)) return { error: "unprojectable" };
  if (box.left < 0 || box.top < 0 || box.right > width || box.bottom > height) {
    return { error: "off-screen" };
  }
  const inset = 0.25;
  const left = Math.round(box.left + (box.right - box.left) * inset);
  const right = Math.round(box.right - (box.right - box.left) * inset);
  const top = Math.round(box.top + (box.bottom - box.top) * inset);
  const bottom = Math.round(box.bottom - (box.bottom - box.top) * inset);
  if (right <= left || bottom <= top) return { error: "unprojectable" };
  let drawn = 0;
  let looked = 0;
  const shades = new Set();
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const at = (y * width + x) * channels;
      looked += 1;
      if (Math.abs(data[at] - corner[0]) > 10
        || Math.abs(data[at + 1] - corner[1]) > 10
        || Math.abs(data[at + 2] - corner[2]) > 10) drawn += 1;
      shades.add(data[at] >> 2);
    }
  }
  return looked
    ? { covered: drawn / looked, shades: shades.size }
    : { error: "unprojectable" };
}

/** Frame one well using the same pan/wheel gestures available to an operator. */
async function frameAround(page, centre, targetZoom) {
  const where = () => page.evaluate(({ at }) => {
    const projected = window.__theStageCanvas.project(at.x, at.y);
    const point = Array.isArray(projected)
      ? { x: projected[0], y: projected[1] }
      : projected;
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    return {
      x: box.left + point.x,
      y: box.top + point.y,
      canvas: {
        left: box.left, top: box.top, right: box.right, bottom: box.bottom,
        x: box.left + box.width / 2, y: box.top + box.height / 2,
      },
    };
  }, { at: centre });

  for (let turn = 0; turn < 16; turn += 1) {
    const zoom = await page.evaluate(() => window.__theStageCanvas.view().zoom);
    if (zoom <= targetZoom) break;
    const anchor = await where();
    await page.mouse.move(anchor.x, anchor.y);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(100);
  }
  await expect.poll(
    () => page.evaluate(() => window.__theStageCanvas.view().zoom),
    { message: `the well never reached ${targetZoom} um per pixel` },
  ).toBeLessThanOrEqual(targetZoom);

  for (let turn = 0; turn < 40; turn += 1) {
    const now = await where();
    const dx = now.canvas.x - now.x;
    const dy = now.canvas.y - now.y;
    if (Math.abs(dx) < 2 && Math.abs(dy) < 2) break;
    const startX = Math.min(Math.max(now.x, now.canvas.left + 20), now.canvas.right - 20);
    const startY = Math.min(Math.max(now.y, now.canvas.top + 20), now.canvas.bottom - 20);
    const movedX = Math.max(now.canvas.left + 20 - startX,
      Math.min(now.canvas.right - 20 - startX, dx));
    const movedY = Math.max(now.canvas.top + 20 - startY,
      Math.min(now.canvas.bottom - 20 - startY, dy));
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + movedX, startY + movedY, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(150);
  }
  await expect.poll(async () => {
    const now = await where();
    return Math.hypot(now.canvas.x - now.x, now.canvas.y - now.y);
  }, { message: "the well never reached the canvas centre" }).toBeLessThan(2);
  await page.mouse.move(4, 4);
}

test("every field the scan took is drawn where the plan put it", async ({ page }) => {
  test.setTimeout(900_000);
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
  await rest(30_000);

  /* Only the overview, using the same control an operator sees, and nothing
     of the plan over it. Layer order is presentation state; hiding focussing
     must not alter any source's Z anchor or the overview underneath. */
  const focussingEye = page.locator(
    '.viewer-panel button[data-acquisition="focussing"]',
  );
  await expect(focussingEye).toHaveAttribute("data-on", "1");
  await focussingEye.click();
  await expect(focussingEye).toHaveAttribute("data-on", "0");
  await expect(page.locator('.viewer-panel button[data-acquisition="overview"]'))
    .toHaveAttribute("data-on", "1");
  await expect.poll(() => page.evaluate(() => {
    const rows = window.__thePicture.layersForMeasurement();
    return rows.filter(({ name }) => name.startsWith("focussing"))
      .every(({ visible }) => !visible)
      && rows.filter(({ name }) => name.startsWith("overview"))
        .every(({ visible }) => visible);
  }), { message: "the panel never left only the overview visible" }).toBe(true);
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0));
  await rest(4000);

  /* The plate's fields, gathered into the wells they belong to. */
  const wells = await page.evaluate(() => {
    const gathered = new Map();
    for (const at of window.__theStageCanvas.plan()) {
      const key = `${Math.round(at.x / 20000)},${Math.round(at.y / 20000)}`;
      const held = gathered.get(key) ?? [];
      held.push(at);
      gathered.set(key, held);
    }
    return [...gathered.entries()].map(([key, held]) => ({ well: key, fields: held }));
  });
  console.log("wells:", wells.map((w) => `${w.well}:${w.fields.length}`).join(" "));

  const missing = [];
  let counted = 0;

  for (const { well, fields } of wells) {
    /* This well's own block across the canvas, so each field is a good many
       screen pixels rather than a speck. */
    const framing = await page.evaluate(({ fields: held }) => {
      const xs = held.map((at) => at.x);
      const ys = held.map((at) => at.y);
      const frame = held[0].frameUm;
      const box = document.querySelector("#stage-canvas").getBoundingClientRect();
      const wide = (Math.max(...xs) - Math.min(...xs)) + 2 * frame;
      const tall = (Math.max(...ys) - Math.min(...ys)) + 2 * frame;
      return {
        centre: {
          x: (Math.min(...xs) + Math.max(...xs)) / 2,
          y: (Math.min(...ys) + Math.max(...ys)) / 2,
        },
        zoom: Math.max(wide / box.width, tall / box.height),
      };
    }, { fields });
    await frameAround(page, framing.centre, framing.zoom);
    await rest(14_000);

    /* Where each field of this well lands in the photograph. The whole box
       is photographed rather than its middle, because the fields reach the
       edges of it. */
    /* Where each field of this well lands in the photograph.
     *
     * The photograph is of the whole window, not of the canvas box on its
     * own, and that is not a detail: the engine draws on a WebGL surface,
     * and an element screenshot of the box it lives in comes back without
     * it — measured, and it is exactly how a picture that was plainly on
     * screen was once counted as blank. `project` answers in the window's
     * own coordinates, which is what a whole-window photograph is in too,
     * so nothing has to be shifted. */
    const boxes = await page.evaluate(({ fields: held }) => {
      /* `project` answers with a pair, and a pair is what has to be read: an
         earlier version of this read `.x` and `.y` off it, got nothing, and
         quietly measured every field as undrawn — a test that fails for a
         reason that has nothing to do with the picture is worse than no test. */
      /* `project` answers in the canvas box's own pixels, and the photograph
         is of the whole window, so where the box sits in the window is added
         back on. Left out, every field was measured against a patch of the
         step rail on the far left, which is never picture and so read as
         nothing drawn. */
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

    const shot = path.join(SHOTS, `well-${well.replace(",", "x")}.png`);
    await page.screenshot({ path: shot });
    const pixels = readPng(fs.readFileSync(shot));
    if (well === wells[0].well) {
      console.log("first well, first field box:", JSON.stringify(boxes[0]),
        "photograph:", pixels.width, "x", pixels.height);
    }

    for (const box of boxes) {
      counted += 1;
      const result = drawnWithin(pixels, box);
      if (result.error || result.covered < 0.5 || result.shades < 8) {
        missing.push({ well, x: box.x, y: box.y, result });
      }
    }
  }

  console.log(`looked at ${counted} fields; ${missing.length} not drawn`);
  if (missing.length) {
    console.log("not drawn:", JSON.stringify(missing.slice(0, 20), null, 1));
  }
  expect(counted, "every field of the plan was looked at").toBe(54);
  expect(missing, `${missing.length} of ${counted} fields were not drawn`).toEqual([]);
});
