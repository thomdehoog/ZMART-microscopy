import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const fixture = fileURLToPath(new URL("./fixtures/write-refresh-positions.py", import.meta.url));
const changedPixels = (a, b) => {
  let changed = 0;
  for (let i = 0; i < a.data.length; i += a.channels) {
    if ([0, 1, 2].some(c => Math.abs(a.data[i + c] - b.data[i + c]) > 30)) changed++;
  }
  return changed;
};
const imagePixels = shot => {
  let count = 0;
  for (let i = 0; i < shot.data.length; i += shot.channels) {
    if (!(shot.data[i] === 255 && shot.data[i + 1] === 0 && shot.data[i + 2] === 255)) count++;
  }
  return count;
};

test("append preserves cached tiles; a source revision refreshes only the rewritten tile", async ({ page }, info) => {
  test.setTimeout(90_000);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "refresh-"));
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
      const underlay = document.createElement("div");
      underlay.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:999;background:magenta";
      const host = document.createElement("div");
      host.id = "refresh-host";
      host.style.cssText = "width:100%;height:100%";
      underlay.append(host);
      document.body.append(underlay);
      const { openerFor } = await import("/parts/canvas/engines.js");
      window.refreshAcquisitions = (count, revision = 1) => [{
        name: "overview", opaque: true, channels: [{ name: "signal", channelIndex: 0,
          colour: [1, 1, 1], window: { low: 0, high: 255 },
          sources: Array.from({ length: count }, (_, i) => `${origin}/P${i}.ome.zarr/|zarr3:`),
          sourceRevisions: Array.from({ length: count }, (_, i) => i ? 1 : revision),
        }],
      }];
      window.refreshViewer = await (await openerFor("neuroglancer-under"))(host, {
        acquisitions: window.refreshAcquisitions(1), presentation: "2d-overlay", transparentBackground: true,
      });
      window.refreshViewer.setView({ centre: { x: 80, y: 32 }, zoom: 0.5 });
    }, origin);
    const photograph = async name => readPng(await page.locator("#refresh-host").screenshot(
      name ? { path: info.outputPath(name) } : {}));
    await expect.poll(() => chunks.length).toBeGreaterThan(0);
    let first;
    await expect.poll(async () => {
      first = await photograph("first.png");
      const shot = first;
      let white = 0;
      for (let i = 0; i < shot.data.length; i += shot.channels) {
        if (shot.data[i] > 180 && shot.data[i + 1] > 180 && shot.data[i + 2] > 180) white++;
      }
      return white;
    }).toBeGreaterThan(1000);
    chunks.length = 0;
    expect(await page.evaluate(() => window.refreshViewer.addSources(window.refreshAcquisitions(2)))).toBe(true);
    await expect.poll(() => chunks.filter(url => url.startsWith("P1.")).length).toBeGreaterThan(0);
    let both;
    await expect.poll(async () => {
      both = await photograph("appended.png");
      if (imagePixels(both) < imagePixels(first) * 1.8) return false;
      for (let i = 0; i < first.data.length; i += first.channels) {
        if (first.data[i] === 255 && first.data[i + 1] === 0 && first.data[i + 2] === 255) continue;
        if ([0, 1, 2].some(c => Math.abs(first.data[i + c] - both.data[i + c]) > 5)) return false;
      }
      return true;
    }, { timeout: 30_000 }).toBe(true);
    expect(chunks.filter(url => url.startsWith("P0."))).toEqual([]);
    chunks.length = 0;
    write("rewrite");
    expect(await page.evaluate(() => window.refreshViewer.addSources(window.refreshAcquisitions(2, 2)))).toBe(true);
    await expect.poll(() => chunks.filter(url => url.startsWith("P0.")).length).toBeGreaterThan(0);
    await expect.poll(async () => {
      const rewritten = await photograph("rewritten.png");
      return imagePixels(rewritten) >= imagePixels(both) * 0.95
        && changedPixels(both, rewritten) > 1000;
    }).toBe(true);
    await page.waitForTimeout(1000);
    expect(chunks.filter(url => url.startsWith("P1."))).toEqual([]);
    chunks.length = 0;
    expect(await page.evaluate(() => window.refreshViewer.addSources(window.refreshAcquisitions(2, 2)))).toBe(true);
    await page.waitForTimeout(1800);
    expect(chunks).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await page.evaluate(() => window.refreshViewer?.destroy()).catch(() => {});
    await new Promise(resolve => server.close(resolve));
  }
});
