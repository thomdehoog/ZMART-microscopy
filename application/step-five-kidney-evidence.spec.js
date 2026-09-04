/** Real Smart Viewer 0.2 / mock-kidney evidence for operator Step 5. */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { rest, showDisplaySettings, showTheChannel, startTheBridge } from
  "./workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from
  "./workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.dirname(HERE);
const ACCEPTED = process.env.ACCEPT_EVIDENCE === "1";
const SHOTS = ACCEPTED
  ? path.join(REPO, "docs", "reviews", "evidence", "2026-09-01-smart-viewer-step-five")
  : path.join(HERE, "test-results", "step-five-kidney");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8812);
const RUN_PORT = PORT + 2;
const PYTHON = process.env.PYTHON ?? "python";
const A_WHOLE_RUN = 900_000;
const SCREEN_TOLERANCE_PX = 1;

const command = (program, args, cwd = REPO) =>
  execFileSync(program, args, { cwd, encoding: "utf8" }).trim();
const provenance = {
  microscopy: {
    branch: command("git", ["branch", "--show-current"]),
    commit: command("git", ["rev-parse", "HEAD"]),
  },
  smartViewer: JSON.parse(command(PYTHON, ["-c", [
    "import json",
    "from importlib.metadata import version",
    "from pathlib import Path",
    "import zmart_viewer",
    "print(json.dumps({'importPath': str(Path(zmart_viewer.__file__).resolve()), " +
      "'version': version('zmart-viewer')}))",
  ].join("; ")])),
};
provenance.smartViewer.commit = command(
  "git", ["rev-parse", "HEAD"], path.dirname(path.dirname(provenance.smartViewer.importPath)),
);
/* Read, not grepped: the machine this runs on need not carry ripgrep, and a
   spec that could not load for want of it proved nothing. */
provenance.smartViewer.measureRoutePresent = fs.readFileSync(
  path.join(path.dirname(provenance.smartViewer.importPath), "server.py"), "utf8",
).includes("/api/measure");

test.beforeAll(() => { fs.mkdirSync(SHOTS, { recursive: true }); });

const xy = (value) => Array.isArray(value)
  ? { x: value[0], y: value[1] }
  : { x: value?.x, y: value?.y };

function acquisitionOf(name, acquisitions) {
  return acquisitions.find((acquisition) => acquisition.name === name) ?? null;
}

function sourcesIn(acquisition) {
  if (!acquisition) return [];
  const channelSources = (acquisition.channels ?? [])
    .flatMap((channel) => channel.sources ?? [channel.source].filter(Boolean));
  return channelSources.length ? channelSources : [acquisition.url].filter(Boolean);
}

function acquisitionSummary(acquisitions) {
  return acquisitions.map((acquisition) => ({
    name: acquisition.name,
    datasetNumber: acquisition.dataset_number ?? acquisition.datasetNumber ?? null,
    url: acquisition.url ?? null,
    logicalChannelCount: acquisition.channels?.length ?? 0,
    channels: (acquisition.channels ?? []).map((channel) => ({
      name: channel.name,
      visible: channel.visible !== false,
      sourceCount: channel.sources?.length ?? (channel.source || acquisition.url ? 1 : 0),
      sources: channel.sources ?? [channel.source ?? acquisition.url].filter(Boolean),
    })),
  }));
}

function unitToUm(unit) {
  if (unit === "m") return 1e6;
  if (unit === "mm") return 1e3;
  if (unit === "nm") return 1e-3;
  return 1;
}

function physicalBounds(source) {
  if (![source?.dims, source?.scales, source?.units, source?.lower, source?.upper]
    .every(Array.isArray)) return null;
  const along = (axis, edge) => {
    const at = source.dims.indexOf(axis);
    if (at < 0) return null;
    return source[edge][at] * source.scales[at] * unitToUm(source.units[at]);
  };
  const values = {
    xMin: along("x", "lower"), yMin: along("y", "lower"),
    xMax: along("x", "upper"), yMax: along("y", "upper"),
  };
  return Object.values(values).every(Number.isFinite) ? values : null;
}

function aggregateBounds(bounds) {
  const present = bounds.filter(Boolean);
  if (!present.length) return null;
  return {
    frame: "absolute-stage",
    unit: "um",
    xMin: Math.min(...present.map(({ xMin }) => xMin)),
    yMin: Math.min(...present.map(({ yMin }) => yMin)),
    xMax: Math.max(...present.map(({ xMax }) => xMax)),
    yMax: Math.max(...present.map(({ yMax }) => yMax)),
  };
}

function positionNumber(url) {
  const found = /P(\d{6})/.exec(url ?? "");
  return found ? Number(found[1]) : null;
}

