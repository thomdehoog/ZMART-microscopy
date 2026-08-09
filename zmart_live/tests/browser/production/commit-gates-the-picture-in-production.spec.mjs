/**
 * Watching a commit decide what reaches the screen — through the real publisher.
 *
 * This is the same question as the test one folder up, asked of the code an
 * acquisition actually runs. There, the two positions are written by a small
 * purpose-built writer and the publication record is kept beside them by hand.
 * That was enough to show that a commit decides the picture, and it left one
 * honest complaint open — finding 4 of `docs/design/codex-review-findings.md` —
 * that the browser was watching a stand-in. If
 * `zmart_live/coordinator.py` ever stopped publishing in the right order, that
 * test would have gone on passing.
 *
 * Here every position on screen was written, inspected and committed by
 * `LivePublisher.write_and_publish`: the pixels and their zoomed-out copies, the
 * run-wide picture rebuilt from what is already published, the arrangement, and
 * then one commit. Nothing in the test writes an image or moves the record
 * itself. The evidence is still a photograph of the screen.
 *
 * ## The sequence, and why it is in this order
 *
 * ```
 *   publish position A            ->  A is drawn.  B is not.
 *   write position B, and stop
 *     short of the commit         ->  A is still drawn, just as brightly.
 *                                     B is still not drawn.
 *   commit position B             ->  both are drawn.
 * ```
 *
 * The middle step is the one that matters, and it is also the one that is easy
 * to get wrong. "B is not drawn" is satisfied perfectly by a completely black
 * screen — by a page that never opened, an engine that never started, a run that
 * was never served. A test making only that claim would go green for every one
 * of those reasons and would be measuring nothing at all.
 *
 * So the middle step always makes both claims at once: **B is not drawn, and A
 * still is, and just as much of it as before.** A black screen fails the second
 * claim immediately. Both are asserted in the same step rather than in
 * neighbouring ones, because a claim made in another test is no protection when
 * this is the one going quietly wrong.
 *
 * ## What the middle step really leaves on disk
 *
 * Writing B's pixels alone would not test anything. The picture the viewer reads
 * is the run-wide seamless overview, and if B's pixels had never been put into
 * it, then "B is not drawn" would be true because there was nothing there to
 * draw — and the commit gate, the thing under test, would never have been asked a
 * question.
 *
 * So the middle step runs the publisher's whole sequence and stops one step
 * short: `write_a_position`, then `write_the_seamless_view`, then
 * `write_the_layout`, and no commit. B's pixels are genuinely sitting in the
 * picture the browser is reading. The only thing standing between them and the
 * screen is that nobody has published B — which is exactly the claim being made.
 *
 * That is also the state a microscope passes through for a moment on every
 * position, and the state it would be left in for good if the software stopped
 * between writing and committing.
 *
 * The last step then calls `publish` on its own. Between the middle step and the
 * last one, not one byte of image changes; the commit is the entire difference.
 *
 * There is a second protection, worth more than any wording: the same sequence is
 * run deliberately broken, twice, by `check-the-production-test-can-fail.mjs`
 * beside this file. One run commits B during the middle step, when the test
 * expects it invisible. The other makes the server refuse everything, so the
 * screen goes black while B is still — quite truthfully — not drawn. Each aims at
 * one of the two claims above, and each must make this test go red. A test that
 * cannot be made to fail on purpose is decoration.
 *
 * ## How the picture is measured
 *
 * Two rectangles of fixed size in fixed places on the page: the left half of the
 * picture, which is always position A's ground, and the right half, which is
 * always position B's.
 *
 * The run-wide picture shows 2048 pixels of specimen across and 1024 down — the
 * two 1152-pixel frames, less the strip each shares with its neighbour. The
 * viewer's box on the page is 1024 by 512, so at two specimen pixels per screen
 * pixel the mosaic fills that box exactly and the halves mean the same thing in
 * every photograph.
 *
 * Fixed rectangles rather than rectangles worked out from wherever the picture
 * happens to be. Finding the lit part of a photograph and measuring inside it is
 * right when the question is "which tiles were imaged"; it is exactly wrong here,
 * because the lit part changes shape the moment a second position appears — so
 * "how much of A is lit" would quietly be measured against a different rectangle
 * in each step.
 *
 * What is measured inside each rectangle is the share of it brighter than the
 * background — its *lit fraction*, from
 * `workflows/target_acquisition/webapp-ui/tests/pixels.js`, the same measurement
 * the older test uses. That file explains why counting colours instead cannot
 * work here: a blank panel and a panel completely covered by an even tile are
 * both one flat colour and score the same, and this run's positions are
 * deliberately even.
 *
 * Each measurement is the fullest of several photographs taken over a few
 * seconds. That is fair in both directions at once, which is the reason for it. A
 * picture caught partway through being fetched can only show *less* than has been
 * served, never more, so keeping the fullest moment gives A its best honest
 * showing — and it cannot flatter B, because if B were ever drawn at all, one of
 * those photographs would catch it.
 *
 * ## Why the test aims the camera itself
 *
 * The page one folder up aims itself, because the store it was written for
 * declares its voxel size in micrometres and the page can read it. The run-wide
 * picture the publisher writes is a plain Zarr array and says no such thing: it
 * carries no voxel size, no units and no axis names, because turning a run into
 * an image the viewer can interpret is the job of `zmart_live/scene.py` and is
 * not part of what this test is checking. So the page's own aim finds nothing to
 * work with, and the test says where to look instead — which axes go on screen,
 * where the middle of the mosaic is, and how many specimen pixels fall in one
 * screen pixel. Nothing else about the page is changed.
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

/** When the middle step is run deliberately broken. See the note at the top. */
const SABOTAGE = process.env.ZMART_SABOTAGE ?? "";

