/**
 * Review evidence: the whole operator workflow on the real bridge, the real
 * mock kidney microscope, and the separate Smart Viewer 0.2 server, with the
 * target acquisition of Step 8 proven as a real Viewer source arrival.
 *
 * Nothing here is stood in for. The page under test is the production build
 * served by the bridge itself (the way the microscope PC serves it), unless
 * `LIVE_TARGET_PAGE=dev` asks for the development server instead. Every
 * screenshot is paired with a JSON record naming the branch, the Viewer
 * commit, the run state, the source structure, requested and engine-observed
 * visibility, coordinates in each frame, the Z anchor provenance, the pixel
 * checks made on the picture, and the PNG's own dimensions and hash.
 *
 * What is deliberately asserted about Step 8:
 *
 * - the target acquisition arrives as a Viewer acquisition group of its own,
 *   separate from the overview and the focussing groups, and the record keeps
 *   the group's exact observed name;
 * - every acquired target position is one spatial source behind that group's
 *   channel rows, not a panel row of its own;
 * - later target positions grow those source lists on the same Viewer
 *   instance, without a remount;
 * - the requested visibility chosen before the targets arrived survives the
 *   arrival, and the three groups can be shown and hidden independently;
 * - the whole-plate Fit chosen before acquisition is unchanged afterwards;
 * - every target source's engine bounds contain the very stage point the
 *   refined target was converted to, and both screen projections agree below
 *   one pixel;
 * - every flat target store anchors its only voxel centre at display z=0
 *   while the requested focus height is kept as provenance.
 */

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
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8821);
const PAGE = process.env.LIVE_TARGET_PAGE ?? "built";
const OUT = process.env.LIVE_TARGET_EVIDENCE_DIR
  ?? path.join(HERE, "test-results", "live-target-arrival");
/* How many targets the gate keeps per tileset. Three is enough to prove that
   later arrivals grow the first target source list, and short enough that the
   mock finishes in seconds. */
const MAX_TARGETS = Number(process.env.LIVE_TARGET_MAX ?? 3);
const PYTHON = process.env.PYTHON ?? "python";
const A_WHOLE_RUN = 2_400_000;
const SCREEN_TOLERANCE_PX = 1;
/* Below one micrometre: a half-voxel (2 um) placement difference between
   tiles of one acquisition must fail this, not pass inside a loose tolerance. */
const PHYSICAL_TOLERANCE_UM = 1;

const command = (program, args, cwd = REPO) =>
  execFileSync(program, args, { cwd, encoding: "utf8" }).trim();

function provenanceOfTheRun() {
  const viewer = JSON.parse(command(PYTHON, ["-c", [
    "import json",
    "from importlib.metadata import version",
    "from pathlib import Path",
    "import zmart_viewer",
    "print(json.dumps({'importPath': str(Path(zmart_viewer.__file__).resolve()), "
      + "'version': version('zmart-viewer')}))",
  ].join("; ")]));
  const checkout = path.dirname(path.dirname(viewer.importPath));
  viewer.commit = command("git", ["rev-parse", "HEAD"], checkout);
  viewer.measureRoutePresent = fs.readFileSync(
    path.join(path.dirname(viewer.importPath), "server.py"), "utf8",
  ).includes("/api/measure");
  return {
    microscopy: {
      repository: "thomdehoog/ZMART-microscopy",
      branch: command("git", ["branch", "--show-current"]),
      commit: command("git", ["rev-parse", "HEAD"]),
      worktreeClean: command("git", ["status", "--porcelain", "--", "application", "zmart_storage", "zmart_live"]) === "",
    },
    smartViewer: { repository: "thomdehoog/ZMART-viewer", ...viewer },
    backend: "real bridge (application/framework/bridge.py) driving the controller's mock kidney driver",
    page: PAGE === "built"
      ? "production build served by the bridge (framework/window/static)"
      : "vite development server",
    python: command(PYTHON, ["-c", "import sys; print(sys.version.split()[0])"]),
  };
}

const sha256 = (buffer) => crypto.createHash("sha256").update(buffer).digest("hex");

const point = (value) => (Array.isArray(value)
  ? { x: value[0], y: value[1] }
  : { x: value?.x, y: value?.y });

function unitToUm(unit) {
  if (unit === "m") return 1e6;
  if (unit === "mm") return 1e3;
  if (unit === "nm") return 1e-3;
  return 1;
}

/** One engine source's physical bounds in absolute-stage micrometres. */
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
    zMin: along("z", "lower"), zMax: along("z", "upper"),
  };
  return [values.xMin, values.yMin, values.xMax, values.yMax].every(Number.isFinite)
    ? values : null;
}

/* ---------------------------------------------------------------- browser audit */

function expectedProbe(url, port) {
  try {
    const parsed = new URL(url);
    if (/\/(?:\.zattrs|\.zgroup)$/.test(parsed.pathname)) return "format-probe";
    if (parsed.port !== String(port)) return null;
    if (parsed.pathname === "/view/overview/tiles.json") return "optional-probe";
    if (/^\/view\/[^/]+\/.+\.(?:mask|labels)\.png$/.test(parsed.pathname)) return "optional-probe";
    if (/^\/view\/target\/.+\.jpg$/.test(parsed.pathname)) return "optional-probe";
    return null;
  } catch {
    return null;
  }
}

function requestKind(url, port) {
  try {
    const parsed = new URL(url);
    if (parsed.hostname !== "127.0.0.1") return null;
    const probe = expectedProbe(url, port);
    if (probe) return probe;
    if (parsed.pathname === "/api/measure") return "measurement";
    if (/\/data\/\d+\/.+\/zarr\.json$/.test(parsed.pathname)) return "metadata";
    if (/\/data\/\d+\/.+\.ome\.zarr\/\d+\/c\//.test(parsed.pathname)) return "chunk";
    if (parsed.port !== String(port)) return null;
    if (parsed.pathname.startsWith("/api/")) return "api";
    if (parsed.pathname.startsWith("/view/")) return "picture";
    return "page";
  } catch {
    return null;
  }
}

function trackBrowser(page, port) {
  const pageErrors = [];
  const consoleErrors = [];
  const failures = [];
  const responses = [];
  const cancelled = new Set();
  /* Stores a shorter rerun has removed on purpose. The engine may still ask
     for their pixels in the moment between the removal and the page reading
     the shrunken source list; those misses are what removing a store means,
     and they are recorded apart from real failures once the test has named
     the store as retired. */
  const retired = new Set();
  const isRetired = (url) => [...retired].some((name) => url.includes(`/${name}/`));
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const location = message.location()?.url ?? "";
    if (expectedProbe(location, port)) return;
    if (/Failed to load resource/.test(message.text()) && expectedProbe(location, port)) return;
    consoleErrors.push({ text: message.text(), location });
  });
  page.on("requestfailed", (request) => {
    const kind = requestKind(request.url(), port);
    if (!kind) return;
    failures.push({ kind, url: request.url(), error: request.failure()?.errorText ?? "failed" });
  });
  page.on("response", (response) => {
    const kind = requestKind(response.url(), port);
    if (!kind) return;
    responses.push({ kind, url: response.url(), status: response.status() });
  });
  return {
    /** Name a store the rerun removed, so misses on it are expected from now on. */
    retire(storeName) { retired.add(storeName); },
    async duringNavigation(action) {
      const first = failures.length;
      await action();
      for (let at = first; at < failures.length; at += 1) {
        if (failures[at].kind === "chunk" && failures[at].error === "net::ERR_ABORTED") {
          cancelled.add(at);
        }
      }
    },
    snapshot() {
      const ok = (kind) => responses.filter(
        (one) => one.kind === kind && one.status >= 200 && one.status < 400).length;
      const expected = (kind) => [
        ...failures.filter((one) => one.kind === kind),
        ...responses.filter((one) => one.kind === kind && one.status >= 400),
      ];
      /* Neuroglancer cancels chunk fetches it no longer needs whenever the view
         moves or a source arrives; the browser reports those as ERR_ABORTED.
         They are recorded, counted, and kept apart from real failures. */
      const chunkCancellations = failures.filter((one, at) => !cancelled.has(at)
        && one.kind === "chunk" && one.error === "net::ERR_ABORTED");
      const retiredStoreMisses = [
        ...failures.filter((one) => isRetired(one.url)),
        ...responses.filter((one) => one.status === 404 && isRetired(one.url)),
      ];
      const unexpectedFailures = [
        ...failures.filter((one, at) => !cancelled.has(at)
          && !chunkCancellations.includes(one)
          && !isRetired(one.url)
          && !["format-probe", "optional-probe"].includes(one.kind)),
        ...responses.filter((one) =>
          !["format-probe", "optional-probe"].includes(one.kind) && one.status >= 400
          && !(one.status === 404 && isRetired(one.url))),
      ];
      const browserErrors = [
        ...pageErrors,
        ...consoleErrors.map(({ text, location }) => `${text}${location ? ` (${location})` : ""}`),
      ];
      return {
        required: {
          metadata: ok("metadata"), chunks: ok("chunk"),
          measurement: ok("measurement"), api: ok("api"), pictures: ok("picture"),
        },
        expectedFormatProbes: expected("format-probe"),
        expectedOptionalProbes: expected("optional-probe"),
        expectedNavigationCancellations: failures.filter((_, at) => cancelled.has(at)),
        expectedChunkCancellations: { count: chunkCancellations.length, sample: chunkCancellations.slice(0, 3) },
        expectedRetiredStoreMisses: { stores: [...retired], count: retiredStoreMisses.length, sample: retiredStoreMisses.slice(0, 3) },
        unexpectedFailures,
        browserErrors,
        workerErrors: browserErrors.filter((error) => /worker|chunk/i.test(error)),
      };
    },
  };
}

/* ------------------------------------------------------------- page questions */

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

async function recordSlot(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(700);
}

async function bridgeJson(page, port, route) {
  return page.evaluate(async ({ bridgePort, path: route_ }) =>
    fetch(`http://127.0.0.1:${bridgePort}${route_}`).then((answer) => answer.json())
      .catch((error) => ({ error: error.message })), { bridgePort: port, path: route });
}

async function engineRows(page) {
  return page.evaluate(() => window.__thePicture?.layersForMeasurement?.() ?? []);
}

function groupOf(row) {
  return String(row.name ?? "").split("/")[0];
}

async function rowsOfGroup(page, prefix) {
  return (await engineRows(page)).filter((row) => row.name.startsWith(prefix));
}

async function sourceCountOf(page, prefix) {
  return (await rowsOfGroup(page, prefix))
    .reduce((count, row) => count + (row.sources?.length ?? 0), 0);
}

/** The panel's requested state and the engine's observed state, side by side. */
async function panelState(page) {
  return page.evaluate(() => window.__viewerPanel?.snapshot?.() ?? null);
}

async function setGroupVisible(page, group, visible) {
  await showDisplaySettings(page);
  const eye = page.locator(`.viewer-panel button[data-acquisition="${group}"]`);
  await expect(eye, `the ${group} acquisition eye exists`).toHaveCount(1);
  if ((await eye.getAttribute("data-on")) === (visible ? "1" : "0")) return;
  await eye.click();
  await expect(eye).toHaveAttribute("data-on", visible ? "1" : "0");
  await expect.poll(async () => {
    const rows = await rowsOfGroup(page, group);
    return rows.length > 0 && rows.every((row) => Boolean(row.visible) === visible);
  }, { message: `${group} visibility did not reach the engine` }).toBe(true);
}

