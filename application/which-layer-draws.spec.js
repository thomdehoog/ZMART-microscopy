/**
 * Which acquisition is actually on screen — the overview, or the focussing?
 *
 * On a run with both, "the picture is there" is not an answer: one tile of
 * tissue at the focus point looks much like an overview that has drawn one
 * field. So each acquisition is turned off in turn and the box photographed,
 * and the pixels are counted rather than looked at.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "@playwright/test";
import {
  rest, startTheBridge,
} from "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "which-layer");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8802);
let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/** How much of the picture box is not the page's own colour. */
async function inked(page, name) {
  /* The whole window, not the picture box on its own: the engine draws on a
     WebGL surface, and an element screenshot of the box it lives in comes
     back blank. */
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  return page.evaluate(() => {
    const host = document.querySelector("#picture-host");
    const engine = host.querySelector("canvas");
    if (!engine) return { drawn: 0, of: 0 };
    const scratch = document.createElement("canvas");
    scratch.width = engine.width;
    scratch.height = engine.height;
    scratch.getContext("2d").drawImage(engine, 0, 0);
    const d = scratch.getContext("2d").getImageData(0, 0, scratch.width, scratch.height).data;
    const corner = [d[0], d[1], d[2]];
    let drawn = 0;
    for (let at = 0; at < d.length; at += 4) {
      if (Math.abs(d[at] - corner[0]) > 8
        || Math.abs(d[at + 1] - corner[1]) > 8
        || Math.abs(d[at + 2] - corner[2]) > 8) drawn += 1;
    }
    return { drawn, of: d.length / 4 };
  });
}

test("the overview draws, and it is the overview that draws", async ({ page }) => {
  test.setTimeout(600_000);
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  /* Which source each data request belongs to, so "the engine never asked"
     can be told from "the data arrived and was not drawn". */
  let tally = new Map();
  page.on("response", (r) => {
    const url = r.url();
    if (!url.includes("/data/")) return;
    const rest = url.split("/data/")[1];
    const store = rest.split("/").slice(0, 2).join("/");
    const key = `${r.status()} ${rest}`;
    tally.set(key, (tally.get(key) ?? 0) + 1);
  });
  const sinceLast = () => { const was = [...tally.entries()]; tally = new Map(); return was; };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(600);

  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(600);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 300_000 });

  await gotoStep("Scan the overview");
  await page.locator(".panel.on button.step-run").click();
  await expect
    .poll(async () => page.evaluate(async (port) => {
      const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
      return !scan.running;
    }, PORT), { timeout: 300_000, message: "the scan never finished" })
    .toBe(true);
  await rest(25_000);

  /* Look where the plan actually put its first field, with the plan faded
     back so only the picture is counted. */
  await page.evaluate(() => {
    window.__theStageCanvas.fadeTo(0);
    const tile = window.__theStageCanvas.plan()[0];
    window.__theStageCanvas.lookAt({ x: tile.x, y: tile.y, zoom: 6 });
  });
  await rest(15_000);

  const rows = await page.evaluate(() =>
    window.__thePicture.layersForMeasurement().map((row) => row.name));
  console.log("rows:", JSON.stringify(rows));

  sinceLast();
  const both = await inked(page, "1-both");
  console.log("both:", JSON.stringify(both), "requests:", JSON.stringify(sinceLast()));

  /* Only the overview. */
  await page.evaluate((names) => {
    names.forEach((name, at) => {
      if (name.startsWith("focussing")) window.__thePicture.setChannel(at, { visible: false });
    });
  }, rows);
  await rest(10_000);
  const overviewOnly = await inked(page, "2-overview-only");
  console.log("overview only:", JSON.stringify(overviewOnly), "requests:", JSON.stringify(sinceLast()));
  console.log("WHAT IS SERVED:", JSON.stringify(await page.evaluate(async (port) => {
    const state = await (await fetch(`http://127.0.0.1:${port}/api/viewer`)).json();
    const out = { sources: state.sources };
    const overview = (state.sources || {}).overview || [];
    for (const source of overview) {
      const base = source.url.split("|")[0].replace(/\/+$/, "");
      const root = await fetch(`${base}/zarr.json`).then((r) => r.ok ? r.json() : `${r.status}`);
      out.root = typeof root === "string" ? root : {
        levels: (root.attributes?.ome?.multiscales?.[0]?.datasets ?? []).map((d) => d.path),
        zmart: root.attributes?.zmart,
      };
      for (const level of out.root.levels ?? []) {
        const arr = await fetch(`${base}/${level}/zarr.json`).then((r) => r.ok ? r.json() : `${r.status}`);
        out[`level ${level}`] = typeof arr === "string" ? arr
          : { shape: arr.shape, chunk: arr.chunk_grid?.configuration?.chunk_shape };
        const chunk = await fetch(`${base}/${level}/c/0/0/0/0/0`);
        out[`level ${level} chunk 0`] = chunk.status;
      }
    }
    return out;
  }, PORT), null, 1));
  console.log("WHERE:", JSON.stringify(await page.evaluate(() => {
    const rows = window.__thePicture.layersForMeasurement();
    const say = (row) => ({
      name: row.name,
      spans: Object.fromEntries((row.dims ?? []).map((d, i) =>
        [d, [row.lower[i], row.upper[i]]])),
      stands: Object.fromEntries((row.navDims ?? []).map((d, i) => [d, row.nav[i]])),
    });
    const tile = window.__theStageCanvas.plan()[0];
    return {
      layers: rows.map(say),
      planFirstField: tile,
      carrierOrigin: window.__theStageCanvas.carrierOriginUm(),
      pictureView: window.__thePicture.whereThingsAreDrawn?.(),
    };
  }), (k, v) => (k === "project" || k === "unproject" ? undefined : v), 1));

  /* Only the focussing. */
  await page.evaluate((names) => {
    names.forEach((name, at) => {
      window.__thePicture.setChannel(at, { visible: !name.startsWith("focussing") ? false : true });
    });
  }, rows);
  await rest(10_000);
  const focussingOnly = await inked(page, "3-focussing-only");
  console.log("focussing only:", JSON.stringify(focussingOnly), "requests:", JSON.stringify(sinceLast()));
});

import { expect } from "@playwright/test";
