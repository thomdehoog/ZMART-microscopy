/**
 * Two ways the commit gate can be right about the wrong thing.
 *
 * The test beside this one — `commit-gates-the-picture-in-production.spec.mjs` —
 * asks the question this whole design rests on: a position is written in full,
 * every file of it is on disk, and nobody has published it, so is it on the
 * operator's screen? The answer must be no. That test watches two tiles at one
 * moment in time, and it passes.
 *
 * A run of two tiles at one moment is, unfortunately, the one shape of run in
 * which two quite different mistakes are both invisible. This file writes the two
 * smallest runs that can see them. Each is a real acquisition shape — a row of
 * three tiles, and a position imaged twice — and in each case the pixels that must
 * not be shown are genuinely sitting in the very picture the browser is reading.
 *
 * ## The first mistake: a stop on the tile slider is not a tile
 *
 * The publisher writes two run-wide pictures. The seamless one crops each tile so
 * that no piece of specimen appears twice, and it is the one an operator
 * navigates by. The other keeps every pixel every tile recorded, overlaps
 * included, so that somebody can look at whether the microscope agreed with itself
 * along a seam. Two tiles that overlap hold two genuinely different measurements
 * of the same place, so that second picture gives each tile a *stop* on a slider
 * and the operator steps between them.
 *
 * There is deliberately not one stop per position. On a real run that would be a
 * slider with five thousand stops, almost all of them empty wherever the operator
 * happens to be looking. Instead the stops are shared out like the squares of a
 * chessboard: tiles far enough apart that they cannot possibly overlap are given
 * the same stop. With this project's frame size and overlap there are four stops
 * in total, however large the run grows.
 *
 * Sharing is the right arrangement and it has a consequence that is easy to miss.
 * **A stop names a scattering of tiles across the whole mosaic, not one tile.** In
 * a row of three, the first and the third tile share a stop. A server that worked
 * out which position a piece of that picture belonged to from its stop alone would
 * call the third tile's pixels the first tile's — and would therefore hand them
 * over the moment the first tile was committed, with the third still unpublished.
 *
 * A row of two tiles cannot show this, because in a row of two no stop is ever
 * shared. That is why this test images three.
 *
 * ## The second mistake: a position is not published all at once
 *
 * A position is committed one moment in time at a time. Once its first moment is
 * published, the question "has position A been published?" is answered yes for
 * ever after — including for a second moment that was written a second ago and
 * that nobody has committed. A gate that asks only about the position hands that
 * second moment straight to the screen, which is exactly what the commit exists
 * to prevent, and a run holding a single moment can never notice.
 *
 * ## Both tests are shaped like the one they came from
 *
 * Each makes its claim in the same three steps, and the middle step always makes
 * **two** claims at once rather than one:
 *
 * ```
 *   the thing under test is not written yet   ->  the rest of the run is drawn.
 *   it is written, and not committed          ->  the rest of the run is still
 *                                                 drawn, just as brightly — and
 *                                                 the new thing is not.
 *   it is committed                           ->  now it is drawn too.
 * ```
 *
 * The second half of the middle step is not decoration. "It is not drawn" is
 * satisfied perfectly by a completely black screen: by a page that never opened,
 * an engine that never started, a run that was never served. Insisting in the same
 * breath that everything else is still on screen, and still as bright as it was, is
 * what stops a black screen passing for a working gate.
 *
 * `check-the-production-test-can-fail.mjs` beside this file runs both of these
 * sequences deliberately broken, to show that each claim can be made to go red.
 */

import { spawn } from "node:child_process";
import { createServer } from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import {
  fractionLit, readPng,
} from "../../../../workflows/target_acquisition/webapp-ui/tests/pixels.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..", "..", "..");

/** When one of these sequences is run deliberately broken. See the note above. */
const SABOTAGE = process.env.ZMART_SABOTAGE ?? "";

/**
 * Where the photographs are kept.
 *
 * A deliberately broken run files its photographs somewhere else, and that is not
 * tidiness. The photographs of an honest run are the evidence that the test proved
 * what it claims, and a broken run producing a black screen would otherwise
 * overwrite them — leaving the project holding a picture of nothing under a name
 * that says the test passed.
 */
const SHOTS = SABOTAGE
  ? path.join(HERE, "photographs", `deliberately-broken-${SABOTAGE}`)
  : path.join(HERE, "photographs");