async function pictureTag(page) {
  return page.evaluate(() => {
    const picture = window.__thePicture;
    if (!picture) return null;
    picture.__reviewTag ??= `picture-${Math.random().toString(36).slice(2)}`;
    return picture.__reviewTag;
  });
}

async function stageView(page) {
  return page.evaluate(() => {
    const box = document.querySelector("#stage-canvas").getBoundingClientRect();
    const plan = window.__theStageCanvas.plan();
    const points = plan.map((at, index) => {
      const projected = window.__theStageCanvas.project(at.x, at.y);
      const p = Array.isArray(projected) ? { x: projected[0], y: projected[1] } : projected;
      return { index, screenPx: { x: box.left + p.x, y: box.top + p.y } };
    });
    return {
      view: window.__theStageCanvas.view(),
      canvas: { left: box.left, top: box.top, width: box.width, height: box.height },
      points,
    };
  });
}

/** Frame the planned grid at 12 um per screen pixel, the way the Step 5 evidence does. */
async function framePlan(page, plan) {
  const centre = {
    x: (Math.min(...plan.map(({ x }) => x)) + Math.max(...plan.map(({ x }) => x))) / 2,
    y: (Math.min(...plan.map(({ y }) => y)) + Math.max(...plan.map(({ y }) => y))) / 2,
  };
  await page.evaluate((at) => window.__theCanvas.lookAt({ zoom: 12, centre: at }), centre);
  await rest(1500);
}

function viewDrift(before, after) {
  return Math.max(...before.points.map((one, index) => Math.hypot(
    one.screenPx.x - after.points[index].screenPx.x,
    one.screenPx.y - after.points[index].screenPx.y,
  )));
}

/* ------------------------------------------------------------- pixel checks */

/** A planned or target box in viewport pixels, from carrier-local micrometres. */
async function boxesOnScreen(page, centres, sideUm) {
  return page.evaluate(({ centres: list, side }) => {
    const canvas = document.querySelector("#stage-canvas").getBoundingClientRect();
    const pt = (value) => (Array.isArray(value) ? { x: value[0], y: value[1] } : value);
    return list.map((at) => {
      const middle = pt(window.__theStageCanvas.project(at.x, at.y));
      const edge = pt(window.__theStageCanvas.project(at.x + side / 2, at.y + side / 2));
      const across = Math.abs(edge.x - middle.x);
      const down = Math.abs(edge.y - middle.y);
      return {
        id: at.id ?? null,
        left: canvas.left + middle.x - across, right: canvas.left + middle.x + across,
        top: canvas.top + middle.y - down, bottom: canvas.top + middle.y + down,
        centre: { x: canvas.left + middle.x, y: canvas.top + middle.y },
      };
    });
  }, { centres, side: sideUm });
}

function inspectBox(pixels, box, { inset = 0.25 } = {}) {
  const edges = [box.left, box.right, box.top, box.bottom];
  if (!edges.every(Number.isFinite)) return { error: "unprojectable" };
  if (box.left < 0 || box.top < 0 || box.right > pixels.width || box.bottom > pixels.height) {
    return { error: "off-screen" };
  }
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
      if (corner.some((value, channel) => Math.abs(data[at + channel] - value) > 10)) drawn += 1;
      shades.add(data[at] >> 2);
    }
  }
  return { covered: drawn / examined, shades: shades.size, examined };
}

const textured = (result) => !result.error && result.covered >= 0.9 && result.shades >= 8;
const blank = (result) => !result.error && result.covered <= 0.05;

/** How many pixels near a point are close to the acquired-target green. */
function greenNear(pixels, centre, radius = 16) {
  const { data, width, height, channels } = pixels;
  let green = 0;
  for (let y = Math.max(0, Math.round(centre.y - radius)); y <= Math.min(height - 1, Math.round(centre.y + radius)); y += 1) {
    for (let x = Math.max(0, Math.round(centre.x - radius)); x <= Math.min(width - 1, Math.round(centre.x + radius)); x += 1) {
      const at = (y * width + x) * channels;
      const [r, g, b] = [data[at], data[at + 1], data[at + 2]];
      if (g > 120 && r < 90 && b < 130 && g - r > 60) green += 1;
    }
  }
  return green;
}

function shadeBins(pixels, box) {
  const left = Math.max(0, Math.floor(box.x));
  const top = Math.max(0, Math.floor(box.y));
  const right = Math.min(pixels.width, Math.ceil(box.x + box.width));
  const bottom = Math.min(pixels.height, Math.ceil(box.y + box.height));
  const { data, width, channels } = pixels;
  const bins = new Set();
  for (let y = top; y < bottom; y += 2) {
    for (let x = left; x < right; x += 2) {
      const at = (y * width + x) * channels;
      bins.add(`${data[at] >> 4}:${data[at + 1] >> 4}:${data[at + 2] >> 4}`);
    }
  }
  return bins.size;
}

function pixelChangesInside(first, second, box) {
  const a = readPng(first);
  const b = readPng(second);
  let changed = 0;
  for (let y = Math.max(0, Math.floor(box.y)); y < Math.min(a.height, Math.ceil(box.y + box.height)); y += 1) {
    for (let x = Math.max(0, Math.floor(box.x)); x < Math.min(a.width, Math.ceil(box.x + box.width)); x += 1) {
      const at = (y * a.width + x) * a.channels;
      if ([0, 1, 2].some((c) => Math.abs(a.data[at + c] - b.data[at + c]) > 10)) changed += 1;
    }
  }
  return changed;
}

/* --------------------------------------------------------------- Z and stores */

function storeTrace(folder, marker) {
  if (!fs.existsSync(folder)) return { error: `${folder} does not exist` };
  const store = fs.readdirSync(folder).find((name) => name.includes(marker));
  if (!store) return { marker, error: "position store not found" };
  const description = JSON.parse(fs.readFileSync(path.join(folder, store, "zarr.json"), "utf8"));
  const level0 = description.attributes.ome.multiscales[0].datasets.find((one) => one.path === "0");
  const scale = level0.coordinateTransformations.find(({ type }) => type === "scale")?.scale;
  const translation = level0.coordinateTransformations.find(({ type }) => type === "translation")?.translation;
  const array = JSON.parse(fs.readFileSync(path.join(folder, store, "0", "zarr.json"), "utf8"));
  return {
    store, axes: ["t", "c", "z", "y", "x"],
    level0: { scale, translation, shape: array.shape },
    zCoordinate: description.attributes.zmart_microscopy?.z_coordinate ?? null,
    derivedCentreUm: translation && scale && array.shape ? {
      x: translation[4] + (array.shape[4] * scale[4]) / 2,
      y: translation[3] + (array.shape[3] * scale[3]) / 2,
    } : null,
  };
}

/* ------------------------------------------------------------------ evidence */

function makeRecorder({ page, port, bridge, audit, provenance }) {
  fs.mkdirSync(OUT, { recursive: true });
  const manifest = [];
  return {
    manifest,
    async take(name, { step, state, expect: checks = null, extra = {} } = {}) {
      await page.mouse.move(4, 4);
      await page.waitForTimeout(150);
      const png = await page.screenshot();
      const pixels = readPng(png);
      const canvasBox = await page.locator("#stage-canvas").boundingBox();
      const raw = await page.evaluate(async (bridgePort) => {
        const json = (route) => fetch(`http://127.0.0.1:${bridgePort}${route}`)
          .then((answer) => answer.json()).catch((error) => ({ error: error.message }));
        const viewer = await json("/api/viewer");
        const scan = await json("/api/scan");
        const layers = window.__thePicture?.layersForMeasurement?.() ?? [];
        const placed = window.__thePicture?.whereThingsAreDrawn?.() ?? null;
        const plan = window.__theStageCanvas.plan();
        const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
        const targets = window.__theStageCanvas.targets();
        const screen = document.querySelector("#stage-canvas").getBoundingClientRect();
        const pt = (value) => (Array.isArray(value) ? { x: value[0], y: value[1] } : value);
        const project = (x, y) => {
          const stage = pt(window.__theStageCanvas.project(x, y));
          const engine = placed?.project?.(x + ox, y + oy) ?? null;
          return {
            stageScreenPx: stage,
            engineScreenPx: engine,
            errorPx: engine ? Math.hypot(stage.x - engine.x, stage.y - engine.y) : null,
          };
        };
        return {
          viewer, scan, layers, plan, targets,
          carrierOriginUm: { x: ox, y: oy },
          run: window.__theRunState?.() ?? null,
          panel: window.__viewerPanel?.snapshot?.() ?? null,
          pictureTag: window.__thePicture?.__reviewTag ?? null,
          stage: {
            view: window.__theStageCanvas.view(),
            canvas: { left: screen.left, top: screen.top, width: screen.width, height: screen.height },
          },
          engineView: placed ? { centre: placed.centre, zoom: placed.zoom, width: placed.width, height: placed.height } : null,
          planProjections: plan.map((at, index) => ({
            index, carrierLocalUm: { x: at.x, y: at.y }, absoluteStageUm: { x: at.x + ox, y: at.y + oy },
            frameUm: at.frameUm, ...project(at.x, at.y),
          })),
          targetProjections: targets.map((at) => ({
            id: at.id, field: at.field, selected: at.selected, acquired: at.acquired,
            carrierLocalUm: { x: at.x, y: at.y }, absoluteStageUm: { x: at.x + ox, y: at.y + oy },
            ...project(at.x, at.y),
          })),
        };
      }, port);
      const rows = raw.layers.map((row) => ({
        name: row.name, group: groupOf(row), visible: Boolean(row.visible),
        window: row.window, weight: row.weight, layerError: row.error ?? null,
        sourceCount: row.sources?.length ?? 0,
        sources: (row.sources ?? []).map((source) => ({
          url: source.url, error: source.error,
          boundsUm: physicalBounds(source),
          matrixSha256: source.matrix ? sha256(JSON.stringify(source.matrix)) : null,
          matrix: source.matrix,
          voxelCenterAtIntegerCoordinates: source.voxelCenterAtIntegerCoordinates ?? null,
        })),
      }));
      const groups = [...new Set(rows.map((row) => row.group))];
      const acquisitions = (raw.viewer.acquisitions ?? []).map((acquisition) => ({
        name: acquisition.name,
        logicalChannelCount: acquisition.channels?.length ?? 0,
        sourceCountPerChannel: (acquisition.channels ?? []).map((channel) => channel.sources?.length ?? 0),
      }));
      const requestedVisibility = raw.panel ? Object.fromEntries(
        Object.entries(raw.panel.acquisitions).map(([name, one]) => [name, one.visible]),
      ) : null;
      const requestedChannels = raw.panel?.channels?.map((channel) => ({
        key: channel.key, acquisition: channel.acquisition, name: channel.name,
        requestedVisible: channel.requested.visible,
        effectiveVisible: channel.requested.effectiveVisible,
        observedVisible: channel.observed?.visible ?? null,
        window: channel.requested.window, observedWindow: channel.observed?.window ?? null,
        opacity: channel.requested.opacity, log: channel.requested.log,
      })) ?? null;
      const engineVisibility = Object.fromEntries(groups.map((group) => [group,
        rows.filter((row) => row.group === group).map((row) => ({ row: row.name, visible: row.visible }))]));
      const planErrors = raw.planProjections.map((one) => one.errorPx).filter(Number.isFinite);
      const targetErrors = raw.targetProjections.map((one) => one.errorPx).filter(Number.isFinite);
      const requests = audit.snapshot();
      const record = {
        schemaVersion: 1,
        name,
        capturedAtUtc: new Date().toISOString(),
        provenance,
        sample: "mock kidney (scikit-image kidney, plane 8)",
        server: { bridge: `http://127.0.0.1:${port}`, viewer: raw.viewer.url ?? null, run: bridge.currentRun() },
        workflow: { step, state, run: raw.run },
        counts: {
          planned: raw.plan.length,
          scan: { acquisitionType: raw.scan.acquisition_type, done: raw.scan.done, of: raw.scan.of, running: raw.scan.running, error: raw.scan.error },
          targetsOnCanvas: raw.targets.length,
          targetsSelected: raw.targets.filter((one) => one.selected).length,
          targetsAcquired: raw.targets.filter((one) => one.acquired).length,
          engineSourcesPerGroup: Object.fromEntries(groups.map((group) => [group,
            rows.filter((row) => row.group === group).map((row) => row.sourceCount)])),
        },
        viewerAcquisitions: acquisitions,
        engineRows: rows.map(({ matrix, ...row }) => ({ ...row, sources: row.sources.map(({ matrix: _m, ...source }) => source) })),
        visibility: { requested: requestedVisibility, requestedChannels, engineObserved: engineVisibility },
        selected: raw.panel?.selectedKey ?? null,
        engineMismatch: raw.panel?.lastMismatch ?? null,
        measurement: raw.panel?.measurement ?? null,
        coordinates: {
          carrierOriginUm: raw.carrierOriginUm,
          plan: raw.planProjections,
          /* Every candidate's projection is checked (projectionError.targetsMaxPx);
             listed are the ones the run acts on. Real discovery finds
             thousands, and 4010 projections made each record 2.4 MB of
             numbers nobody reads. */
          targets: raw.targetProjections.filter((one) => one.selected || one.acquired),
          targetsOnCanvas: raw.targetProjections.length,
          stageView: raw.stage.view,
          engineView: raw.engineView,
          canvas: raw.stage.canvas,
        },
        projectionError: {
          planMaxPx: planErrors.length ? Math.max(...planErrors) : null,
          targetsMaxPx: targetErrors.length ? Math.max(...targetErrors) : null,
          tolerancePx: SCREEN_TOLERANCE_PX,
        },
        pictureTag: raw.pictureTag,
        pixelCheck: {
          canvasShadeBins: canvasBox ? shadeBins(pixels, canvasBox) : null,
          ...extra.pixelCheck,
        },
        requests,
        browserErrors: requests.browserErrors,
        workerErrors: requests.workerErrors,
        bridgeErrors: raw.scan.error ? [raw.scan.error] : [],
        viewerError: raw.viewer.error ?? null,
        artifact: { file: `${name}.png`, width: pixels.width, height: pixels.height, sha256: sha256(png) },
        ...extra,
      };
      fs.writeFileSync(path.join(OUT, `${name}.png`), png);
      fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(record, null, 2));
      manifest.push({ name, step, state, file: record.artifact });
      expect(record.requests.unexpectedFailures, `${name}: no unexpected request failed`).toEqual([]);
      expect(record.browserErrors, `${name}: no browser error occurred`).toEqual([]);
      expect(record.bridgeErrors, `${name}: the bridge reported no scan error`).toEqual([]);
      expect(record.viewerError, `${name}: the viewer service reported no error`).toBeNull();
      if (checks) await checks({ record, pixels, png, raw });
      return { record, pixels, png, raw };
    },
    writeManifest(extra) {
      fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({
        schemaVersion: 1, capturedAtUtc: new Date().toISOString(), provenance, records: manifest, ...extra,
      }, null, 2));
    },
  };
}

