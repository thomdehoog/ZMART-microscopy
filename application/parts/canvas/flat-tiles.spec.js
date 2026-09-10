/** The original eight-tile rig regression, through the named Top publication.
 * Each tile keeps its specimen Z; one aggregate must show all eight at every
 * display depth. Pixels, rather than the retired metre-thick slab, are the oracle.
 */
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const heights = [62.99, 62.79, 64.26, 64.01, 61.10, 60.40, 62.20, 61.40];
for (const bake of [false, true]) for (const together of [false, true]) {
  test(`eight real-height flats through Top: bake ${bake}, together ${together}`, async ({ page }, info) => {
    test.setTimeout(120_000);
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), "flat-top-"));
    const names = execFileSync(pythonForTheBridge(), [
      path.join(here, "fixtures/write-flat-tiles.py"), folder, "8", heights.join(","),
    ], { encoding: "utf8", windowsHide: true }).trim().split(/\r?\n/).map(p => path.basename(p));
    const positions = path.join(folder, "positions");
    const child = spawn(pythonForTheBridge(), [path.join(here, "fixtures/serve-mixed-acquisition.py"), positions, "--existing"],
      { windowsHide: true });
    let logs = "";
    child.stderr.on("data", data => { logs += data; });
    const origin = await new Promise((resolve, reject) => {
      let out = "";
      child.stdout.on("data", data => {
        out += data;
        if (out.includes("\n")) resolve(JSON.parse(out.split("\n")[0]).url);
      });
      child.on("error", reject);
      child.on("exit", code => reject(new Error(`server exited ${code}: ${logs}`)));
    });
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    try {
      await page.goto("/?backend=pretend");
      await page.evaluate(() => {
        const host = document.createElement("div");
        host.id = "flat-proof";
        host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:160px;z-index:999;background:magenta";
        document.body.append(host);
      });
      for (let count = together ? 8 : 1; count <= 8; count++) {
        const first = count === (together ? 8 : 1);
        const data = { path: positions, source_revisions: Object.fromEntries(names.slice(0,count).map(n => [n,1])),
          composition: { regions: "complete", order: names.slice(0,count), xy_origin: "corner" } };
        const response = await page.request.post(origin + "/api/" + (first ? "stores/open" : "announce"), {
          data: first ? { ...data, bake, canvas: { x_um:[488,8680], y_um:[1488,2512] },
            views: { path:path.join(folder,"view"), acquisition:"overview", modes:["top"] } }
            : { publications:[data] },
        });
        expect(response.ok(), await response.text()).toBe(true);
        const config = await (await page.request.get(origin + "/api/config")).json();
        await page.evaluate(async ({ origin, rows, first }) => {
          const channels = rows.filter(row => row.kind === "image" && row.channelIndex === 0).map(row => ({
            ...row, colour:[0,1,0], window:{low:0,high:10000},
            sources:row.sources.map(s => origin+s), coverageSources:row.coverageSources.map(s => origin+s),
          }));
          const acquisitions = [{name:"overview", embeddingUrl:origin+"/embedding.js", channels}];
          if (first) {
            const { openerFor } = await import("/parts/canvas/engines.js");
            window.flatViewer = await (await openerFor("neuroglancer-under"))(document.querySelector("#flat-proof"),
              {acquisitions, presentation:"2d-overlay", transparentBackground:true});
            window.initialFlatViewer = flatViewer;
          } else if (!await flatViewer.addSources(acquisitions)) throw new Error("aggregate was reopened");
          flatViewer.setView({centre:{x:4584,y:2000},zoom:16});
        }, {origin, rows:config.layers, first});
      }
      for (const z of [-1000,0,1000]) {
        await page.evaluate(z => flatViewer.setPlane(z), z);
        await expect.poll(async () => {
          const shot = readPng(await page.locator("#flat-proof").screenshot());
          return Math.max(...heights.map((_,i) => {
            const at=(80*shot.width+96+i*64)*shot.channels;
            return Math.max(shot.data[at], shot.data[at+2], Math.abs(shot.data[at+1]-(i+1)*25.5));
          }));
        }).toBeLessThanOrEqual(1); // Allow only 8-bit shader quantization.
      }
      expect(await page.evaluate(() => flatViewer === initialFlatViewer)).toBe(true);
      expect(await page.evaluate(() => flatViewer.layersForMeasurement().map(r=>r.sources.length))).toEqual([1]);
      await page.locator("#flat-proof").screenshot({path:info.outputPath("eight-flat-tiles.png")});
      expect(errors).toEqual([]);
    } finally {
      await page.evaluate(() => window.flatViewer?.destroy());
      child.kill();
    }
  });
}
