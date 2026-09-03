/**
 * Move a measured focus point, and its curve goes: what was read for it was
 * read where it used to be. The plot is photographed before and after the
 * drag, and what has to be true is that the curve is gone -- not merely that
 * a message appeared over it, which is what used to happen.
 */

import { expect, test } from "@playwright/test";
import { rest, startTheBridge } from "../scan_the_overview/live-bridge.js";

const PORT = Number(process.env.LIVE_MOVE_PORT ?? 8813);

let bridge = null;
test.beforeAll(async () => { bridge = await startTheBridge({ port: PORT }); });
test.afterAll(async () => { await bridge?.stop(); });

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

async function record(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(800);
}

/**
 * How many pixels of the plot's own bitmap carry a curve.
 *
 * Read off the canvas itself rather than photographed: the notice that
 * replaces a curve is an opaque panel over the canvas, so a photograph of the
 * region shows the notice whatever the canvas holds -- and what has to be
 * true is that the canvas was wiped, not that something now covers it. The
 * curves are blue and green; only pixels with colour in them count.
 */
async function drawnPixels(page) {
  return page.evaluate(() => {
    const cv = document.getElementById("trace-canvas");
    const { data, width, height } = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height);
    let coloured = 0;
    for (let i = 0; i < width * height; i++) {
      const r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2];
      if (Math.max(r, g, b) - Math.min(r, g, b) > 40) coloured++;
    }
    return coloured;
  });
}

test("a moved point loses its curve", async ({ page }) => {
  test.setTimeout(300_000);

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);
  await gotoStep(page, "Overview scan area");
  await record(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);
  await gotoStep(page, "Focus strategy");
  await record(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  /* The class, not the label: the button says "Interrupt" while a stoppable
     run is out, so waiting for "working" to leave the prose returned before
     the run had measured a thing. */
  await expect(page.locator(".panel.on button.step-run")).not.toHaveClass(/\brunning\b/, { timeout: 120_000 });
  await rest(500);

  const before = await drawnPixels(page);
  expect(before, "a measured point has a curve").toBeGreaterThan(200);

  // Points are taken hold of with the pick tool. It toggles, so it is pressed
  // only if it is not already on.
  const pick = page.locator("#fp-pick");
  if (!(await pick.getAttribute("class") ?? "").includes("on")) await pick.click();
  await rest(200);
  // Drag the selected point a little way across the stage.
  const at = await page.evaluate(() => {
    const p = window.__theFocusPoints?.();
    return p ? window.__theStageCanvas.project(p.x, p.y) : null;
  });
  expect(at, "the page says where the point is").not.toBeNull();
  const box = await page.locator("#stage-canvas").boundingBox();
  const x = box.x + at[0], y = box.y + at[1];
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 25, y + 25, { steps: 8 });
  await page.mouse.up();
  await rest(300);

  const after = await drawnPixels(page);
  await expect(page.locator("#trace-empty")).toContainText("moved");
  expect(after, `the curve stayed on the plot: ${before}px -> ${after}px`).toBeLessThan(before / 4);
});