/* -------------------------------------------------------------------- the walk */

const identityOf = (targets) => targets.map(({ id, field, x, y }) => ({ id, field, x, y }));

/* A place on the gate plot, as fractions of its frame: the frame keeps a
   column at the right for the y labels and two lines below for the x axis,
   so a fraction of the whole canvas landed in the margins. The frame's
   inset is the plot's own `PAD`. */
const PLOT_PAD = { l: 1, r: 62, t: 1, b: 38 };
const plotPoint = (sc, gx, gy) => [
  sc.x + PLOT_PAD.l + (sc.width - PLOT_PAD.l - PLOT_PAD.r) * gx,
  sc.y + PLOT_PAD.t + (sc.height - PLOT_PAD.t - PLOT_PAD.b) * gy,
];

/** Steps 1 to 5 on the real bridge, with a record of each. */
async function throughStepFive({ page, take, port, bridge }) {
  await page.goto(PAGE === "built"
    ? `http://127.0.0.1:${port}/`
    : `/?bridge=${encodeURIComponent(`http://127.0.0.1:${port}`)}`);
  const instruments = await bridgeJson(page, port, "/api/instruments");
  const scopeOptions = await page.locator(".session-form select").first().locator("option").allTextContents();
  expect(scopeOptions.some((text) => /mock/i.test(text)), "the microscope list comes from the backend").toBe(true);
  expect(instruments.instruments.some((one) => one.vendor === "mock"), "the backend lists the mock").toBe(true);
  /* The page ships no password and demands none (the operator's decision,
     third pass): the field starts empty, Connect is ready with it empty, and
     the session is opened that way -- the mock wants no password, and an
     instrument that does says so when the session is opened. */
  const passwordPrefilled = await page.locator('.field input[type="password"]').inputValue();
  expect(passwordPrefilled, "the page ships no password").toBe("");
  await expect(page.locator(".session-foot button.run"), "Connect is ready without a password").toBeEnabled();
  await expect(page.locator(".session-foot"), "nothing on the page says a password is needed").not.toContainText("password");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".check-row")).not.toHaveCount(0);
  await expect(page.locator(".check-row.pending")).toHaveCount(0);
  await expect(page.locator(".check-row.failed")).toHaveCount(0);
  const info = await bridgeJson(page, port, "/api/info");
  const stageNow = await bridgeJson(page, port, "/api/xyz");
  const checks = await page.locator(".check-row").evaluateAll((rows) => rows.map((row) => ({
    name: row.querySelector(".check-name")?.textContent,
    value: row.querySelector(".check-value")?.textContent,
  })));
  const travel = await page.evaluate(() => window.__theStageCanvas.view());
  await take("step1-connected", {
    step: 1, state: "connected; every driver check answered",
    extra: { connection: { checks, driverCanvas: info.canvas ?? null, stagePosition: stageNow, instrumentsListed: instruments.instruments.length, openingView: travel, passwordPrefilledByThePage: passwordPrefilled !== "" } },
  });

  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);
  const carrier = await page.evaluate(() => ({
    origin: window.__theStageCanvas.carrierOriginUm(),
    view: window.__theStageCanvas.view(),
    layers: window.__theStageCanvas.layers(),
  }));
  expect(carrier.layers.find((one) => one.key === "carrier")?.shown, "the carrier is drawn").toBe(true);
  await take("step2-carrier", {
    step: 2, state: "75 x 25 mm slide chosen; carrier centred in the driver's travel",
    extra: { carrier: { ...carrier, driverCanvas: info.canvas ?? null } },
  });

  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);
  const plan = await page.evaluate(() => window.__theStageCanvas.plan());
  expect(plan.length, "a 3 x 3 plan on the slide").toBe(9);
  const setting = await bridgeJson(page, port, "/api/setting?type=acquisition");
  expect(plan.every((at) => at.frameUm === setting.frameUm), "every field takes the driver's frame").toBe(true);
  await take("step3-plan", {
    step: 3, state: "optical configuration recorded from the microscope; 3 x 3 grid applied",
    expect: async ({ record }) => {
      expect(record.coordinates.plan.every(({ stageScreenPx }) =>
        stageScreenPx.x >= 0 && stageScreenPx.y >= 0
        && stageScreenPx.x <= record.coordinates.canvas.width
        && stageScreenPx.y <= record.coordinates.canvas.height), "every planned position is on screen").toBe(true);
    },
    extra: { optics: { frameUm: setting.frameUm, summary: setting.summary } },
  });

  await gotoStep(page, "Focus strategy");
  await recordSlot(page, "focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
  const focus = await bridgeJson(page, port, "/api/focus/measure");
  const focusZ = await page.evaluate(() => window.__theStageCanvas.plan().map(({ x, y }) => ({ x, y, z: window.__theStageCanvas.focusZAt(x, y) })));
  expect(focus.points.length, "a focus point was measured through the bridge").toBeGreaterThan(0);
  expect(focus.points.every((one) => Number.isFinite(one.z)), "every measured point has a height").toBe(true);
  await take("step4-focus-map", {
    step: 4, state: "focus map measured on the mock through the analysis; traces shown",
    extra: { focus: { points: focus.points.map(({ traces: _t, slices: _s, ...one }) => one), predictedZAtPlan: focusZ, runState: await page.evaluate(() => window.__theRunState().focus) } },
  });

  await gotoStep(page, "Scan the overview");
  await expect.poll(() => rowsOfGroup(page, "focussing").then((rows) => rows.length), { timeout: 60_000 }).toBe(1);
  await rest(1500);
  await setGroupVisible(page, "focussing", false);
  /* The eye was pressed on the display settings; the step's own press
     stands in its channel, a tab back. */
  await showTheChannel(page);
  await page.locator(".panel.on button.step-run").click();
  await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).done, { timeout: 400_000 }).toBe(9);
  await expect.poll(async () => !(await bridgeJson(page, port, "/api/scan")).running, { timeout: 400_000 }).toBe(true);
  await expect.poll(async () => {
    const rows = await rowsOfGroup(page, "overview");
    return { rows: rows.length, sources: rows.map((row) => row.sources?.length ?? 0) };
  }, { timeout: 90_000 }).toEqual({ rows: 3, sources: [9, 9, 9] });
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
  await framePlan(page, plan);
  const planBoxes = await boxesOnScreen(page, plan, plan[0].frameUm);
  await take("step5-overview-complete", {
    step: 5, state: "actual Run button; 9 of 9 overview positions landed; focussing hidden by the panel; planned grid framed at 12 um per pixel",
    expect: async ({ record, pixels }) => {
      const results = planBoxes.map((box) => inspectBox(pixels, box));
      expect(results.filter((one) => !one.error), "nine planned ROIs examined").toHaveLength(9);
      expect(results.filter(textured).length, "nine textured overview ROIs").toBe(9);
      expect(record.projectionError.planMaxPx).toBeLessThan(SCREEN_TOLERANCE_PX);
      expect(record.visibility.engineObserved.focussing.every((one) => !one.visible)).toBe(true);
      expect(record.visibility.engineObserved.overview.every((one) => one.visible)).toBe(true);
      record.pixelCheck.plannedRois = results;
      fs.writeFileSync(path.join(OUT, `${record.name}.json`), JSON.stringify(record, null, 2));
    },
  });
  return { plan, planBoxes, info, setting, focusZ, bridge };
}

/**
 * Watch a target scan arrive in the Viewer and the engine, then prove the
 * source model. `trigger` starts the scan: the Step 8 button, or a direct
 * publication through the bridge when the operator path cannot be walked.
 */