/** How lit a rectangle has to be before that counts as the tile being drawn. */
const DRAWN = 0.5;

/**
 * How lit a rectangle may be while still counting as nothing drawn there.
 *
 * Not zero, because a browser drawing in software leaves a few stray pixels along
 * an edge, and insisting on a perfect nought would make the test fail for reasons
 * that have nothing to do with commits. Two per cent is a hundred times less than
 * a tile genuinely on screen.
 */
const NOT_DRAWN = 0.02;

/** The box on the page the viewer draws into, in page pixels. */
const PICTURE = { x: 0, y: 0, width: 1024, height: 512 };

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** Find a port nothing is listening on, so two runs of this test cannot collide. */
function aFreePort() {
  return new Promise((done, fail) => {
    const probe = createServer();
    probe.on("error", fail);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => done(port));
    });
  });
}

/**
 * Start a run of the shape asked for, and its server, and wait until it answers.
 *
 * The run is written into a folder of its own outside the project, so that two
 * runs of this test cannot meet each other's leftovers and so that nothing the
 * test writes looks to anything else like somebody editing the project.
 *
 * `tiles` is how many positions sit side by side in the row, and `moments` is how
 * many times each of them is imaged. Everything else about the run — the frame
 * size, the overlap, the storage plan — comes from the project's own profile, as
 * it does for every test in this folder.
 */
async function startTheRun({ tiles, moments }) {
  const port = await aFreePort();
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-production-gate-"));
  const server = spawn(
    process.env.PYTHON ?? "python",
    [
      "-m", "zmart_live.tests.browser.production.production_run",
      "--folder", folder, "--port", String(port),
      "--tiles-in-a-row", String(tiles), "--moments", String(moments),
    ],
    { cwd: REPO, stdio: "inherit" },
  );

  const address = `http://127.0.0.1:${port}`;
  const state = async () => (await fetch(`${address}/control/state`)).json();
  const tell = async (what, position, moment) => {
    const asks = new URLSearchParams();
    if (position) asks.set("position", position);
    if (moment !== undefined) asks.set("moment", String(moment));
    const answer = await fetch(
      `${address}/control/${what}${asks.size ? `?${asks}` : ""}`, { method: "POST" },
    );
    if (!answer.ok) {
      throw new Error(
        `the run refused "${what} ${position ?? ""} ${moment ?? ""}": ` +
        `${await answer.text()}`,
      );
    }
    return answer.json();
  };

  const until = Date.now() + 60_000;
  for (;;) {
    try {
      await state();
      break;
    } catch {
      if (Date.now() > until) throw new Error("the run never started answering");
      await rest(300);
    }
  }

  return {
    address,
    /** The run-wide picture that crops the overlaps away. */
    seamless: `${address}/views/overview-seamless.ome.zarr/0/|zarr3:`,
    /** The run-wide picture that keeps every pixel every tile recorded. */
    everyOverlappingPixel: `${address}/views/overview-raw.zarr/0/|zarr3:`,
    state,
    /** The whole production path for one moment of one position, ending in a commit. */
    publish: (position, moment) => tell("publish", position, moment),
    /** All of that sequence apart from the commit. */
    writeWithoutCommitting: (position, moment) =>
      tell("write-everything-except-the-commit", position, moment),
    /** Publish something already on disk, changing no image at all. */
    commit: (position, moment) => tell("commit", position, moment),
    forgetWhatWasAsked: () => tell("forget-what-was-asked"),
    refuseEverything: () => tell("refuse-everything"),
    stop() { server.kill(); },
  };
}

/**
 * Open the page on one store and wait until the drawing engine is up.
 *
 * Anything the page complains about is collected, apart from the one complaint
 * these tests are built on: a browser writes a line into its console whenever a
 * request comes back "not found", and this server answers exactly that for every
 * piece nobody has published. Those lines are the machinery working rather than a
 * fault — a viewer is meant to take "there is nothing here" as empty ground and
 * carry on drawing what it does have. Everything else is treated as a failure,
 * because a page that is quietly throwing is a page whose black screen would have
 * nothing to do with commits.
 */
