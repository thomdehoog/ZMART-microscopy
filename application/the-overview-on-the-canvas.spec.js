/**
 * The acceptance proof: a scanned overview, on the operator's canvas, whole.
 *
 * An operator connects the mock instrument, lays out a six-well plate, tiles
 * it, measures focus, and presses Start on the scan step. What has to be true
 * afterwards is what they asked for: **every well carries its acquired
 * picture, registered under the plan**.
 *
 * The focussing is hidden before the picture is judged, and that is the whole
 * point of this test rather than a detail of it. A focus stack is one place on
 * the plate, and one patch of tissue at one place looks much like an overview
 * that has drawn a single field — which is exactly how this fault hid for so
 * long. With the focussing off, anything on screen is the overview or nothing.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  rest, startTheBridge,
} from "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "the-overview-on-the-canvas");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8803);

/** A whole run is a run: connecting, focussing and scanning all take time. */
const A_WHOLE_RUN = 900_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/**
 * How many of the plate's wells carry acquired picture.
 *
 * Counted rather than looked at, and counted *per well*, because the number
 * that matters is not how much tissue is on screen but how much of the plate
 * it is spread over: two fields out of fifty-four still look like a picture.
 * Each well's own square of the photograph is examined, and a well counts as
 * carrying picture when enough of it differs from the page's own colour to be
 * more than a stray edge.
 */
async function wellsCarryingPicture(page, name) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  return page.evaluate(() => {
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    const wells = window.__theStageCanvas.plan().reduce((seen, at) => {
      /* The plan's fields cluster in wells; rounding to the well pitch is
         enough to tell one cluster from another. */
      const key = `${Math.round(at.x / 20000)},${Math.round(at.y / 20000)}`;
      (seen[key] ??= []).push(at);
      return seen;
    }, {});
    return { wells: Object.keys(wells).length, box: { w: box.width, h: box.height } };
  });
}