/**
 * Where the photographs are kept, so a failure can be looked at rather than only
 * read about.
 *
 * A deliberately broken run puts its photographs somewhere else, and that is not
 * tidiness. The photographs of an honest run are the evidence that this test
 * proved what it claims. A broken run producing a black screen would otherwise
 * overwrite them, leaving the project holding a picture of nothing under a name
 * that says the test passed — worse than having no picture at all.
 */
const SHOTS = SABOTAGE
  ? path.join(HERE, "photographs", `deliberately-broken-${SABOTAGE}`)
  : path.join(HERE, "photographs");

/**
 * Where the run-wide picture is put on screen.
 *
 * The publisher's two 1152-pixel frames overlap by 128, and each gives the shared
 * strip to one neighbour rather than both, so the picture shows 2048 pixels of
 * specimen across and 1024 down. The viewer's box on the page is 1024 by 512, so
 * two specimen pixels per screen pixel makes the mosaic fill the box exactly.
 */
const MOSAIC = { across: 2048, down: 1024 };
const PIXELS_PER_SCREEN_PIXEL = 2;

/**
 * The two rectangles the picture is measured in, in page pixels.
 *
 * The picture fills the top-left 1024 by 512 of the page, and the boundary
 * between the positions runs down the middle of it. Each rectangle is inset from
 * its half by a comfortable margin, so that the seam down the middle and the
 * outer edge of the picture cannot land inside a measurement and blur what it
 * means.
 */
const WHERE_A_IS = { x: 32, y: 32, width: 448, height: 448 };
const WHERE_B_IS = { x: 544, y: 32, width: 448, height: 448 };

/**
 * How lit a rectangle has to be before that counts as the position being drawn.
 *
 * A position that is drawn at all fills its whole half, so the honest reading is
 * near one. Half is chosen as the line because it is nowhere near either answer —
 * a drawn position measures well above it and an undrawn one measures essentially
 * nothing — so the test does not depend on where exactly it sits.
 */
const DRAWN = 0.5;

/**
 * How lit a rectangle may be while still counting as nothing drawn there.
 *
 * Not zero, because a browser drawing in software leaves a few stray pixels along
 * an edge, and insisting on a perfect nought would make the test fail for reasons
 * that have nothing to do with commits. Two per cent is a hundred times less than
 * a position genuinely on screen.
 */
const NOT_DRAWN = 0.02;

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
 * Start the run and its server, and wait until it is answering.
 *
 * The run is written into a folder of its own outside the project, so that two
 * runs of this test cannot meet each other's leftovers and so that nothing the
 * test writes looks to anything else like somebody editing the project.
 */