async function openThePage(page, run, store) {
  const complaints = [];
  const refusalsTheBrowserNoticed = [];
  const note = (text, where) => {
    if (where.startsWith(`${run.address}/views/`)) refusalsTheBrowserNoticed.push(where);
    else complaints.push(`${text} (${where || "nowhere in particular"})`);
  };
  page.on("console", (message) => {
    if (message.type() === "error") note(message.text(), message.location()?.url ?? "");
  });
  page.on("pageerror", (trouble) => note(String(trouble), ""));

  await page.goto(`${run.address}/page/index.html?store=${encodeURIComponent(store)}`);
  await page.waitForFunction(
    () => window.probe?.ready || window.probe?.failed, null, { timeout: 60_000 },
  );
  const failed = await page.evaluate(() => window.probe.failed);
  expect(failed, `the viewer did not open: ${failed}`).toBeFalsy();
  return { complaints, refusalsTheBrowserNoticed };
}

/**
 * Tell the engine which axes go on screen, where to look, and how far out.
 *
 * The run-wide pictures the publisher writes are plain Zarr arrays: no voxel size,
 * no units, no axis names. Turning a run into an image a viewer can interpret is
 * the job of `zmart_live/scene.py` and is not what these tests are checking, so
 * the page's own aiming finds nothing to read and the test says where to look
 * instead.
 *
 * The last three axes of either picture are the ones that say where in the
 * specimen something is, and only those belong on screen — widest first, so that
 * the mosaic's width runs across the window rather than time being drawn against
 * depth. `sliders` then sets any of the remaining axes that matter: which moment
 * in time, and — for the picture that keeps every overlapping pixel — which stop
 * on the tile slider. Those are given as positions counted from the start of the
 * axis, and a half is added so that each lands squarely in the middle of the step
 * asked for rather than on the boundary between two.
 */
async function aimAtTheWholeMosaic(page, { mosaic, perPixel, sliders = {} }) {
  return page.evaluate(({ mosaic, perPixel, sliders }) => {
    const viewer = window.probe.viewer;
    const navigation = viewer.navigationState;
    const space = navigation.position.coordinateSpace.value;
    const onScreen = space.names.slice(-3).reverse();
    navigation.pose.displayDimensions.restoreState(onScreen);

    const info = navigation.displayDimensionRenderInfo.value;
    const across = info.displayDimensionIndices[0];
    const down = info.displayDimensionIndices[1];
    const where = Float32Array.from(navigation.position.value);
    where[across] = mosaic.across / 2;
    where[down] = mosaic.down / 2;
    for (const [axis, step] of Object.entries(sliders)) {
      where[Number(axis)] = step + 0.5;
    }
    navigation.position.value = where;
    // The engine's own idea of zoom is "how many of the smallest voxel on screen
    // fall in one browser pixel". Converting from specimen pixels is the line
    // below; with an image that states no voxel size, every scale is one and the
    // two numbers are the same thing.
    navigation.zoomFactor.value =
      perPixel * space.scales[across] / info.canonicalVoxelPhysicalSize;
    return {
      onScreen, across, down, sliders,
      zoom: navigation.zoomFactor.value,
      at: Array.from(navigation.position.value),
    };
  }, { mosaic, perPixel, sliders });
}

/**
 * Watch the picture for a few seconds and keep the fullest reading of each place.
 *
 * Keeping the fullest moment is fair in both directions at once, which is the
 * reason for it. A picture caught partway through being fetched can only show
 * *less* than has been served, never more, so the fullest reading gives an
 * already-published tile its best honest showing — and it cannot flatter an
 * unpublished one, because if that tile were ever drawn at all, one of these
 * photographs would catch it.
 *
 * A photograph of the whole picture is saved alongside, under the name given, so
 * that a person looking into a failure can see what the test saw.
 */
async function fullestOverEachPlace(page, places, name, { seconds = 8 } = {}) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const until = Date.now() + seconds * 1000;
  const fullest = Object.fromEntries(Object.keys(places).map((where) => [where, 0]));
  do {
    for (const [where, box] of Object.entries(places)) {
      const lit = fractionLit(readPng(await page.screenshot({ clip: box })));
      if (lit > fullest[where]) fullest[where] = lit;
    }
    await rest(500);
  } while (Date.now() < until);
  fs.writeFileSync(
    path.join(SHOTS, `${name}.png`), await page.screenshot({ clip: PICTURE }),
  );
  return fullest;
}

