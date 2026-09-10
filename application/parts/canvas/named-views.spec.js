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
  test(`named views: bake ${bake}, flat first ${flatFirst}`, async ({ page }, info) => {
    test.setTimeout(90_000);
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), "named-op-"));
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
    const errors = [], requests = [];
    page.on("pageerror", error => errors.push(String(error)));
    page.on("request", request => { if (/\/data\/.*\/c\//.test(request.url())) requests.push(request.url()); });
    const publish = async (names, opening = false) => {
      const data = { path: folder, source_revisions: Object.fromEntries(names.map(n => [`${n}.ome.zarr`, 1])),
        composition: { regions: "complete", order: names.map(n => `${n}.ome.zarr`), xy_origin: "corner" } };
      const reply = await page.request.post(`${origin}/api/${opening ? "stores/open" : "announce"}`, {
        data: opening ? { ...data, bake, canvas: { x_um: [0, 512], y_um: [0, 128] },
          views: { path: path.join(folder, "view"), acquisition: "mixed",
            modes: ["top", "slice"], projections: ["max"],
            projection_path: path.join(folder, "projections") } } : { publications: [data] },
      });
      expect(reply.ok(), await reply.text()).toBe(true);
      return (await (await page.request.get(`${origin}/api/config`)).json()).layers;
    };
    try {
      const first = await publish(flatFirst ? ["flat"] : ["stack"], true);
      await page.goto("/?backend=pretend");
      await page.evaluate(async ({ origin, layers }) => {
        const below = document.createElement("div");
        below.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:999;background:magenta";
        const host = document.createElement("div");
        host.id = "named-host";
        host.style.cssText = "width:100%;height:100%";
        below.append(host);
        document.body.append(below);
        const api = await import(origin + "/embedding.js");
        window.namedAcquisitions = (rows, mode) => {
          const choice = api.viewChoices(rows)[0];
          const selected = api.selectedViews(rows, { [choice.id]: mode });
          return [{ name: "mixed", embeddingUrl: origin + "/embedding.js",
            channels: rows.filter(row => api.inSelectedView(row, selected)).map(row => ({
              ...row, colour: row.channelIndex === 0 ? [1, 0, 0] : [0, 1, 0],
              window: { low: 0, high: 255 },
              sources: row.sources.map(url => origin + url),
              coverageSources: row.coverageSources.map(url => origin + url),
            })) }];
        };
        const { openerFor } = await import("/parts/canvas/engines.js");
        window.namedViewer = await (await openerFor("neuroglancer-under"))(host, {
          acquisitions: namedAcquisitions(layers, "top"),
          presentation: "2d-overlay", transparentBackground: true,
        });
        window.initialNamedViewer = namedViewer;
      }, { origin, layers: first });
      let layers = await publish(["flat", "stack"]);
      const select = async mode => {
        expect(await page.evaluate(({ layers, mode }) =>
          namedViewer.addSources(namedAcquisitions(layers, mode)), { layers, mode })).toBe(true);
        await page.evaluate(() => namedViewer.setView({ centre: { x: 128, y: 32 }, zoom: 0.5 }));
      };
      const photo = async name => readPng(await page.locator("#named-host").screenshot(
        name ? { path: info.outputPath(name) } : {}));
      const pixel = (shot, x) => Array.from(shot.data.slice((160 * shot.width + x) * shot.channels,
        (160 * shot.width + x) * shot.channels + 3));
      if (bake && flatFirst) {
        await select("top");
        await page.evaluate(() => namedViewer.setPlane(0));
        await expect.poll(async () => pixel(await photo(), 384)).toEqual([40, 40, 0]);
        const before = requests.length;
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        let blocked = 0;
        const delay = async route => { blocked++; await gate; await route.continue(); };
        await page.route("**/data/**/c/**", delay);
        try {
          await page.evaluate(() => namedViewer.setPlane(2));
          await expect.poll(() => blocked).toBeGreaterThan(0);
          const cold = await photo("cold-z-waiting.png");
          console.log({coldZ: {flat:pixel(cold,128), stack:pixel(cold,384), requests:requests.length-before}});
          expect(pixel(cold,128)).toEqual([80,80,0]);
          expect(pixel(cold,384)).toEqual([40,40,0]);
          await expect(page.getByRole("status").filter({hasText:"Loading Z"})).toBeVisible();
        } finally {
          release();
          await page.unrouteAll({behavior:"wait"});
        }
        await expect.poll(async () => pixel(await photo(), 384)).toEqual([160, 160, 0]);
        await photo("cold-z-ready.png");
        await expect(page.getByRole("status").filter({hasText:"Loading Z"})).toBeHidden();
        const warm = requests.length;
        await page.evaluate(() => namedViewer.setPlane(0));
        await expect.poll(async () => pixel(await photo(), 384)).toEqual([40, 40, 0]);
        await page.evaluate(() => { namedViewer.setPlane(2); namedViewer.setPlane(0); namedViewer.setPlane(2); });
        await expect.poll(async () => pixel(await photo(), 384)).toEqual([160, 160, 0]);
        expect(requests.length - warm).toBe(0);
      }
      for (const mode of ["top", "slice", "max", "top"]) {
        await select(mode);
        await page.waitForFunction(() => namedViewer.layersForMeasurement().every(row => row.dims?.length));
        const cases = mode === "slice" ? [[65,40], [66.3,100], [67.6,160], [78,null]]
          : [[0,40], [1,100], [2,160], [20,160]];
        for (const [z, stackValue] of cases) {
          await page.evaluate(z => namedViewer.setPlane(z), z);
          const flat = mode === "slice" && z !== 78 ? [255, 0, 255] : [80, 80, 0];
          const value = mode === "max" ? 160 : stackValue;
          const stack = value === null ? [255, 0, 255] : [value, value, 0];
          await expect.poll(async () => pixel(await photo(), 128)).toEqual(flat);
          await expect.poll(async () => pixel(await photo(), 384)).toEqual(stack);
          expect(pixel(await photo(), 256)).toEqual([255, 0, 255]);
        }
        await page.evaluate(z => namedViewer.setPlane(z), mode === "slice" ? 78 : 0);
        await expect.poll(async () => pixel(await photo(), 128)).toEqual([80, 80, 0]);
        await photo(`${mode}.png`);
      }
      // Top at the stack's top plane and MIP must place every edge identically.
      const scanline = shot => Array.from(shot.data.slice(160 * shot.width * shot.channels,
        161 * shot.width * shot.channels));
      await select("top");
      await page.evaluate(() => namedViewer.setPlane(2));
      await expect.poll(async () => pixel(await photo(), 384)).toEqual([160, 160, 0]);
      const topEdges = scanline(await photo());
      await select("max");
      await expect.poll(async () => scanline(await photo())).toEqual(topEdges);
      for (const zoom of [0.5, 1, 2, 4]) {
        await select("top");
        await page.evaluate(zoom => {
          namedViewer.setView({centre:{x:96,y:24}, zoom});
          namedViewer.setPlane(2);
        }, zoom);
        await expect(page.getByRole("status").filter({hasText:"Loading Z"})).toBeHidden();
        // Require actual detail, not a timer or matching blank screenshots.
        const detail = shot => {
          const at = x => {
            const sx = Math.floor(320 + (x - 96) / zoom);
            const sy = Math.floor(160 + (8.5 - 24) / zoom);
            return shot.data[(sy * shot.width + sx) * shot.channels];
          };
          return zoom <= 1 ? Math.abs(at(136.5) - at(137.5)) : at(136.5);
        };
        await expect.poll(async () => detail(await photo())).toBe(zoom <= 1 ? 60 : 190);
        const reference = Array.from((await photo()).data);
        await select("max");
        await page.evaluate(zoom => namedViewer.setView({centre:{x:96,y:24}, zoom}), zoom);
        await expect.poll(async () => {
          const result = (await photo()).data;
          return reference.reduce((count, value, i) => count + (result[i] !== value), 0);
        }).toBe(0);
        if (bake && flatFirst) await photo(`mip-detail-zoom-${zoom}.png`);
      }
      // A later acquired black stack covers the old flat signal, not the ground.
      const beforeUpdate = requests.length;
      layers = await publish(["flat", "stack", "black"]);
      await select("top");
      await expect.poll(async () => pixel(await photo(), 128)).toEqual([0, 0, 0]);
      expect(pixel(await photo(), 256)).toEqual([255, 0, 255]);
      expect(requests.length).toBeGreaterThan(beforeUpdate);
      // A coarse zoom must keep exactly the same black/empty distinction.
      await page.evaluate(() => namedViewer.setView({ centre: { x: 64, y: 32 }, zoom: 2 }));
      await expect.poll(async () => pixel(await photo(), 304)).toEqual([0, 0, 0]);
      expect(pixel(await photo(), 336)).toEqual([255, 0, 255]);
      await photo("coarse-black-and-gap.png");
      expect(await page.evaluate(() => namedViewer === initialNamedViewer)).toBe(true);
      const after = requests.length;
      await page.waitForTimeout(2300);
      expect(requests.length).toBe(after);
      console.log({ bake, flatFirst, imageRequests: after, idleImageRequests: 0 });
      expect(errors).toEqual([]);
      expect(fs.readdirSync(path.join(folder, "view")).filter(n => n.endsWith(".zmartview.zarr")).sort())
        .toEqual(["mixed_max.zmartview.zarr", "mixed_slice.zmartview.zarr", "mixed_top.zmartview.zarr"]);
    } finally {
      await page.evaluate(() => window.namedViewer?.destroy()).catch(() => {});
      child.kill();
    }
  });
}
