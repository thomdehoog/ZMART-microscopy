/**
 * Interrupt stops the focus map between two points.
 *
 * Against the real bridge on the mock microscope. Nothing asks the
 * microscope to stop: the run's own loop is told, and it does not drive to
 * the next point. The points measured stand; the rest stay rows with no
 * height. A press that reached only the page and not the loop measured every
 * point anyway, and the map ended as if nobody had pressed anything.
 */

import { expect, test, type Page } from "@playwright/test";
import { operateTheInstrument, rest, startTheBridge } from "../../testing/live-bridge.ts";

const PORT = Number(process.env.LIVE_FOCUS_PORT ?? 8809);

let bridge: Awaited<ReturnType<typeof startTheBridge>> | null = null;
test.beforeAll(async () => { bridge = await startTheBridge({ port: PORT }); });
test.afterAll(async () => { await bridge?.stop(); });

const gotoStep = (page: Page, name: string) => page.locator(`.step:has-text("${name}")`).first().click();

async function record(page: Page, host: string, name: string) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(800);
}

const heights = async (page: Page) =>
  (await page.locator("#focus-traces .point-row").allTextContents()).filter((t) => /\d µm/.test(t)).length;

test("Interrupt ends the focus map between two points", async ({ page }) => {
  test.setTimeout(300_000);

  await page.goto(process.env.BUILT_PAGE ? `http://127.0.0.1:${PORT}/` : `/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);
  await gotoStep(page, "Overview scan area");
  operateTheInstrument("choose", "Overview");
  await record(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);
  await gotoStep(page, "Focus strategy");
  operateTheInstrument("choose", "Focussing");
  await record(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);

  const press = page.locator(".panel.on button.step-run");
  await press.click();
  await expect.poll(() => heights(page), { timeout: 120_000 }).toBeGreaterThan(0);
  /* The rows appear as the run reaches them; how many points it is to
     measure is the count in its progress box. */
  const count = (await page.locator("#focus-count").textContent()) ?? "";
  const rows = Number(/of (\d+)/.exec(count)?.[1]);
  expect(rows, `too few points for an interruption to show (${count})`).toBeGreaterThan(3);
  /* While the map runs, the brake stands in its Rerun cell. */
  await page.locator("#fp-rerun").click();

  const until = Date.now() + 120_000;
  while (((await press.getAttribute("class")) ?? "").includes("running") && Date.now() < until) await rest(100);

  const measured = await heights(page);
  console.log(`points measured before the run stopped: ${measured} of ${rows}`);
  expect(measured, "the run measured every point after Interrupt").toBeLessThan(rows);
});
