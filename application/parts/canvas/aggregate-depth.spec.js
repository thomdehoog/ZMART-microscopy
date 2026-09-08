import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const fixture = fileURLToPath(new URL("./fixtures/serve-mixed-acquisition.py", import.meta.url));
for (const bake of [false, true]) for (const flatFirst of [false, true]) {
  test(`mixed aggregates: bake ${bake}, flat first ${flatFirst}`, async ({ page }, info) => {
    test.setTimeout(90_000);
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), "mixed-aggregate-"));
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
    const requests = [], errors = [];
    page.on("request", request => { if (/\/data\/.*\/c\//.test(request.url())) requests.push(request.url()); });
    page.on("pageerror", error => errors.push(String(error)));
    const publish = async (names, opening = false, regions = "complete") => {
      const payload = { path: folder, source_revisions: Object.fromEntries(names.map(n => [`${n}.ome.zarr`, 1])),
        composition: { regions, order: names.map(n => `${n}.ome.zarr`), xy_origin: "corner",
          pyramid_reduction: "mean-xy2-crop-f32-rint-int" } };
      const response = await page.request.post(`${origin}/api/${opening ? "stores/open" : "announce"}`, {
        data: opening ? { ...payload, bake, canvas: { x_um: [0, 512], y_um: [0, 128], z_um: [0, 1000] } }
          : { publications: [payload] },
      });
      expect(response.ok(), await response.text()).toBe(true);
      const config = await (await page.request.get(`${origin}/api/config`)).json();
      return [{ name: "mixed", channels: config.layers.filter(row => row.kind === "image").map(row => ({
        ...row, colour: row.channelIndex === 0 ? [1, 0, 0] : [0, 1, 0],
        window: { low: 0, high: 255 },
        sources: row.sources.map(url => origin + url),
        coverageSources: row.coverageSources.map(url => origin + url),
      })) }];
    };
    try {
      const first = await publish(flatFirst ? ["flat"] : ["stack"], true);
      await page.goto("/?backend=pretend");
      await page.evaluate(async acquisitions => {
        const below = document.createElement("div");
        below.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:999;background:magenta";
        const host = document.createElement("div");
        host.id = "mixed-host";
        host.style.cssText = "width:100%;height:100%";
        below.append(host);
        document.body.append(below);
        const { openerFor } = await import("/parts/canvas/engines.js");
        window.mixedViewer = await (await openerFor("neuroglancer-under"))(host, {
          acquisitions, presentation: "2d-overlay", transparentBackground: true,
        });
      }, first);
      await page.waitForFunction(() => mixedViewer.layersForMeasurement().some(row => row.dims?.length));
      await page.evaluate(() => mixedViewer.setChannel(0, { visible: false }));
      await page.evaluate(() => mixedViewer.setChannel(1, {
        colour: [0, 0, 1], window: { low: 0, high: 510 }, gamma: 0.5, weight: 0.5,
      }));
      const both = await publish(["flat", "stack"]);
      expect(both[0].channels.every(row => row.sources.length === 2)).toBe(true);
      expect(await page.evaluate(rows => mixedViewer.addSources(rows), both)).toBe(true);
      await page.waitForFunction(() => mixedViewer.layersForMeasurement().length === 2
        && mixedViewer.layersForMeasurement().every(row => row.sources.length === 2
          && row.sources.every(source => source.dims?.length)));
      const depth = await page.evaluate(() => mixedViewer.theDepthItCanShow());
      expect(depth.lowUm).toBeCloseTo(-1.3);
      expect(depth.highUm).toBeCloseTo(1.3);
      const photo = async name => readPng(await page.locator("#mixed-host").screenshot(name ? { path: info.outputPath(name) } : {}));
      const pixel = (shot, x, y) => Array.from(shot.data.slice((y * shot.width + x) * shot.channels, (y * shot.width + x) * shot.channels + 3));
      const look = async (z, zoom = 0.5) => {
        await page.evaluate(({ z, zoom }) => {
          mixedViewer.setView({ centre: { x: 128, y: 32 }, zoom });
          mixedViewer.setPlane(z);
        }, { z, zoom });
      };
      await look(0);
      for (const [x, intensity] of [[128, 80], [384, 100]]) {
        const expected = Math.round(255 * Math.sqrt(intensity / 510) * 0.5);
        await expect.poll(async () => pixel(await photo(), x, 160)).toEqual([0, 0, expected]);
      }
      await page.evaluate(() => mixedViewer.setChannel(1, {
        colour: [0, 1, 0], window: { low: 0, high: 255 }, gamma: 1, weight: 1,
      }));
      for (const [z, intensity] of [[-1.3, 40], [0, 100], [1.3, 160], [10, null]]) {
        await look(z);
        await expect.poll(async () => pixel(await photo(), 384, 160)).toEqual(
          intensity === null ? [255, 0, 255] : [0, intensity, 0]);
        expect(pixel(await photo(), 128, 160)).toEqual([0, 80, 0]);
        expect(pixel(await photo(), 256, 160)).toEqual([255, 0, 255]);
      }
      await page.evaluate(() => mixedViewer.setChannel(0, { visible: true }));
      await look(0, 2);
      await expect.poll(async () => pixel(await photo(), 336, 160)).toEqual([100, 100, 0]);
      expect(pixel(await photo("coarse.png"), 272, 160)).toEqual([80, 80, 0]);
      await look(0);
      const black = await publish(["flat", "stack", "black"]);
      expect(await page.evaluate(rows => mixedViewer.addSources(rows), black)).toBe(true);
      await expect.poll(async () => pixel(await photo(), 128, 160)).toEqual([0, 0, 0]);
      expect(pixel(await photo("black-and-gap.png"), 256, 160)).toEqual([255, 0, 255]);
      await page.evaluate(() => mixedViewer.setChannel(0, { visible: false }));
      await expect.poll(async () => pixel(await photo(), 384, 160)).toEqual([0, 100, 0]);
      await look(10);
      await expect.poll(async () => pixel(await photo(), 128, 160)).toEqual([0, 80, 0]);
      await page.waitForTimeout(500);
      const before = requests.length;
      expect(await page.evaluate(rows => mixedViewer.addSources(rows), black)).toBe(true);
      await page.waitForTimeout(3200);
      expect(requests.length).toBe(before);
      expect(requests.every(url => decodeURIComponent(url).includes("/.zmart-viewer/"))).toBe(true);
      const measurement = await page.evaluate(async acquisitions => {
        const { mountViewerPanel, measureViewerRow, viewerRowsFor } = await import("/parts/canvas/viewer-panel.js");
        const rows = await viewerRowsFor(acquisitions);
        // The flat aggregate has no acquired pixels in this box; Auto must also
        // measure the stack, not mistake the first aggregate for the whole channel.
        const measured = await measureViewerRow(rows[0], { box: [[0, 0.25], [0.5, 0.375]] });
        window.mixedPanel = await mountViewerPanel(document.body, {
          viewer: mixedViewer, acquisitions, into: document.body,
        });
        return measured;
      }, black);
      expect(measurement.ok).toBe(true);
      expect(measurement.answer.window.high).toBeGreaterThan(80);
      await expect(page.locator('[data-engine-state="agrees"]')).toHaveCount(1);
      const channels = await page.evaluate(() => mixedPanel.snapshot().channels);
      expect(channels).toHaveLength(2);
      expect(channels.every(row => row.observed.sources.length === 2)).toBe(true);
      const retired = await publish([]);
      expect(await page.evaluate(rows => mixedViewer.addSources(rows), retired)).toBe(true);
      await look(0);
      await expect.poll(async () => pixel(await photo(), 128, 160)).toEqual([255, 0, 255]);
      await expect.poll(async () => pixel(await photo(), 384, 160)).toEqual([255, 0, 255]);
      expect(errors).toEqual([]);
      console.log({ bake, flatFirst, imageRequests: before, idleImageRequests: 0 });
    } finally {
      await page.evaluate(() => { window.mixedPanel?.destroy(); window.mixedViewer?.destroy(); }).catch(() => {});
      child.kill();
    }
  });
}