/** Planned field boxes in viewport pixels. Nothing is clipped or skipped. */
async function fieldsOnScreen(page) {
  return page.evaluate(() => {
    const point = (value) => Array.isArray(value)
      ? { x: value[0], y: value[1] }
      : { x: value?.x, y: value?.y };
    const canvas = document.querySelector("#stage-canvas").getBoundingClientRect();
    return window.__theStageCanvas.plan().map((position, index) => {
      const middle = point(window.__theStageCanvas.project(position.x, position.y));
      const edge = point(window.__theStageCanvas.project(
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

/** Zoom around a carrier-local point, then pan it to the canvas centre. */
async function frameAround(page, centre, targetZoom) {
  const where = () => page.evaluate(({ at }) => {
    const projected = window.__theStageCanvas.project(at.x, at.y);
    const point = Array.isArray(projected)
      ? { x: projected[0], y: projected[1] }
      : projected;
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    return {
      x: box.left + point.x,
      y: box.top + point.y,
      canvas: {
        left: box.left, top: box.top, right: box.right, bottom: box.bottom,
        x: box.left + box.width / 2, y: box.top + box.height / 2,
      },
    };
  }, { at: centre });

  for (let turn = 0; turn < 12; turn += 1) {
    const zoom = await page.evaluate(() => window.__theStageCanvas.view().zoom);
    if (zoom <= targetZoom) break;
    const anchor = await where();
    await page.mouse.move(anchor.x, anchor.y);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(100);
  }
  await expect.poll(
    () => page.evaluate(() => window.__theStageCanvas.view().zoom),
    { message: `the view never reached ${targetZoom} um per pixel` },
  ).toBeLessThanOrEqual(targetZoom);

  for (let turn = 0; turn < 24; turn += 1) {
    const now = await where();
    const dx = now.canvas.x - now.x;
    const dy = now.canvas.y - now.y;
    if (Math.abs(dx) < 2 && Math.abs(dy) < 2) break;
    const startX = Math.min(Math.max(now.x, now.canvas.left + 20), now.canvas.right - 20);
    const startY = Math.min(Math.max(now.y, now.canvas.top + 20), now.canvas.bottom - 20);
    const movedX = Math.max(now.canvas.left + 20 - startX,
      Math.min(now.canvas.right - 20 - startX, dx));
    const movedY = Math.max(now.canvas.top + 20 - startY,
      Math.min(now.canvas.bottom - 20 - startY, dy));
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + movedX, startY + movedY, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(150);
  }
  await expect.poll(async () => {
    const now = await where();
    return Math.hypot(now.canvas.x - now.x, now.canvas.y - now.y);
  }, { message: "the requested field never reached the canvas centre" }).toBeLessThan(2);
  /* Leaving the pointer over a planned field opens the stage-coordinate tip.
     That is useful to an operator and not part of the acquired pixels; park it
     in the page margin before taking evidence so it cannot cover an ROI. */
  await page.mouse.move(4, 4);
  await page.waitForTimeout(150);
}

async function framePlannedGrid(page) {
  const centre = await page.evaluate(() => {
    const plan = window.__theStageCanvas.plan();
    return {
      x: (Math.min(...plan.map(({ x }) => x)) + Math.max(...plan.map(({ x }) => x))) / 2,
      y: (Math.min(...plan.map(({ y }) => y)) + Math.max(...plan.map(({ y }) => y))) / 2,
    };
  });
  await frameAround(page, centre, 12);
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

function isTextured(result) {
  return !result.error && result.covered >= 0.9 && result.shades >= 8;
}

/** A screenshot-owned pixel result, including views too wide for texture ROIs. */
function inspectScreenRegion(pixels, box) {
  if (!box || ![box.x, box.y, box.width, box.height].every(Number.isFinite)) {
    return { error: "unprojectable" };
  }
  const left = Math.max(0, Math.floor(box.x));
  const top = Math.max(0, Math.floor(box.y));
  const right = Math.min(pixels.width, Math.ceil(box.x + box.width));
  const bottom = Math.min(pixels.height, Math.ceil(box.y + box.height));
  if (right <= left || bottom <= top) return { error: "off-screen" };
  const { data, width, channels } = pixels;
  const first = (top * width + left) * channels;
  const background = [data[first], data[first + 1], data[first + 2]];
  const shades = new Set();
  let differentFromCorner = 0;
  let examined = 0;
  // Sampling every other pixel keeps the JSON summary small to compute while
  // still examining tens of thousands of pixels in the operator canvas.
  for (let y = top; y < bottom; y += 2) {
    for (let x = left; x < right; x += 2) {
      const at = (y * width + x) * channels;
      const rgb = [data[at], data[at + 1], data[at + 2]];
      examined += 1;
      if (rgb.some((value, channel) => Math.abs(value - background[channel]) > 10)) {
        differentFromCorner += 1;
      }
      shades.add(`${rgb[0] >> 4}:${rgb[1] >> 4}:${rgb[2] >> 4}`);
    }
  }
  return { examined, differentFromCorner, shadeBins: shades.size, backgroundRgb: background };
}

function pixelChangesInside(first, second, box) {
  const a = readPng(first);
  const b = readPng(second);
  const left = Math.max(0, Math.floor(box.left));
  const top = Math.max(0, Math.floor(box.top));
  const right = Math.min(a.width, Math.ceil(box.right));
  const bottom = Math.min(a.height, Math.ceil(box.bottom));
  let changed = 0;
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      const at = (y * a.width + x) * a.channels;
      if ([0, 1, 2].some((channel) => Math.abs(a.data[at + channel] - b.data[at + channel]) > 10)) {
        changed += 1;
      }
    }
  }
  return changed;
}

function expectedFormatProbe(url) {
  try {
    return /\/(?:\.zattrs|\.zgroup)$/.test(new URL(url).pathname);
  } catch {
    return false;
  }
}

function expectedOptionalProbe(url, port) {
  try {
    const parsed = new URL(url);
    return parsed.hostname === "127.0.0.1" && parsed.port === String(port)
      && parsed.pathname === "/view/overview/tiles.json";
  } catch {
    return false;
  }
}

function dataRequestKind(url, port) {
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== "127.0.0.1") return null;
    if (expectedFormatProbe(url)) return "format-probe";
    if (expectedOptionalProbe(url, port)) return "optional-probe";
    if (parsed.pathname === "/api/measure") return "measurement";
    /* Smart Viewer serves the stores from a data server whose port is chosen
       at run time. The URL path, not the bridge port, identifies these. */
    if (/\/data\/\d+\/.+\/zarr\.json$/.test(parsed.pathname)) return "metadata";
    if (/\/data\/\d+\/.+\.ome\.zarr\/\d+\/c\//.test(parsed.pathname)) return "chunk";
    if (parsed.port !== String(port)) return null;
    if (parsed.pathname.startsWith("/api/")) return "api";
    return null;
  } catch {
    return null;
  }
}

function trackBrowser(page, port) {
  const pageErrors = [];
  const consoleErrors = [];
  const failures = [];
  const responses = [];
  const navigationCancellations = new Set();

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const location = message.location()?.url ?? "";
    if (expectedFormatProbe(location) || expectedOptionalProbe(location, port)) return;
    consoleErrors.push({ text: message.text(), location });
  });
  page.on("requestfailed", (request) => {
    const kind = dataRequestKind(request.url(), port);
    if (!kind) return;
    failures.push({
      kind, url: request.url(), error: request.failure()?.errorText ?? "failed",
    });
  });
  page.on("response", (response) => {
    const kind = dataRequestKind(response.url(), port);
    if (!kind) return;
    responses.push({ kind, url: response.url(), status: response.status() });
  });

  return {
    /**
     * Bound ordinary browser cancellation to one explicit view transition.
     * Only chunk reads cancelled with ERR_ABORTED inside this interval qualify;
     * HTTP failures, metadata/API failures, and anything outside it remain
     * unexpected. The returned record keeps the cancellations visible.
     */
    async duringNavigation(action) {
      const first = failures.length;
      await action();
      for (let at = first; at < failures.length; at += 1) {
        const failure = failures[at];
        if (failure.kind === "chunk" && failure.error === "net::ERR_ABORTED") {
          navigationCancellations.add(at);
        }
      }
    },

    snapshot() {
      const successful = (kind) => responses.filter(
        (response) => response.kind === kind && response.status >= 200 && response.status < 400,
      ).length;
      const expectedFormatProbes = [
        ...failures.filter(({ kind }) => kind === "format-probe"),
        ...responses.filter(({ kind, status }) => kind === "format-probe" && status >= 400),
      ];
      const expectedOptionalProbes = [
        ...failures.filter(({ kind }) => kind === "optional-probe"),
        ...responses.filter(({ kind, status }) => kind === "optional-probe" && status >= 400),
      ];
      /* The engine cancels a chunk fetch it no longer needs whenever a
         source's placement settles or the view moves; the browser reports
         that as ERR_ABORTED. They are counted here, apart from a request the
         server refused or lost, which stays unexpected. */
      const expectedEngineCancellations = failures.filter(({ kind, error }, at) =>
        !navigationCancellations.has(at) && kind === "chunk" && error === "net::ERR_ABORTED");
      const unexpectedFailures = [
        ...failures.filter(({ kind, error }, at) => !navigationCancellations.has(at)
          && !(kind === "chunk" && error === "net::ERR_ABORTED")
          && !["format-probe", "optional-probe"].includes(kind)),
        ...responses.filter(({ kind, status }) =>
          !["format-probe", "optional-probe"].includes(kind) && status >= 400),
      ];
      const browserErrors = [
        ...pageErrors,
        ...consoleErrors.map(({ text, location }) => `${text}${location ? ` (${location})` : ""}`),
      ];
      return {
        required: {
          metadata: { successful: successful("metadata") },
          chunks: { successful: successful("chunk") },
          measurement: { successful: successful("measurement") },
          api: { successful: successful("api") },
        },
        expectedFormatProbes,
        expectedOptionalProbes,
        expectedNavigationCancellations: failures
          .filter((_, at) => navigationCancellations.has(at))
          .map((failure) => ({ ...failure, reason: "operator view transition" })),
        expectedEngineCancellations,
        unexpectedFailures,
        browserErrors,
        workerErrors: browserErrors.filter((error) => /worker|chunk/i.test(error)),
      };
    },
  };
}

async function walkToScan(page, port) {
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${port}`)}`);
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);
  await gotoStep("Overview scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => window.__theStageCanvas.plan().length), "a 3 x 3 plan")
    .toBe(9);

  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });

  await gotoStep("Scan the overview");
  await expect.poll(() => frontOverviewState(page), {
    timeout: 60_000,
    message: "the focusing acquisition never opened in Smart Viewer",
  }).toMatchObject({ focusingRows: 1 });
  await rest(2500);
}

