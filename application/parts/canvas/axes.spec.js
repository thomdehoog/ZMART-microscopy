/**
 * The Z and T sliders under the picture, on a real stack timelapse.
 *
 * A small picture is written the way a run writes one -- three planes deep,
 * four moments long -- served to the built page, and opened as the picture.
 * Both sliders should stand under it, Z above T, across its whole width;
 * each moved should move the picture, which is checked on the pixels rather
 * than on the control. A flat picture of one moment, opened the same way,
 * should show neither.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge, rest, startTheBridge }
  from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { photograph } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..", "..");
const PORT = Number(process.env.AXES_BRIDGE_PORT ?? 8891);

/** A picture written to a folder of its own, and a server that hands its
 *  files to the page from another origin, as the viewer beside the bridge
 *  would. */
async function aPictureServed(frames, planes) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-timelapse-"));
  const store = execFileSync(pythonForTheBridge(),
    [path.join(HERE, "fixtures", "write-a-timelapse.py"), folder, String(frames), String(planes)],
    { cwd: REPO, encoding: "utf8" }).trim();
  const server = http.createServer((request, response) => {
    const asked = path.normalize(decodeURIComponent(new URL(request.url, "http://x").pathname));
    const file = path.join(folder, asked);
    response.setHeader("Access-Control-Allow-Origin", "*");
    if (!file.startsWith(folder) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      response.statusCode = 404;
      response.end();
      return;
    }
    response.setHeader("Content-Type", "application/octet-stream");
    fs.createReadStream(file).pipe(response);
  });
  await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
  const at = `http://127.0.0.1:${server.address().port}/${path.relative(folder, store).split(path.sep).join("/")}/|zarr3:`;
  return { at, stop: () => server.close() };
}

function pixelsDiffering(a, b) {
  let changed = 0;
  for (let at = 0; at < Math.min(a.data.length, b.data.length); at += a.channels) {
    if ([0, 1, 2].some((c) => Math.abs(a.data[at + c] - b.data[at + c]) > 24)) changed += 1;
  }
  return changed;
}

const slide = (page, id, to) => page.locator(`#${id}`).evaluate((slider, value) => {
  slider.value = String(value);
  slider.dispatchEvent(new Event("input", { bubbles: true }));
}, to);

test.describe("the sliders under the picture", () => {
  test.setTimeout(180_000);

  test("a stack timelapse gets Z above T across the picture's width, and each moves it", async ({ page }) => {
    const picture = await aPictureServed(4, 3);
    const bridge = await startTheBridge({ port: PORT, connect: false });
    try {
      await page.goto(`${bridge.at}/?picture=${encodeURIComponent(picture.at)}&engine=neuroglancer-under`);
      await expect(page.locator("#axis-t")).toBeVisible({ timeout: 60_000 });
      await expect(page.locator("#axis-z")).toBeVisible();
      await expect(page.locator("#moment-readout")).toHaveText("moment 1 of 4");
      await expect(page.locator("#plane-readout")).toContainText("of 3");

      /* Z above T, and the rows as wide as the picture's column. */
      const z = await page.locator("#axis-z").boundingBox();
      const t = await page.locator("#axis-t").boundingBox();
      const column = await page.locator(".plot-column").boundingBox();
      expect(z.y).toBeLessThan(t.y);
      expect(t.width).toBeGreaterThan(column.width * 0.9);

      await rest(2500);
      if (process.env.OPERATOR_EVIDENCE_DIR) {
        fs.mkdirSync(process.env.OPERATOR_EVIDENCE_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.OPERATOR_EVIDENCE_DIR, "axes-opened.png") });
      }
      /* The whole picture, since the square walks across it. */
      const first = await photograph(page, "#picture-host", 1);
      await slide(page, "moment", 3);
      await expect.poll(() => page.evaluate(() => window.__thePicture.theMomentsItCanShow().at)).toBe(3);
      await expect(page.locator("#moment-readout")).toHaveText("moment 4 of 4");
      await rest(2500);
      const later = await photograph(page, "#picture-host", 1);
      expect(pixelsDiffering(first, later), "the picture changed with the moment").toBeGreaterThan(200);

      await slide(page, "plane", 4);
      await expect(page.locator("#plane-readout")).toContainText("plane 3 of 3");
      await rest(2500);
      const deeper = await photograph(page, "#picture-host", 1);
      expect(pixelsDiffering(later, deeper), "the picture changed with the plane").toBeGreaterThan(200);

      /* Play walks T by itself and leaves Z alone; pressed again, it stops. */
      await page.locator("#moment-play").click();
      await expect(page.locator("#moment-play")).toHaveAttribute("aria-pressed", "true");
      await expect.poll(() => page.locator("#moment-readout").textContent(), { timeout: 5000 }).not.toBe("moment 4 of 4");
      await expect(page.locator("#plane-play")).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#plane-readout")).toContainText("plane 3 of 3");
      await page.locator("#moment-play").click();
      await expect(page.locator("#moment-play")).toHaveAttribute("aria-pressed", "false");
      const paused = await page.locator("#moment-readout").textContent();
      await rest(1200);
      expect(await page.locator("#moment-readout").textContent(), "paused, it stays").toBe(paused);
      if (process.env.OPERATOR_EVIDENCE_DIR) {
        fs.mkdirSync(process.env.OPERATOR_EVIDENCE_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.OPERATOR_EVIDENCE_DIR, "axes-stack-timelapse.png") });
      }
    } finally {
      await bridge.stop();
      picture.stop();
    }
  });

  test("a flat picture of one moment shows neither slider", async ({ page }) => {
    const picture = await aPictureServed(1, 1);
    const bridge = await startTheBridge({ port: PORT + 1, connect: false });
    try {
      await page.goto(`${bridge.at}/?picture=${encodeURIComponent(picture.at)}&engine=neuroglancer-under`);
      await expect.poll(() => page.evaluate(() => Boolean(window.__thePicture)), { timeout: 60_000 }).toBe(true);
      await rest(4000);
      await expect(page.locator("#canvas-axes")).toBeHidden();
    } finally {
      await bridge.stop();
      picture.stop();
    }
  });
});
