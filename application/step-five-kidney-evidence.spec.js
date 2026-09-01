/** Real Step 5 kidney evidence. A screenshot without its JSON record is not evidence. */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { rest, startTheBridge } from
  "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from
  "./workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(HERE);
const SHOTS = path.join(HERE, "test-results", "step-five-kidney");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8812);
const PYTHON = process.env.PYTHON ?? "python";
const A_WHOLE_RUN = 900_000;

const command = (program, args, cwd = REPO) =>
  execFileSync(program, args, { cwd, encoding: "utf8" }).trim();
const provenance = {
  microscopy: {
    branch: command("git", ["branch", "--show-current"]),
    commit: command("git", ["rev-parse", "HEAD"]),
  },
  viewer: JSON.parse(command(PYTHON, ["-c", [
    "import json",
    "from importlib.metadata import version",
    "from pathlib import Path",
    "import zmart_viewer",
    "print(json.dumps({'path': str(Path(zmart_viewer.__file__).resolve()), " +
      "'version': version('zmart-viewer')}))",
  ].join("; ")])),
};
provenance.viewer.commit = command(
  "git", ["rev-parse", "HEAD"], path.dirname(path.dirname(provenance.viewer.path)),
);
provenance.viewer.hasMeasure = command(
  "rg", ["-q", '"/api/measure"', path.join(path.dirname(provenance.viewer.path), "server.py")],
) === "";

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/** Planned field boxes in viewport pixels. Nothing is clipped or skipped. */
async function fieldsOnScreen(page) {
  return page.evaluate(() => {
    const xy = (value) => Array.isArray(value)
      ? { x: value[0], y: value[1] }
      : { x: value?.x, y: value?.y };
    const canvas = document.querySelector("#stage-canvas").getBoundingClientRect();
    return window.__theStageCanvas.plan().map((position, index) => {
      const middle = xy(window.__theStageCanvas.project(position.x, position.y));
      const edge = xy(window.__theStageCanvas.project(
        position.x + position.frameUm / 2,
        position.y + position.frameUm / 2,
      ));
      const across = Math.abs(edge.x - middle.x);
      const down = Math.abs(edge.y - middle.y);
      return {
        index,
        centreUm: { x: position.x, y: position.y },
        frameUm: position.frameUm,
        left: canvas.left + middle.x - across,
        right: canvas.left + middle.x + across,
        top: canvas.top + middle.y - down,
        bottom: canvas.top + middle.y + down,
      };
    });
  });
}

/** Measure one complete planned ROI. Off-screen and non-finite boxes are errors. */
function inspectField(pixels, box) {
  const edges = [box.left, box.right, box.top, box.bottom];
  if (!edges.every(Number.isFinite)) return { error: "unprojectable" };
  if (box.left < 0 || box.top < 0 || box.right > pixels.width || box.bottom > pixels.height) {
    return { error: "off-screen" };
  }
  const inset = 0.25;
  const left = Math.round(box.left + (box.right - box.left) * inset);
  const right = Math.round(box.right - (box.right - box.left) * inset);
  const top = Math.round(box.top + (box.bottom - box.top) * inset);
  const bottom = Math.round(box.bottom - (box.bottom - box.top) * inset);
  if (right <= left || bottom <= top) return { error: "unprojectable" };

  const { data, width, channels } = pixels;
  const corner = [data[0], data[1], data[2]];
  let drawn = 0;
  let examined = 0;
  const shades = new Set();
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const at = (y * width + x) * channels;
      examined += 1;
      if (corner.some((value, channel) => Math.abs(data[at + channel] - value) > 10)) {
        drawn += 1;
      }
      shades.add(data[at] >> 2);
    }
  }
  return { covered: drawn / examined, shades: shades.size };
}

async function liveState(page) {
  return page.evaluate(async (port) => {
    const viewer = await fetch(`http://127.0.0.1:${port}/api/viewer`)
      .then((answer) => answer.json()).catch((error) => ({ error: error.message }));
    const acquisitions = viewer.acquisitions ?? [];
    const layers = window.__thePicture?.layersForMeasurement?.() ?? [];
    const placed = window.__thePicture?.whereThingsAreDrawn?.() ?? null;
    const plan = window.__theStageCanvas.plan();
    const [originX, originY] = window.__theStageCanvas.carrierOriginUm();
    const tracedPositions = [0, 8].map((index) => {
      const position = plan[index];
      if (!position) return null;
      const absolute = { x: position.x + originX, y: position.y + originY };
      const stageScreen = window.__theStageCanvas.project(position.x, position.y);
      const engineScreen = placed?.project?.(absolute.x, absolute.y) ?? null;
      const stage = Array.isArray(stageScreen)
        ? { x: stageScreen[0], y: stageScreen[1] }
        : stageScreen;
      return {
        index,
        carrierLocalUm: { x: position.x, y: position.y },
        carrierOriginUm: { x: originX, y: originY },
        absoluteStageUm: absolute,
        stageScreenPx: stage,
        engineScreenPx: engineScreen,
        screenErrorPx: stage && engineScreen
          ? Math.hypot(stage.x - engineScreen.x, stage.y - engineScreen.y)
          : null,
      };
    }).filter(Boolean);
    const view = placed ? {
      centre: placed.centre,
      zoom: placed.zoom,
      width: placed.width,
      height: placed.height,
    } : null;
    const sourceCount = acquisitions.reduce((total, acquisition) => total +
      (acquisition.channels ?? []).reduce((count, channel) =>
        count + (channel.sources?.length ?? (channel.source || acquisition.url ? 1 : 0)), 0), 0);
    return {
      sourceCount,
      acquisitions,
      engine: { layers, view },
      stage: { view: window.__theStageCanvas.view(), tracedPositions },
      visibility: layers.map(({ name, visible }) => ({ name, visible })),
    };
  }, PORT);
}

