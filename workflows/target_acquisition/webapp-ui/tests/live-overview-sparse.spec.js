import { expect, test } from "@playwright/test";
import { fullestOver, rest, settledPhotograph, startDemoRun, walkToTheScan } from "./live-run.js";
import { fractionLit, litBounds, litGrid, meanGrid, photograph } from "./pixels.js";

/* What happens when most of the canvas was never imaged.
 *
 * This is the shape a real run of this workflow produces, and it is the harder
 * one. An operator marks a few positions on a map and images only those, so the
 * canvas is declared large enough to cover the whole carrier and almost none of
 * it is ever written. Zarr's rule is that a piece of image nobody wrote simply
 * does not exist — there is no file for it, and reading it gives the fill value
 * — but that rule has to survive the whole path: a server answering for a file
 * that is not there, a reader treating that as "nothing was imaged" rather than
 * as a fault, and a layer drawing a gap where a gap belongs.
 *
 * Neuroglancer, which the project's other viewer uses, does all of this. Whether
 * Viv does was not known before this test, and guessing has cost this project
 * time before. So it is asked here directly, of the pixels:
 *
 *   - the five imaged places are drawn, in their right places;
 *   - the room between them is drawn as nothing, not as picture smeared across
 *     the gaps and not as a black rectangle over the whole canvas;
 *   - stepping through the depth of the stack changes the picture and keeps it
 *     in the right places, and costs only the plane being looked at;
 *   - and, in the second test here, whether a place nobody imaged lets what is
 *     drawn underneath it show through. That last one decides whether an image
 *     can be a layer over the operator's own drawing at all.
 *
 * The run is six positions on a five by five canvas: the four corners and the
 * middle, and one more that was visited and came back empty. Each is a stack
 * five planes deep, and every plane lights a different amount of its tile so
 * that a step through depth is something a test can state rather than something
 * a person has to notice.
 */

const PORT = Number(process.env.LIVE_OVERVIEW_SPARSE_PORT ?? 8789);
const ACROSS = 5;                    // the canvas is five tiles by five
const PLANES = 5;
const POSITIONS = 6;

/** Which squares of that five by five canvas hold a picture. */
const IMAGED = new Set(["0,0", "0,4", "4,0", "4,4", "2,2"]);

/* And the one that was imaged and came back empty: the stage went there and
   there was nothing to see. It is written, so there is a piece of image on disk
   for it, but every value in it is below the brightness the run asked to be
   shown — so it should be drawn as black, and an operator should be able to tell
   it apart from the squares nobody has visited yet. */
const IMAGED_BUT_EMPTY = "0,2";

let run = null;

test.beforeAll(async () => {
  run = await startDemoRun({ port: PORT, pattern: "scattered", planes: PLANES });
});
test.afterAll(() => { run?.stop(); });