async function startTheRun() {
  const port = await aFreePort();
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-production-gate-"));
  const server = spawn(
    process.env.PYTHON ?? "python",
    [
      "-m", "zmart_live.tests.browser.production.production_run",
      "--folder", folder, "--port", String(port),
    ],
    { cwd: REPO, stdio: "inherit" },
  );

  const address = `http://127.0.0.1:${port}`;
  const state = async () => (await fetch(`${address}/control/state`)).json();
  const tell = async (what, position) => {
    const answer = await fetch(
      `${address}/control/${what}${position ? `?position=${position}` : ""}`,
      { method: "POST" },
    );
    if (!answer.ok) {
      throw new Error(`the run refused "${what} ${position}": ${await answer.text()}`);
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
    /** The one image the viewer opens: the run's seamless overview. */
    store: `${address}/views/overview-seamless.ome.zarr/|zarr3:`,
    state,
    /** The whole production path for one position, ending in a commit. */
    publish: (position) => tell("publish", position),
    /** All of that sequence apart from the commit. */
    writeWithoutCommitting: (position) =>
      tell("write-everything-except-the-commit", position),
    /** Publish something already on disk, changing no image at all. */
    commit: (position) => tell("commit", position),
    forgetWhatWasAsked: () => tell("forget-what-was-asked"),
    refuseEverything: () => tell("refuse-everything"),
    stop() { server.kill(); },
  };
}

/**
 * Tell the engine which axes go on screen, where to look, and how far out.
 *
 * See the note at the top of this file for why this is done here rather than by
 * the page. In short, the picture the publisher writes carries no statement of
 * voxel size or axis names, so there is nothing for the page's own aim to read.
 *
 * An image written this way has five axes — which moment, which colour, and then
 * the three that say where in the specimen something is. Only the last three
 * belong on screen, widest first, which is what puts the mosaic's width across
 * the window rather than drawing time against depth.
 */
async function aimAtTheWholeMosaic(page) {
  return page.evaluate(({ mosaic, perPixel }) => {
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
    navigation.position.value = where;
    // The engine's own idea of zoom is "how many of the smallest voxel on screen
    // fall in one browser pixel". Converting from specimen pixels is the line
    // below; with an image that states no voxel size, every scale is one and the
    // two numbers are the same thing.
    navigation.zoomFactor.value =
      perPixel * space.scales[across] / info.canonicalVoxelPhysicalSize;
    return { onScreen, across, down, zoom: navigation.zoomFactor.value };
  }, { mosaic: MOSAIC, perPixel: PIXELS_PER_SCREEN_PIXEL });
}

/**
 * Watch the picture for a few seconds and keep the fullest reading of each half.
 *
 * See the note at the top of this file for why the fullest moment is the fair one
 * to keep. A photograph of the whole picture is saved alongside, under the name
 * given, so that a person looking into a failure can see what the test saw.
 */
async function fullestOverBothHalves(page, name, { seconds = 8 } = {}) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const until = Date.now() + seconds * 1000;
  const fullest = { A: 0, B: 0 };
  do {
    for (const [half, box] of [["A", WHERE_A_IS], ["B", WHERE_B_IS]]) {
      const lit = fractionLit(readPng(await page.screenshot({ clip: box })));
      if (lit > fullest[half]) fullest[half] = lit;
    }
    await rest(500);
  } while (Date.now() < until);
  fs.writeFileSync(
    path.join(SHOTS, `${name}.png`),
    await page.screenshot({ clip: { x: 0, y: 0, width: 1024, height: 512 } }),
  );
  return fullest;
}

/** A short line of numbers, for the summary the test prints as it goes. */
const said = (step, lit) =>
  `${step}: A ${lit.A.toFixed(3)}, B ${lit.B.toFixed(3)}`;

