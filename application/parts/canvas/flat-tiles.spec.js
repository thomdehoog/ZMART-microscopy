/**
 * Every flat tile of an overview is drawn, whatever height it landed at.
 *
 * A scanned overview is a row of one-plane stores, each at the stage z its
 * focus map gave the field, a fraction of a micrometre apart. The engine
 * draws a layer at one depth, so a flat tile is made a metre thick along its
 * own depth (`countFromTheCornerOfTheVoxelRatherThanItsMiddle` in the
 * neuroglancer engine) and every tile crosses whatever depth is looked at.
 * On the first real four-field run the last tile to load stayed one voxel
 * thick and was not drawn. Four tiles are written through the run's writer,
 * served from another origin, and opened the way a scan opens them: the
 * first as the picture, each later one added to the open rows as its field
 * lands, the last one served slowly so its extent arrives after the pass
 * that saw it added. Each source's own depth is read back from the engine:
 * all four must be thick, and all must stand at the one depth every slice
 * is drawn at (the rule: slices all at one z, stacks relative to each
 * other; the store keeps the height a slice was really taken at). Then the
 * first real eight-field run's own heights, arriving one by one and all at
 * once: two of its eight tiles showed.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge }
  from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..", "..");
const TILES = 4;

/** The tiles written to a folder of their own, and a server that hands their
 *  files to the page from another origin, as the viewer beside the bridge
 *  would. One store, named by `slowly`, is answered `byMs` late, so its
 *  description lands after the engine has looked at the row it joined. */
async function tilesServed(count, { slowly = null, byMs = 0, heights = null } = {}) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-flat-tiles-"));
  const stores = execFileSync(pythonForTheBridge(),
    [path.join(HERE, "fixtures", "write-flat-tiles.py"), folder, String(count),
      ...(heights ? [heights.join(",")] : [])],
    { cwd: REPO, encoding: "utf8" }).trim().split(/\r?\n/);
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
    const wait = slowly && asked.includes(slowly) ? byMs : 0;
    setTimeout(() => fs.createReadStream(file).pipe(response), wait);
  });
  await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
  const at = stores.map((store) => `http://127.0.0.1:${server.address().port}/${store}/|zarr3:`);
  return { at, stop: () => server.close() };
}

/** Where the engine holds each source of the one layer along whichever axis
 *  is its depth: `[lower, upper]` in voxels of that depth. */
const depthSpansOfTheSources = (page) => page.evaluate(() =>
  window.__flatTiles.layersForMeasurement().flatMap((layer) => layer.sources.map((source) => {
    if (!source.dims || !source.lower) return null;
    const at = source.dims.findIndex((name) => name.startsWith("z"));
    return at < 0 ? null : [source.lower[at], source.upper[at]];
  })));

/** How many voxels deep the engine holds each source. */
const depthsOfTheSources = async (page) =>
  (await depthSpansOfTheSources(page)).map((span) => (span ? span[1] - span[0] : span));

/** Every slice is drawn at the same depth: one lower bound shared by all,
 *  whatever height each was taken at. Returns the lower bounds that differ
 *  from the first source's, with their index; empty when all agree. */
const slicesStandingApart = async (page) => {
  const spans = await depthSpansOfTheSources(page);
  const shared = spans[0]?.[0];
  return spans.map((span, index) => (span?.[0] === shared ? null : `source ${index} stands at ${span?.[0]}, not ${shared}`))
    .filter(Boolean);
};

/** The heights the first real eight-field run left its tiles at (two wells
 *  of four, a measured focus map): not monotonic, a fraction of a micrometre
 *  to a micrometre and a half apart. Two of them showed. */
const A_REAL_RUNS_HEIGHTS = [62.99, 62.79, 64.26, 64.01, 61.10, 60.40, 62.20, 61.40];

const theOverviewOf = (sources) => [{
  name: "overview", url: sources[0],
  channels: [
    { name: "488", colour: [0, 1, 0], sources, channelIndex: 0 },
    { name: "561", colour: [1, 0, 1], sources, channelIndex: 1 },
  ],
}];