async function scanStatus(page, port) {
  return page.evaluate(async (bridgePort) =>
    fetch(`http://127.0.0.1:${bridgePort}/api/scan`).then((answer) => answer.json()), port);
}

async function frontOverviewState(page) {
  return page.evaluate(() => {
    const layers = window.__thePicture?.layersForMeasurement?.() ?? [];
    const overview = layers.filter(({ name }) => name.startsWith("overview"));
    return {
      focusingRows: layers.filter(({ name }) => name.startsWith("focussing")).length,
      overviewRows: overview.length,
      sourceCounts: overview.map((row) => row.sources?.length ?? 0),
      errors: overview.flatMap((row) => row.sources ?? []).filter(({ error }) => error).length,
      bounded: overview.flatMap((row) => row.sources ?? [])
        .filter((source) => Array.isArray(source.lower) && Array.isArray(source.upper)).length,
    };
  });
}

async function waitForOverview(page, positions) {
  await expect.poll(() => frontOverviewState(page), {
    timeout: 90_000,
    intervals: [250, 500, 1000],
    message: `Smart Viewer never loaded ${positions} overview positions per channel`,
  }).toEqual({
    focusingRows: 1,
    overviewRows: 3,
    sourceCounts: [positions, positions, positions],
    errors: 0,
    bounded: positions * 3,
  });
  await rest(1500);
}

