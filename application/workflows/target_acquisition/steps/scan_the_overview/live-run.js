/**
 * Driving a real run for the browser tests: starting one, walking the page to
 * the step that draws it, and photographing what ends up on screen.
 *
 * The run is written by the project's own writer, through
 * `live_overview_demo.py`, so what these tests point the page at is the same
 * OME-Zarr an acquisition leaves on disk rather than something shaped like it.
 * The demo is started with `--interval 0`, which means it writes nothing until
 * it is asked to — that is what lets a test photograph a run before it has
 * begun, and decide exactly when each tile lands.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { colourSpread, fractionLit, photograph } from "./pixels.js";
import { existsSync } from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/* The writer's python: `zmart_storage` writes OME-Zarr, and the operator's
   own environment deliberately carries no zarr -- the page reads runs in the
   browser, and only this demo writes one. `PYTHON=` overrides, for a machine
   that keeps a writer-capable environment elsewhere. */
const A_PYTHON_WITH_THE_WRITER =
  "C:/ProgramData/MinicondaZMB/envs/dino3_test/python.exe";
const pythonForTheWriter = () =>
  process.env.PYTHON ?? (existsSync(A_PYTHON_WITH_THE_WRITER) ? A_PYTHON_WITH_THE_WRITER : "python");
const WRITER = path.resolve(HERE, "..", "..", "..", "..", "live_overview_demo.py");

/** Where the photographs are kept, so a failure can be looked at rather than
    only read about. */
export const SHOTS = path.resolve(HERE, "..", "test-results", "live-overview");

export const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/**
 * Start a demo run and wait until it is answering.
 *
 * @param port which port to serve it on. Two runs in one suite need two ports.
 * @param pattern `"raster"` fills the canvas position by position;
 *   `"scattered"` images five places far apart and leaves the room between them
 *   unwritten, which is what imaging a few marked targets looks like on disk.
 * @param planes how many planes deep each position is.
 *
 * @returns the run: where it is served, how to ask it for more tiles, and how to
 *   stop it. `acquire` does nothing when the environment sets
 *   `LIVE_OVERVIEW_SABOTAGE=stalled`, which is how these tests are made to fail
 *   on purpose.
 */
export async function startDemoRun({
  port, pattern = "raster", planes = 1, surveyUnderneath = false,
} = {}) {
  /* A folder of its own every time, and well away from the page's own source.
     Two reasons, and both have already bitten. The writer refuses to declare its
     images over a run that has already been imaged, which is right and would
     otherwise stop the second run of a test. And a run written inside the
     project would look to the development server like somebody editing the page,
     which reloads the browser — so the run under test would vanish, and the
     picture would be blank for a reason that has nothing to do with the
     picture. */
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-live-overview-"));
  fs.mkdirSync(SHOTS, { recursive: true });

  const writer = spawn(
    pythonForTheWriter(),
    [
      WRITER, "--folder", folder, "--port", String(port), "--interval", "0",
      "--pattern", pattern, "--planes", String(planes),
      ...(surveyUnderneath ? ["--survey-underneath"] : []),
    ],
    { stdio: "inherit" },
  );

  const state = async () => (await fetch(`http://127.0.0.1:${port}/scan`)).json();

  const until = Date.now() + 30_000;
  for (;;) {
    try {
      await state();
      break;
    } catch {
      if (Date.now() > until) throw new Error("the demo run never started serving");
      await rest(300);
    }
  }

  return {
    /* Where the acquisition being watched is served. With a survey underneath it
       there are two: the finished survey is `overview`, and the scan filling in
       over it is `targetscan`. */
    store: `http://127.0.0.1:${port}/${surveyUnderneath ? "targetscan" : "overview"}.ome.zarr`,
    survey: surveyUnderneath ? `http://127.0.0.1:${port}/overview.ome.zarr` : null,
    folder,
    state,
    async acquire(count) {
      if ((process.env.LIVE_OVERVIEW_SABOTAGE ?? "") === "stalled") return;
      for (let i = 0; i < count; i++) {
        await fetch(`http://127.0.0.1:${port}/scan/next`, { method: "POST" });
      }
    },
    stop() { writer.kill(); },
  };
}

