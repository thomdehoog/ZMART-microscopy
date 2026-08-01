/**
 * The built page — what actually gets copied to the microscope computer.
 *
 * Every other browser test in this folder drives the development server, which
 * is right for what those tests ask: they are about how the page behaves, and
 * the development server serves the same page. This one is different, and the
 * difference is the whole reason it exists.
 *
 * The microscope computer has no build tools and no network. It is handed the
 * output of `npm run build` and nothing else. That output is *not* the same
 * arrangement of files the development server serves: the page is folded into
 * one self-contained HTML document, and neuroglancer's two background programs
 * are placed beside it as files of their own, because a browser will not start a
 * background program from anything folded into a page. `vite.config.js` and
 * `neuroglancer-workers.mjs` say why at length.
 *
 * So a page that draws beautifully under the development server tells you
 * nothing about whether the built one draws. This file builds the page for real
 * and then looks at the result, twice over, in the two ways somebody actually
 * opens it:
 *
 * * **Served over HTTP**, which is how an operator will meet it once the Python
 *   server hands it out. All three engines have to draw.
 * * **Opened straight off the disk**, as `python dev_window.py --build` does.
 *   A browser gives such a page no address, and refuses to start a background
 *   program for it, so neuroglancer cannot work there — and the page has to say
 *   so and offer the two that can, rather than offering a button that draws
 *   nothing.
 *
 * Nothing here is asserted about elements existing or loaders resolving. The
 * question is whether a picture reached the screen, so the box is photographed
 * and the photograph is measured, exactly as in `viewer-workflow.spec.js`.
 *
 * ## Making sure it can fail
 *
 * `LIVE_OVERVIEW_SABOTAGE=stalled` stops the demo writing any tile, so there is
 * nothing to draw and the measurements below go red. That is the proof they are
 * reading the picture and not the plumbing.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { expect, test } from "@playwright/test";
import { colourSpread, fractionLit, photograph } from "./pixels.js";
import { SHOTS, rest, startDemoRun } from "./live-run.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE_SOURCE = path.resolve(HERE, "..");

/** Where `npm run build` puts what the microscope computer is given. */
const BUILT = path.resolve(PAGE_SOURCE, "..", "workflow", "webapp", "static");

const PORT = Number(process.env.VIEWER_BUILT_PORT ?? 8792);
const SERVE_ON = Number(process.env.VIEWER_BUILT_SERVE_PORT ?? 5175);

/* The same three numbers `viewer-workflow.spec.js` uses, and for the same
   reason: they sit a long way below what a drawn picture measures and a long way
   above what an empty box measures, so they are not fussy about the exact shade
   an engine happens to draw. */
const ENOUGH_OF_IT_LIT = 0.5;
const ENOUGH_DIFFERENT_COLOURS = 50;
const NOT_ALL_ONE_COLOUR = 0.2;

let run = null;
let served = null;

/**
 * Serve a folder over HTTP, plainly.
 *
 * Small enough to write out rather than install, and there is one thing about it
 * that is not decoration: JavaScript has to be handed over with a JavaScript
 * content type, because a browser refuses to start a background program from a
 * file described as anything else. Get that wrong and the page loads, the engine
 * reports itself content, and no picture ever appears.
 */
