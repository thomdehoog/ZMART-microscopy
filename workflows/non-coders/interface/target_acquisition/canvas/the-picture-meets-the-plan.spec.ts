/**
 * A tile's picture begins where the operator's plan drew its outline.
 *
 * The plan draws a field as its stage centre less half a frame. The run's
 * writer stores the same field by the centre of its first voxel, every level
 * by the centre of its own first voxel (OME-NGFF RFC-5), and the engine
 * draws a voxel centred on that number. Zoomed in eight times past the
 * finest level, half a voxel is four screen pixels, so the left edge of the
 * drawn picture has to land on the outline's screen column within one pixel:
 *
 * - the published picture the operator page draws (the viewer's composition
 *   of the position, asked for as the interface asks for it);
 * - the position's own store: the engine draws its finest level, and its
 *   coarser levels beneath wherever the finest has nothing, so a coarse level
 *   placed by any other point than its own first voxel's centre stands out
 *   past the outline (by three and a half micrometres for the 8 µm level when
 *   every level was given the finest level's corner);
 * - the same store without its finest level, so the engine's finest is the
 *   2 µm level, however far in the view is zoomed.
 */
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { pythonForTheBridge } from "../testing/python.ts";
import { readPng, type Pixels } from "../testing/pixels.ts";
import type { Acquisition, EngineViewer } from "./engines/neuroglancer-under/viewer.ts";

declare global {
  interface Window {
    /** The engine this spec opens on one tile's picture. */
    planViewer?: EngineViewer;
  }
}

const here = path.dirname(fileURLToPath(import.meta.url));
/* What write-flat-tiles.py writes for one tile: 1024 pixels of 1 µm, centred
   at x 1000 µm, y 2000 µm. The plan's outline of it begins at x 488 µm. */
const CENTRE = { x: 1000, y: 2000 }, FRAME_UM = 1024;
const OUTLINE_X = CENTRE.x - FRAME_UM / 2;
/* Eight screen pixels to the micrometre, the view centred on the outline:
   the outline falls on the host's middle column. */
const WIDTH = 640, HEIGHT = 160, ZOOM = 1 / 8;
const OUTLINE_COLUMN = WIDTH / 2;
const GROUND = [255, 0, 255];

/** The first column, along the host's middle row, that is not the ground: where the picture begins. */
function firstLitColumn(shot: Pixels): number | null {
  const row = Math.floor(HEIGHT / 2);
  for (let x = 0; x < shot.width; x++) {
    const at = (row * shot.width + x) * shot.channels;
    if (GROUND.some((value, c) => Math.abs(shot.data[at + c] - value) > 8)) return x;
  }
  return null;
}

/** Open the engine on `channels` over a magenta ground, looking at the outline from eight times in. */
async function openOn(page: Page, channels: unknown[], embeddingUrl?: string) {
  await page.goto("/?backend=pretend");
  await page.evaluate(async ({ channels, embeddingUrl, width, height, view }) => {
    const below = document.createElement("div");
    below.style.cssText = `position:fixed;left:0;top:0;width:${width}px;height:${height}px;z-index:999;background:magenta`;
    const host = document.createElement("div");
    host.id = "plan-proof";
    host.style.cssText = "width:100%;height:100%";
    below.append(host);
    document.body.append(below);
    // A stand-in handed over as the engine's Acquisition: it has no `url`, only its channels' sources.
    const acquisitions = [{ name: "overview", ...(embeddingUrl ? { embeddingUrl } : {}), channels }] as unknown as Acquisition[];
    const { openerFor } = await import("/@zmart-workflows/target_acquisition/canvas/engines.ts");
    window.planViewer = await (await openerFor("neuroglancer-under"))(host,
      { acquisitions, presentation: "2d-overlay", transparentBackground: true });
    window.planViewer!.setView(view);
  }, { channels, embeddingUrl, width: WIDTH, height: HEIGHT, view: { centre: { x: OUTLINE_X, y: CENTRE.y }, zoom: ZOOM } });
}

/** How far the drawn picture's first column stands from the outline's, in screen pixels, once it is drawn. */
async function expectThePictureOnTheOutline(page: Page, name: string, outputPath: (name: string) => string) {
  let measured: number | null = null, shot: Buffer | null = null;
  try {
    await expect.poll(async () => {
      shot = await page.locator("#plan-proof").screenshot();
      measured = firstLitColumn(readPng(shot));
      return measured === null ? Infinity : Math.abs(measured - OUTLINE_COLUMN);
    }, { message: `${name}: first lit column against the outline's ${OUTLINE_COLUMN}` }).toBeLessThanOrEqual(1);
  } finally {
    // The last picture measured, kept whichever way the measurement went.
    if (shot) fs.writeFileSync(outputPath(`${name}.png`), shot);
    console.log({ picture: name, outlineColumn: OUTLINE_COLUMN, firstLitColumn: measured,
      offsetPx: (measured ?? NaN) - OUTLINE_COLUMN });
  }
}