test("a position published by the real writer is drawn only once it is committed",
     async ({ page }) => {
  const run = await startTheRun();

  /* Anything the page complains about, apart from the one complaint this test is
     built on.

     A browser writes a line into its console whenever a request comes back "not
     found", and this server answers exactly that for every piece of a position
     nobody has published. Those lines are the machinery working rather than a
     fault: a viewer is expected to take "there is nothing here" as empty ground
     and carry on drawing what it does have. So complaints about the run's own
     address are counted and reported, and everything else is treated as a
     failure — because a page that is quietly throwing is a page whose black
     screen would have nothing to do with commits. */
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

  try {
    // -- position A is imaged and published, all the way through -------------
    //
    // One call to LivePublisher.write_and_publish: pixels, zoomed-out copies,
    // the run-wide picture, the arrangement, and then the commit.
    await run.publish("A");

    await page.goto(
      `${run.address}/page/index.html?store=${encodeURIComponent(run.store)}`,
    );
    await page.waitForFunction(
      () => window.probe?.ready || window.probe?.failed, null, { timeout: 60_000 },
    );
    const failed = await page.evaluate(() => window.probe.failed);
    expect(failed, `the viewer did not open: ${failed}`).toBeFalsy();
    console.log("the viewer is aimed:", JSON.stringify(await aimAtTheWholeMosaic(page)));

    /* The counts are deliberately *not* cleared here. Nothing was fetched before
       the page opened, so they already start at nought — and clearing them at
       this point would race with the engine, which has by now fetched some of A
       and may have fetched all of it. */
    const first = await fullestOverBothHalves(page, "1-only-A-is-published",
                                              { seconds: 10 });
    console.log(said("with only A published   ", first));

    expect(first.A, "A has been published, so A is drawn").toBeGreaterThan(DRAWN);
    expect(first.B, "B has not been imaged at all, so nothing is drawn there")
      .toBeLessThan(NOT_DRAWN);

    const askedFirst = (await run.state()).asked;
    console.log("pieces of image asked for  ", JSON.stringify(askedFirst));
    expect(askedFirst.A.served, "A's pieces really were fetched").toBeGreaterThan(0);

    // -- position B is imaged, and the sequence stops short of the commit -----
    //
    // This is the step the whole test exists for. B's pixels are now genuinely
    // inside the picture the browser is reading. Nobody has published B, so
    // nobody may see it.
    await run.writeWithoutCommitting("B");
    /* The two deliberate faults, each of which ought to make this step go red,
       and each aimed at one half of the claim it makes. See
       `check-the-production-test-can-fail.mjs`. Neither happens in an ordinary
       run. */
    if (SABOTAGE === "commit-b-early") {
      await run.commit("B");
      console.log("SABOTAGE: B was committed during the step that expects it hidden");
    }
    if (SABOTAGE === "black-screen") {
      await run.refuseEverything();
      console.log("SABOTAGE: the server now refuses everything, so the screen goes black");
    }
    await run.forgetWhatWasAsked();
    // The engine has no reason of its own to ask for anything a second time, so
    // it is sent back to the store. Without this the step would prove nothing:
    // "B was asked for and refused" and "B was never asked for" look identical on
    // screen.
    const readers = await page.evaluate(() => window.probe.refresh());
    expect(readers, "the engine really was sent back to the store").toBeGreaterThan(0);

    const middle = await fullestOverBothHalves(page, "2-B-is-written-but-not-committed",
                                               { seconds: 12 });
    console.log(said("B written, not committed", middle));

    const asked = (await run.state()).asked;
    console.log("pieces of image asked for  ", JSON.stringify(asked));
    expect(asked.B.served + asked.B.refused,
           "the engine really did go and ask for B's pieces").toBeGreaterThan(0);

    // Both halves of the claim, together. The first is what stops a black screen
    // passing the second; see the note at the top of this file.
    expect(middle.A,
           `A was published and is still published, so it is still drawn — and it `
           + `is still as bright as it was, which is what stops a blank screen `
           + `passing the next line: ${said("now", middle)} against `
           + `${said("before", first)}`)
      .toBeGreaterThan(DRAWN);
    expect(middle.A,
           "nothing about A changed, so nothing about how much of it is drawn should")
      .toBeGreaterThan(first.A - 0.05);
    expect(middle.B,
           "B's pixels are complete and are sitting in the very picture the browser "
           + "is reading, but nobody has published B, so they must not be on screen")
      .toBeLessThan(NOT_DRAWN);

    // -- and now position B is committed, and nothing else changes -----------
    if (SABOTAGE !== "commit-b-early") await run.commit("B");
    await run.forgetWhatWasAsked();
    await page.evaluate(() => window.probe.refresh());

    const both = await fullestOverBothHalves(page, "3-both-are-committed",
                                             { seconds: 12 });
    console.log(said("both committed          ", both));
    const askedAtTheEnd = (await run.state()).asked;
    console.log("pieces of image asked for  ", JSON.stringify(askedAtTheEnd));

    expect(both.A, "A is still drawn").toBeGreaterThan(DRAWN);
    expect(both.B, "B has been committed, so now B is drawn too").toBeGreaterThan(DRAWN);
    expect(askedAtTheEnd.B.served, "B's pieces really were fetched this time")
      .toBeGreaterThan(0);
    expect(askedAtTheEnd.B.refused, "and none of them was refused any more").toBe(0);

    console.log(
      `the browser was told "there is nothing here" `
      + `${refusalsTheBrowserNoticed.length} times and went on drawing`,
    );
    expect(complaints, `the page complained: ${complaints.join(" | ")}`).toEqual([]);
    console.log(`photographs of each step are in ${SHOTS}`);
  } finally {
    run.stop();
  }
});
