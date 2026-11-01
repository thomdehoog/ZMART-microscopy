/** Source arrival must not replace the view chosen by the operator. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { operateTheInstrument, rest, setAcquisitionShown, startTheBridge } from
  "../../testing/live-bridge.ts";
import type { EngineViewer } from "../../canvas/engines/neuroglancer-under/viewer.ts";

declare global {
  interface Window {
    /** Test-only: the picture as the first overview field left it, to check later fields keep the same one. */
    __pictureBeforeSourceGrowth?: EngineViewer | null;
  }
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "test-results", "step-five-kidney");
const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8813);
const A_WHOLE_RUN = 900_000;

let bridge: Awaited<ReturnType<typeof startTheBridge>> | null = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

async function walkToScan(page: Page) {
  const gotoStep = (name: string) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host: string, name: string) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  await page.goto(`/?bridge=${encodeURIComponent(`http://127.0.0.1:${PORT}`)}`);
  await page.locator(".session-foot button.run").click();
  await page.locator('.step.done:has-text("Connect")').waitFor({ timeout: 60_000 });

  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='slide']").click();
  await page.waitForTimeout(600);
  await gotoStep("Overview scan area");
  /* As an operator does: the job in the vendor's software first, then the
     page records it. What another spec left the instrument on is not this
     one's to inherit. */
  operateTheInstrument("choose", "Overview");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => window.__theStageCanvas!.plan().length)).toBe(9);

  await gotoStep("Focus strategy");
  operateTheInstrument("choose", "Focussing");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(400);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Run again", { timeout: 400_000 });
  await expect.poll(() => frontSourceCount(page, "focussing"), {
    timeout: 60_000,
    message: "the focusing source never opened in Smart Viewer",
  }).toBeGreaterThan(0);

  await gotoStep("Scan the overview");
  await rest(2500);
}

async function frontSourceCount(page: Page, acquisition: string) {
  return page.evaluate((prefix: string) => (window.__thePicture?.layersForMeasurement?.() ?? [])
    .filter(({ name }) => (name as string).startsWith(prefix))
    .reduce((count, row) => count + (row.sources?.length ?? 0), 0), acquisition);
}

/** How many of an acquisition's fields the viewer has published, as the
    bridge's viewer status counts them -- and whether it is caught up. Each
    channel is one picture that grows as fields land, so the page's sources
    stay one per channel however many fields there are; this is where the
    growth is counted. */
async function publishedFields(acquisition: string) {
  const status = await (await fetch(`${bridge!.at}/api/target_acquisition/viewer`)).json() as {
    publications?: Record<string, { published?: number; state?: string }>;
  };
  const one = status.publications?.[acquisition];
  return one?.state === "ready" ? one.published ?? 0 : -1;
}

async function setAcquisitionVisible(page: Page, acquisition: string, visible: boolean) {
  await setAcquisitionShown(page, acquisition, visible);
  await expect.poll(() => acquisitionVisible(page, acquisition)).toBe(visible);
}

async function acquisitionVisible(page: Page, acquisition: string) {
  return page.evaluate((prefix: string) => {
    const rows = (window.__thePicture?.layersForMeasurement?.() ?? [])
      .filter(({ name }) => (name as string).startsWith(prefix));
    return rows.length > 0 && rows.every(({ visible }) => Boolean(visible));
  }, acquisition);
}

async function stageSnapshot(page: Page, name: string) {
  return page.evaluate((label: string) => {
    const box = document.querySelector("#stage-canvas")!.getBoundingClientRect();
    const plan = window.__theStageCanvas!.plan();
    const points = [0, 4, 8].map((index) => {
      const at = plan[index];
      const projected = window.__theStageCanvas!.project(at.x, at.y);
      const point = Array.isArray(projected)
        ? { x: projected[0], y: projected[1] }
        : projected;
      return {
        index,
        carrierLocalUm: { x: at.x, y: at.y },
        screenPx: { x: box.left + point.x, y: box.top + point.y },
      };
    });
    return {
      name: label,
      view: window.__theStageCanvas!.view(),
      canvas: {
        left: box.left, top: box.top, width: box.width, height: box.height,
      },
      points,
    };
  }, name);
}

/** Where the stage stood at one moment: the view, the canvas box, and three plan tiles on screen. */
type Snapshot = Awaited<ReturnType<typeof stageSnapshot>>;

function projectionDrift(before: Snapshot, after: Snapshot) {
  return Math.max(...before.points.map((point, index) => {
    const next = after.points[index];
    return Math.hypot(point.screenPx.x - next.screenPx.x, point.screenPx.y - next.screenPx.y);
  }));
}

function expectSameView(before: Snapshot, after: Snapshot, message: string) {
  expect(after.canvas, `${message}: the canvas box changed`).toEqual(before.canvas);
  expect(after.view!.zoom, `${message}: zoom changed`).toBeCloseTo(before.view!.zoom, 9);
  expect(after.view!.centre.x, `${message}: x centre changed`).toBeCloseTo(before.view!.centre.x, 6);
  expect(after.view!.centre.y, `${message}: y centre changed`).toBeCloseTo(before.view!.centre.y, 6);
  expect(projectionDrift(before, after), `${message}: plan projections drifted`).toBeLessThan(0.25);
}

async function absolutePlan(page: Page) {
  return page.evaluate(() => {
    const [ox, oy] = window.__theStageCanvas!.carrierOriginUm();
    return window.__theStageCanvas!.plan().map(({ x, y }) => ({ x: x + ox, y: y + oy, z: 0 }));
  });
}