async function texturedIndices(page) {
  const boxes = await fieldsOnScreen(page);
  const pixels = readPng(await page.screenshot());
  return boxes
    .filter((field) => isTextured(inspectField(pixels, field)))
    .map(({ index }) => index);
}

async function waitForTexture(page, count) {
  const expected = Array.from({ length: count }, (_, index) => index);
  await expect.poll(() => texturedIndices(page), {
    timeout: 90_000,
    intervals: [500, 1000, 1500],
    message: `the expected ${count} overview ROIs never became textured`,
  }).toEqual(expected);
}

async function setAcquisitionVisible(page, acquisition, visible) {
  await page.evaluate(({ name, on }) => {
    const headings = Array.from(document.querySelectorAll(".viewer-panel span"));
    const label = headings.find((element) => element.textContent.trim() === name
      && element.parentElement?.querySelector("button[data-on]"));
    const button = label?.parentElement?.querySelector("button[data-on]");
    if (!button) throw new Error(`the ${name} visibility control is missing`);
    if ((button.dataset.on === "1") !== on) button.click();
  }, { name: acquisition, on: visible });
  await expect.poll(() => page.evaluate(({ prefix, on }) => {
    const rows = (window.__thePicture?.layersForMeasurement?.() ?? [])
      .filter(({ name }) => name.startsWith(prefix));
    return rows.length > 0 && rows.every((row) => Boolean(row.visible) === on);
  }, { prefix: acquisition, on: visible }), {
    message: `${acquisition} visibility did not reach the engine`,
  }).toBe(true);
}

async function liveState(page, port) {
  return page.evaluate(async (bridgePort) => {
    const viewer = await fetch(`http://127.0.0.1:${bridgePort}/api/viewer`)
      .then((answer) => answer.json()).catch((error) => ({ error: error.message }));
    const scan = await fetch(`http://127.0.0.1:${bridgePort}/api/scan`)
      .then((answer) => answer.json()).catch((error) => ({ error: error.message }));
    const acquisitions = viewer.acquisitions ?? [];
    const layers = window.__thePicture?.layersForMeasurement?.() ?? [];
    const placed = window.__thePicture?.whereThingsAreDrawn?.() ?? null;
    const plan = window.__theStageCanvas.plan();
    const [originX, originY] = window.__theStageCanvas.carrierOriginUm();
    const screen = document.querySelector("#stage-canvas").getBoundingClientRect();
    const planFrameBounds = {
      xMin: Math.min(...plan.map(({ x, frameUm }) => x - frameUm / 2)),
      yMin: Math.min(...plan.map(({ y, frameUm }) => y - frameUm / 2)),
      xMax: Math.max(...plan.map(({ x, frameUm }) => x + frameUm / 2)),
      yMax: Math.max(...plan.map(({ y, frameUm }) => y + frameUm / 2)),
    };
    const projections = plan.map((position, index) => {
      const absolute = { x: position.x + originX, y: position.y + originY };
      const stage = window.__theStageCanvas.project(position.x, position.y);
      const engine = placed?.project?.(absolute.x, absolute.y) ?? null;
      const stagePoint = Array.isArray(stage) ? { x: stage[0], y: stage[1] } : stage;
      return {
        index,
        carrierLocalUm: { x: position.x, y: position.y },
        carrierOriginUm: { x: originX, y: originY },
        absoluteStageUm: absolute,
        stageScreenPx: stagePoint,
        engineScreenPx: engine,
        errorPx: stagePoint && engine
          ? Math.hypot(stagePoint.x - engine.x, stagePoint.y - engine.y)
          : null,
      };
    });
    return {
      acquisitions,
      layers,
      scan,
      plan,
      planBounds: {
        carrierLocal: { frame: "carrier-local", unit: "um", ...planFrameBounds },
        absoluteStage: {
          frame: "absolute-stage", unit: "um",
          xMin: planFrameBounds.xMin + originX,
          yMin: planFrameBounds.yMin + originY,
          xMax: planFrameBounds.xMax + originX,
          yMax: planFrameBounds.yMax + originY,
        },
      },
      stage: {
        view: window.__theStageCanvas.view(),
        canvas: {
          left: screen.left, top: screen.top, right: screen.right, bottom: screen.bottom,
          width: screen.width, height: screen.height,
        },
        projections,
      },
      engineView: placed ? {
        centre: placed.centre, zoom: placed.zoom, width: placed.width, height: placed.height,
      } : null,
    };
  }, port);
}