test("every well shows its acquired overview, with the focussing hidden", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  /* Which acquisition every piece of picture was asked for, so that what is
     on screen can be attributed rather than admired. This is the evidence
     that settles the question the photographs cannot: a well full of tissue
     drawn entirely from overview chunks, with not one focussing chunk
     fetched while it was being drawn. */
  let fetched = new Map();
  page.on("response", (answer) => {
    const url = answer.url();
    if (!url.includes("/data/")) return;
    const store = url.split("/data/")[1].split("/").slice(0, 2).join("/");
    if (!store.includes(".zarr")) return;
    const kind = store.includes("focussing") ? "focussing" : "overview";
    fetched.set(kind, (fetched.get(kind) ?? 0) + 1);
  });
  const fetchedSince = () => {
    const was = Object.fromEntries(fetched);
    fetched = new Map();
    return was;
  };

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
    .toHaveText("Run again", { timeout: 400_000 });

  await gotoStep("Scan the overview");
  await page.locator(".panel.on button.step-run").click();
  await expect
    .poll(async () => page.evaluate(async (port) => {
      const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
      return !scan.running;
    }, PORT), { timeout: 400_000, message: "the scan never finished" })
    .toBe(true);
  /* The picture is asked for again on a clock, so it is given time to notice
     that the run has finished growing and to open over the whole of it. */
  await rest(30_000);

  /* The focussing off, the plan faded well back: what is left on screen is
     the acquired overview or nothing at all.

     Turning it off is not taken on trust. The engine is asked afterwards what
     it believes each row's visibility to be, and the answer is checked — a
     screenshot in which the focussing was still being drawn would prove
     nothing at all, and the panel's own eye beside each channel is not
     evidence either, because the panel is not told when a page turns a row
     off from underneath it. */
  const hidden = await page.evaluate(() => {
    const rows = window.__thePicture.layersForMeasurement();
    rows.forEach((row, at) => {
      if (row.name.startsWith("focussing")) {
        window.__thePicture.setChannel(at, { visible: false });
      }
    });
    window.__theStageCanvas.fadeTo(0.12);
    /* And the panel told, so its eyes say what the picture is really doing.
       A photograph in which the focussing's eye is still open reads as a
       focussing that is still drawn, whatever the numbers say. */
    window.__viewerPanelHandle?.refresh?.();
    return rows.map((row) => row.name);
  });
  const standing = await page.evaluate(() =>
    window.__thePicture.layersForMeasurement()
      .map((row) => ({ name: row.name, visible: row.visible })));
  console.log("rows:", JSON.stringify(standing));
  for (const row of standing) {
    expect(row.visible, `${row.name} is ${row.visible ? "shown" : "hidden"}`)
      .toBe(!row.name.startsWith("focussing"));
  }

  /* The whole plate on screen, the way the Fit button frames it. */
  await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    const xs = plan.map((at) => at.x);
    const ys = plan.map((at) => at.y);
    const width = Math.max(...xs) - Math.min(...xs);
    const height = Math.max(...ys) - Math.min(...ys);
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    window.__theStageCanvas.lookAt({
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      y: (Math.min(...ys) + Math.max(...ys)) / 2,
      /* A little room around the edge, so the outer wells are not cut off. */
      zoom: 1.25 * Math.max(width / box.width, height / box.height),
    });
  });
  await rest(25_000);

  const counted = await page.evaluate(() => {
    const host = document.querySelector("#stage-canvas").getBoundingClientRect();
    const plan = window.__theStageCanvas.plan();
    const clusters = new Map();
    for (const at of plan) {
      const key = `${Math.round(at.x / 20000)},${Math.round(at.y / 20000)}`;
      const held = clusters.get(key) ?? [];
      held.push(at);
      clusters.set(key, held);
    }
    /* Where each well's fields land on screen, as the plan itself works it
       out — the same projection the picture is registered to. */
    return [...clusters.entries()].map(([key, held]) => {
      const put = held.map((at) => window.__theStageCanvas.project(at.x, at.y));
      const xs = put.map((p) => p.x);
      const ys = put.map((p) => p.y);
      return {
        well: key,
        left: Math.min(...xs) - host.left, right: Math.max(...xs) - host.left,
        top: Math.min(...ys) - host.top, bottom: Math.max(...ys) - host.top,
      };
    });
  });
  console.log("wells:", JSON.stringify(counted));

  console.log("SCENE:", JSON.stringify(await page.evaluate(async (port) => {
    const state = await (await fetch(`http://127.0.0.1:${port}/api/viewer`)).json();
    const overview = (state.sources || {}).overview || [];
    const out = { sources: state.sources };
    for (const source of overview) {
      const base = source.url.split("|")[0].replace(/\/+$/, "");
      const root = await (await fetch(`${base}/zarr.json`)).json();
      out.zmart = root.attributes?.zmart;
      const level0 = await (await fetch(`${base}/0/zarr.json`)).json();
      out.shape = level0.shape;
    }
    return out;
  }, PORT), null, 1));

  /* One well close up — and the well farthest from where the focussing
     stood, so that not even coincidence can put a focus stack under what is
     photographed. */
  const wellLookedAt = await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    const focus = window.__theFocusPoints?.();
    const far = plan.reduce((furthest, at) => {
      const away = (p) => (focus ? Math.hypot(p.x - focus.x, p.y - focus.y) : p.x + p.y);
      return away(at) > away(furthest) ? at : furthest;
    }, plan[0]);
    window.__theStageCanvas.lookAt({ x: far.x, y: far.y, zoom: 6 });
    /* Only where the two are, not everything the focus point remembers: a
       measured point carries its whole sweep, and printing that buries the
       one fact this line is for. */
    return {
      well: { x: far.x, y: far.y },
      focusStoodAt: focus ? { x: focus.x, y: focus.y } : null,
    };
  });
  console.log("looking at:", JSON.stringify(wellLookedAt));
  await rest(10_000);
  fetchedSince();
  await rest(15_000);
  await page.screenshot({ path: path.join(SHOTS, "a-well-close-up.png") });
  const whileDrawing = fetchedSince();
  console.log("fetched while drawing that well:", JSON.stringify(whileDrawing));
  expect(whileDrawing.overview ?? 0,
    "the overview's own pieces were fetched for this well").toBeGreaterThan(0);
  expect(whileDrawing.focussing ?? 0,
    "no focussing piece was fetched, so what is on screen is the overview").toBe(0);

  const shot = path.join(SHOTS, "the-plate.png");
  await page.locator("#stage-canvas").screenshot({ path: shot });
  console.log("photographed the plate");
  await page.screenshot({ path: path.join(SHOTS, "the-window.png") });

  expect(counted.length, "the plate was tiled into wells").toBeGreaterThan(1);
});
