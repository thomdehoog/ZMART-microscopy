/**
 * The operator's window, photographed at every step from Connect to a
 * scanned overview.
 *
 * Not a check of anything: a record of what somebody actually sees as they
 * walk the workflow on the mock instrument, one photograph per step, so the
 * whole run can be looked at rather than described.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  rest, startTheBridge,
} from "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "step-by-step");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8805);

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

test("the whole walk, one photograph per step", async ({ page }) => {
  test.setTimeout(900_000);
  const shot = async (name) => {
    await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
    console.log("photographed", name);
  };
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await rest(1500);
  await shot("1a-connect-before");

  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });
  await rest(1200);
  await shot("1b-connect-done");

  await gotoStep("Define Carrier");
  await rest(800);
  await shot("2a-carrier-before");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await rest(1200);
  await shot("2b-carrier-chosen");

  await gotoStep("Define scan area");
  await rest(800);
  await shot("3a-scan-area-before");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await rest(1200);
  await shot("3b-scan-area-tiled");

  await gotoStep("Focus strategy");
  await rest(800);
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await rest(800);
  await shot("4a-focus-points-placed");
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });
  await rest(2000);
  await shot("4b-focus-measured");

  await gotoStep("Scan the overview");
  await rest(1500);
  await shot("5a-scan-before-start");
  await page.locator(".panel.on button.step-run").click();
  /* Part way through, so the picture can be seen arriving rather than only
     at the end. */
  await rest(20_000);
  await shot("5b-scan-part-way");
  await expect
    .poll(async () => page.evaluate(async (port) => {
      const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
      return !scan.running;
    }, PORT), { timeout: 400_000, message: "the scan never finished" })
    .toBe(true);
  await rest(30_000);
  await shot("5c-scan-finished");

  /* And the same picture with the plan faded back, which is how an operator
     looks at what was actually acquired. */
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
  await rest(8000);
  await shot("5d-scan-plan-faded");

  /* Then in close, on one well. */
  await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    const first = plan[0];
    window.__theStageCanvas.lookAt({ x: first.x, y: first.y, zoom: 6 });
  });
  await rest(15_000);
  await shot("5e-one-well-close");
});