function serve(folder, port) {
  const types = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
  };
  const server = http.createServer((request, response) => {
    const asked = decodeURIComponent(request.url.split("?")[0]);
    const file = path.join(folder, asked === "/" ? "index.html" : asked);
    if (!file.startsWith(folder) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      response.writeHead(404).end("not found");
      return;
    }
    response.writeHead(200, {
      "Content-Type": types[path.extname(file)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((ready) => server.listen(port, "127.0.0.1", () => ready(server)));
}

test.beforeAll(async () => {
  /* Build the page for real. It is the thing under test, so using whatever
     happened to be lying in the output folder would be measuring a page nobody
     can account for. */
  execFileSync("npm", ["run", "build"], { cwd: PAGE_SOURCE, stdio: "inherit" });
  run = await startDemoRun({ port: PORT });
  served = await serve(BUILT, SERVE_ON);
});

test.afterAll(async () => {
  run?.stop();
  await new Promise((done) => (served ? served.close(done) : done()));
});

/** Open the built page on the run and stand on the workflow that is only the canvas. */
async function standOnTheViewerStep(page, where, { engine = null } = {}) {
  const asked = new URLSearchParams({ overview: run.store });
  if (engine) asked.set("engine", engine);
  await page.goto(`${where}?${asked}`);
  await page.selectOption("#wf-select", "viewer_only");
  await expect(page.locator("#panel-viewer")).toHaveClass(/\bon\b/);
}

/**
 * Watch the box for a few seconds and keep the fullest photograph of it.
 *
 * The same reasoning as in `viewer-workflow.spec.js`: a picture part way through
 * fetching its pieces is honestly half drawn, and the fault only goes one way,
 * so the fullest of several moments is the honest answer to "is it drawing". It
 * cannot flatter an engine that draws nothing, because the fullest of several
 * blank photographs is still blank.
 */
async function fullestPictureOf(page, name, { seconds = 15 } = {}) {
  const until = Date.now() + seconds * 1000;
  let best = null;
  do {
    const pixels = await photograph(page, "#viewer-box", 0.5);
    const lit = fractionLit(pixels);
    if (!best || lit > best.lit) {
      best = { lit, ...colourSpread(pixels) };
      best.shot = await page.locator("#viewer-box").screenshot();
    }
    await rest(700);
  } while (Date.now() < until);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), best.shot);
  delete best.shot;
  return best;
}

/** What a photograph has to show before we will call it a picture. */
function itIsReallyDrawing(measured, whichEngine) {
  expect(measured.lit, `${whichEngine}: share of the box showing picture`)
    .toBeGreaterThan(ENOUGH_OF_IT_LIT);
  expect(measured.distinct, `${whichEngine}: how many different colours are in it`)
    .toBeGreaterThan(ENOUGH_DIFFERENT_COLOURS);
  expect(measured.dominantFraction, `${whichEngine}: share taken by one flat colour`)
    .toBeLessThan(NOT_ALL_ONE_COLOUR);
}

test("the build produces the page and the two background programs, and nothing else", () => {
  /* This is what has to be copied to the microscope computer: one folder with
     three files in it. It used to be one file, and the reason it is now three is
     recorded in `README.md`. Naming them here means that if the build ever
     stops producing one of them — which is easy to do by accident and impossible
     to notice by looking at the page in a browser that has the old one cached —
     something goes red with the reason in front of it. */
  const there = fs.readdirSync(BUILT).sort();

  expect(there).toContain("index.html");
  expect(there).toContain("async_computation.bundle.js");
  // Vite gives the fetching program a name with a fingerprint in it, so that a
  // browser cannot serve a stale copy from its cache after a rebuild.
  expect(there.filter((f) => /^chunk_worker\.bundle-.*\.js$/.test(f))).toHaveLength(1);
  expect(there).toHaveLength(3);

  /* Both background programs have to be real compiled programs. Neuroglancer
     ships each as a twenty-line list of imports that only a build tool can read,
     and a page built with those loads perfectly and never draws — which is
     precisely the failure that is hardest to notice. `neuroglancer-workers.mjs`
     is what compiles them. */
  for (const name of there.filter((f) => f.endsWith(".bundle.js") || /chunk_worker/.test(f))) {
    const size = fs.statSync(path.join(BUILT, name)).size;
    expect(size, `${name} looks like the uncompiled list rather than a program`)
      .toBeGreaterThan(50 * 1024);
  }
});

test("served over HTTP, the built page draws with every engine it offers", async ({ page }) => {
  test.setTimeout(300_000);

  const where = `http://127.0.0.1:${SERVE_ON}/`;
  await standOnTheViewerStep(page, where);
  await run.acquire(25);

  const offered = await page.locator("#viewer-engine button").allTextContents();
  expect(offered).toEqual(["viv-under", "viv-inside", "neuroglancer-under"]);

  /* Each in turn, on the same run, from the same view. Doing all three in one
     test rather than three is deliberate: the run is written once and building
     the page takes a few seconds, and what is being asked is a single question
     about one delivered page. */
  for (const engine of offered) {
    if ((await page.locator("#viewer-engine button[aria-checked='true']").textContent()) !== engine) {
      await page.locator(`#viewer-engine button[data-engine="${engine}"]`).click();
      await expect(page.locator(`#viewer-engine button[data-engine="${engine}"]`))
        .toHaveAttribute("aria-checked", "true");
    }
    const measured = await fullestPictureOf(page, `viewer-built-http-${engine}`);
    console.log(
      `the built page drew with ${engine}: ${(measured.lit * 100).toFixed(1)}% of ` +
        `the box lit, ${measured.distinct} distinct colours`,
    );
    itIsReallyDrawing(measured, engine);
  }
});

test("opened straight off the disk, it offers only what can draw there, and says why", async ({ page }) => {
  test.setTimeout(300_000);

  /* This is what `python dev_window.py --build` does, and what double-clicking
     the page would do. A browser gives a page opened this way no address of its
     own and refuses to start a background program for it, so neuroglancer cannot
     draw here however well it is built. The page has to know that and act on it,
     because a button that quietly draws nothing is the worst of the three
     possible behaviours. */
  const where = pathToFileURL(path.join(BUILT, "index.html")).href;
  await standOnTheViewerStep(page, where, { engine: "neuroglancer-under" });
  await run.acquire(25);

  const offered = await page.locator("#viewer-engine button").allTextContents();
  expect(offered).toEqual(["viv-under", "viv-inside"]);

  // And it says where the third one went, in a sentence somebody can act on.
  const note = await page.locator("#viewer-note").textContent();
  expect(note).toContain("neuroglancer-under");
  expect(note).toContain("HTTP");

  // Asking for it by name gets an answer rather than a different engine in silence.
  expect(note).toContain("was asked for and is not here");

  /* And the page is still a working page: the two that can draw, do. A page that
     told the truth about the missing engine and then drew nothing at all would
     have failed at the thing that matters. */
  const measured = await fullestPictureOf(page, "viewer-built-from-disk-viv-under");
  console.log(
    `opened off the disk, the page drew with viv-under: ` +
      `${(measured.lit * 100).toFixed(1)}% of the box lit, ` +
      `${measured.distinct} distinct colours`,
  );
  itIsReallyDrawing(measured, "viv-under");
});
