import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const fixture = fileURLToPath(new URL("./fixtures/write-coverage-source.py", import.meta.url));
const count = (shot, colour) => {
  let pixels = 0;
  for (let i = 0; i < shot.data.length; i += shot.channels) {
    if (colour.every((value, c) => Math.abs(shot.data[i + c] - value) < 20)) pixels++;
  }
  return pixels;
};

test("coverage preserves black pixels, transparent gaps and additive channels across a revision", async ({ page }, info) => {
  test.setTimeout(90_000);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "coverage-"));
  const write = (...args) => execFileSync(pythonForTheBridge(), [fixture, folder, ...args]);
  write();
  const chunks = [];
  const server = http.createServer((request, response) => {
    const relative = decodeURIComponent(new URL(request.url, "http://x").pathname).slice(1);
    const file = path.resolve(folder, relative);
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Cache-Control", "no-store");
    if (!file.startsWith(folder + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404).end();
      return;
    }
    if (relative.includes("/c/")) chunks.push(relative);
    fs.createReadStream(file).pipe(response);
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  try {
    await page.goto("/?backend=pretend");
    await page.evaluate(async origin => {
      const below = document.createElement("div");
      below.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:999;background:magenta";
      const host = document.createElement("div");
      host.id = "coverage-host";
      host.style.cssText = "width:100%;height:100%";
      below.append(host);
      document.body.append(below);
      const { openerFor } = await import("/parts/canvas/engines.js");
      window.coveredAcquisition = revision => [{ name: "overview", opaque: false,
        channels: [[1, 0, 0], [0, 1, 0]].map((colour, channelIndex) => ({
          name: String(channelIndex), channelIndex, colour, window: { low: 0, high: 255 },
          sources: [`${origin}/signal.ome.zarr/|zarr3:`],
          coverageSources: [`${origin}/signal.ome.zarr/coverage/|zarr3:`],
          sourceRevisions: [revision],
        })),
      }];
      window.coveredViewer = await (await openerFor("neuroglancer-under"))(host, {
        acquisitions: window.coveredAcquisition(1), presentation: "2d-overlay", transparentBackground: true,
      });
      window.coveredViewer.setView({ centre: { x: 128, y: 32 }, zoom: 0.5 });
    }, origin);
    const photograph = async name => readPng(await page.locator("#coverage-host").screenshot(
      name ? { path: info.outputPath(name) } : {}));
    await expect.poll(async () => count(await photograph(), [240, 240, 0])).toBeGreaterThan(1000);
    await expect.poll(async () => count(await photograph(), [0, 0, 0])).toBeGreaterThan(1000);
    const initial = await photograph("initial.png");
    expect(count(initial, [255, 0, 255])).toBeGreaterThan(10000);
    expect(chunks.some(url => url.includes("/coverage/"))).toBe(true);

    chunks.length = 0;
    write("rewrite");
    expect(await page.evaluate(() => coveredViewer.addSources(coveredAcquisition(2)))).toBe(true);
    await expect.poll(async () => count(await photograph(), [0, 0, 0]))
      .toBeGreaterThan(count(initial, [0, 0, 0]) * 2.5);
    const updated = await photograph("updated.png");
    expect(count(updated, [0, 240, 0])).toBeGreaterThan(1000);
    expect(count(updated, [240, 240, 0])).toBe(0);
    expect(count(updated, [255, 0, 255])).toBeLessThan(count(initial, [255, 0, 255]) - 1000);
    expect(count(updated, [255, 0, 255])).toBeGreaterThan(10000);
    expect(chunks.some(url => url.includes("/coverage/"))).toBe(true);
    console.log({
      initialBlack: count(initial, [0, 0, 0]), updatedBlack: count(updated, [0, 0, 0]),
      initialClear: count(initial, [255, 0, 255]), updatedClear: count(updated, [255, 0, 255]),
      coverageChunkRequests: chunks.filter(url => url.includes("/coverage/")).length,
    });

    await page.evaluate(() => { coveredViewer.setChannel(0, { visible: false }); coveredViewer.setChannel(1, { visible: false }); });
    await expect.poll(async () => count(await photograph(), [255, 0, 255])).toBe(640 * 320);
    await page.evaluate(() => coveredViewer.setChannel(1, { visible: true }));
    await expect.poll(async () => count(await photograph(), [0, 0, 0])).toBeGreaterThan(1000);
    await page.evaluate(() => coveredViewer.showPicture(false));
    await expect.poll(async () => count(await photograph(), [255, 0, 255])).toBe(640 * 320);
    await page.evaluate(() => coveredViewer.showPicture(true));
    await expect.poll(async () => count(await photograph(), [0, 0, 0])).toBeGreaterThan(1000);
    await page.waitForTimeout(500);
    chunks.length = 0;
    expect(await page.evaluate(() => coveredViewer.addSources(coveredAcquisition(2)))).toBe(true);
    await page.waitForTimeout(1800);
    expect(chunks).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await page.evaluate(() => window.coveredViewer?.destroy()).catch(() => {});
    await new Promise(resolve => server.close(resolve));
  }
});