test("a canvas imaged in a few scattered places draws the gaps as gaps", async ({ page }) => {
  test.setTimeout(240_000);

  /* Every answer the run gives is recorded, because what a server says about a
     piece of image that was never written is one of the things being asked
     here. A missing piece is expected to come back as "not found", and what
     matters is whether the page carries on drawing when it does. */
  const answers = [];
  page.on("response", (response) => {
    if (!response.url().startsWith(run.store)) return;
    answers.push({ url: response.url(), status: response.status() });
  });

  await page.goto(`/?overview=${encodeURIComponent(run.store)}`);
  await page.waitForTimeout(300);
  await walkToTheScan(page);
  await expect(page.locator("#overview-canvas")).toBeVisible();
  await expect(page.locator("#overview-note")).toContainText("overview open");

  // A run taken as a stack offers its depth; a single-plane overview does not.
  await expect(page.locator("#overview-depth")).toBeVisible();
  await expect(page.locator("#overview-plane-readout")).toHaveText(`1 / ${PLANES}`);

  /* This test looks at the whole canvas rather than the middle of it, because
     *where* each tile was drawn is the question. That means the page's own
     status label, which sits over the bottom corner of the picture, would be
     counted as picture and would move the edges the squares are measured
     against — so it is taken off the screen for the measuring. It is the same
     hazard `pixels.js` avoids by looking only at the middle. */
  await page.addStyleTag({ content: ".live-note { display: none !important; }" });

  await run.acquire(POSITIONS);
  expect((await run.state()).written, "six places visited, nineteen not").toBe(POSITIONS);

  /* The deepest plane first, because there every imaged tile is lit all the way
     through and the picture's own edges can be found. Those edges are what the
     squares are measured against afterwards. */
  await page.locator("#overview-plane").fill(String(PLANES - 1));
  await page.locator("#overview-plane").dispatchEvent("input");
  const deepest = await fullestOver(page, "sparse-1-deepest-plane", { seconds: 12, share: 1 });

  const bounds = litBounds(deepest.pixels);
  expect(bounds, "something was drawn").not.toBeNull();
  const grid = litGrid(deepest.pixels, ACROSS, { over: bounds });
  const readable = grid.map((row) => row.map((cell) => cell.toFixed(2)).join(" ")).join("\n");
  console.log(`how lit each of the 25 squares is, deepest plane:\n${readable}`);

  for (let row = 0; row < ACROSS; row++) {
    for (let col = 0; col < ACROSS; col++) {
      const where = `${row},${col}`;
      if (IMAGED.has(where)) {
        expect(grid[row][col], `the tile imaged at ${where} is drawn:\n${readable}`)
          .toBeGreaterThan(0.8);
      } else {
        expect(grid[row][col], `nothing was imaged at ${where}, so nothing is drawn there:\n${readable}`)
          .toBeLessThan(0.05);
      }
    }
  }

  /* And the whole picture is mostly gaps, which is the other half of the same
     statement: five squares of twenty-five is a fifth of the canvas. A viewer
     that filled the declared area with something would pass the check above and
     fail this one. */
  expect(deepest.lit, `about a fifth of the canvas has a picture in it: ${deepest.lit}`)
    .toBeGreaterThan(0.1);
  expect(deepest.lit).toBeLessThan(0.35);

  /* What the run answered for pieces of image that were never written. Zarr says
     there is no file for them, so the honest answer is "not found", and the
     reader is expected to take that as emptiness rather than as a failure. The
     picture above is the proof that it did. */
  const missing = answers.filter((a) => a.status === 404).length;
  const served = answers.filter((a) => a.status === 200 || a.status === 206).length;
  console.log(
    `pieces of image asked for: ${served} answered, ${missing} not found `
    + "(never written, and drawn as gaps)",
  );
  expect(missing, "unwritten pieces really were asked for and really were absent")
    .toBeGreaterThan(0);

  /* Stepping through the depth of the stack.
   *
   * Each plane lights more of its tile than the one above it, so the share of
   * the canvas that is lit has to rise as the plane goes down — and the five
   * imaged squares have to stay the same five, measured against the edges found
   * at the deepest plane so that the comparison is between like and like. */
  const perPlane = [];
  for (let plane = 0; plane < PLANES; plane++) {
    const asked = answers.length;
    const missed = answers.filter((a) => a.status === 404).length;
    await page.locator("#overview-plane").fill(String(plane));
    await page.locator("#overview-plane").dispatchEvent("input");
    await rest(4000);
    const pixels = await photograph(page, "#overview-canvas", 1);
    /* Nearly the whole of each square is looked at here, rather than the middle
       of it: on the first plane only a strip along the top of each tile has
       anything in it, and a measurement confined to the middle would report the
       imaged places as empty. */
    const planeGrid = litGrid(pixels, ACROSS, { over: bounds, inset: 0.04 });
    perPlane.push({
      plane,
      lit: fractionLit(pixels),
      requests: answers.length - asked,
      // How much of that was spent on room that was never imaged. Making the
      // gaps look right does not stop them being fetched, and on a canvas the
      // size of a carrier the fetching may be the greater cost of the two — so
      // it is worth having the number rather than an impression.
      missing: answers.filter((a) => a.status === 404).length - missed,
      drawn: planeGrid.flatMap((row, r) => row.map((cell, c) => (cell > 0.05 ? `${r},${c}` : null)))
        .filter(Boolean),
    });
  }
  console.log(
    "stepping through the stack: "
    + perPlane.map((p) => `plane ${p.plane + 1} lit ${p.lit.toFixed(3)} in ${p.requests} `
      + `requests, ${p.missing} of them for room never imaged`).join(", "),
  );

  for (const measured of perPlane) {
    expect(new Set(measured.drawn), `plane ${measured.plane + 1} draws the same five places`)
      .toEqual(IMAGED);
    expect(measured.requests, `plane ${measured.plane + 1} was read from the run`)
      .toBeGreaterThan(0);
  }
  expect(perPlane[PLANES - 1].lit,
    `the deepest plane shows more than the first: ${perPlane.map((p) => p.lit.toFixed(3))}`)
    .toBeGreaterThan(perPlane[0].lit + 0.05);
});


/* Can the acquired image be a *layer* over a picture the page draws itself?
 *
 * This settles a question about the whole design rather than a corner case. The
 * intention is that the operator's own drawing — the carrier outline, the wells,
 * the positions they laid out — sits underneath the image, and the image appears
 * over it as the run fills in. That only works if the parts of the canvas nobody
 * has imaged let what is beneath them through. A run declares room for the whole
 * carrier, so if unimaged room is drawn as solid black, the image is a black
 * sheet over everything the page drew and the arrangement is dead.
 *
 * The answer, measured below rather than assumed: **Viv draws it solid.** Its
 * shader ends by giving every pixel an opacity of one, so the whole declared
 * canvas is opaque whether or not anything was ever imaged into it. A bright
 * chequer painted underneath survives only in the border that lies outside the
 * picture; inside, nothing of it is left.
 *
 * It is fixable, and cheaply. `live/overview.js` carries a dozen lines of shader
 * code that deck.gl lets a layer slip into the last step of its drawing, setting
 * how solid each pixel is from how bright it is. With that on, the ground shows
 * through the gaps and the layered arrangement works. What it cannot do is tell
 * a place that was imaged and came back black from a place nobody has visited:
 * by the time the shader sees them they are the same colour, and that difference
 * is real during a run. So this test states both halves as they are, and if
 * either ever changes it will say so by going red.
 */