/** A short line of numbers, for the summary each test prints as it goes. */
const said = (step, lit) =>
  `${step}: ` + Object.entries(lit)
    .map(([where, much]) => `${where} ${much.toFixed(3)}`).join(", ");

/* ------------------------------------------------------------------------- *
 *  A row of three tiles, and the picture that keeps every overlapping pixel
 * ------------------------------------------------------------------------- */

/**
 * How large that picture is, in specimen pixels, for a row of three tiles.
 *
 * This picture keeps each tile's whole frame rather than cropping it, so the row
 * reaches from the left edge of the first frame to the right edge of the third:
 * two stage steps of 1024 pixels, plus one whole frame of 1152, is 3200 across.
 * One frame is 1152 down.
 */
const THREE_TILES = { across: 3200, down: 1152 };

/**
 * Three and an eighth specimen pixels per screen pixel puts all 3200 of them
 * across the 1024-pixel box exactly, so the row fills the width of the picture and
 * each tile always lands in the same place.
 */
const THREE_TILES_PER_SCREEN_PIXEL = 3200 / 1024;

/**
 * Which stop on the tile slider to look at, and which axis carries it.
 *
 * This picture has six axes — the stop on the tile slider, then which moment,
 * which colour, and the three that say where in the specimen something is — so the
 * stop is the first of them. Stop 0 is the one the first and third tiles of the row
 * share, which is the whole reason this run has three tiles in it.
 */
const THE_SHARED_STOP = 0;
const TILE_SLIDER_AXIS = 0;

/**
 * The two rectangles this picture is measured in, in page pixels.
 *
 * At three and an eighth specimen pixels per screen pixel, the first tile occupies
 * the leftmost 369 pixels of the picture and the third occupies the rightmost 369.
 * The 287 pixels between them are ground that no tile at this stop photographed,
 * and they stay black throughout. Each rectangle is inset from its tile by a
 * comfortable margin so that the edge of a frame cannot land inside a measurement
 * and blur what it means.
 */
const WHERE_THE_FIRST_TILE_IS = { x: 40, y: 110, width: 280, height: 280 };
const WHERE_THE_THIRD_TILE_IS = { x: 700, y: 110, width: 280, height: 280 };