function evidenceState(raw) {
  const overviewLayers = raw.layers.filter(({ name }) => name.startsWith("overview"));
  const overviewSources = overviewLayers.flatMap((layer) => layer.sources ?? []);
  const boundedSources = overviewSources.map((source) => ({
    url: source.url,
    position: positionNumber(source.url),
    boundsUm: physicalBounds(source),
    error: source.error,
  }));
  const firstRowByPosition = new Map();
  for (const source of overviewLayers[0]?.sources ?? []) {
    const position = positionNumber(source.url);
    if (position !== null) firstRowByPosition.set(position, physicalBounds(source));
  }
  const physicalErrors = raw.plan.flatMap((position, index) => {
    const bounds = firstRowByPosition.get(index);
    if (!bounds) return [];
    const expected = raw.stage.projections[index].absoluteStageUm;
    const observed = {
      x: (bounds.xMin + bounds.xMax) / 2,
      y: (bounds.yMin + bounds.yMax) / 2,
    };
    return [{
      index, expectedAbsoluteStageUm: expected, engineCentreUm: observed,
      errorUm: Math.hypot(expected.x - observed.x, expected.y - observed.y),
    }];
  });
  const screenErrors = raw.stage.projections
    .filter(({ engineScreenPx }) => engineScreenPx)
    .map(({ errorPx }) => errorPx);
  const engineVisibility = (prefix) => raw.layers
    .filter(({ name }) => name.startsWith(prefix))
    .map(({ name, visible }) => ({ row: name, visible: Boolean(visible) }));
  const sourceCount = raw.acquisitions.reduce(
    (total, acquisition) => total + sourcesIn(acquisition).length, 0,
  );

  return {
    sourceCount,
    acquisitions: acquisitionSummary(raw.acquisitions),
    logicalChannelRows: raw.layers.map(({ name, visible, sources, error }) => ({
      name, visible: Boolean(visible), sourceCount: sources?.length ?? 0,
      layerError: error ?? null,
    })),
    overviewSources: boundedSources,
    planBoundsUm: raw.planBounds,
    imageAggregateBoundsUm: aggregateBounds(boundedSources.map(({ boundsUm }) => boundsUm)),
    registration: {
      positions: physicalErrors,
      maximumErrorUm: physicalErrors.length
        ? Math.max(...physicalErrors.map(({ errorUm }) => errorUm)) : null,
      maximumErrorPx: screenErrors.length ? Math.max(...screenErrors) : null,
      declaredTolerancePx: SCREEN_TOLERANCE_PX,
      screenProjections: raw.stage.projections,
    },
    visibility: {
      engineObserved: {
        focussing: engineVisibility("focussing"),
        overview: engineVisibility("overview"),
      },
    },
    stage: raw.stage,
    engineView: raw.engineView,
    bridgeErrors: raw.scan.error ? [raw.scan.error] : [],
  };
}

function zarrTrace(bridge, position) {
  const folder = path.join(bridge.currentRun(), "positions", "overview");
  const marker = `P${String(position).padStart(6, "0")}`;
  const store = fs.readdirSync(folder).find((name) => name.includes(marker));
  if (!store) return { position, error: "position store not found" };
  const metadata = JSON.parse(fs.readFileSync(path.join(folder, store, "zarr.json"), "utf8"));
  const array = JSON.parse(fs.readFileSync(path.join(folder, store, "0", "zarr.json"), "utf8"));
  const level0 = metadata.attributes.ome.multiscales[0].datasets
    .find((dataset) => dataset.path === "0");
  const scale = level0.coordinateTransformations.find(({ type }) => type === "scale")?.scale;
  const translation = level0.coordinateTransformations
    .find(({ type }) => type === "translation")?.translation;
  return {
    position, store, axes: ["t", "c", "z", "y", "x"],
    level0: { scale, translation, shape: array.shape },
    zCoordinate: metadata.attributes.zmart_microscopy?.z_coordinate ?? null,
  };
}

function viewRecord(raw) {
  return { stage: raw.stage.view, engine: raw.engineView };
}

