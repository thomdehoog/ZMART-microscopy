/** Source arrival must not replace the view chosen by the operator. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { rest, startTheBridge } from
  "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "step-five-kidney");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8813);
const A_WHOLE_RUN = 900_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

async function walkToScan(page) {
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
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);
  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => window.__theStageCanvas.plan().length)).toBe(9);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });
  await expect.poll(() => frontSourceCount(page, "focussing"), {
    timeout: 60_000,
    message: "the focusing source never opened in Smart Viewer",
  }).toBeGreaterThan(0);

  await gotoStep("Scan the overview");
  await rest(2500);
}

async function frontSourceCount(page, acquisition) {
  return page.evaluate((prefix) => (window.__thePicture?.layersForMeasurement?.() ?? [])
    .filter(({ name }) => name.startsWith(prefix))
    .reduce((count, row) => count + (row.sources?.length ?? 0), 0), acquisition);
}

async function stageSnapshot(page, name) {
  return page.evaluate((label) => {
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    const plan = window.__theStageCanvas.plan();
    const points = [0, 4, 8].map((index) => {
      const at = plan[index];
      const projected = window.__theStageCanvas.project(at.x, at.y);
      const point = Array.isArray(projected)
        ? { x: projected[0], y: projected[1] }
        : projected;
      return {
        index,
        carrierLocalUm: { x: at.x, y: at.y },
        screenPx: { x: box.left + point.x, y: box.top + point.y },
      };
    });
    return {
      name: label,
      view: window.__theStageCanvas.view(),
      canvas: {
        left: box.left, top: box.top, width: box.width, height: box.height,
      },
      points,
    };
  }, name);
}

function projectionDrift(before, after) {
  return Math.max(...before.points.map((point, index) => {
    const next = after.points[index];
    return Math.hypot(point.screenPx.x - next.screenPx.x, point.screenPx.y - next.screenPx.y);
  }));
}

function expectSameView(before, after, message) {
  expect(after.canvas, `${message}: the canvas box changed`).toEqual(before.canvas);
  expect(after.view.zoom, `${message}: zoom changed`).toBeCloseTo(before.view.zoom, 9);
  expect(after.view.centre.x, `${message}: x centre changed`).toBeCloseTo(before.view.centre.x, 6);
  expect(after.view.centre.y, `${message}: y centre changed`).toBeCloseTo(before.view.centre.y, 6);
  expect(projectionDrift(before, after), `${message}: plan projections drifted`).toBeLessThan(0.25);
}

async function absolutePlan(page) {
  return page.evaluate(() => {
    const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
    return window.__theStageCanvas.plan().map(({ x, y }) => ({ x: x + ox, y: y + oy, z: 0 }));
  });
}

test("first and later overview sources preserve pan, zoom, and whole-plate Fit", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await walkToScan(page);
  const positions = await absolutePlan(page);

  await page.locator("#fit-btn").click();
  const fittedBeforeHand = await stageSnapshot(page, "fit before the operator moves");
  const box = await page.locator("#stage-canvas").boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.5);
  await page.mouse.wheel(0, -650);
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.57, box.y + box.height * 0.56, { steps: 8 });
  await page.mouse.up();
  await rest(500);
  const chosen = await stageSnapshot(page, "operator pan and zoom before acquisition");
  expect(projectionDrift(fittedBeforeHand, chosen), "the operator gesture changed the view")
    .toBeGreaterThan(1);

  await bridge.image(positions.slice(0, 1));
  await expect.poll(() => frontSourceCount(page, "overview"), {
    timeout: 60_000,
    message: "the first overview source never opened in Smart Viewer",
  }).toBe(3);
  await rest(2000);
  const afterFirst = await stageSnapshot(page, "after source 1 of 9");
  expectSameView(chosen, afterFirst, "first source arrival");

  // The deterministic bridge call declares the complete acquisition each
  // time, so later checkpoints repeat the positions already present and add
  // the new ones. This is the same cumulative contract used by the live tile
  // arrival checks; sending only the delta would deliberately replace the
  // acquisition's record with that delta.
  await bridge.image(positions.slice(0, 8));
  await expect.poll(() => frontSourceCount(page, "overview"), {
    timeout: 60_000,
    message: "later overview sources never opened in Smart Viewer",
  }).toBe(24);
  await rest(2000);
  const afterLater = await stageSnapshot(page, "after source 8 of 9");
  expectSameView(chosen, afterLater, "later source arrival");

  await page.locator("#fit-btn").click();
  await rest(500);
  const wholePlate = await stageSnapshot(page, "whole-plate Fit before source 9");
  await bridge.image(positions);
  await expect.poll(() => frontSourceCount(page, "overview"), {
    timeout: 60_000,
    message: "the final overview source never opened in Smart Viewer",
  }).toBe(27);
  await rest(2000);
  const afterFitArrival = await stageSnapshot(page, "whole-plate Fit after source 9");
  expectSameView(wholePlate, afterFitArrival, "source arrival after Fit");
  expect(browserErrors, "source replacement raised a browser error").toEqual([]);

  fs.writeFileSync(path.join(SHOTS, "view-preservation.json"), JSON.stringify({
    fittedBeforeHand, chosen, afterFirst, afterLater, wholePlate, afterFitArrival,
    driftPx: {
      first: projectionDrift(chosen, afterFirst),
      later: projectionDrift(chosen, afterLater),
      fit: projectionDrift(wholePlate, afterFitArrival),
    },
    browserErrors,
  }, null, 2));
});