async function proveTargetArrival({
  page, take, port, bridge, plan, planBoxes, expectedTargets, trigger, mode, outcome,
}) {
  await page.locator("#fit-btn").click();
  await rest(800);
  const fitBefore = await stageView(page);
  const pictureBefore = await pictureTag(page);
  const panelBefore = await panelState(page);
  expect(panelBefore.acquisitions.focussing.visible, "focussing was hidden before acquisition").toBe(false);
  expect(panelBefore.acquisitions.overview.visible).toBe(true);
  const groupsBefore = [...new Set((await engineRows(page)).map(groupOf))];
  const [ox, oy] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());

  await trigger();
  const arrivals = [];
  let arriving = null;
  const started = Date.now();
  while (Date.now() - started < 300_000) {
    const scan = await bridgeJson(page, port, "/api/scan");
    const viewer = await bridgeJson(page, port, "/api/viewer");
    const rows = await engineRows(page);
    const tag = await pictureTag(page);
    const targetGroups = (viewer.acquisitions ?? []).filter((one) => !["overview", "focussing"].includes(one.name));
    const engineTargetRows = rows.filter((row) => !["overview", "focussing"].includes(groupOf(row)));
    const sources = engineTargetRows.map((row) => row.sources?.length ?? 0);
    const last = arrivals.at(-1);
    const seen = {
      at: Date.now() - started, scanDone: scan.done, scanRunning: scan.running,
      viewerGroups: targetGroups.map((one) => one.name),
      viewerSourcesPerChannel: targetGroups.map((one) => (one.channels ?? []).map((channel) => channel.sources?.length ?? 0)),
      engineRows: engineTargetRows.length, sourcesPerRow: sources, pictureTag: tag,
    };
    if (!last || JSON.stringify({ ...last, at: 0 }) !== JSON.stringify({ ...seen, at: 0 })) arrivals.push(seen);
    if (!arriving && engineTargetRows.length && sources.some((count) => count > 0)) {
      outcome.observedTargetGroupName = targetGroups[0]?.name ?? groupOf(engineTargetRows[0]);
      arriving = await take("step8-target-source-arriving", {
        step: 8, state: `${mode}: first target source observed in the engine (scan ${scan.done}/${scan.of}); Viewer group "${outcome.observedTargetGroupName}"`,
        extra: { arrival: seen },
      });
    }
    if (!scan.running && scan.acquisition_type !== "overview" && sources.length && sources.every((count) => count === expectedTargets)) break;
    await rest(40);
  }
  const finalScan = await bridgeJson(page, port, "/api/scan");
  expect(finalScan.acquisition_type, "the bridge ran the target scan").not.toBe("overview");
  expect(finalScan.error).toBeNull();
  expect(finalScan.done, "every target position was captured").toBe(expectedTargets);
  expect(arriving, "the first target source was observed arriving").not.toBeNull();
  const rowsAfter = await engineRows(page);
  const targetRows = rowsAfter.filter((row) => !["overview", "focussing"].includes(groupOf(row)));
  const targetGroupNames = [...new Set(targetRows.map(groupOf))];
  expect(targetGroupNames, "one separate target acquisition group").toHaveLength(1);
  outcome.observedTargetGroupName = targetGroupNames[0];
  expect(targetRows.map((row) => row.sources.length), "every acquired position is a source behind each target channel row")
    .toEqual(targetRows.map(() => expectedTargets));
  expect(targetRows.length, "targets are channel rows, not one row per field").toBeLessThanOrEqual(3);
  const viewerAfter = await bridgeJson(page, port, "/api/viewer");
  expect(viewerAfter.acquisitions.map((one) => one.name).sort()).toEqual(["focussing", "overview", outcome.observedTargetGroupName].sort());
  const targetAcquisition = viewerAfter.acquisitions.find((one) => one.name === outcome.observedTargetGroupName);
  expect(targetAcquisition.channels.map((channel) => channel.sources.length)).toEqual(targetAcquisition.channels.map(() => expectedTargets));
  const firstTargetSeen = arrivals.findIndex((one) => one.sourcesPerRow.some((count) => count > 0));
  const tagAtFirst = arrivals[firstTargetSeen]?.pictureTag;
  const tagAtEnd = await pictureTag(page);
  outcome.remounts = {
    pictureTagBefore: pictureBefore, tagAtFirstTargetSource: tagAtFirst, tagAtEnd,
    remountedAtFirstTargetArrival: tagAtFirst !== pictureBefore,
    tagsSeenDuringArrival: [...new Set(arrivals.map((one) => one.pictureTag))],
  };
  expect(tagAtEnd, "later target sources grow the picture opened for the first one").toBe(tagAtFirst);
  const panelAfter = await panelState(page);
  expect(panelAfter.acquisitions.focussing.visible, "requested focussing visibility survived target arrival").toBe(false);
  expect(panelAfter.acquisitions.overview.visible).toBe(true);
  expect(panelAfter.acquisitions[outcome.observedTargetGroupName]?.visible, "the target group opens visible").toBe(true);
  await expect.poll(async () => (await rowsOfGroup(page, "focussing")).every((row) => !row.visible)).toBe(true);
  await expect.poll(async () => (await rowsOfGroup(page, "overview")).every((row) => row.visible)).toBe(true);
  const fitAfter = await stageView(page);
  expect(fitAfter.view.zoom).toBeCloseTo(fitBefore.view.zoom, 9);
  expect(fitAfter.view.centre.x).toBeCloseTo(fitBefore.view.centre.x, 6);
  expect(fitAfter.view.centre.y).toBeCloseTo(fitBefore.view.centre.y, 6);
  expect(viewDrift(fitBefore, fitAfter), "target arrival did not replace the whole-plate Fit").toBeLessThan(0.25);
  const records = finalScan.records;
  expect(records.length).toBe(expectedTargets);
  const registration = targetRows[0].sources.map((source, index) => {
    const bounds = physicalBounds(source);
    const centre = bounds ? { x: (bounds.xMin + bounds.xMax) / 2, y: (bounds.yMin + bounds.yMax) / 2 } : null;
    const nearest = centre ? records.map((record) => ({
      label: record.position_label, expected: record.requested_position_um,
      errorUm: Math.hypot(centre.x - record.requested_position_um.x, centre.y - record.requested_position_um.y),
    })).sort((a, b) => a.errorUm - b.errorUm)[0] : null;
    return {
      index, url: source.url, label: nearest?.label ?? null, boundsUm: bounds,
      expectedAbsoluteStageUm: nearest?.expected ?? null, engineCentreUm: centre,
      errorUm: nearest?.errorUm ?? null, error: source.error,
    };
  });
  expect(new Set(registration.map((one) => one.label)).size, "each target source stands at a different target").toBe(registration.length);
  expect.soft(registration.every((one) => one.errorUm !== null && one.errorUm < PHYSICAL_TOLERANCE_UM),
    `target sources are placed at their stage points within ${PHYSICAL_TOLERANCE_UM} um: ${JSON.stringify(registration.map((one) => one.errorUm))}`).toBe(true);
  const targetsFolder = path.join(bridge.currentRun(), "positions", outcome.observedTargetGroupName);
  const zTraces = records.map((record) => storeTrace(targetsFolder, record.position_label));
  for (const [index, trace] of zTraces.entries()) {
    expect(trace.error, `target store ${index} exists`).toBeUndefined();
    expect(trace.level0.translation[2], `target store ${index} begins at display z zero`).toBe(0);
    expect(trace.zCoordinate.display_anchor.coordinate_um).toBe(0);
    expect(trace.zCoordinate.acquisition_provenance.registered_specimen_z).toBe(false);
    expect(trace.zCoordinate.acquisition_provenance.requested_stage_focus_z_um)
      .toBeCloseTo(records[index].requested_position_um.z, 6);
    expect(trace.derivedCentreUm.x).toBeCloseTo(records[index].requested_position_um.x, 3);
    expect(trace.derivedCentreUm.y).toBeCloseTo(records[index].requested_position_um.y, 3);
  }
  const targetSetting = await bridgeJson(page, port, "/api/setting?type=acquisition");
  const targetFrameUm = targetSetting.frameUm;
  const targetCentres = records.map((record, index) => ({
    id: record.position_label, index,
    x: record.requested_position_um.x - ox, y: record.requested_position_um.y - oy,
  }));
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
  await framePlan(page, plan);
  const completed = await take("step8-complete-overview-and-targets", {
    step: 8, state: `${mode}: ${expectedTargets} targets acquired; overview base, "${outcome.observedTargetGroupName}" above, focussing hidden`,
    expect: async ({ record }) => {
      expect(record.projectionError.planMaxPx).toBeLessThan(SCREEN_TOLERANCE_PX);
      const engineProjection = await page.evaluate(({ centres }) => {
        const placed = window.__thePicture.whereThingsAreDrawn();
        const [ox2, oy2] = window.__theStageCanvas.carrierOriginUm();
        const pt = (value) => (Array.isArray(value) ? { x: value[0], y: value[1] } : value);
        return centres.map((at) => {
          const stage = pt(window.__theStageCanvas.project(at.x, at.y));
          const engine = placed.project(at.x + ox2, at.y + oy2);
          return Math.hypot(stage.x - engine.x, stage.y - engine.y);
        });
      }, { centres: targetCentres });
      expect(Math.max(...engineProjection), "target stage points project to the same pixel through plan and engine").toBeLessThan(SCREEN_TOLERANCE_PX);
      record.projectionError.targetStagePointsMaxPx = Math.max(...engineProjection);
      fs.writeFileSync(path.join(OUT, `${record.name}.json`), JSON.stringify(record, null, 2));
    },
    extra: { arrivals, registration, zTraces, remounts: outcome.remounts, targetFrameUm, groupsBefore, mode },
  });

  const fieldsWithoutTargets = plan.map((_, index) => index).filter((index) => !targetCentres.some((at) =>
    Math.abs(at.x - plan[index].x) <= plan[index].frameUm / 2 + targetFrameUm / 2
    && Math.abs(at.y - plan[index].y) <= plan[index].frameUm / 2 + targetFrameUm / 2));
  await page.evaluate(() => window.__theStageCanvas.fadeTo(0));
  await page.evaluate(() => { for (const key of ["cells", "targets"]) if (window.__theStageCanvas.layers().some((one) => one.key === key)) window.__theStageCanvas.showLayer(key, false); });
  await setGroupVisible(page, "overview", false);
  await rest(2500);
  const targetBoxes = await boxesOnScreen(page, targetCentres, targetFrameUm);
  const emptyBoxes = await boxesOnScreen(page, fieldsWithoutTargets.slice(0, 2).map((index) => plan[index]), plan[0].frameUm);
  await take("step8-target-only", {
    step: 8, state: `${mode}: only "${outcome.observedTargetGroupName}" visible; plan and marks faded away`,
    expect: async ({ record, pixels }) => {
      const targetResults = targetBoxes.map((box) => ({ id: box.id, ...inspectBox(pixels, box, { inset: 0.3 }) }));
      const emptyResults = emptyBoxes.map((box) => inspectBox(pixels, box, { inset: 0.35 }));
      expect(targetResults.filter((one) => !one.error), "every target box is on screen").toHaveLength(targetBoxes.length);
      expect(targetResults.every(textured), `target pixels are drawn at every acquired target: ${JSON.stringify(targetResults)}`).toBe(true);
      expect(emptyResults.length, "a field without a target exists to compare against").toBeGreaterThan(0);
      expect(emptyResults.every(blank), `a field without a target stays empty when only targets are drawn: ${JSON.stringify(emptyResults)}`).toBe(true);
      expect(record.visibility.engineObserved.overview.every((one) => !one.visible)).toBe(true);
      expect(record.visibility.engineObserved[outcome.observedTargetGroupName].every((one) => one.visible)).toBe(true);
      record.pixelCheck.targetBoxes = targetResults;
      record.pixelCheck.fieldsWithoutTarget = emptyResults;
      fs.writeFileSync(path.join(OUT, `${record.name}.json`), JSON.stringify(record, null, 2));
    },
  });
  await setGroupVisible(page, "overview", true);
  await setGroupVisible(page, outcome.observedTargetGroupName, false);
  await rest(2500);
  await take("step8-overview-only", {
    step: 8, state: `${mode}: only overview visible; "${outcome.observedTargetGroupName}" and focussing hidden`,
    expect: async ({ record, pixels }) => {
      const results = planBoxes.map((box) => inspectBox(pixels, box));
      expect(results.filter(textured).length, "nine overview ROIs stay textured with targets hidden").toBe(9);
      expect(record.visibility.engineObserved[outcome.observedTargetGroupName].every((one) => !one.visible)).toBe(true);
      expect(record.visibility.engineObserved.focussing.every((one) => !one.visible)).toBe(true);
      record.pixelCheck.plannedRois = results;
      fs.writeFileSync(path.join(OUT, `${record.name}.json`), JSON.stringify(record, null, 2));
    },
  });
  const matricesBefore = completed.raw.layers.flatMap((row) => row.sources.map((one) => JSON.stringify(one.matrix)));
  const matricesNow = (await engineRows(page)).flatMap((row) => row.sources.map((one) => JSON.stringify(one.matrix)));
  expect(matricesNow, "visibility changes left every source matrix untouched").toEqual(matricesBefore);
  await setGroupVisible(page, outcome.observedTargetGroupName, true);
  await setGroupVisible(page, "focussing", true);
  await rest(1500);
  expect((await rowsOfGroup(page, "focussing")).every((row) => row.visible), "focussing shows again independently").toBe(true);
  await setGroupVisible(page, "focussing", false);
  const panelEnd = await panelState(page);
  expect(panelEnd.lastMismatch, "the engine never disagreed with the requested state").toBeNull();
  return { records, targetCentres, targetFrameUm, registration, zTraces, arrivals };
}