test("first and later overview sources preserve pan, zoom, and whole-plate Fit", async ({ page }) => {
  test.setTimeout(A_WHOLE_RUN);
  const browserErrors: string[] = [];
  const sourceFailures: { url: string; error?: string | null; status?: number }[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  const engineCancellations: { url: string; error: string }[] = [];
  page.on("requestfailed", (request) => {
    if (!request.url().includes("/data/")) return;
    const error = request.failure()?.errorText ?? null;
    /* The engine cancels a chunk fetch it no longer needs the moment a
       source's placement is settled; the browser reports that as ERR_ABORTED.
       Those are counted apart from a request the server refused or lost. */
    if (error === "net::ERR_ABORTED" && /\/c\//.test(request.url())) {
      engineCancellations.push({ url: request.url(), error });
      return;
    }
    sourceFailures.push({ url: request.url(), error });
  });
  /* A picture that grows field by field answers a chunk not written yet with
     404, which the engine draws as empty, and a chunk being rewritten just
     now with 503, which the engine asks again. Those are the store speaking,
     counted apart; anything else -- metadata, another status -- is a loss. */
  const growingChunkAnswers: { url: string; status: number }[] = [];
  page.on("response", (response) => {
    if (!response.url().includes("/data/") || response.status() < 400) return;
    const answer = { url: response.url(), status: response.status() };
    if (/\/c\//.test(response.url()) && (answer.status === 404 || answer.status === 503)) {
      growingChunkAnswers.push(answer);
      return;
    }
    sourceFailures.push(answer);
  });

  await walkToScan(page);
  /* The fields below are imaged through the harness, not the page's Start,
     and the harness sends positions only -- the page's scan would apply the
     overview recording first. The focus map left the instrument on its
     focussing job, so the overview job is chosen again here. */
  operateTheInstrument("choose", "Overview");
  const positions = await absolutePlan(page);

  await page.locator("#carrier-btn").click();
  const fittedBeforeHand = await stageSnapshot(page, "fit before the operator moves");
  const box = (await page.locator("#stage-canvas").boundingBox())!;
  expect(box).not.toBeNull();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.5);
  await page.mouse.wheel(0, -650);
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.57, box.y + box.height * 0.56, { steps: 8 });
  await page.mouse.up();
  await rest(500);
  const chosen = await stageSnapshot(page, "operator pan and zoom before acquisition");
  expect(projectionDrift(fittedBeforeHand, chosen), "the operator gesture changed the view")
    .toBeGreaterThan(1);
  await setAcquisitionVisible(page, "focussing", false);

  await bridge!.image(positions.slice(0, 1));
  await expect.poll(() => frontSourceCount(page, "overview"), {
    timeout: 60_000,
    message: "the first overview source never opened in Smart Viewer",
  }).toBe(3);
  await rest(2000);
  const afterFirst = await stageSnapshot(page, "after source 1 of 9");
  expectSameView(chosen, afterFirst, "first source arrival");
  expect(await acquisitionVisible(page, "focussing"),
    "first source arrival preserves requested focussing visibility").toBe(false);
  // The first overview field adds a new acquisition beside focussing. From
  // this point onward the acquisition shape is stable and fields 2–9 must be
  // appended to this exact Viewer instance.
  await page.evaluate(() => { window.__pictureBeforeSourceGrowth = window.__thePicture; });

  // The deterministic bridge call declares the complete acquisition each
  // time, so later checkpoints repeat the positions already present and add
  // the new ones. This is the same cumulative contract used by the live tile
  // arrival checks; sending only the delta would deliberately replace the
  // acquisition's record with that delta.
  await bridge!.image(positions.slice(0, 8));
  await expect.poll(() => publishedFields("overview"), {
    timeout: 60_000,
    message: "later overview fields were never published",
  }).toBe(8);
  expect(await frontSourceCount(page, "overview"),
    "the later fields grow the same three channel pictures").toBe(3);
  await rest(2000);
  const afterLater = await stageSnapshot(page, "after source 8 of 9");
  expectSameView(chosen, afterLater, "later source arrival");
  expect(await acquisitionVisible(page, "focussing"),
    "later source arrival preserves requested focussing visibility").toBe(false);
  expect(await page.evaluate(() => window.__thePicture === window.__pictureBeforeSourceGrowth),
    "later overview sources keep the same Viewer instance").toBe(true);

  await page.locator("#carrier-btn").click();
  await rest(500);
  const wholePlate = await stageSnapshot(page, "whole-plate Fit before source 9");
  await bridge!.image(positions);
  await expect.poll(() => publishedFields("overview"), {
    timeout: 60_000,
    message: "the final overview field was never published",
  }).toBe(9);
  expect(await frontSourceCount(page, "overview"),
    "the final field grows the same three channel pictures").toBe(3);
  await rest(2000);
  const afterFitArrival = await stageSnapshot(page, "whole-plate Fit after source 9");
  expectSameView(wholePlate, afterFitArrival, "source arrival after Fit");
  expect(await page.evaluate(() => window.__thePicture === window.__pictureBeforeSourceGrowth),
    "the final overview source keeps the same Viewer instance").toBe(true);
  expect(browserErrors, "source replacement raised a browser error").toEqual([]);
  expect(sourceFailures, "stable source growth aborted or lost a Viewer request").toEqual([]);

  fs.writeFileSync(path.join(SHOTS, "view-preservation.json"), JSON.stringify({
    fittedBeforeHand, chosen, afterFirst, afterLater, wholePlate, afterFitArrival,
    driftPx: {
      first: projectionDrift(chosen, afterFirst),
      later: projectionDrift(chosen, afterLater),
      fit: projectionDrift(wholePlate, afterFitArrival),
    },
    requestedVisibility: { focussing: false, overview: true },
    browserErrors, sourceFailures, engineCancellations, growingChunkAnswers,
  }, null, 2));
});