test("an unimaged part of the canvas is drawn solid, and can be made see-through",
  async ({ page }) => {
    test.setTimeout(300_000);

    /* Magenta, because nothing in the picture itself is anywhere near it: the
       run is drawn in green, so any red or blue on the screen came from
       underneath and nothing else. */
    const magenta = (colour) => colour[0] > 60 && colour[2] > 60;

    /** Open the page over a magenta chequer and photograph what survives. */
    async function groundUnder(seeThrough) {
      await page.goto(
        `/?overview=${encodeURIComponent(run.store)}&ground=ff00ff`
        + (seeThrough ? "&seethrough=1" : ""),
      );
      await page.waitForTimeout(300);
      await walkToTheScan(page);
      await expect(page.locator("#overview-canvas")).toBeVisible();
      // The depth control only knows how deep the run is once the run has been
      // opened, so this is how long to wait before asking it for a plane.
      await expect(page.locator("#overview-plane"))
        .toHaveAttribute("max", String(PLANES - 1));
      await page.addStyleTag({ content: ".live-note { display: none !important; }" });

      await run.acquire(POSITIONS);
      await page.locator("#overview-plane").fill(String(PLANES - 1));
      await page.locator("#overview-plane").dispatchEvent("input");
      await expect(page.locator("#overview-plane-readout")).toHaveText(`${PLANES} / ${PLANES}`);
      const shown = await settledPhotograph(
        page,
        seeThrough ? "sparse-3-ground-showing-through" : "sparse-2-ground-hidden-by-the-image",
        { seconds: 14 },
      );

      /* The squares are measured against the specimen's own edges, found by
         looking for green alone. Green is the run and nothing else, so those
         edges are the declared canvas however much or little of the ground
         survived — which keeps the measurement honest whatever the answer is. */
      const bounds = litBounds(shown.pixels, { only: 1 });
      expect(bounds, "the picture was drawn").not.toBeNull();
      const colours = meanGrid(shown.pixels, ACROSS, { over: bounds });

      /* The control, and it is what makes the rest worth reading: the ground is
         drawn a little wider than the run's canvas, so a border of it lies
         outside the picture. That border being magenta proves the ground is on
         the screen — so wherever it is missing, something covered it, rather
         than it never having been drawn. */
      const border = meanGrid(shown.pixels, 1, {
        over: {
          left: Math.max(0, bounds.left - 30), top: bounds.top + 40,
          right: Math.max(1, bounds.left - 6), bottom: bounds.bottom - 40,
        },
      })[0][0];
      expect(magenta(border),
        `the ground really is drawn under the image — its border is ${border}`).toBe(true);

      const gaps = [];
      for (let row = 0; row < ACROSS; row++) {
        for (let col = 0; col < ACROSS; col++) {
          const where = `${row},${col}`;
          if (IMAGED.has(where) || where === IMAGED_BUT_EMPTY) continue;
          gaps.push(colours[row][col]);
        }
      }
      const [emptyRow, emptyCol] = IMAGED_BUT_EMPTY.split(",").map(Number);
      const readable = colours
        .map((row) => row.map((c) => c.map((v) => String(v).padStart(3)).join(",")).join("  "))
        .join("\n");
      console.log(
        `${seeThrough ? "with" : "without"} the see-through shader, `
        + `the average colour of each of the 25 squares:\n${readable}`,
      );
      return {
        gaps,
        showedThrough: gaps.filter(magenta).length,
        imagedButEmpty: colours[emptyRow][emptyCol],
        imaged: colours[2][2],
        readable,
      };
    }

    const solid = await groundUnder(false);
    console.log(
      `Viv as it stands: ${solid.showedThrough} of ${solid.gaps.length} unimaged squares `
      + `let the ground through; a never-imaged square is ${solid.gaps[0]}`,
    );
    expect(solid.showedThrough,
      "Viv draws the whole declared canvas solid, so nothing under an unimaged "
      + `part of it survives:\n${solid.readable}`).toBe(0);

    const through = await groundUnder(true);
    console.log(
      `with the see-through shader: ${through.showedThrough} of ${through.gaps.length} `
      + `unimaged squares let the ground through; the place that was imaged and came `
      + `back empty is ${through.imagedButEmpty}`,
    );
    expect(through.showedThrough,
      "with a dozen lines of shader code the gaps let what is under them show, "
      + `which is what the layered design needs:\n${through.readable}`)
      .toBe(through.gaps.length);
    expect(magenta(through.imaged),
      "and a place that was imaged still covers what is under it").toBe(false);

    /* The cost of that fix, stated so nobody is surprised by it later: a place
       that was imaged and came back black becomes as see-through as a place
       nobody has visited. During a run those are two different things — "not
       yet" and "nothing there" — and this cannot tell them apart. */
    expect(magenta(through.imagedButEmpty),
      "a place imaged and found empty is indistinguishable from one never imaged, "
      + "which is the price of making the dark parts see-through").toBe(true);
  });