test.describe("a row of flat tiles at their own heights", () => {
  test.setTimeout(120_000);

  test("every tile is drawn thick, the last to land included", async ({ page }) => {
    const last = `P${String(TILES - 1).padStart(6, "0")}`;
    const served = await tilesServed(TILES, { slowly: last, byMs: 800 });
    const said = [];
    page.on("pageerror", (why) => said.push(why.message));
    try {
      await page.goto("/?backend=pretend");
      await page.evaluate(async ({ acquisitions }) => {
        const host = document.createElement("div");
        host.style.cssText = "position:fixed;inset:0;z-index:999;background:#fff;";
        document.body.append(host);
        const { openerFor } = await import("/parts/canvas/engines.js");
        const openViewer = await openerFor("neuroglancer-under");
        window.__flatTiles = await openViewer(host, {
          acquisitions, presentation: "2d-overlay", background: "#ffffff",
        });
      }, { acquisitions: theOverviewOf(served.at.slice(0, 1)) });
      /* The rest land one at a time, as a scan's fields do. */
      for (let landed = 2; landed <= TILES; landed += 1) {
        await page.waitForTimeout(400);
        const grown = await page.evaluate(
          (acquisitions) => window.__flatTiles.addSources(acquisitions),
          theOverviewOf(served.at.slice(0, landed)));
        expect(grown, `tile ${landed} joined the open picture`).toBe(true);
      }

      await expect.poll(() => depthsOfTheSources(page), {
        message: "every source should be read",
        timeout: 30_000,
      }).toEqual(Array.from({ length: 2 * TILES }, () => expect.any(Number)));
      /* Read, and then given time to be made thick: a source is thickened in
         a pass after its extent lands, not in the read itself. */
      await page.waitForTimeout(3000);
      const depths = await depthsOfTheSources(page);
      for (const [index, depth] of depths.entries()) {
        expect(depth, `tile ${index % TILES} of channel ${Math.floor(index / TILES)} is one voxel thick, so it is drawn at one height only`)
          .toBeGreaterThan(1e6);
      }
      expect(await slicesStandingApart(page), "every slice is drawn at the one shared depth").toEqual([]);
      expect(said, "the page raised nothing").toEqual([]);
    } finally {
      served.stop();
    }
  });

  for (const [arrival, howMany] of [["one field at a time", "one by one"], ["all at once", "together"]]) {
    test(`eight tiles at a real run's heights are all drawn thick, arriving ${arrival}`, async ({ page }) => {
      const count = A_REAL_RUNS_HEIGHTS.length;
      const served = await tilesServed(count, { heights: A_REAL_RUNS_HEIGHTS });
      const said = [];
      page.on("pageerror", (why) => said.push(why.message));
      try {
        await page.goto("/?backend=pretend");
        const opened = howMany === "together" ? count : 1;
        await page.evaluate(async ({ acquisitions }) => {
          const host = document.createElement("div");
          host.style.cssText = "position:fixed;inset:0;z-index:999;background:#fff;";
          document.body.append(host);
          const { openerFor } = await import("/parts/canvas/engines.js");
          const openViewer = await openerFor("neuroglancer-under");
          window.__flatTiles = await openViewer(host, {
            acquisitions, presentation: "2d-overlay", background: "#ffffff",
          });
        }, { acquisitions: theOverviewOf(served.at.slice(0, opened)) });
        for (let landed = opened + 1; landed <= count; landed += 1) {
          await page.waitForTimeout(300);
          const grown = await page.evaluate(
            (acquisitions) => window.__flatTiles.addSources(acquisitions),
            theOverviewOf(served.at.slice(0, landed)));
          expect(grown, `tile ${landed} joined the open picture`).toBe(true);
        }
        await expect.poll(() => depthsOfTheSources(page), {
          message: "every source should be read",
          timeout: 30_000,
        }).toEqual(Array.from({ length: 2 * count }, () => expect.any(Number)));
        await page.waitForTimeout(3000);
        const depths = await depthsOfTheSources(page);
        const thin = depths.map((depth, index) => (depth > 1e6 ? null : `tile ${index % count} of channel ${Math.floor(index / count)}: ${depth}`))
          .filter(Boolean);
        expect(thin, "every tile is thick").toEqual([]);
        expect(await slicesStandingApart(page), "every slice is drawn at the one shared depth").toEqual([]);
        if (process.env.FLAT_TILES_SHOT) await page.screenshot({ path: process.env.FLAT_TILES_SHOT + "-" + howMany.replace(/ /g, "_") + ".png" });
        expect(said, "the page raised nothing").toEqual([]);
      } finally {
        served.stop();
      }
    });
  }
});