/** One tile written by the run's writer into `folder`; its store's path relative to it. */
function oneTile(folder: string): string {
  return execFileSync(pythonForTheBridge(), [path.join(here, "fixtures/write-flat-tiles.py"), folder, "1"],
    { encoding: "utf8", windowsHide: true }).trim();
}

const channelOf = (sources: string[], coverageSources: string[] = []) => ({
  name: "0", channelIndex: 0, colour: [0, 1, 0], window: { low: 0, high: 1000 },
  sources, coverageSources, sourceRevisions: sources.map(() => 1),
});

test("the published picture of a tile begins on the plan's outline", async ({ page }, info) => {
  test.setTimeout(90_000);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "plan-published-"));
  const name = path.basename(oneTile(folder));
  const positions = path.join(folder, "positions");
  const child = spawn(pythonForTheBridge(), [path.join(here, "fixtures/serve-mixed-acquisition.py"), positions, "--existing"],
    { windowsHide: true });
  let logs = "";
  child.stderr.on("data", data => { logs += data; });
  const origin = await new Promise<string>((resolve, reject) => {
    let out = "";
    child.stdout.on("data", data => {
      out += data;
      if (out.includes("\n")) resolve(JSON.parse(out.split("\n")[0]).url);
    });
    child.on("error", reject);
    child.on("exit", code => reject(new Error(`server exited ${code}: ${logs}`)));
  });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  try {
    /* As the interface asks for it (storage/viewer_service.py): the
       positions composed in order, averaged into each coarser level. */
    const response = await page.request.post(`${origin}/api/stores/open`, { data: {
      path: positions, source_revisions: { [name]: 1 },
      composition: { regions: "complete", order: [name], pyramid_reduction: "mean-xy2-crop-f32-rint-int" },
      bake: false, canvas: { x_um: [0, 2048], y_um: [1024, 3072] },
      views: { path: path.join(folder, "view"), acquisition: "overview", modes: [], projections: ["max"],
        projection_path: path.join(folder, "projections") },
    } });
    expect(response.ok(), await response.text()).toBe(true);
    const rows: { kind: string; channelIndex: number; sources: string[]; coverageSources: string[] }[] =
      (await (await page.request.get(`${origin}/api/config`)).json()).layers;
    const row = rows.find(one => one.kind === "image" && one.channelIndex === 0)!;
    await openOn(page, [{ ...row, colour: [0, 1, 0], window: { low: 0, high: 1000 },
      sources: row.sources.map(s => origin + s), coverageSources: row.coverageSources.map(s => origin + s) }],
    `${origin}/embedding.js`);
    await expectThePictureOnTheOutline(page, "published", info.outputPath.bind(info));
    expect(errors).toEqual([]);
  } finally {
    await page.evaluate(() => window.planViewer?.destroy()).catch(() => {});
    child.kill();
  }
});

for (const finest of [true, false]) {
  test(`a tile's own store, drawn at ${finest ? "its finest" : "a coarse"} level, begins on the plan's outline`, async ({ page }, info) => {
    test.setTimeout(90_000);
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), "plan-store-"));
    const store = path.join(folder, oneTile(folder));
    if (!finest) {
      /* The finest level taken out of the description: the engine's finest
         is now the 2 µm level, which it draws however far in it is zoomed. */
      const described = path.join(store, "zarr.json");
      const description = JSON.parse(fs.readFileSync(described, "utf8"));
      const multiscale = description.attributes.ome.multiscales[0];
      expect(multiscale.datasets[1].coordinateTransformations[0].scale.slice(-1)).toEqual([2]);
      multiscale.datasets.shift();
      fs.writeFileSync(described, JSON.stringify(description));
    }
    const server = http.createServer((request, response) => {
      const file = path.resolve(folder, decodeURIComponent(new URL(request.url!, "http://x").pathname).slice(1));
      response.setHeader("Access-Control-Allow-Origin", "*");
      if (!file.startsWith(folder + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        response.writeHead(404).end();
        return;
      }
      fs.createReadStream(file).pipe(response);
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(String(error)));
    try {
      const url = `${origin}/${path.relative(folder, store).split(path.sep).join("/")}/|zarr3:`;
      await openOn(page, [channelOf([url])]);
      await expectThePictureOnTheOutline(page, finest ? "store-finest" : "store-coarse", info.outputPath.bind(info));
      expect(errors).toEqual([]);
    } finally {
      await page.evaluate(() => window.planViewer?.destroy()).catch(() => {});
      await new Promise(resolve => server.close(resolve));
    }
  });
}