async function takeEvidence({
  page, bridge, port, audit, name, captureMethod, landed,
  inspect = false, expectedTextured = null, requestedVisibility,
  viewBefore = null, action = null, extra = {},
}) {
  const boxes = inspect ? await fieldsOnScreen(page) : [];
  const canvasBox = await page.locator("#stage-canvas").boundingBox();
  const png = await page.screenshot();
  const pixels = readPng(png);
  const roiResults = boxes.map((field) => ({ field, result: inspectField(pixels, field) }));
  const examined = roiResults.filter(({ result }) => !result.error);
  const textured = roiResults.filter(({ result }) => isTextured(result));
  const raw = await liveState(page, port);
  const state = evidenceState(raw);
  const requests = audit.snapshot();
  const record = {
    schemaVersion: 1,
    provenance,
    sample: "mock kidney",
    workflowStep: 5,
    captureMethod,
    name,
    timestampUtc: new Date().toISOString(),
    bridge: { origin: `http://127.0.0.1:${port}` },
    counts: {
      planned: raw.plan.length,
      landed,
      examined: examined.length,
      textured: textured.length,
    },
    pixelCheck: {
      canvas: inspectScreenRegion(pixels, canvasBox),
      plannedRois: {
        required: inspect ? 9 : 0,
        examined: examined.length,
        textured: textured.length,
      },
    },
    roiResults,
    ...state,
    visibility: { requested: requestedVisibility, ...state.visibility },
    viewTransition: {
      action,
      before: viewBefore,
      after: viewRecord(raw),
    },
    requests,
    browserErrors: requests.browserErrors,
    workerErrors: requests.workerErrors,
    /* The screenshot's own size and fingerprint, so a record can be matched
       to the picture it describes and a swapped picture is noticed. */
    artifact: {
      png: `${name}.png`,
      width: pixels.width,
      height: pixels.height,
      sha256: crypto.createHash("sha256").update(png).digest("hex"),
    },
    ...extra,
  };
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), png);
  fs.writeFileSync(path.join(SHOTS, `${name}.json`), JSON.stringify(record, null, 2));
  /* Write the paired record even when an assertion below fails. A rejected
     screenshot is diagnostic evidence too, and it must remain inspectable
     rather than disappearing at the first mismatch. */
  if (inspect) {
    expect(boxes, `${name}: exactly nine planned ROIs are projected`).toHaveLength(9);
    expect(examined, `${name}: no ROI is off-screen or unprojectable`).toHaveLength(9);
  }
  if (expectedTextured !== null) {
    expect(textured.map(({ field }) => field.index), `${name}: textured ROI ledger`)
      .toEqual(Array.from({ length: expectedTextured }, (_, index) => index));
  }
  expect(record.pixelCheck.canvas.error, `${name}: the canvas can be sampled`).toBeUndefined();
  expect(record.pixelCheck.canvas.shadeBins, `${name}: the screenshot contains drawn pixels`)
    .toBeGreaterThan(3);
  expect(record.requests.unexpectedFailures, `${name}: no unexpected request failed`).toEqual([]);
  expect(record.browserErrors, `${name}: no browser error occurred`).toEqual([]);
  expect(record.workerErrors, `${name}: no worker error occurred`).toEqual([]);
  expect(record.bridgeErrors, `${name}: the bridge completed without error`).toEqual([]);
  return { png, record, raw, roiResults, textured };
}

function assertCompleteEvidence(record) {
  const overview = acquisitionOf("overview", record.acquisitions);
  expect(record.counts).toMatchObject({ planned: 9, landed: 9, examined: 9, textured: 9 });
  expect(overview.logicalChannelCount, "three overview logical channels").toBe(3);
  expect(overview.channels.map(({ sourceCount }) => sourceCount),
    "nine overview positions remain behind every channel").toEqual([9, 9, 9]);
  expect(record.registration.maximumErrorPx, "screen registration error")
    .toBeLessThan(SCREEN_TOLERANCE_PX);
  expect(record.registration.maximumErrorUm, "physical registration error").toBeLessThan(4);
  expect(record.imageAggregateBoundsUm, "the engine exposes overview bounds").not.toBeNull();
  expect(record.logicalChannelRows.filter(({ name }) => name.startsWith("overview")))
    .toHaveLength(3);
  expect(record.logicalChannelRows.filter(({ layerError }) => layerError)).toEqual([]);
  expect(record.requests.required.metadata.successful,
    "required OME-Zarr metadata was fetched").toBeGreaterThan(0);
  expect(record.requests.required.chunks.successful,
    "required OME-Zarr chunks were fetched").toBeGreaterThan(0);
  expect(record.requests.required.measurement.successful,
    "the real Viewer answered /api/measure").toBeGreaterThan(0);
  expect(record.autoMeasurement.successfulAfterAuto,
    "Auto makes a new real Viewer measurement")
    .toBeGreaterThan(record.autoMeasurement.successfulBeforeAuto);
  expect(record.autoMeasurement.histogramBars,
    "the real measurement draws the panel histogram").toBeGreaterThan(0);
  expect(record.requests.unexpectedFailures, "no unexpected request failed").toEqual([]);
  expect(record.browserErrors, "no browser error occurred").toEqual([]);
  expect(record.workerErrors, "no worker error occurred").toEqual([]);
  expect(record.bridgeErrors, "the bridge completed without error").toEqual([]);
}

async function proveAutoUsesViewerMeasurement(page, audit) {
  const successful = () => audit.snapshot().required.measurement.successful;
  const beforeSelection = successful();
  await showDisplaySettings(page);
  await page.locator('.viewer-panel [data-channel-row="channel 0"]').first().click();
  await expect.poll(successful, {
    message: "selecting overview channel 0 never reached the real Viewer measurement route",
  }).toBeGreaterThan(beforeSelection);
  await expect.poll(() => page.locator(".viewer-panel svg rect").count(), {
    message: "the real Viewer measurement never drew a histogram",
  }).toBeGreaterThan(0);

  const successfulBeforeAuto = successful();
  /* The panel names this button by its accessible label, "auto contrast
     <channel>", so the visible word "Auto" alone never matches it. */
  await page.locator('.viewer-panel button[aria-label^="auto contrast"]').click();
  await expect.poll(successful, {
    message: "Auto never requested a fresh real Viewer measurement",
  }).toBeGreaterThan(successfulBeforeAuto);
  /* Back to the step's channel, where the next press stands. */
  await showTheChannel(page);
  return {
    endpoint: "/api/measure",
    successfulBeforeAuto,
    successfulAfterAuto: successful(),
    histogramBars: await page.locator(".viewer-panel svg rect").count(),
  };
}

