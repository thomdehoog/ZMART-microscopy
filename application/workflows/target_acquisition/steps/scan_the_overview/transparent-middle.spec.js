import { expect, test } from "@playwright/test";
import { startTheBridge } from "./live-bridge.js";
import { readPng } from "./pixels.js";

let bridge;
test.beforeAll(async () => { bridge = await startTheBridge({ port: 8893 }); });
test.afterAll(async () => { await bridge?.stop(); });

test("Connect opens an empty middle viewer; focusing and overview fill it above the plan", async ({ page }, info) => {
  test.setTimeout(300_000);
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.goto(`/?bridge=${encodeURIComponent(bridge.at)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await page.waitForFunction(() => !!window.__thePicture, null, { timeout: 60_000 });
  await page.evaluate(() => { window.firstPicture = window.__thePicture; });
  const order = await page.evaluate(() => {
    const host = document.getElementById("picture-host");
    return {
      parent: !!host.closest("#stage-canvas"),
      below: getComputedStyle(host.previousElementSibling).zIndex,
      middle: getComputedStyle(host).zIndex,
      above: getComputedStyle(host.nextElementSibling).zIndex,
      images: window.__thePicture.layersForMeasurement().length,
    };
  });
  expect(order).toEqual({ parent: true, below: "0", middle: "1", above: "2", images: 0 });
  const keys = await page.evaluate(() => window.__theStageCanvas.layers().map(layer => layer.key));
  expect(keys.indexOf("focus")).toBeLessThan(keys.indexOf("plan"));
  for (const key of ["tiles", "focusPoints", "editing", "stage"]) {
    expect(keys.indexOf(key)).toBeGreaterThan(keys.indexOf("plan"));
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
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await step("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.locator(".panel.on button.step-run").click();
  await page.waitForFunction(() => window.__thePicture?.layersForMeasurement().length > 0, null, { timeout: 120_000 });
  expect(await page.evaluate(() => window.firstPicture === window.__thePicture)).toBe(true);
  await expect(page.locator(".panel.on button.step-run")).not.toHaveClass(/running/, { timeout: 120_000 });
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
  expect(await page.evaluate(() => window.__theStageCanvas.groundWindows())).toEqual([]);

  await step("Scan the overview");
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run")).not.toHaveClass(/running/, { timeout: 120_000 });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: info.outputPath("step-5-overview.png") });
  expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);
  expect(await page.evaluate(() => window.__theStageCanvas.groundWindows())).toEqual([]);

  // A conspicuous lower surface and an upper mark: photograph the actual
  // compositor, not an alpha value that CSS could still cover up.
  await page.evaluate(() => {
    const host = document.getElementById("picture-host");
    const below = document.createElement("div");
    below.style.cssText = "position:absolute;inset:0;background:#ff00ff;z-index:0;pointer-events:none";
    host.before(below);
    const above = document.createElement("div");
    above.textContent = "ABOVE: operator annotations";
    above.style.cssText = "position:absolute;left:35%;top:45%;background:#ff8800;color:black;padding:12px;z-index:3;pointer-events:none";
    host.after(above);
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
  console.log(JSON.stringify({ order, below, above, image, imageOnly }));
});