async function disconnectAndReconnect({ page, take, port }) {
  await gotoStep(page, "Connect");
  await page.locator(".session-foot button.danger").click();
  /* The page fires the disconnect and does not wait for the bridge to finish
     it, so the readings below wait for the bridge rather than for a fixed
     moment: closing the analysis workers and the viewer took longer than
     that moment on one machine, and the viewer was still up when asked. */
  await expect.poll(async () => (await bridgeJson(page, port, "/api/viewer")).running, {
    timeout: 30_000, message: "the bridge never finished the disconnect",
  }).toBe(false);
  const afterDisconnect = await page.evaluate(async (bridgePort) => ({
    run: window.__theRunState(), targets: window.__theStageCanvas.targets().length,
    /* Nothing is open after a disconnect: the closed session has no run to
       draw, so the page must not reopen an empty picture on the JPEG
       fallback address, as it once did. */
    pictureOpen: Boolean(window.__thePicture),
    acquisitionRows: window.__thePicture?.layersForMeasurement?.()?.length ?? 0,
    viewer: await fetch(`http://127.0.0.1:${bridgePort}/api/viewer`).then((a) => a.json()).catch(() => null),
    plan: window.__theStageCanvas.plan().length,
  }), port);
  expect(afterDisconnect.run.done, "disconnect clears every finished step").toEqual([]);
  expect(afterDisconnect.targets, "disconnect forgets the targets").toBe(0);
  expect(afterDisconnect.acquisitionRows, "disconnect leaves no acquisition source on the picture").toBe(0);
  expect(afterDisconnect.pictureOpen, "disconnect leaves no picture open at all").toBe(false);
  expect(afterDisconnect.viewer?.running, "disconnect stops the viewer service").toBe(false);
  expect(afterDisconnect.plan, "disconnect forgets the plan").toBe(0);
  await expect(page.locator(".session-foot button.run")).toBeEnabled();
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".check-row.pending")).toHaveCount(0);
  await take("step1-reconnected", { step: 1, state: "disconnected then reconnected; run-owned state reset", extra: { afterDisconnect } });
}