/** Everything the run needs before the scan step can be stood on. */
export async function walkToTheScan(page) {
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();

  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);

  /* Each step is walked the way an operator walks it. A recording comes first
     wherever one is asked for: the ways of making tilesets are only offered
     once the microscope state they would be taken with has been read, and the
     focus step is the same. */
  const record = async (hostId, name) => {
    const bar = page.locator(`#${hostId} .setting-box.open`);
    // a slot whose reading names itself has no field to name it in
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  // Standing on the carrier step settles it; the tilesets need a grid.
  await gotoStep("Define Carrier");
  await page.waitForTimeout(200);
  await gotoStep("Overview scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(300);

  /* The focus strategy wants a reading, a map to lay points in, and the points
     themselves before it will run. One to a tileset is enough here — the run
     below is about what the scan draws, not about how well the plane fits. */
  await gotoStep("Focus strategy");
  await record("focus-preset", "af");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await page.locator(".panel.on button.step-run").click();
  await page.waitForTimeout(1600);

  await gotoStep("Scan the overview");

  /* Everything measured after this walk is about the acquired picture, and the
     plan draws on the stage canvas *above* it — pale ground, field outlines, a
     grid glyph — which would light every photograph before a single tile has
     landed. So the stage canvas is switched off here, the way a microscopist
     turns one channel off to look at another: the picture underneath keeps
     drawing exactly as it would with the plan over it, and the photographs
     measure the picture alone. */
  await page.addStyleTag({
    content: ".stagecv { visibility: hidden !important; }",
  });
}

/**
 * Watch the overview for a few seconds and keep the fullest photograph of it.
 *
 * A single photograph is not a fair measure of how much has been imaged, because
 * reading the run again means fetching every piece of image in view, and while
 * that is in flight the picture is honestly half-drawn. Waiting for it to hold
 * still does not help either: a reload that takes longer than the gap between
 * two photographs looks perfectly still.
 *
 * What saves it is that the fault only ever goes one way. A picture in the
 * middle of being read again can show *less* than has been written, never more —
 * there is nothing on the screen that was not fetched from the run. So watching
 * for a few seconds and keeping the fullest moment gives the honest answer to
 * "how much of the overview exists by now", and it cannot flatter a viewer that
 * is drawing nothing, because the fullest of several blank photographs is still
 * blank.
 *
 * @param share how much of the canvas to look at: the middle half by default,
 *   because the page draws its own labels over the corners, or all of it when
 *   *where* something was drawn is the question.
 */
export async function fullestOver(page, name, { seconds = 6, share = 0.5 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const pixels = await photograph(page, "#overview-canvas", share);
    const lit = fractionLit(pixels);
    if (!best || lit > best.lit) {
      best = { lit, ...colourSpread(pixels), pixels };
      best.shot = await page.locator("#overview-canvas").screenshot();
    }
    await rest(700);
  } while (Date.now() < until);
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), best.shot);
  delete best.shot;
  return best;
}

/**
 * Wait for the picture to settle, then photograph it once.
 *
 * {@link fullestOver} keeps the fullest of several photographs, which is right
 * when the question is how much has been imaged: a picture half way through
 * being read can only show less than has been written. It is exactly wrong when
 * something bright has been drawn *underneath* the image, because then the
 * emptiest moment is the brightest one and "fullest" would pick the frame with
 * the least picture in it. When the question is what covers what, waiting and
 * then looking once is the honest measurement.
 */
export async function settledPhotograph(page, name, { seconds = 12, share = 1 } = {}) {
  await rest(seconds * 1000);
  const pixels = await photograph(page, "#overview-canvas", share);
  fs.writeFileSync(
    path.join(SHOTS, `${name}.png`),
    await page.locator("#overview-canvas").screenshot(),
  );
  return { lit: fractionLit(pixels), ...colourSpread(pixels), pixels };
}

/** A short line of numbers, for the summary a passing test prints. */
export const said = (measured) => measured.map((m) => m.lit.toFixed(3)).join(" -> ");
