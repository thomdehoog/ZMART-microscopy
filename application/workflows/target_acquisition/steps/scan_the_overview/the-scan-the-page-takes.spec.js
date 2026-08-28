/**
 * Does a scan the page itself takes reach the screen?
 *
 * Everything between a captured plane and a drawn tile is real here: the mock
 * microscope through the controller, the bridge writing OME-TIFFs and making
 * one small JPEG per field beside them, the bridge serving those, and the page
 * opening them with a drawing engine. Nothing is stood in for and nothing is
 * routed around.
 *
 * The question is about pixels, so pixels are what is measured: the picture is
 * photographed after one field has landed and again after four, and what has to
 * be true is that *more of the screen is lit*. Not that a loader resolved, not
 * that a counter counted — a viewer that reports itself perfectly opened while
 * drawing nothing has happened in this project more than once, and every check
 * of that kind passed while it did.
 *
 * ## Why it does not start from an empty picture
 *
 * There is no note to open until a field has landed: the bridge writes
 * `tiles.json` when it makes the first picture, and asking for it before then
 * is honestly a 404. So the first photograph is of one field, and what the
 * later ones have to show is that the note was read *again* — which is the
 * join this test exists to check, because nothing on disk announces a new
 * field and a page that only ever read the note once would stop at one tile.
 *
 * ## Making sure it can fail
 *
 * A test that cannot go red is worse than no test. Set
 * `LIVE_BRIDGE_SABOTAGE=stalled` and no field is ever imaged: the page still
 * opens, the canvas is still there, and the picture stays black. The
 * assertions below then fail, which is the proof that they measure the picture
 * and not the plumbing around it.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { rest, startTheBridge, theFirst, throughToAPlan } from "./live-bridge.js";
import { fractionNear, photograph } from "./pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.resolve(HERE, "..", "test-results", "the-scan-the-page-takes");

const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8791);

/** A scan of a few fields is a run, and a run is not quick. */
const A_RUN_TAKES_A_WHILE = 180_000;

let bridge = null;

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

/**
 * How many pixels of the box are covered by fields.
 *
 * Measured against the photograph's own corner rather than a colour written
 * down here: the engine paints its background the page's own screen colour,
 * and what that is belongs to the stylesheet. Anything unlike the corner is a
 * field; everything else is room the scan has not reached.
 *
 * Covered rather than lit, because these fields are pictures of the same
 * tissue: twelve of them are no brighter and no more colourful than three,
 * only larger. Area is the thing that grows.
 *
 * Counted in pixels rather than as a fraction because the numbers are small
 * and deserve to be legible: a field is a millimetre of a plate a hundred
 * millimetres across, so a whole scan of them covers a percent of the canvas
 * and a fraction would read as a rounding error.
 */
function coveredPixels(pixels) {
  const corner = [pixels.data[0], pixels.data[1], pixels.data[2]];
  const of = pixels.width * pixels.height;
  return Math.round((1 - fractionNear(pixels, corner)) * of);
}

/**
 * Watch the picture for a few seconds and keep the fullest photograph of it.
 *
 * A single photograph is not a fair measure: reading the note again means
 * fetching the pictures in view, and while that is in flight the picture is
 * honestly half-drawn. The fault only goes one way -- a picture mid-fetch can
 * show less than has been imaged, never more -- so the fullest moment of
 * several is the honest answer, and it cannot flatter a viewer drawing
 * nothing, because the fullest of several blank photographs is still blank.
 */
async function fullestOf(page, name, { seconds = 8 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const covered = coveredPixels(await photograph(page, "#picture-host", 1));
    if (!best || covered > best.covered) {
      best = { covered, shot: await page.locator("#picture-host").screenshot() };
    }
    await rest(700);
  } while (Date.now() < until);
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), best.shot);
  return { covered: best.covered };
}

test("the fields a scan takes appear on the canvas as they land", async ({ page }) => {
  test.setTimeout(A_RUN_TAKES_A_WHILE);

  await page.goto(`/?backend=pretend&picture=${encodeURIComponent(bridge.pictures)}`);
  const plan = await throughToAPlan(page);
  const places = theFirst(12, plan);
  expect(places.length, "the plan has somewhere to scan").toBe(12);

  await bridge.image(places.slice(0, 3));
  await page.waitForFunction(() => !!window.__thePicture, null, { timeout: 30_000 });

  const three = await fullestOf(page, "1-three-fields");
  expect(three.covered, `nothing was drawn for the first fields: ${three.covered}px`)
    .toBeGreaterThan(20);

  // Nine more places on the sample, imaged while the page is watching.
  await bridge.image(places.slice(3));
  const twelve = await fullestOf(page, "2-twelve-fields", { seconds: 14 });

  const grew = `${three.covered}px -> ${twelve.covered}px`;
  expect(twelve.covered, `the picture did not grow as fields landed: ${grew}`)
    .toBeGreaterThan(three.covered * 2);
  console.log(`covered: ${grew}`);
});

test("the pixels stay in the TIFFs; only a copy is drawn", async () => {
  test.setTimeout(A_RUN_TAKES_A_WHILE);
  await bridge.image([{ x: 0, y: 0, z: 5_000 }]);
  // Looking is what makes the copies: nothing is made for a scan nobody opens.
  await fetch(`${bridge.pictures}/tiles.json`);

  const data = path.join(bridge.folder, "overview", "data");
  const view = path.join(bridge.folder, "overview", "view");

  /* Two folders, and the acquisition is in only one of them. A display copy is
     lossy on purpose and nothing is ever read back out of it, so the run's own
     pixels must stay where the driver wrote them. */
  expect(fs.readdirSync(data).some((name) => name.endsWith(".ome.tiff"))).toBe(true);
  expect(fs.readdirSync(view).some((name) => name.endsWith(".jpg"))).toBe(true);
  expect(fs.readdirSync(view).some((name) => name.endsWith(".tiff"))).toBe(false);
  expect(fs.existsSync(path.join(view, "tiles.json"))).toBe(true);
});
