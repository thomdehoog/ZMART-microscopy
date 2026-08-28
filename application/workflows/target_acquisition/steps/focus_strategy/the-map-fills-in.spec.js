/**
 * The focus map fills in as each point is measured, not all at once at the end.
 *
 * Against the real bridge on the mock microscope. The rows in the list are
 * counted while the run is going: what has to be true is that the count is
 * seen at more than one value before the run ends. A map that appears whole
 * when the run finishes is seen at one.
 */

import { expect, test } from "@playwright/test";
import { rest, startTheBridge } from "../scan_the_overview/live-bridge.js";

const PORT = Number(process.env.LIVE_FOCUS_PORT ?? 8809);

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

test("points appear in the list one at a time while the map is measured", async ({ page }) => {
  test.setTimeout(300_000);

  await page.goto(process.env.BUILT_PAGE ? `http://127.0.0.1:${PORT}/` : `/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);
  await gotoStep(page, "Define scan area");
  await record(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);
  await gotoStep(page, "Focus strategy");
  await record(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);

  await page.locator(".panel.on button.step-run").click();

  /* The rows are there from the moment the points are laid; what a measured
     point changes is its height, from nothing to a number. So it is heights
     that are counted, sampled while the run goes. */
  const counts = new Set();
  const until = Date.now() + 120_000;
  do {
    const rows = await page.locator("#focus-traces .point-row").allTextContents();
    counts.add(rows.filter((t) => /\d µm/.test(t)).length);
    if (!(await page.locator(".panel.on button.step-run").textContent()).includes("working")) break;
    await rest(100);
  } while (Date.now() < until);

  const seen = [...counts].sort((a, b) => a - b);
  console.log(`heights seen while measuring: ${seen.join(", ")}`);
  expect(seen.length, `the map appeared all at once: heights seen ${seen}`).toBeGreaterThan(2);
});