test("Steps 1 to 8 through the operator page on the real bridge, Viewer 0.2 and the mock kidney", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const provenance = provenanceOfTheRun();
  const bridge = await startTheBridge({ port: PORT });
  const audit = trackBrowser(page, PORT);
  const recorder = makeRecorder({ page, port: PORT, bridge, audit, provenance });
  const take = recorder.take.bind(recorder);
  const outcome = { mode: "operator page", observedTargetGroupName: null, remounts: null, discovery: null };
  try {
    const { plan, planBoxes } = await throughStepFive({ page, take, port: PORT, bridge });

    /* ---------------------------------------------------------- Step 6 */
    await gotoStep(page, "Detect objects");
    /* The review runs Cellpose, the accurate way; the page opens on the fast one. */
    await page.selectOption("#detect-method", "accurate");
    await expect(page.locator("#tile-label")).toHaveText("1 / 9");
    /* A tile test stopped by hand first: the press that started it reads
       Interrupt, the bridge puts the field's worker down, the readout says
       the field was not examined and the press is ready again. The real
       test that follows then pays the worker's spawn once more. */
    await page.getByRole("button", { name: "Test this tile" }).click();
    await expect(page.locator("#detect-try"), "the press that started the test becomes Interrupt").toHaveText("Interrupt");
    await expect.poll(async () => (await bridgeJson(page, PORT, "/api/targets/discover")).running, { timeout: 30_000 }).toBe(true);
    await page.locator("#detect-try").click();
    await expect(page.locator("#detect-readout")).toContainText("stopped by hand", { timeout: 120_000 });
    const afterTheHand = await bridgeJson(page, PORT, "/api/targets/discover");
    expect(afterTheHand, "the bridge says the test was stopped, not failed, and examined nothing").toMatchObject({ running: false, stopped: true, error: null, fields: [], failed: [] });
    await expect(page.locator("#detect-try")).toHaveText("Test this tile");
    await expect(page.locator("#detect-try")).toBeEnabled();
    outcome.discovery = { tileTestStoppedByHand: afterTheHand };
    await page.getByRole("button", { name: "Test this tile" }).click();
    await expect.poll(async () => {
      const state = await bridgeJson(page, PORT, "/api/targets/discover");
      return !state.running && (state.error || ((state.fields?.length ?? 0) + (state.failed?.length ?? 0)) >= 1);
    }, { timeout: 900_000, message: "the tile test never answered" }).toBeTruthy();
    const tried = await bridgeJson(page, PORT, "/api/targets/discover");
    const blocked = tried.error ?? tried.failed?.[0]?.why ?? null;
    outcome.discovery = { ...outcome.discovery, tileTest: { error: tried.error, failed: tried.failed, fields: tried.fields?.length ?? 0 } };
    if (blocked) {
      /* The panel must show the analysis's own sentence, not a page error. */
      await expect(page.locator("#detect-readout")).toContainText(/pipeline failed|Cellpose|not examined/);
      await take("step6-discovery-blocked", {
        step: 6, state: "the real Cellpose detection could not run in this environment; the bridge reported the reason",
        extra: { discovery: outcome.discovery },
      });
      recorder.writeManifest({ outcome, skipped: `Steps 6 to 8 through the operator page: ${blocked}` });
      test.skip(true, `real discovery is unavailable here: ${blocked}`);
    }
    expect(tried.fields.length, "the tile test examined one field").toBe(1);
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 1_500_000 });
    const discovery = await bridgeJson(page, PORT, "/api/targets/discover");
    expect(discovery.error, "discovery finished without a bridge error").toBeNull();
    expect(discovery.failed, "every field was examined; a filed failure is not a pass").toEqual([]);
    expect(discovery.fields.length, "every field answered").toBe(plan.length);
    const discovered = await page.evaluate(() => window.__theStageCanvas.targets());
    expect(discovered.length, "discovery placed targets on the canvas").toBeGreaterThan(0);
    expect(discovered.every((one) => !one.selected && !one.acquired), "candidates are not silently selected").toBe(true);
    expect(discovered.every((one) => {
      const field = plan[one.field];
      return field && Math.abs(one.x - field.x) <= field.frameUm / 2 && Math.abs(one.y - field.y) <= field.frameUm / 2;
    }), "every candidate lies inside the field that produced it").toBe(true);
    expect(new Set(discovered.map((one) => one.id)).size, "every candidate has a unique id").toBe(discovered.length);
    const bridgeCells = discovery.fields.flatMap((field) => field.cells.map((cell) => ({ ...cell, position_label: field.position_label })));
    expect(bridgeCells.length, "the canvas holds every cell the bridge found").toBe(discovered.length);
    const [ox, oy] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());
    const byId = new Map(bridgeCells.map((cell) => [cell.id, cell]));
    const worstCarrierError = Math.max(...discovered.map((one) => {
      const cell = byId.get(one.id);
      return cell ? Math.hypot(cell.x - (one.x + ox), cell.y - (one.y + oy)) : Infinity;
    }));
    expect(worstCarrierError, "canvas positions are the bridge's stage positions minus the carrier origin").toBeLessThan(1e-6);
    await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
    await framePlan(page, plan);
    const canvasBox = await page.locator("#stage-canvas").boundingBox();
    const withCells = await page.screenshot();
    await page.evaluate(() => window.__theStageCanvas.showLayer("cells", false));
    await page.waitForTimeout(300);
    const withoutCells = await page.screenshot();
    await page.evaluate(() => window.__theStageCanvas.showLayer("cells", true));
    await page.waitForTimeout(300);
    const cellsChanged = pixelChangesInside(withCells, withoutCells, canvasBox);
    expect(cellsChanged, "the candidate layer materially changes the canvas").toBeGreaterThan(10);
    const hovered = discovered[0];
    await page.mouse.move(canvasBox.x + hovered.screen.x, canvasBox.y + hovered.screen.y);
    await expect(page.locator("#stage-tip"), "a candidate is hoverable at its projection").toContainText(hovered.id);
    await take("step6-discovered-over-overview", {
      step: 6, state: `discovery finished: ${discovered.length} candidates from ${discovery.fields.length} fields, ${discovery.failed?.length ?? 0} failed`,
      extra: { discovery: { fields: discovery.fields.map((field) => ({ field: field.field, label: field.position_label, cells: field.cells.length })), failed: discovery.failed ?? [], candidateLayerPixelChange: cellsChanged, hoverCheck: { id: hovered.id, screen: hovered.screen } } },
    });

    /* The display settings are a tab away from the step's channel, in the
       same column: pressing it shows the picture's panel there and hides the
       channel, pressing the step's name brings the channel back, and the
       canvas does not move by a pixel either way. */
    await expect(page.locator(".side-tab button.tab")).toHaveCount(2);
    await page.locator(".side-tab button.tab", { hasText: "Detect objects" }).click();
    await expect(page.locator("#canvas-side")).toBeVisible();
    const canvasBefore = await page.locator("#stage-canvas").boundingBox();
    await page.locator(".side-tab button.tab", { hasText: "Display settings" }).click();
    await expect(page.locator("#display-side .viewer-panel")).toBeVisible();
    await expect(page.locator("#canvas-side")).toBeHidden();
    await expect(page.locator(".side-tab button.tab", { hasText: "Display settings" })).toHaveAttribute("aria-selected", "true");
    expect(await page.locator("#stage-canvas").boundingBox(), "showing the display settings does not move the canvas").toEqual(canvasBefore);
    await take("step6-display-settings-tab", {
      step: 6, state: "the display settings shown in the channel's column, a tab away from the step; the canvas where it was",
    });
    await page.locator(".side-tab button.tab", { hasText: "Detect objects" }).click();
    await expect(page.locator("#canvas-side")).toBeVisible();
    await expect(page.locator("#display-side")).toBeHidden();
    expect(await page.locator("#stage-canvas").boundingBox(), "bringing the channel back does not move the canvas").toEqual(canvasBefore);

    /* ---------------------------------------------------------- Step 7 */
    await gotoStep(page, "Discover Targets");
    const beforeGate = await page.evaluate(() => window.__theStageCanvas.targets());
    expect(identityOf(beforeGate)).toEqual(identityOf(discovered));
    expect(beforeGate.every((one) => !one.selected), "no gate selects nothing, not everything").toBe(true);
    await expect(page.locator("#gate-readout")).toHaveText("");
    await take("step7-candidates-before-gate", {
      step: 7, state: "refine step opened; all candidates drawn as context; no gate yet",
      expect: async ({ record }) => {
        expect(record.counts.targetsSelected).toBe(0);
        expect(record.counts.targetsOnCanvas).toBe(discovered.length);
      },
    });
    const fx = await page.locator("#gate-fx").inputValue();
    const fy = await page.locator("#gate-fy").inputValue();
    const sc = await page.locator("#scatter-canvas").boundingBox();
    const polygon = [[0.2, 0.08], [0.98, 0.08], [0.98, 0.85], [0.2, 0.85]];
    const lay = async () => {
      for (const [gx, gy] of polygon) {
        await page.mouse.click(...plotPoint(sc, gx, gy));
        await page.waitForTimeout(150);
      }
      await page.mouse.click(...plotPoint(sc, polygon[0][0], polygon[0][1]));
      await page.waitForTimeout(400);
    };
    /* The gate rings its catch as it is drawn; the ceiling is applied by
       the Restrict press, and only then is the selection a run's worth. */
    const restrict = async () => {
      await gotoStep(page, "Target scan area");
      await page.locator("#gate-max").fill(String(MAX_TARGETS));
      await page.locator("#gate-max").dispatchEvent("input");
      await page.locator(".panel.on button.step-run").click();
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 30_000 });
      await gotoStep(page, "Discover Targets");
    };
    /* What Restrict kept, as the canvas marks it. */
    const restrictedIds = async () => (await page.evaluate(() => window.__theStageCanvas.targets()))
      .filter((one) => one.restricted).map((one) => one.id);
    await lay();
    await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
    await expect(page.locator("#gate-readout")).toContainText(/selected|kept of/);
    await restrict();
    const gated = await page.evaluate(() => window.__theStageCanvas.targets());
    const selectedIds = await restrictedIds();
    expect(selectedIds.length, "the gate kept a bounded selection").toBeGreaterThan(0);
    expect(identityOf(gated), "gating leaves coordinates untouched").toEqual(identityOf(discovered));
    const readout = await page.locator("#gate-readout").textContent();
    const fyOptions = await page.locator("#gate-fy option").allTextContents();
    const other = fyOptions.find((name) => name !== fy && name !== fx);
    let intersection = null;
    if (other) {
      await page.locator("#gate-fy").selectOption(other);
      await page.waitForTimeout(200);
      await lay();
      await expect(page.locator("#gate-list .gate-row")).toHaveCount(2);
      await restrict();
      const twice = await page.evaluate(() => window.__theStageCanvas.targets());
      intersection = twice.filter((one) => one.restricted).map((one) => one.id);
      expect(intersection.length, "a second all-encompassing gate cannot widen the selection").toBeLessThanOrEqual(selectedIds.length);
      await page.locator("#gate-list .gate-row").nth(1).locator("button.rec-drop").click();
      await page.waitForTimeout(300);
      await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
      await page.locator("#gate-fy").selectOption(fy);
      await page.waitForTimeout(200);
      await restrict();
    }
    const selectedAfter = await restrictedIds();
    await gotoStep(page, "Scan the overview");
    await page.waitForTimeout(300);
    await gotoStep(page, "Discover Targets");
    await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
    const kept = await page.evaluate(() => window.__theStageCanvas.targets());
    expect(kept.filter((one) => one.restricted).map((one) => one.id).sort()).toEqual([...selectedAfter].sort());
    await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
    await take("step7-gated-selection", {
      step: 7, state: `polygon gate on ${fx} x ${fy}; ${selectedAfter.length} selected of ${discovered.length}; cap ${MAX_TARGETS} per tileset`,
      expect: async ({ record }) => {
        expect(record.counts.targetsSelected).toBe(selectedAfter.length);
        expect(record.counts.targetsOnCanvas).toBe(discovered.length);
      },
      extra: { gate: { fx, fy, polygonFractions: polygon, readout, selectedIds: selectedAfter, secondGateIntersection: intersection, capPerTileset: MAX_TARGETS } },
    });
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 30_000 });

    /* ---------------------------------------------------------- Step 8 */
    await gotoStep(page, "Acquire Targets");
    const ready = await page.evaluate(() => window.__theStageCanvas.targets());
    expect(identityOf(ready)).toEqual(identityOf(discovered));
    expect(ready.filter((one) => one.restricted).map((one) => one.id).sort()).toEqual([...selectedAfter].sort());
    await expect(page.locator(".panel.on button.step-run"), "acquisition waits for the target configuration").toBeDisabled();
    await expect(page.locator(".action-hint")).toContainText(/add the tiles/);
    /* The settings are recorded on the target scan area, the step before. */
    await gotoStep(page, "Target scan area");
    await page.locator("#target-type .setting-box.open button.run").click();
    await page.waitForTimeout(700);
    await expect(page.locator("#target-type .setting-box.done")).toHaveCount(1);
    await page.locator("#add-tiles").click();
    await page.waitForTimeout(300);
    await gotoStep(page, "Acquire Targets");
    await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
    await take("step8-ready-to-acquire", {
      step: 8, state: `target configuration recorded; ${selectedAfter.length} targets gated; Acquire enabled`,
    });
    const arrival = await proveTargetArrival({
      page, take, port: PORT, bridge, plan, planBoxes, expectedTargets: selectedAfter.length, mode: "operator page", outcome,
      trigger: async () => { await page.locator(".panel.on button.step-run").click(); },
    });
    /* The eyes were pressed on the display settings; the gallery and the
       step's press stand in its channel, a tab back. */
    await showTheChannel(page);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 120_000 });
    const acquired = await page.evaluate(() => window.__theStageCanvas.targets());
    const acquiredIds = acquired.filter((one) => one.acquired).map((one) => one.id).sort();
    expect(acquiredIds, "exactly the gated targets are acquired").toEqual([...selectedAfter].sort());
    expect(identityOf(acquired), "acquisition never moved a target").toEqual(identityOf(discovered));
    /* The page acquires the gated cells in its own order (the order the
       ceiling drew them), so a record is matched to its target by where it
       was taken, not by its place in the list. */
    const recordedAt = arrival.records.map((record) => acquired.filter((one) =>
      one.acquired
      && Math.abs(record.requested_position_um.x - (one.x + ox)) < 1e-6
      && Math.abs(record.requested_position_um.y - (one.y + oy)) < 1e-6).map((one) => one.id));
    expect(recordedAt.every((ids) => ids.length === 1), `every record was taken at exactly one gated target: ${JSON.stringify(recordedAt)}`).toBe(true);
    expect(recordedAt.flat().sort(), "every gated target was taken once").toEqual([...selectedAfter].sort());
    await page.evaluate(() => { window.__theStageCanvas.showLayer("cells", true); window.__theStageCanvas.showLayer("targets", true); window.__theStageCanvas.fadeTo(1); });
    const first = acquired.find((one) => one.acquired);
    await page.evaluate(({ x, y }) => {
      const view = window.__theStageCanvas.view();
      window.__theCanvas.lookAt({ zoom: Math.min(view.zoom, 2), centre: { x, y } });
    }, first);
    await rest(2000);
    await take("step8-acquired-ring-close-up", {
      step: 8, state: `close-up of acquired target ${first.id}: green ring and high-resolution frame over the overview`,
      expect: async ({ record, pixels }) => {
        const [box] = await boxesOnScreen(page, [first], arrival.targetFrameUm);
        /* The ring is drawn at a radius the acquired layer sizes by zoom
           (`layers.js`: 9 px scaled by the square root of the pixels per
           micrometre over 0.03, at least 7 px), so the search reaches out
           to where the ring is: at this close-up it stood 36 px out, beyond
           a fixed 24 px window that saw only the sample's green. */
        const [oneHundredUm] = await boxesOnScreen(page, [first], 200);
        const pxPerUm = (oneHundredUm.right - oneHundredUm.left) / 200;
        const ringPx = Math.max(7, 9 * Math.sqrt(pxPerUm / 0.03));
        const green = greenNear(pixels, box.centre, ringPx + 8);
        expect(green, `the acquired target wears a green ring at its projection (ring ${ringPx.toFixed(1)} px out)`).toBeGreaterThan(20);
        record.pixelCheck.ringRadiusPx = ringPx;
        const withRing = await page.screenshot();
        await page.evaluate(() => window.__theStageCanvas.showLayer("targets", false));
        await page.waitForTimeout(300);
        const withoutRing = await page.screenshot();
        await page.evaluate(() => window.__theStageCanvas.showLayer("targets", true));
        await page.waitForTimeout(300);
        const canvas = await page.locator("#stage-canvas").boundingBox();
        const changed = pixelChangesInside(withRing, withoutRing, canvas);
        expect(changed, "the acquired-target layer materially changes the canvas").toBeGreaterThan(10);
        record.pixelCheck.greenRingPixels = green;
        record.pixelCheck.acquiredLayerPixelChange = changed;
        fs.writeFileSync(path.join(OUT, `${record.name}.json`), JSON.stringify(record, null, 2));
      },
    });
    /* The channel lists the acquired targets, one row each, and shows one
       pair: the chosen target's. Choosing is done in the list or on the
       canvas, and either way the other follows. */
    const rows = page.locator("#target-list .point-row");
    await expect(rows).toHaveCount(selectedAfter.length);
    const captions = await rows.allTextContents();
    for (const id of acquiredIds) expect(captions.some((text) => text.includes(id)), `gallery row for ${id}`).toBe(true);
    await expect(page.locator(".pair"), "one pair on show").toHaveCount(1);
    await rows.first().locator("button").click();
    await expect(rows.first()).toHaveAttribute("aria-current", "true");
    await expect(page.locator(".pair .meta")).toContainText(acquiredIds[0]);
    if (selectedAfter.length > 1) {
      const other = acquired.find((one) => one.id === selectedAfter[1]);
      const at = await page.evaluate(({ x, y }) => window.__theStageCanvas.project(x, y), { x: other.x, y: other.y });
      const [px, py] = Array.isArray(at) ? at : [at.x, at.y];
      const box = await page.locator("#stage-canvas").boundingBox();
      await page.mouse.click(box.x + px, box.y + py);
      await expect(rows.nth(1), "a press on a ringed target on the canvas chooses its row").toHaveAttribute("aria-current", "true");
      await expect(page.locator(".pair .meta")).toContainText(acquiredIds[1]);
      await rows.first().locator("button").click();
    }
    /* The eye on the targets acquisition hides the acquired frames: the
       picture draws them itself, and the canvas prints no copies over them. */
    expect((await rowsOfGroup(page, "targets")).length, "the picture draws the targets acquisition").toBeGreaterThan(0);
    await setGroupVisible(page, "targets", false);
    await setGroupVisible(page, "targets", true);
    await showTheChannel(page);
    const gallery = [];
    const finalScan = await bridgeJson(page, PORT, "/api/scan");
    for (const [index, record] of arrival.records.entries()) {
      const answer = await page.request.get(`http://127.0.0.1:${PORT}/view/${finalScan.acquisition_type}/${record.position_label}.jpg`);
      const cell = acquired.find((one) => one.id === selectedAfter[index]);
      const fieldLabel = discovery.fields.find((one) => one.field === cell.field)?.position_label;
      const overview = await page.request.get(`http://127.0.0.1:${PORT}/view/overview/${fieldLabel}.jpg`);
      gallery.push({ id: cell.id, field: cell.field, targetPicture: { label: record.position_label, status: answer.status(), bytes: (await answer.body()).length }, overviewPicture: { label: fieldLabel, status: overview.status(), bytes: (await overview.body()).length } });
    }
    expect(gallery.every((one) => one.targetPicture.status === 200 && one.targetPicture.bytes > 1000), `every target frame picture is served: ${JSON.stringify(gallery)}`).toBe(true);
    expect(gallery.every((one) => one.overviewPicture.status === 200 && one.overviewPicture.bytes > 1000), "every overview field picture is served").toBe(true);
    await page.locator(".pair button.pick-good").click();
    await expect(page.locator("#gallery-readout")).toContainText("1 marked");
    await expect(page.locator("#gallery-readout")).toContainText("1 good");
    await expect(rows.first().locator(".z"), "the verdict is listed on the row").toHaveText("✓");
    if (selectedAfter.length > 1) {
      await rows.nth(1).locator("button").click();
      await page.locator(".pair button.pick-bad").click();
      await expect(page.locator("#gallery-readout")).toContainText("2 marked");
      await page.locator(".pair button.pick-bad").click();
      await expect(page.locator("#gallery-readout")).toContainText("1 marked");
    }
    await expect(page.locator(".side-tab")).toContainText("Acquire Targets");
    await take("step8-gallery-with-verdict", {
      step: 8, state: `${selectedAfter.length} gallery pairs; first marked good`,
      extra: { gallery, readout: await page.locator("#gallery-readout").textContent() },
    });
    await disconnectAndReconnect({ page, take, port: PORT });
    recorder.writeManifest({ outcome, canonicalName: "targets" });
  } finally {
    recorder.writeManifest({ outcome, finished: true });
    await bridge.stop();
  }
});

