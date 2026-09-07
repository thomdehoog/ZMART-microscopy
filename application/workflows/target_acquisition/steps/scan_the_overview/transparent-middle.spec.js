import { expect, test } from "@playwright/test";
import { operateTheInstrument, startTheBridge } from "./live-bridge.js";
import { readPng } from "./pixels.js";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let bridge;
let previousMachine;
let previousState;
test.beforeAll(async () => {
  previousMachine = process.env.ZMART_MOCK_MACHINE;
  previousState = process.env.ZMART_MOCK_STATE;
  // A configuration walk may have published a different stage origin.
  process.env.ZMART_MOCK_MACHINE = mkdtempSync(join(tmpdir(), "transparent-machine-"));
  process.env.ZMART_MOCK_STATE = join(process.env.ZMART_MOCK_MACHINE, "instrument.json");
  bridge = await startTheBridge({ port: 8893 });
});
test.afterAll(async () => {
  await bridge?.stop();
  if (previousMachine === undefined) delete process.env.ZMART_MOCK_MACHINE;
  else process.env.ZMART_MOCK_MACHINE = previousMachine;
  if (previousState === undefined) delete process.env.ZMART_MOCK_STATE;
  else process.env.ZMART_MOCK_STATE = previousState;
});

test("Connect opens an empty middle viewer; focusing and overview fill it above the plan", async ({ page }, info) => {
  test.setTimeout(300_000);
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto(process.env.ZMART_TEST_BUILT ? bridge.at : `/?bridge=${encodeURIComponent(bridge.at)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await page.waitForFunction(() => !!window.__thePicture, null, { timeout: 60_000 });
  await page.evaluate(() => { window.firstPicture = window.__thePicture; });
  const order = await page.evaluate(() => {
    const host = document.getElementById("picture-host");
    const slot = host.parentElement;
    return {
      parent: !!host.closest("#stage-canvas"),
      below: getComputedStyle(slot.previousElementSibling).zIndex,
      middle: getComputedStyle(slot).zIndex,
      above: getComputedStyle(slot.nextElementSibling).zIndex,
      images: window.__thePicture.layersForMeasurement().length,
    };
  });
  expect(order).toEqual({ parent: true, below: "0", middle: "1", above: "2", images: 0 });
  const keys = await page.evaluate(() => window.__theStageCanvas.layers().map(layer => layer.key));
  expect(keys.indexOf("focus")).toBeLessThan(keys.indexOf("plan"));
  expect(keys.indexOf("plan")).toBeLessThan(keys.indexOf("picture"));
  for (const key of ["tiles", "focusPoints", "editing", "stage"]) {
    expect(keys.indexOf(key)).toBeGreaterThan(keys.indexOf("picture"));
  }
  const step = name => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (id, name) => {
    const bar = page.locator(`#${id} .setting-box.open`);
    if (await bar.locator("input").count()) await bar.locator("input").fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(700);
  };
  await step("Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await step("Overview scan area");
  operateTheInstrument("choose", "Overview");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await step("Focus strategy");
  operateTheInstrument("choose", "Focussing");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  const focusCount = await page.evaluate(() => window.__theRunState().focus.points);
  expect(focusCount).toBeGreaterThan(0);
  await page.locator(".panel.on button.step-run").click();
  await page.waitForFunction(() => window.__thePicture?.layersForMeasurement().length > 0, null, { timeout: 120_000 });
  expect(await page.evaluate(() => window.firstPicture === window.__thePicture)).toBe(true);
  await expect(page.locator(".panel.on button.step-run")).not.toHaveClass(/running/, { timeout: 120_000 });
  const focus = await (await page.request.get(`${bridge.at}/api/focus/measure`)).json();
  expect(focus).toMatchObject({ running: false, error: null, stopped: false, done: focusCount, of: focusCount });
  expect(focus.points).toHaveLength(focusCount);
  for (const point of focus.points) {
    expect(point.lost, JSON.stringify(point)).toBe(false);
    expect(point.slices.length).toBeGreaterThan(0);
  }
  expect(await page.evaluate(() => window.__thePicture.theMomentsItCanShow())).toBeNull();
  await page.waitForTimeout(3500);
  const box = await page.locator("#stage-canvas").boundingBox();
  const at = await page.evaluate(() => {
    const p = window.__theStageCanvas.plan()[0];
    return window.__theStageCanvas.project(p.x,p.y);
  });
  await page.mouse.move(box.x+at[0], box.y+at[1]);
  await page.mouse.wheel(0,-2200);
  await page.waitForTimeout(1800);
  await page.screenshot({ path: info.outputPath("step-4-focus.png") });
  expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);

  await step("Scan the overview");
  await page.locator("#tileset-btn").click();
  const planned = await page.evaluate(() => window.__theStageCanvas.plan().length);
  expect(planned).toBeGreaterThan(0);
  // Acquire one real field. This gives the pixel assertion
  // a stable partial plan rather than racing the mock's acquisition speed.
  const firstField = await page.evaluate(() => {
    const { centre } = window.__theStageCanvas.view();
    const nearest = window.__theStageCanvas.plan().reduce((a, b) =>
      Math.hypot(a.x - centre.x, a.y - centre.y) < Math.hypot(b.x - centre.x, b.y - centre.y) ? a : b);
    const { x, y } = nearest;
    const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
    return { x: x + ox, y: y + oy, z: window.__theStageCanvas.focusZAt(x, y) };
  });
  operateTheInstrument("choose", "Overview");
  const preview = await bridge.image([firstField]);
  expect(preview).toMatchObject({ running: false, error: null, stopped: false, done: 1, of: 1 });
  expect(preview.records).toHaveLength(1);
  expect(preview.records.filter(record => record.zarr_error)).toEqual([]);
  await page.waitForFunction(() => window.__thePicture.layersForMeasurement().some(
    row => row.name.startsWith("overview") && row.dims?.length,
  ));
  // Adding the first overview row changes the panel layout. Take the hidden
  // reference afterwards so both photographs use the same canvas geometry.
  await page.evaluate(() => window.__thePicture.showPicture(false));
  const beforeScan = readPng(await page.locator("#stage-canvas").screenshot({ path: info.outputPath("step-5-plan.png") }));
  await page.evaluate(() => window.__thePicture.showPicture(true));
  // Validate the saved frame, not just metadata. Dark specimen pixels must
  // cover the previously coloured plan while some of that plan stays visible.
  await expect.poll(async () => {
    const shot = readPng(await page.locator("#stage-canvas").screenshot({ path: info.outputPath("step-5-partial.png") }));
    expect([shot.width, shot.height]).toEqual([beforeScan.width, beforeScan.height]);
    let acquired = 0, unchangedPlan = 0;
    for (let i = 0; i < shot.data.length; i += shot.channels) {
      const [r, g, b] = beforeScan.data.subarray(i, i + 3);
      if (!(r > 80 && g > r + 5 && b > r + 5)) continue;
      const [nowR, nowG, nowB] = shot.data.subarray(i, i + 3);
      if (Math.max(nowR, nowG, nowB) < 15) acquired++;
      if (Math.abs(r - nowR) + Math.abs(g - nowG) + Math.abs(b - nowB) < 5) unchangedPlan++;
    }
    return acquired > 1000 && unchangedPlan > 1000;
  }, { timeout: 30_000 }).toBe(true);
  expect(preview.done).toBeLessThan(planned);
  expect(await page.evaluate(() => window.__thePicture.theMomentsItCanShow())).toBeNull();
  await page.waitForFunction(() => window.__viewerPanel?.acquisitions().some(row => row.name === "overview"));
  expect(await page.evaluate(() => window.firstPicture === window.__thePicture)).toBe(true);
  expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);

  // A conspicuous lower surface and an upper mark: photograph the actual
  // compositor, not an alpha value that CSS could still cover up.
  await page.evaluate(() => {
    const host = document.getElementById("picture-host");
    const slot = host.parentElement;
    const below = document.createElement("div");
    below.style.cssText = "position:absolute;inset:0;background:#ff00ff;z-index:0;pointer-events:none";
    slot.before(below);
    const above = document.createElement("div");
    above.textContent = "ABOVE: operator annotations";
    above.style.cssText = "position:absolute;left:35%;top:45%;background:#ff8800;color:black;padding:12px;z-index:3;pointer-events:none";
    slot.after(above);
  });
  const screenshot = await page.locator("#stage-canvas").screenshot({ path: info.outputPath("three-layers.png") });
  const { data, channels } = readPng(screenshot);
  let below = 0, above = 0, image = 0;
  for (let i = 0; i < data.length; i += channels) {
    const [r,g,b] = data.subarray(i,i+3);
    if (r === 255 && g === 0 && b === 255) below++;
    else if (r === 255 && g === 136 && b === 0) above++;
    else if (Math.max(r,g,b) > 45) image++;
  }
  expect(below).toBeGreaterThan(1000);
  expect(above).toBeGreaterThan(1000);
  expect(image).toBeGreaterThan(1000);
  await page.evaluate(() => window.__thePicture.showPicture(false));
  await page.waitForTimeout(300);
  const hidden = readPng(await page.locator("#stage-canvas").screenshot());
  let imageOnly = 0;
  for (let i=0;i<data.length;i+=channels) {
    if (Math.abs(data[i]-hidden.data[i]) + Math.abs(data[i+1]-hidden.data[i+1])
        + Math.abs(data[i+2]-hidden.data[i+2]) > 30) imageOnly++;
  }
  expect(imageOnly).toBeGreaterThan(1000);
  await page.evaluate(() => window.__thePicture.showPicture(true));
  expect(errors).toEqual([]);
  await info.attach("pixel-measurements", {
    body: JSON.stringify({ order, below, above, image, imageOnly }), contentType: "application/json",
  });
});
