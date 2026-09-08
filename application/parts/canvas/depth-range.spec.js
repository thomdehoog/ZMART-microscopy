import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

for (const bake of [false, true]) test(`selected relative acquisition keeps its own depth, bake ${bake}`, async ({ page }) => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "relative-depth-range-"));
  const fixture = fileURLToPath(new URL("./fixtures/serve-depth-ranges.py", import.meta.url));
  const child = spawn(pythonForTheBridge(), [fixture, folder], { windowsHide: true });
  let logs = "";
  child.stderr.on("data", data => { logs += data; });
  const origin = await new Promise((resolve, reject) => {
    let output = "";
    child.stdout.on("data", data => {
      output += data;
      if (output.includes("\n")) resolve(JSON.parse(output.split("\n")[0]).url);
    });
    child.on("exit", code => reject(new Error(`fixture exited ${code}: ${logs}`)));
    child.on("error", reject);
  });
  try {
    for (const name of ["a", "b"]) {
      const response = await page.request.post(`${origin}/api/stores/open`, { data: {
        path: path.join(folder, name), bake, canvas: { x_um: [0, 512], y_um: [0, 128] },
        source_revisions: { "position.ome.zarr": 1 }, composition: { regions: "complete",
          order: ["position.ome.zarr"], xy_origin: "corner", pyramid_reduction: "mean-xy2-crop-f32-rint-int" },
      } });
      expect(response.ok(), await response.text()).toBe(true);
    }
    const config = await (await page.request.get(`${origin}/api/config`)).json();
    const acquisitions = config.layers.filter(row => row.kind === "image").map(row => ({
      name: row.group, channels: [{ ...row, colour: [0, 1, 0], window: { low: 0, high: 255 },
        sources: row.sources.map(url => origin + url), coverageSources: row.coverageSources.map(url => origin + url) }],
    }));
    expect(acquisitions.map(row => row.name).sort()).toEqual(["a", "b"]);
    await page.goto("/?backend=pretend");
    await page.evaluate(async acquisitions => {
      const host = document.createElement("div");
      host.id = "depth-range-host";
      host.style.cssText = "position:fixed;inset:0;width:640px;height:320px;z-index:999;background:magenta";
      document.body.append(host);
      const { openerFor } = await import("/parts/canvas/engines.js");
      window.depthViewer = await (await openerFor("neuroglancer-under"))(host, {
        acquisitions, presentation: "2d-overlay", transparentBackground: true,
      });
      depthViewer.setView({ centre: { x: 128, y: 32 }, zoom: 0.5 });
    }, acquisitions);
    await expect.poll(() => page.evaluate(() => depthViewer.theDepthItCanShow("b")?.stepUm)).toBeCloseTo(2);
    const ranges = await page.evaluate(() => ["a", "b", null].map(name => depthViewer.theDepthItCanShow(name)));
    for (const [at, low, high, step] of [[0, -5, 5, 1], [1, -1, 3, 2], [2, -5, 5, 1]]) {
      expect(ranges[at].lowUm).toBeCloseTo(low);
      expect(ranges[at].highUm).toBeCloseTo(high);
      expect(ranges[at].stepUm).toBeCloseTo(step);
    }
    for (const [z, value] of [[-1, 40], [1, 50], [3, 60]]) {
      await page.evaluate(z => depthViewer.setPlane(z), z);
      await expect.poll(async () => {
        const photo = readPng(await page.locator("#depth-range-host").screenshot());
        const offset = (160 * photo.width + 384) * photo.channels;
        return Array.from(photo.data.slice(offset, offset + 3));
      }).toEqual([0, value, 0]);
    }
  } finally {
    await page.evaluate(() => window.depthViewer?.destroy()).catch(() => {});
    child.kill();
  }
});