async function absolutePlan(page) {
  return page.evaluate(() => {
    const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
    return window.__theStageCanvas.plan().map(({ x, y }) => {
      const z = window.__theStageCanvas.focusZAt(x, y);
      return z === null ? { x: x + ox, y: y + oy } : { x: x + ox, y: y + oy, z };
    });
  });
}

test("deterministic kidney evidence records 0, 3, 6, and 9 landed positions", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const bridge = await startTheBridge({ port: PORT });
  const audit = trackBrowser(page, PORT);
  try {
    await walkToScan(page, PORT);
    const positions = await absolutePlan(page);
    const allVisible = { focussing: true, overview: true };
    const onlyOverview = { focussing: false, overview: true };
    const zeroBefore = viewRecord(await liveState(page, PORT));
    await takeEvidence({
      page, bridge, port: PORT, audit, name: "0-of-9",
      captureMethod: "deterministic live bridge before acquisition",
      landed: 0, requestedVisibility: allVisible, viewBefore: zeroBefore,
      action: "none; Step 5 is ready and Run has not been pressed",
    });

    /* A focusing field overlaps the middle overview ROI. Hide it while the
       partial overview ledger is measured so 3 and 6 mean overview positions,
       not overview positions plus one unrelated focusing image. */
    await setAcquisitionVisible(page, "focussing", false);
    await audit.duringNavigation(async () => {
      await page.evaluate(() => window.__theStageCanvas.fadeTo(0));
      await framePlannedGrid(page);
      await rest(1000);
    });

    let before = viewRecord(await liveState(page, PORT));
    await bridge.image(positions.slice(0, 3));
    await waitForOverview(page, 3);
    await waitForTexture(page, 3);
    const three = await takeEvidence({
      page, bridge, port: PORT, audit, name: "3-of-9",
      captureMethod: "deterministic live bridge; cumulative first row",
      landed: 3, inspect: true, expectedTextured: 3, requestedVisibility: onlyOverview,
      viewBefore: before, action: "published cumulative positions 0 through 2",
    });

    before = viewRecord(three.raw);
    await bridge.image(positions.slice(0, 6));
    await waitForOverview(page, 6);
    await waitForTexture(page, 6);
    const six = await takeEvidence({
      page, bridge, port: PORT, audit, name: "6-of-9",
      captureMethod: "deterministic live bridge; cumulative first two rows",
      landed: 6, inspect: true, expectedTextured: 6, requestedVisibility: onlyOverview,
      viewBefore: before, action: "published cumulative positions 0 through 5",
    });

    before = viewRecord(six.raw);
    await setAcquisitionVisible(page, "focussing", true);
    await bridge.image(positions);
    await waitForOverview(page, 9);
    await waitForTexture(page, 9);
    const autoMeasurement = await proveAutoUsesViewerMeasurement(page, audit);
    const all = await takeEvidence({
      page, bridge, port: PORT, audit, name: "9-of-9-harness",
      captureMethod: "deterministic live bridge; all positions",
      landed: 9, inspect: true, expectedTextured: 9, requestedVisibility: allVisible,
      viewBefore: before, action: "published cumulative positions 0 through 8",
      extra: {
        autoMeasurement,
        positionStores: [zarrTrace(bridge, 0), zarrTrace(bridge, 8)],
      },
    });
    assertCompleteEvidence(all.record);
    expect(all.record.positionStores.map(({ level0 }) => level0.translation[2]),
      "every traced flat overview begins at z zero").toEqual([0, 0]);

    const beforeVisibility = viewRecord(all.raw);
    await setAcquisitionVisible(page, "focussing", false);
    await rest(1500);
    const overviewOnly = await takeEvidence({
      page, bridge, port: PORT, audit, name: "overview-only",
      captureMethod: "deterministic live bridge; panel visibility control",
      landed: 9, inspect: true, expectedTextured: 9,
      requestedVisibility: { focussing: false, overview: true },
      viewBefore: beforeVisibility, action: "clicked the focussing acquisition eye off",
      extra: { autoMeasurement },
    });
    expect(overviewOnly.record.visibility.engineObserved.focussing
      .every(({ visible }) => !visible), "focussing is hidden in the engine").toBe(true);
    expect(overviewOnly.record.visibility.engineObserved.overview
      .every(({ visible }) => visible), "overview remains visible in the engine").toBe(true);
    const canvas = overviewOnly.record.stage.canvas;
    const changed = pixelChangesInside(all.png, overviewOnly.png, canvas);
    expect(changed, "hiding focussing changes acquired pixels on the canvas").toBeGreaterThan(10);

    const beforeFit = viewRecord(overviewOnly.raw);
    await audit.duringNavigation(async () => {
      await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
      await page.locator("#fit-btn").click();
      await rest(1000);
    });
    const wholePlate = await takeEvidence({
      page, bridge, port: PORT, audit, name: "whole-plate",
      captureMethod: "deterministic live bridge; explicit operator Fit",
      landed: 9, requestedVisibility: { focussing: false, overview: true },
      viewBefore: beforeFit, action: "operator clicked Fit after image arrival",
    });
    const projected = wholePlate.record.registration.screenProjections;
    expect(projected.every(({ stageScreenPx }) => stageScreenPx.x >= 0
      && stageScreenPx.y >= 0
      && stageScreenPx.x <= wholePlate.record.stage.canvas.width
      && stageScreenPx.y <= wholePlate.record.stage.canvas.height),
    "the complete overview plan remains in the whole-plate frame").toBe(true);

    const centre = positions[4];
    const [originX, originY] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());
    const closeCentre = { x: centre.x - originX, y: centre.y - originY };
    const beforeClose = viewRecord(wholePlate.raw);
    await audit.duringNavigation(async () => {
      await page.evaluate(() => window.__theStageCanvas.fadeTo(0));
      await frameAround(page, closeCentre, 3);
      await rest(1500);
    });
    const close = await takeEvidence({
      page, bridge, port: PORT, audit, name: "kidney-close-up",
      captureMethod: "deterministic live bridge; operator zoomed to the centre field",
      landed: 9, requestedVisibility: { focussing: false, overview: true },
      viewBefore: beforeClose, action: "operator zoomed and panned to position 4",
    });
    expect(close.record.stage.view.zoom, "close-up reaches microscopy scale").toBeLessThanOrEqual(3);
    expect(close.record.pixelCheck.canvas.shadeBins,
      "close-up contains microscopy texture across the canvas").toBeGreaterThan(16);

    /* The same view must be the same picture after crossing level-of-detail
       boundaries repeatedly. This catches missing coarser chunks, stale
       composites, and redraws that retain a level from the preceding zoom. */
    /* The stage view takes carrier-local centres. The engine view beneath is
       stage-absolute and follows this one; using it here would add the
       carrier origin twice. */
    const closeView = close.raw.stage.view;
    const wideView = wholePlate.raw.stage.view;
    const stableBefore = await page.locator("#stage-canvas").screenshot();
    fs.writeFileSync(path.join(SHOTS, "zoom-return-before.png"), stableBefore);
    for (let cycle = 0; cycle < 3; cycle += 1) {
      await audit.duringNavigation(async () => {
        await page.evaluate((view) => window.__theStageCanvas.lookAt(view), wideView);
        await rest(700);
        await page.evaluate((view) => window.__theStageCanvas.lookAt(view), closeView);
        await rest(1000);
      });
      expect(await page.evaluate(() => window.__thePicture.layersForMeasurement()
        .filter(({ name }) => name.startsWith("overview"))
        .every(({ visible }) => visible)),
      `overview visibility survives zoom cycle ${cycle + 1}`).toBe(true);
    }
    const stableAfter = await page.locator("#stage-canvas").screenshot();
    fs.writeFileSync(path.join(SHOTS, "zoom-return-after.png"), stableAfter);
    const returnedView = await liveState(page, PORT);
    expect(returnedView.stage.view.zoom, "the stage returns to the exact close zoom")
      .toBeCloseTo(closeView.zoom, 9);
    expect(returnedView.stage.view.centre.x, "the stage returns to the exact close x")
      .toBeCloseTo(closeView.centre.x, 6);
    expect(returnedView.stage.view.centre.y, "the stage returns to the exact close y")
      .toBeCloseTo(closeView.centre.y, 6);
    expect(returnedView.engineView.zoom, "the acquired picture follows the close zoom")
      .toBeCloseTo(closeView.zoom, 9);
    const stablePixels = readPng(stableBefore);
    const changedOnReturn = pixelChangesInside(stableBefore, stableAfter, {
      left: 0, top: 0, right: stablePixels.width, bottom: stablePixels.height,
    });
    expect(changedOnReturn / (stablePixels.width * stablePixels.height),
      "returning to the identical close view produces the identical composite")
      .toBeLessThan(0.005);
    assertCompleteEvidence(overviewOnly.record);
  } finally {
    await bridge.stop();
  }
});