test("a tile sharing a slider stop with a published one is drawn only once it is "
     + "committed", async ({ page }) => {
  const run = await startTheRun({ tiles: 3, moments: 1 });
  const places = { A: WHERE_THE_FIRST_TILE_IS, C: WHERE_THE_THIRD_TILE_IS };

  try {
    // -- the first two tiles are imaged and published, all the way through ----
    await run.publish("A");
    await run.publish("B");

    const { complaints } = await openThePage(page, run, run.everyOverlappingPixel);
    console.log("the viewer is aimed:", JSON.stringify(
      await aimAtTheWholeMosaic(page, {
        mosaic: THREE_TILES,
        perPixel: THREE_TILES_PER_SCREEN_PIXEL,
        sliders: { [TILE_SLIDER_AXIS]: THE_SHARED_STOP },
      }),
    ));

    const first = await fullestOverEachPlace(page, places,
      "4-three-tiles-with-C-not-yet-imaged", { seconds: 8 });
    console.log(said("A and B published, C not imaged", first));
    expect(first.A, "A is published and sits at this stop, so A is drawn")
      .toBeGreaterThan(DRAWN);
    expect(first.C, "C has not been imaged at all, so nothing is drawn there")
      .toBeLessThan(NOT_DRAWN);

    // -- the third tile is imaged, and the sequence stops short of the commit --
    //
    // C's whole frame is now genuinely sitting in this picture, at the very stop
    // the page is looking at, right beside A's. The only thing between C's pixels
    // and the screen is that nobody has published C.
    await run.writeWithoutCommitting("C");
    if (SABOTAGE === "commit-c-early") {
      await run.commit("C");
      console.log("SABOTAGE: C was committed during the step that expects it hidden");
    }
    if (SABOTAGE === "black-screen-with-three-tiles") {
      await run.refuseEverything();
      console.log("SABOTAGE: the server now refuses everything, so the screen goes black");
    }
    await run.forgetWhatWasAsked();
    // The engine has no reason of its own to ask for anything a second time, so it
    // is sent back to the store. Without this the step would prove nothing: "C was
    // asked for and refused" and "C was never asked for" look identical on screen.
    const readers = await page.evaluate(() => window.probe.refresh());
    expect(readers, "the engine really was sent back to the store").toBeGreaterThan(0);

    const middle = await fullestOverEachPlace(page, places,
      "5-three-tiles-with-C-written-but-not-committed", { seconds: 10 });
    console.log(said("C written, not committed     ", middle));

    const asked = (await run.state()).asked;
    console.log("pieces of image asked for  ", JSON.stringify(asked));

    // Both halves of the claim, together. The first is what stops a black screen
    // passing the second.
    expect(middle.A,
           "A was published and is still published, so it is still drawn — and it "
           + "is still as bright as it was, which is what stops a blank screen "
           + `passing the next line: ${said("now", middle)} against `
           + `${said("before", first)}`)
      .toBeGreaterThan(DRAWN);
    expect(middle.A,
           "nothing about A changed, so nothing about how much of it is drawn should")
      .toBeGreaterThan(first.A - 0.05);
    expect(middle.C,
           "C's frame is complete and is sitting at the same stop on the tile "
           + "slider as A, which is published — but nobody has published C, so C's "
           + "pixels must not be on screen. Sharing a stop is not sharing a "
           + "publication.")
      .toBeLessThan(NOT_DRAWN);

    /* And the counters, which say the claim above was answered rather than never
       asked. This has to be a claim about C in particular: a server that mistook
       C's pieces for A's would count them under A, hand them over, and report
       that C had never been asked for at all. */
    expect(asked.C.served + asked.C.refused,
           "the engine really did go and ask for C's pieces, and the server knew "
           + "they were C's").toBeGreaterThan(0);
    expect(asked.C.served,
           "and not one piece of C should have been handed over")
      .toBe(0);

    // -- and now the third tile is committed, and nothing else changes --------
    if (SABOTAGE !== "commit-c-early") await run.commit("C");
    await run.forgetWhatWasAsked();
    await page.evaluate(() => window.probe.refresh());

    const both = await fullestOverEachPlace(page, places,
      "6-three-tiles-with-C-committed", { seconds: 10 });
    console.log(said("C committed                  ", both));
    const askedAtTheEnd = (await run.state()).asked;
    console.log("pieces of image asked for  ", JSON.stringify(askedAtTheEnd));

    expect(both.A, "A is still drawn").toBeGreaterThan(DRAWN);
    expect(both.C, "C has been committed, so now C is drawn too").toBeGreaterThan(DRAWN);
    expect(askedAtTheEnd.C.served, "C's pieces really were fetched this time")
      .toBeGreaterThan(0);

    expect(complaints, `the page complained: ${complaints.join(" | ")}`).toEqual([]);
    console.log(`photographs of each step are in ${SHOTS}`);
  } finally {
    run.stop();
  }
});

/* ------------------------------------------------------------------------- *
 *  One position imaged twice, and the seamless picture
 * ------------------------------------------------------------------------- */

/**
 * How large the seamless picture is, in specimen pixels, for a row of two tiles.
 *
 * This picture crops the strip each tile shares with its neighbour, so each tile
 * shows 1024 pixels of specimen and two of them show 2048 across by 1024 down.
 * That is exactly twice the 1024 by 512 box on the page, so at two specimen pixels
 * per screen pixel the mosaic fills the box, the left half of it is always A's
 * ground and the right half is always B's.
 */
const TWO_TILES = { across: 2048, down: 1024 };
const TWO_TILES_PER_SCREEN_PIXEL = 2;

/** Which axis of the seamless picture carries the moment, and which one to watch. */
const MOMENT_AXIS = 0;
const THE_LATER_MOMENT = 1;

const WHERE_A_IS = { x: 32, y: 32, width: 448, height: 448 };
const WHERE_B_IS = { x: 544, y: 32, width: 448, height: 448 };

