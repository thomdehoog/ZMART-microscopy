/**
 * A photograph of the viewer panel standing in the canvas row.
 *
 * Not an assertion suite: this walks the pretend run far enough to have the
 * canvas on screen, mounts the panel the way `watching-the-run` does, and
 * photographs the page open and folded — the check that the layout holds is
 * a person (or their agent) looking at the pictures. It exists because the
 * panel's first appearance was shipped unphotographed, and the canvas grid
 * quietly wrapped it onto a second row.
 */
import { expect, test } from "@playwright/test";

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

async function recordSlot(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(650);
}

test("the panel stands between the picture and the channel", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/?backend=pretend");
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(300);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(400);

  await page.evaluate(async () => {
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    const sources = Array.from(
      { length: 9 },
      (_, at) => `http://127.0.0.1:9/data/0/overview_P${String(at).padStart(6, "0")}.ome.zarr/|zarr3:`,
    );
    await mountViewerPanel(document.querySelector("#picture-host"), {
      viewer: { setChannel: () => {} },
      acquisitions: [
        {
          url: sources[0],
          name: "overview",
          channels: [0, 1, 2].map((channel) => ({
            name: `channel ${channel}`,
            colour: [0, channel / 2, 1],
            window: { low: 192, high: 2575 },
            channelIndex: channel,
            sources,
          })),
        },
      ],
    });
  });
  await page.waitForTimeout(600);
  const panel = page.locator(".viewer-panel");
  await expect(panel.locator("[data-channel-row]")).toHaveCount(3);
  await expect(panel.locator('[data-channel-row="channel 0"]')).toHaveCount(1);
  await expect(panel.locator('[data-channel-row="channel 1"]')).toHaveCount(1);
  await expect(panel.locator('[data-channel-row="channel 2"]')).toHaveCount(1);
  await page.screenshot({ path: "test-results/viewer-panel-open.png", fullPage: true });

  await page.locator(".viewer-panel button").first().click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: "test-results/viewer-panel-folded.png", fullPage: true });
});