function zarrTrace(position) {
  const folder = path.join(bridge.currentRun(), "positions", "overview");
  const marker = `P${String(position).padStart(6, "0")}`;
  const store = fs.readdirSync(folder).find((name) => name.includes(marker));
  if (!store) return { position, error: "position store not found" };
  const metadata = JSON.parse(fs.readFileSync(path.join(folder, store, "zarr.json"), "utf8"));
  const level0 = metadata.attributes.ome.multiscales[0].datasets
    .find((dataset) => dataset.path === "0");
  const scale = level0.coordinateTransformations.find(({ type }) => type === "scale")?.scale;
  const translation = level0.coordinateTransformations
    .find(({ type }) => type === "translation")?.translation;
  return { position, store, axes: ["t", "c", "z", "y", "x"], scale, translation };
}

test("nine kidney fields are all examined; off-screen fields fail", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const browserErrors = [];
  const failedRequests = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push({
    url: request.url(), error: request.failure()?.errorText ?? "failed",
  }));

  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };
  const imaged = () => page.evaluate(async (port) => {
    const scan = await (await fetch(`http://127.0.0.1:${port}/api/scan`)).json();
    return { done: scan.done ?? 0, of: scan.of ?? 0, running: !!scan.running };
  }, PORT);
  const shot = async (name, extra = {}) => {
    const png = await page.screenshot();
    fs.writeFileSync(path.join(SHOTS, `${name}.png`), png);
    fs.writeFileSync(path.join(SHOTS, `${name}.json`), JSON.stringify({
      ...provenance,
      name,
      timestampUtc: new Date().toISOString(),
      bridgePort: PORT,
      ...(await liveState(page)),
      browserErrors,
      failedRequests,
      ...extra,
    }, null, 2));
    return readPng(png);
  };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);
  await gotoStep("Define scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);

  const planned = await page.evaluate(() => window.__theStageCanvas.plan().length);
  expect(planned, "a three by three tileset").toBe(9);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });

  await gotoStep("Scan the overview");
  await rest(1500);
  await shot("0-of-9", { planned, landed: 0, examined: 0, textured: 0 });
  expect((await imaged()).done, "nothing is imaged before Run").toBe(0);
  await page.locator(".panel.on button.step-run").click();

  for (const wanted of [1, 9]) {
    await expect.poll(async () => (await imaged()).done, {
      timeout: 400_000,
      intervals: [100],
      message: `the scan never reached ${wanted} fields`,
    }).toBeGreaterThanOrEqual(wanted);
    await rest(1500);
    const now = await imaged();
    await shot(`${wanted}-requested-${now.done}-landed`, {
      planned, landed: now.done, examined: 0, textured: 0,
    });
  }
  await expect.poll(async () => !(await imaged()).running, {
    timeout: 400_000,
    message: "the scan never finished",
  }).toBe(true);
  expect((await imaged()).done, "every planned field was imaged").toBe(9);
  await rest(12_000);

  await page.evaluate(() => {
    window.__thePicture.layersForMeasurement().forEach((row, index) => {
      if (row.name.startsWith("focussing")) {
        window.__thePicture.setChannel(index, { visible: false });
      }
    });
    window.__theStageCanvas.fadeTo(0);
  });
  await rest(4000);

  const fields = await fieldsOnScreen(page);
  expect(fields, "exactly the nine planned ROIs are projected").toHaveLength(9);
  const pixels = readPng(await page.screenshot());
  const results = fields.map((field) => ({ field, result: inspectField(pixels, field) }));
  const failedProjection = results.filter(({ result }) => result.error);
  const examined = results.filter(({ result }) => !result.error);
  const thin = examined.filter(({ result }) => result.covered < 0.9);
  const flat = examined.filter(({ result }) => result.shades < 8);
  const trace = {
    browser: (await liveState(page)).stage.tracedPositions,
    stores: [zarrTrace(0), zarrTrace(8)],
    engineLayers: (await liveState(page)).engine.layers,
  };
  fs.writeFileSync(path.join(SHOTS, "coordinate-trace.json"), JSON.stringify(trace, null, 2));

  await shot("overview-only", {
    planned,
    landed: 9,
    examined: examined.length,
    textured: examined.length - flat.length,
    roiResults: results,
    coordinateTrace: trace,
  });
  expect(failedProjection, "no planned ROI is off-screen or unprojectable").toEqual([]);
  expect(examined, "all nine planned ROIs were examined").toHaveLength(9);
  expect(thin, "every planned ROI carries picture").toEqual([]);
  expect(flat, "every planned ROI is textured kidney data").toEqual([]);

  await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
  await page.locator("#fit-btn").click();
  await rest(6000);
  await shot("whole-plate", {
    planned, landed: 9, examined: examined.length, textured: examined.length - flat.length,
  });
});