test("a later moment of an already published position is drawn only once that "
     + "moment is committed", async ({ page }) => {
  const run = await startTheRun({ tiles: 2, moments: 2 });
  const places = { A: WHERE_A_IS, B: WHERE_B_IS };

  try {
    // -- both positions are imaged once, and B is imaged a second time -------
    //
    // B's second moment is committed properly. It is what makes this test
    // possible at all: without something published at the later moment, a black
    // screen would satisfy every claim made below.
    await run.publish("A", 0);
    await run.publish("B", 0);
    await run.publish("B", THE_LATER_MOMENT);

    const { complaints } = await openThePage(page, run, run.seamless);
    console.log("the viewer is aimed:", JSON.stringify(
      await aimAtTheWholeMosaic(page, {
        mosaic: TWO_TILES,
        perPixel: TWO_TILES_PER_SCREEN_PIXEL,
        sliders: { [MOMENT_AXIS]: THE_LATER_MOMENT },
      }),
    ));

    const first = await fullestOverEachPlace(page, places,
      "7-the-later-moment-before-A-is-imaged-again", { seconds: 8 });
    console.log(said("only B has a second moment  ", first));
    expect(first.B, "B's second moment is committed, so it is drawn")
      .toBeGreaterThan(DRAWN);
    expect(first.A, "A has not been imaged a second time, so nothing is drawn there")
      .toBeLessThan(NOT_DRAWN);

    // -- A is imaged a second time, and the sequence stops short of the commit -
    //
    // A's first moment was published long ago and is still on the screen at that
    // moment. This second moment is not published at all, and the fact that the
    // position it belongs to is published says nothing about it.
    await run.writeWithoutCommitting("A", THE_LATER_MOMENT);
    if (SABOTAGE === "commit-the-later-moment-early") {
      await run.commit("A", THE_LATER_MOMENT);
      console.log("SABOTAGE: A's second moment was committed during the step that "
                  + "expects it hidden");
    }
    if (SABOTAGE === "black-screen-at-a-later-moment") {
      await run.refuseEverything();
      console.log("SABOTAGE: the server now refuses everything, so the screen goes black");
    }
    await run.forgetWhatWasAsked();
    const readers = await page.evaluate(() => window.probe.refresh());
    expect(readers, "the engine really was sent back to the store").toBeGreaterThan(0);

    const middle = await fullestOverEachPlace(page, places,
      "8-the-later-moment-written-but-not-committed", { seconds: 10 });
    console.log(said("A's second moment not committed", middle));

    const asked = (await run.state()).asked_by_moment;
    console.log("pieces of image asked for  ", JSON.stringify(asked));

    expect(middle.B,
           "B's second moment was published and still is, so it is still drawn — "
           + "and still as bright, which is what stops a blank screen passing the "
           + `next line: ${said("now", middle)} against ${said("before", first)}`)
      .toBeGreaterThan(DRAWN);
    expect(middle.B,
           "nothing about B changed, so nothing about how much of it is drawn should")
      .toBeGreaterThan(first.B - 0.05);
    expect(middle.A,
           "A's second moment is complete and is sitting in the very picture the "
           + "browser is reading, but nobody has committed that moment. A commit "
           + "of the position's first moment is not a commit of this one.")
      .toBeLessThan(NOT_DRAWN);

    /* And the counters, which say the claim above was answered rather than never
       asked. */
    expect(asked["A moment 1"].served + asked["A moment 1"].refused,
           "the engine really did go and ask for A's second moment")
      .toBeGreaterThan(0);
    expect(asked["A moment 1"].served,
           "and not one piece of A's second moment should have been handed over")
      .toBe(0);

    // -- and now that moment is committed, and nothing else changes ----------
    if (SABOTAGE !== "commit-the-later-moment-early") {
      await run.commit("A", THE_LATER_MOMENT);
    }
    await run.forgetWhatWasAsked();
    await page.evaluate(() => window.probe.refresh());

    const both = await fullestOverEachPlace(page, places,
      "9-the-later-moment-committed", { seconds: 10 });
    console.log(said("A's second moment committed   ", both));
    const askedAtTheEnd = (await run.state()).asked_by_moment;
    console.log("pieces of image asked for  ", JSON.stringify(askedAtTheEnd));

    expect(both.B, "B is still drawn").toBeGreaterThan(DRAWN);
    expect(both.A, "A's second moment is committed, so now it is drawn too")
      .toBeGreaterThan(DRAWN);
    expect(askedAtTheEnd["A moment 1"].served,
           "A's second moment really was fetched this time").toBeGreaterThan(0);

    expect(complaints, `the page complained: ${complaints.join(" | ")}`).toEqual([]);
    console.log(`photographs of each step are in ${SHOTS}`);
  } finally {
    run.stop();
  }
});