test("the actual Step 5 Run button lands and renders all nine kidney fields", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const bridge = await startTheBridge({ port: RUN_PORT });
  const audit = trackBrowser(page, RUN_PORT);
  try {
    await walkToScan(page, RUN_PORT);
    const beforeRun = viewRecord(await liveState(page, RUN_PORT));
    await page.locator(".panel.on button.step-run").click();
    await expect.poll(async () => (await scanStatus(page, RUN_PORT)).done, {
      timeout: 400_000,
      intervals: [100, 250, 500],
      message: "the actual Step 5 scan never reached nine positions",
    }).toBe(9);
    await expect.poll(async () => !(await scanStatus(page, RUN_PORT)).running, {
      timeout: 400_000,
      message: "the actual Step 5 scan never finished",
    }).toBe(true);
    await waitForOverview(page, 9);
    /* Framing the grid is an operator view transition like Fit and the
       close-up: chunk fetches the engine cancels while zooming are recorded
       as navigation cancellations, not as failures. */
    await audit.duringNavigation(async () => {
      await page.evaluate(() => window.__theStageCanvas.fadeTo(0));
      await framePlannedGrid(page);
      await waitForTexture(page, 9);
      await rest(1500);
    });
    const autoMeasurement = await proveAutoUsesViewerMeasurement(page, audit);
    const run = await takeEvidence({
      page, bridge, port: RUN_PORT, audit, name: "9-of-9-run",
      captureMethod: "actual Step 5 Run button end to end",
      landed: 9, inspect: true, expectedTextured: 9,
      requestedVisibility: { focussing: true, overview: true },
      viewBefore: beforeRun, action: "operator clicked the Step 5 Run button",
      extra: {
        autoMeasurement,
        positionStores: [zarrTrace(bridge, 0), zarrTrace(bridge, 8)],
      },
    });
    assertCompleteEvidence(run.record);
  } finally {
    await bridge.stop();
  }
});