test("Step 8 source model: real target positions published through the bridge arrive as a separate Viewer 0.2 acquisition", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const port = PORT + 2;
  const provenance = provenanceOfTheRun();
  const bridge = await startTheBridge({ port });
  const audit = trackBrowser(page, port);
  const recorder = makeRecorder({ page, port, bridge, audit, provenance });
  /* Records of this test carry a prefix so they never overwrite the operator-page ones. */
  const take = (name, options) => recorder.take(`bridge-${name}`, options);
  const outcome = { mode: "bridge-published targets", observedTargetGroupName: null, remounts: null };
  try {
    const { plan, planBoxes, focusZ } = await throughStepFive({ page, take, port, bridge });
    const [ox, oy] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());
    /* Three target positions inside three different overview fields, off the
       field centres, at the focus height the real Step 8 would request. */
    const chosenFields = [0, 4, 8];
    const positions = chosenFields.map((index) => {
      const at = plan[index];
      const x = at.x + at.frameUm * 0.18;
      const y = at.y - at.frameUm * 0.12;
      const z = focusZ[index]?.z;
      return z === null || z === undefined ? { x: x + ox, y: y + oy } : { x: x + ox, y: y + oy, z };
    });
    expect(positions.every((one) => Number.isFinite(one.z)), "the focus map gives every target a height").toBe(true);
    await take("step8-ready-to-acquire", {
      step: 8, state: `bridge path: ${positions.length} target positions chosen inside fields ${chosenFields.join(", ")}; no operator gate (discovery unavailable here)`,
      extra: { targetPositionsAbsoluteStageUm: positions, chosenFields },
    });
    const proven = await proveTargetArrival({
      page, take, port, bridge, plan, planBoxes, expectedTargets: positions.length, mode: "bridge-published targets", outcome,
      trigger: async () => {
        const answer = await fetch(`http://127.0.0.1:${port}/api/scan`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ positions, acquisition_type: "targets", state: null }),
        });
        expect(answer.ok, "the bridge accepted the target scan").toBe(true);
      },
    });
    /* A rerun with fewer targets: the records say two, and the Viewer group
       must account for exactly the positions the rerun captured. */
    const rerun = positions.slice(0, 2);
    /* The third store is retired by the rerun: the engine may still ask for
       its pixels until the page reads the shrunken list, and those misses
       are recorded as expected. Any other failed request still fails. */
    audit.retire(`${outcome.observedTargetGroupName}_${proven.records[2].position_label}.ome.zarr`);
    const answer = await fetch(`http://127.0.0.1:${port}/api/scan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ positions: rerun, acquisition_type: "targets", state: null }),
    });
    expect(answer.ok).toBe(true);
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).done, { timeout: 120_000 }).toBe(2);
    await expect.poll(async () => !(await bridgeJson(page, port, "/api/scan")).running, { timeout: 120_000 }).toBe(true);
    await rest(4000);
    const afterRerun = await bridgeJson(page, port, "/api/viewer");
    const group = afterRerun.acquisitions.find((one) => one.name === outcome.observedTargetGroupName);
    const rerunSources = group.channels.map((channel) => channel.sources.length);
    const rerunRows = (await engineRows(page)).filter((row) => groupOf(row) === outcome.observedTargetGroupName).map((row) => row.sources.length);
    const storesOnDisk = fs.readdirSync(path.join(bridge.currentRun(), "positions", outcome.observedTargetGroupName)).filter((name) => name.endsWith(".ome.zarr")).length;
    outcome.rerun = { recordsCaptured: 2, viewerSourcesPerChannel: rerunSources, engineSourcesPerRow: rerunRows, storesOnDisk };
    await take("step8-rerun-with-fewer-targets", {
      step: 8, state: `bridge path: target scan run again with 2 positions; Viewer shows ${JSON.stringify(rerunSources)} sources per channel, ${storesOnDisk} stores on disk`,
      extra: { rerun: outcome.rerun },
    });
    expect(rerunSources, "a rerun with fewer targets leaves no stale target source in the Viewer group").toEqual(group.channels.map(() => 2));
    expect(rerunRows, "the engine's rows hold exactly the rerun's sources").toEqual(rerunRows.map(() => 2));
    expect(storesOnDisk, "the stores of the first run are gone from disk").toBe(2);
    await disconnectAndReconnect({ page, take, port });
    recorder.writeManifest({ outcome, canonicalName: "targets" });
  } finally {
    recorder.writeManifest({ outcome, finished: true });
    await bridge.stop();
  }
});

/* ------------------------------------------------------- interruption accounting */

/* How many cells the ceiling keeps for the interrupted run: enough that the
   mock, which takes a target every 130 ms or so, is still running when the
   operator's Interrupt lands after the first pair. */
const INTERRUPTED_RUN_TARGETS = Number(process.env.LIVE_INTERRUPT_TARGETS ?? 12);

/** Everything the run and its surroundings say about acquired targets, read at once. */
async function targetAccounting({ page, port, bridge, group }) {
  const scan = await bridgeJson(page, port, "/api/scan");
  const viewer = await bridgeJson(page, port, "/api/viewer");
  const acquisition = (viewer.acquisitions ?? []).find((one) => one.name === group);
  const rows = (await engineRows(page)).filter((row) => groupOf(row) === group);
  const targets = await page.evaluate(() => window.__theStageCanvas.targets());
  const run = await page.evaluate(() => window.__theRunState());
  const folder = path.join(bridge.currentRun(), "positions", group);
  return {
    scan: {
      running: scan.running, stopped: Boolean(scan.stopped), done: scan.done, of: scan.of,
      error: scan.error, records: (scan.records ?? []).length,
    },
    viewerSourcesPerChannel: acquisition ? acquisition.channels.map((channel) => channel.sources.length) : [],
    engineSourcesPerRow: rows.map((row) => row.sources.length),
    storesOnDisk: fs.existsSync(folder) ? fs.readdirSync(folder).filter((name) => name.endsWith(".ome.zarr")).length : 0,
    acquiredOnCanvas: targets.filter((one) => one.acquired).map((one) => one.id),
    galleryPairs: await page.locator("#target-list .point-row").count(),
    galleryCaptions: await page.locator("#target-list .point-row").allTextContents(),
    button: (await page.locator(".panel.on button.step-run").textContent())?.trim(),
    hint: (await page.locator(".action-hint").first().textContent().catch(() => ""))?.trim(),
    stepDone: run.done.includes("acquire"),
    stepRan: run.ran.includes("acquire"),
    note: run.notes.acquire ?? null,
    records: (scan.records ?? []).map((record) => ({ label: record.position_label, at: record.requested_position_um })),
  };
}

/** For each record, the ids of the gated targets standing at its requested position. */
const targetsAtRecords = (records, targets, ox, oy) => records.map((record) => targets.filter((one) =>
  Math.abs(record.at.x - (one.x + ox)) < 1e-6 && Math.abs(record.at.y - (one.y + oy)) < 1e-6).map((one) => one.id));

test("Step 8 interruption: an acquisition stopped by hand accounts for exactly what it took, and Run again completes it", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const port = PORT + 4;
  const provenance = provenanceOfTheRun();
  const bridge = await startTheBridge({ port });
  const audit = trackBrowser(page, port);
  const recorder = makeRecorder({ page, port, bridge, audit, provenance });
  const take = recorder.take.bind(recorder);
  const outcome = { mode: "operator page, interrupted acquisition", interrupted: null, runAgain: null };
  const group = "targets";
  const all = INTERRUPTED_RUN_TARGETS;
  try {
    await throughStepFive({ page, take, port, bridge });

    /* Steps 6 and 7 the short way: the whole population discovered, one
       gate, a ceiling high enough that the run outlasts the operator's hand. */
    await gotoStep(page, "Detect objects");
    /* The review runs Cellpose, the accurate way; the page opens on the fast one. */
    await page.selectOption("#detect-method", "accurate");
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 1_500_000 });
    const discovery = await bridgeJson(page, port, "/api/targets/discover");
    expect(discovery.error, "discovery finished without a bridge error").toBeNull();
    expect(discovery.fields.length, "every field was examined").toBe(9);
    await gotoStep(page, "Discover Targets");
    const sc = await page.locator("#scatter-canvas").boundingBox();
    const polygon = [[0.2, 0.08], [0.98, 0.08], [0.98, 0.85], [0.2, 0.85]];
    for (const [gx, gy] of polygon) {
      await page.mouse.click(...plotPoint(sc, gx, gy));
      await page.waitForTimeout(150);
    }
    await page.mouse.click(...plotPoint(sc, polygon[0][0], polygon[0][1]));
    await page.waitForTimeout(400);
    await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
    await gotoStep(page, "Target scan area");
    await page.locator("#gate-max").fill(String(all));
    await page.locator("#gate-max").dispatchEvent("input");
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 30_000 });
    const gated = (await page.evaluate(() => window.__theStageCanvas.targets())).filter((one) => one.restricted);
    expect(gated.length, "the ceiling kept a run's worth of targets").toBe(all);
    const [ox, oy] = await page.evaluate(() => window.__theStageCanvas.carrierOriginUm());

    /* Step 8: started with the real button, stopped with the same button
       once the first pair has landed. */
    await page.locator("#target-type .setting-box.open button.run").click();
    await page.waitForTimeout(700);
    await page.locator("#add-tiles").click();
    await page.waitForTimeout(300);
    await gotoStep(page, "Acquire Targets");
    await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run"), "the press that started the run becomes Interrupt").toHaveText("Interrupt", { timeout: 10_000 });
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).done, { timeout: 60_000, message: "the first pair never landed" }).toBeGreaterThanOrEqual(1);
    const pressedAt = (await bridgeJson(page, port, "/api/scan")).done;
    await page.locator(".panel.on button.step-run").click();
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).running, { timeout: 60_000, message: "the scan never stopped" }).toBe(false);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 30_000 });
    const taken = (await bridgeJson(page, port, "/api/scan")).done;
    expect(taken, "the run was stopped before it finished, or the interruption proves nothing").toBeLessThan(all);
    expect(taken, "what was captured before the hand stands").toBeGreaterThanOrEqual(1);
    /* The Viewer and the engine follow the page's polls; give them theirs. */
    await expect.poll(async () => (await targetAccounting({ page, port, bridge, group })).engineSourcesPerRow, { timeout: 30_000 }).toEqual([taken, taken, taken]);
    const stopped = await targetAccounting({ page, port, bridge, group });
    outcome.interrupted = { pressedAt, ...stopped };
    expect(stopped.scan, "the bridge says stopped, not failed, with exactly the captured records").toMatchObject({ running: false, stopped: true, error: null, done: taken, records: taken, of: all });
    expect(stopped.viewerSourcesPerChannel, "the Viewer group holds one source per captured position").toEqual([taken, taken, taken]);
    expect(stopped.storesOnDisk, "one store on disk per captured position").toBe(taken);
    expect(stopped.acquiredOnCanvas.length, "the canvas marks exactly the captured cells as acquired").toBe(taken);
    const atRecords = targetsAtRecords(stopped.records, gated, ox, oy);
    expect(atRecords.every((ids) => ids.length === 1), `every record was taken at one gated target: ${JSON.stringify(atRecords)}`).toBe(true);
    expect(atRecords.flat().sort(), "the acquired cells are the ones the records were taken at").toEqual([...stopped.acquiredOnCanvas].sort());
    expect(stopped.galleryPairs, "the gallery lists one target per captured position").toBe(taken);
    for (const id of stopped.acquiredOnCanvas) expect(stopped.galleryCaptions.some((text) => text.includes(id)), `gallery card for ${id}`).toBe(true);
    expect(stopped.button).toBe("Run again");
    expect(stopped.note, "the step says it was stopped by hand and how far it got").toBe(`stopped by hand — ${taken} of ${all} pairs acquired`);
    expect(stopped.hint, "the sentence stands beside the button").toBe(stopped.note);
    expect(stopped.stepDone, "an interrupted step is not done").toBe(false);
    expect(stopped.stepRan, "but it ran, so it can be run again").toBe(true);
    await page.evaluate(() => { window.__theStageCanvas.showLayer("targets", true); window.__theStageCanvas.fadeTo(0.15); });
    await take(`step8-interrupted-after-${taken}-of-${all}`, {
      step: 8, state: `acquisition interrupted by hand after ${taken} of ${all} pairs; page, bridge, Viewer and disk agree on ${taken}`,
      extra: { interrupted: outcome.interrupted },
    });

    /* Run again: the whole gated set, the interrupted run's stores replaced
       under their own names, nothing of it left over anywhere. */
    await page.locator(".panel.on button.step-run").click();
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).done, { timeout: 120_000 }).toBe(all);
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).running, { timeout: 60_000 }).toBe(false);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 30_000 });
    await expect.poll(async () => (await targetAccounting({ page, port, bridge, group })).engineSourcesPerRow, { timeout: 30_000 }).toEqual([all, all, all]);
    const again = await targetAccounting({ page, port, bridge, group });
    outcome.runAgain = again;
    expect(again.scan, "the bridge says finished, with every record").toMatchObject({ running: false, stopped: false, error: null, done: all, records: all, of: all });
    expect(again.viewerSourcesPerChannel, "the Viewer group holds every position and nothing else").toEqual([all, all, all]);
    expect(again.storesOnDisk, "one store on disk per position, the interrupted run's replaced").toBe(all);
    expect(again.acquiredOnCanvas.length).toBe(all);
    const atAll = targetsAtRecords(again.records, gated, ox, oy);
    expect(atAll.every((ids) => ids.length === 1)).toBe(true);
    expect(atAll.flat().sort(), "every gated target was taken once").toEqual(gated.map((one) => one.id).sort());
    expect(again.galleryPairs).toBe(all);
    expect(again.note, "the step says how many pairs it took").toContain(`${all} pairs`);
    expect(again.stepDone, "a completed run is done").toBe(true);
    await take("step8-run-again-after-interruption", {
      step: 8, state: `Run again after the interruption: ${all} of ${all} pairs; page, bridge, Viewer and disk agree on ${all}`,
      extra: { runAgain: outcome.runAgain },
    });
    await disconnectAndReconnect({ page, take, port });
    recorder.writeManifest({ outcome, canonicalName: "targets" });
  } finally {
    recorder.writeManifest({ outcome, finished: true });
    await bridge.stop();
  }
});

test("Steps 4 to 6: the picture's own box is the switch the focus map reads, and the field in Discover wears the picture's display", async ({ page }) => {
  /* The box in the display settings used to reach the engine directly, past
     the flag the layers above the picture read: the focus map kept drawing
     itself translucent over a picture that was no longer there. One switch,
     whichever way it is thrown -- and the map goes solid when it is off. */
  test.setTimeout(A_WHOLE_RUN);
  const port = PORT + 6;
  const bridge = await startTheBridge({ port });
  try {
    await page.goto(PAGE === "built"
      ? `http://127.0.0.1:${port}/`
      : `/?bridge=${encodeURIComponent(`http://127.0.0.1:${port}`)}`);
    await page.locator(".session-foot button.run").click();
    await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(".check-row.pending")).toHaveCount(0);
    await gotoStep(page, "Define Carrier");
    await page.locator(".carrier-type[data-type='slide']").click();
    await page.waitForTimeout(600);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(800);
    await gotoStep(page, "Focus strategy");
    await recordSlot(page, "focus-preset", "af");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(400);
    await page.locator(".panel.on button.step-run").click();
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
    await expect.poll(() => rowsOfGroup(page, "focussing").then((rows) => rows.length), { timeout: 60_000 }).toBe(1);
    await rest(1500);

    /* The map as drawn, read off the drawn layers at every field of the plan
       and a third of a pitch past each: the whole slide is on screen, so the
       map is a few pixels across and its marks fall where they fall. The
       layers are drawn over the carrier's own outline, so it is the colours
       that say how solid the surface was laid, not the alpha. */
    const coloursOverTheMap = () => page.evaluate(() => {
      const plan = window.__theStageCanvas.plan();
      const pitch = Math.abs(plan[1].x - plan[0].x) || 1;
      const drawnAt = (wx, wy) => {
        const at = window.__theStageCanvas.project(wx, wy);
        const [x, y] = Array.isArray(at) ? at : [at.x, at.y];
        return [...document.querySelectorAll("#stage-canvas canvas")]
          .map((canvas) => {
            const ctx = canvas.getContext("2d");
            if (!ctx) return null;
            const px = (canvas.width / canvas.clientWidth) || 1;
            return [...ctx.getImageData(Math.round(x * px), Math.round(y * px), 1, 1).data];
          })
          .filter((rgba) => rgba && rgba[3] > 0)
          .at(-1) ?? null;
      };
      return plan.flatMap((field) => [drawnAt(field.x, field.y), drawnAt(field.x + pitch / 3, field.y + pitch / 3)]);
    });
    const shown = () => page.evaluate(() => window.__theStageCanvas.layerShown("picture"));

    await showDisplaySettings(page);
    const showThePicture = (on) => page.evaluate((flag) => window.__theStageCanvas.showLayer("picture", flag), on);
    expect(await shown()).toBe(true);
    const seeThrough = await coloursOverTheMap();
    expect(seeThrough.filter(Boolean).length, "the map is drawn over the plan").toBeGreaterThan(0);

    await showThePicture(false);
    await expect.poll(shown, "the layers read the picture as off").toBe(false);
    await expect.poll(coloursOverTheMap, "without the picture the surface is laid solid: the map changes colour").not.toEqual(seeThrough);

    await showThePicture(true);
    await expect.poll(shown).toBe(true);
    await expect.poll(coloursOverTheMap, "and is see-through again with it").toEqual(seeThrough);

    /* ------------------------------------------------------- Steps 5 and 6
       The field in the Discover panel is the sample as the canvas shows it:
       the copy is asked for with the picture's own display -- one entry per
       channel of the overview, its window and colour as the panel keeps
       them -- and comes back drawn differently from the plain copy. */
    await gotoStep(page, "Scan the overview");
    await showTheChannel(page);
    await page.locator(".panel.on button.step-run").click();
    await expect.poll(async () => (await bridgeJson(page, port, "/api/scan")).done, { timeout: 400_000 }).toBe(9);
    await expect.poll(async () => !(await bridgeJson(page, port, "/api/scan")).running, { timeout: 400_000 }).toBe(true);
    await expect.poll(() => rowsOfGroup(page, "overview").then((rows) => rows.length), { timeout: 60_000 }).toBeGreaterThan(0);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
    await gotoStep(page, "Detect objects");
    await expect(page.locator("#tile-label")).toHaveText("1 / 9");
    const field = page.locator(".panel.on canvas[data-picture]");
    await expect.poll(() => field.getAttribute("data-picture"), "the field is asked for with a display").toContain("display=");
    const address = await field.getAttribute("data-picture");
    const asked = JSON.parse(decodeURIComponent(address.split("display=")[1]));
    const kept = await page.evaluate(() => window.__viewerPanel.snapshot().channels
      .filter((row) => row.acquisition === "overview")
      .map((row) => ({ visible: row.requested.effectiveVisible, window: [row.requested.window.low, row.requested.window.high], color: row.requested.color })));
    expect(kept.length, "the panel has channel rows for the overview").toBeGreaterThan(0);
    expect(asked.map(({ visible, window, color }) => ({ visible, window, color })), "the copy is asked for with the panel's own windows and colours").toEqual(kept);
    const [displayed, plain] = await page.evaluate(async (where) => {
      const bytes = async (url) => Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer()));
      return [await bytes(where), await bytes(where.split("?")[0])];
    }, address);
    expect(displayed.length, "the displayed copy arrives").toBeGreaterThan(1000);
    expect(displayed, "and is drawn differently from the plain copy").not.toEqual(plain);
  } finally {
    await bridge.stop();
  }
});
