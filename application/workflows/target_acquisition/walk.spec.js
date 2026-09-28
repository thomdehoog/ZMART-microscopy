/**
 * A walk of the target acquisition workflow, screen by screen, with nothing
 * stood in for.
 *
 * The page is the built page, served by the real bridge. The bridge drives
 * the mock microscope through the controller, on a configuration the mock
 * already holds, exactly as it would drive a Leica. What an operator would
 * do in the vendor's own software -- choose the job for a step -- goes
 * through the mock instrument window's own method, the same code its
 * buttons run.
 *
 * All ten steps are walked: connect, the carrier, the overview plan, the
 * focus map measured through the analysis, three test tiles of the overview
 * scanned onto the picture, objects detected on them with the page's fast
 * method, a gate drawn on the feature plot, scan areas placed under a cap,
 * the targets acquired -- and then the protocol: a setting edited turns the
 * steps below it orange, Accept all turns them green, Run protocol walks
 * every step again over the whole plan and writes the protocol, and a
 * fresh session opens on it with every step orange. Where detection cannot run on the machine the walk keeps the
 * page's own reason on screen and stops there, since the last three steps
 * stand on what detection finds. Set `OPERATOR_EVIDENCE_DIR` to keep a
 * screenshot of every screen the operator sees.
 */
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { operateTheInstrument, rest, setAcquisitionShown, showTheChannel, startTheBridge }
  from "./steps/scan_the_overview/live-bridge.js";
import { bestShift, fractionLit, photograph } from "./steps/scan_the_overview/pixels.js";

/** How far two photographs of the same box differ: the mean absolute gap
 * per sample. Zero when nothing on the picture changed. */
function differenceOf(a, b) {
  const n = Math.min(a.data.length, b.data.length);
  let sum = 0;
  for (let at = 0; at < n; at++) sum += Math.abs(a.data[at] - b.data[at]);
  return n ? sum / n : 0;
}

/** How coloured a photograph is: the mean gap between a pixel's strongest
 * and weakest channel. Zero for a grey picture. */
function chromaOf({ data, channels }) {
  let sum = 0, count = 0;
  for (let at = 0; at < data.length; at += channels) {
    const r = data[at], g = data[at + 1], b = data[at + 2];
    sum += Math.max(r, g, b) - Math.min(r, g, b);
    count += 1;
  }
  return count ? sum / count : 0;
}

const PORT = Number(process.env.ACQUISITION_BRIDGE_PORT ?? 8833);
const A_WHOLE_WALK = 2_400_000;

/* The mock keeps its instrument state in a file named by the environment. A
   folder of its own, so the walk starts from a machine nobody has touched
   and leaves nothing behind in anyone's home. The machine folder is left to
   the mock's default: the bridge connects on the configuration it holds. */
const home = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-acquisition-"));
process.env.ZMART_MOCK_STATE = path.join(home, "instrument.json");
/* The saved protocols go into a library of the walk's own, not the machine's. */
process.env.ZMART_PROTOCOL_LIBRARY = path.join(home, "protocols");

let shots = 0;
async function shot(page, name) {
  const folder = process.env.OPERATOR_EVIDENCE_DIR;
  if (!folder) return;
  fs.mkdirSync(folder, { recursive: true });
  shots += 1;
  await page.screenshot({ path: path.join(folder, `${String(shots).padStart(2, "0")}-${name}.png`) });
}

const walkTo = async (page, title) => {
  await page.locator(`.step:has-text("${title}")`).first().click();
  await rest(600);
};

/** Take the reading a step will not proceed without, and name it. */
async function record(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await rest(800);
}

const ask = (page, port, route) => page.evaluate(async ({ port: p, route: r }) =>
  fetch(`http://127.0.0.1:${p}${r}`).then((a) => a.json()).catch((e) => ({ error: e.message })),
{ port, route });

/** Bring the canvas in on the planned fields the way an operator does: the
 * Tile set press in the canvas's own row. The slide is 75 mm wide and the
 * overview 3 mm, so at the whole-slide view the picture is a few pixels. */
async function framePlan(page) {
  await page.locator("#tileset-btn").click();
  await rest(1500);
}

/* A place on the gate plot, as fractions of its frame: the frame keeps a
   column at the right for the y labels and two lines below for the x axis. */
const PLOT_PAD = { l: 1, r: 62, t: 1, b: 38 };
const plotPoint = (sc, gx, gy) => [
  sc.x + PLOT_PAD.l + (sc.width - PLOT_PAD.l - PLOT_PAD.r) * gx,
  sc.y + PLOT_PAD.t + (sc.height - PLOT_PAD.t - PLOT_PAD.b) * gy,
];

const inTheInstrument = {
  choose: (job) => operateTheInstrument("choose", job),
};

test.describe("the target acquisition workflow, walked screen by screen", () => {
  test.setTimeout(A_WHOLE_WALK);

  for (const bake of [true]) test(`from Connect to acquired targets, bake ${bake ? "on" : "off"}`, async ({ page }) => {
    const bridge = await startTheBridge({ port: PORT });
    const errors = [];
    const imageRequests = [];
    page.on("request", request => {
      if (/\/data\/.*\/c\//.test(request.url())) imageRequests.push(request.url());
    });
    page.on("pageerror", (why) => { errors.push(why.message); console.log(`page error: ${why.message}`); });
    try {
      await page.goto(`${bridge.at}/`);
      await rest(2500);
      /* A machine with a configuration opens on target acquisition, with the
         newest configuration chosen on the card. */
      await expect(page.locator("#wf-select")).toHaveValue("target_acquisition");
      await shot(page, "opened");

      /* Step 1: the card, the mock chosen, its configuration offered. */
      const offered = page.locator(".panel.on .session-form select").nth(2);
      await expect(offered).toBeEnabled();
      await page.locator(".panel.on .session-buttons button.run").click();
      await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
      await expect(page.locator(".check-row.pending")).toHaveCount(0);
      await page.waitForFunction(() => !!window.__thePicture);
      await page.evaluate(() => { window.connectedPicture = window.__thePicture; });
      await rest(1200);
      await shot(page, "connected");

      /* Step 2: a slide. */
      await walkTo(page, "Define Carrier");
      await shot(page, "carrier-before");
      await page.locator(".carrier-type[data-type='slide']").click();
      await rest(800);
      await shot(page, "carrier-slide");

      /* Step 3: the overview job, its optics read off the instrument, and a
         grid laid over the slide in that job's frame. */
      await walkTo(page, "Overview scan area");
      await shot(page, "overview-area-before");
      inTheInstrument.choose("Overview");
      await record(page, "sf-preset", "overview");
      await shot(page, "overview-area-recorded");
      await page.locator(".sf-apply-grid").click();
      await rest(800);
      const plan = await page.evaluate(() => window.__theStageCanvas.plan());
      expect(plan.length, "the slide was tiled").toBeGreaterThan(0);
      await shot(page, "overview-area-planned");
      /* There is a current tile from the first plan on: Tile is live, frames
         the plan's first field, and pressed again frames that same field:
         the press never chooses another one. */
      await expect(page.locator("#tile-btn")).toBeEnabled();
      await page.locator("#tile-btn").click();
      await rest(400);
      const onTheFirst = await page.evaluate(() => window.__theStageCanvas.view());
      expect(Math.hypot(onTheFirst.centre.x - plan[0].x, onTheFirst.centre.y - plan[0].y),
        "Tile frames the first field").toBeLessThan(1);
      await page.locator("#tile-btn").click();
      await rest(400);
      const onTheSecond = await page.evaluate(() => window.__theStageCanvas.view());
      expect(Math.hypot(onTheSecond.centre.x - plan[0].x, onTheSecond.centre.y - plan[0].y),
        "Tile again stays on the field the box is on").toBeLessThan(1);
      expect(onTheSecond.zoom).toBeCloseTo(onTheFirst.zoom, 6);
      await shot(page, "overview-area-tile-again");

      /* Step 4: the focus job, points placed, every one measured. */
      await walkTo(page, "Focus strategy");
      /* The tile stays current on every step after the plan. */
      await expect(page.locator("#tile-btn")).toBeEnabled();
      await shot(page, "focus-before");
      inTheInstrument.choose("Focussing");
      await record(page, "focus-preset", "af");
      await page.locator("#fp-place").click();
      await rest(500);
      await shot(page, "focus-points-placed");
      await page.locator(".panel.on button.step-run").click();
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
      const focus = await ask(page, PORT, "/api/focus/measure");
      expect(focus.points?.length, "a focus point was measured through the bridge").toBeGreaterThan(0);
      await rest(1500);
      await shot(page, "focus-measured");

      /* Step 5: the overview, scanned onto the picture. */
      await walkTo(page, "Scan the overview");
      await rest(1500);
      await shot(page, "scan-before");
      await showTheChannel(page);
      /* Three test tiles drawn at random: the rehearsal scans only these,
         and the box and the summary say so. */
      await expect(page.locator("#test-tiles-count")).toHaveAttribute("data-green", "0");
      /* Shift-drag over the first two tiles turns them green; the same drag
         again turns them back. */
      await framePlan(page);
      {
        const box = await page.locator("#stage-canvas").boundingBox();
        const onScreen = ([x, y]) => { const p = window.__theStageCanvas.project(x, y); return Array.isArray(p) ? { x: p[0], y: p[1] } : p; };
        const a = await page.evaluate(onScreen, [plan[0].x, plan[0].y]);
        const b = await page.evaluate(onScreen, [plan[1].x, plan[1].y]);
        const drag = async () => {
          await page.keyboard.down("Shift");
          await page.mouse.move(box.x + a.x - 60, box.y + a.y - 60);
          await page.mouse.down();
          await page.mouse.move(box.x + b.x + 40, box.y + b.y + 40, { steps: 24 });
          await page.mouse.up();
          await page.keyboard.up("Shift");
          await rest(300);
        };
        await drag();
        expect((await page.evaluate(() => window.__theRunState())).testTiles.sort()).toEqual([0, 1]);
        await shot(page, "scan-shift-drag");
        await drag();
        expect((await page.evaluate(() => window.__theRunState())).testTiles).toEqual([]);
      }
      await page.locator("#test-n").fill("3");
      await page.locator("#test-random").click();
      await rest(400);
      await expect(page.locator("#test-tiles-count")).toHaveAttribute("data-green", "3");
      expect((await page.evaluate(() => window.__theRunState())).testTiles).toHaveLength(3);
      await shot(page, "scan-test-tiles");
      const TEST_TILES = 3;
      await page.locator(".panel.on button.step-run").click();
      await expect.poll(async () => (await ask(page, PORT, "/api/scan")).done, { timeout: 400_000 }).toBe(TEST_TILES);
      await expect.poll(async () => !(await ask(page, PORT, "/api/scan")).running, { timeout: 400_000 }).toBe(true);
      const overview = await ask(page, PORT, "/api/scan");
      expect(overview).toMatchObject({ error: null, stopped: false, done: TEST_TILES, of: TEST_TILES });
      expect(overview.records).toHaveLength(TEST_TILES);
      expect((await page.evaluate(() => window.__theRunState())).scannedFields, "the fields are the test tiles")
        .toHaveLength(TEST_TILES);
      expect(overview.records.filter(record => record.zarr_error)).toEqual([]);
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
      await rest(3000);
      await shot(page, "scan-done");
      expect(await page.evaluate(() => window.connectedPicture === window.__thePicture),
        "overview rows keep the viewer opened at Connect").toBe(true);
      await expect(page.locator(".layer-fade input")).toHaveValue("100");
      expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);
      await framePlan(page);
      await shot(page, "scan-done-picture");
      /* How the picture is drawn, in the row over it beside the acquisitions:
         the projection, and three ways that are not built yet, greyed out.
         Every acquisition, the focus stacks included, is one flat product. */
      const viewModes = page.locator("#view-modes");
      await expect.poll(() => page.evaluate(() => window.__viewerPanel?.viewModes?.("overview") ?? []),
        { timeout: 60_000 }).toEqual(["projection"]);
      await expect(page.locator("#acquisition-name")).toHaveText("overview");
      await expect(viewModes).toBeVisible();
      await expect(viewModes).toHaveValue("projection");
      await expect(viewModes.locator("option")).toHaveText(["Projection", "Z-slices (Top view)", "Z-slice (Absolute)", "3D"]);
      await expect(viewModes.locator("option:disabled")).toHaveCount(3);
      expect(await page.locator("#viewer-pick").evaluate((press) => {
        const strip = press.nextElementSibling;
        return strip?.id === "acquisition-pick" && press.getBoundingClientRect().right <= strip.getBoundingClientRect().left;
      }), "the viewer's press stands directly left of the acquisitions strip").toBe(true);
      await expect(page.locator("#viewer-pick .bar-word")).toHaveText("viewer");
      await expect.poll(() => page.evaluate(() => {
        const rows = window.__thePicture.layersForMeasurement();
        const of = (kind) => rows.filter(row => row.name.startsWith(`${kind}/`));
        return ["overview", "focussing"].every(kind => of(kind).length > 0 && of(kind).every(row =>
          row.sources.every(source => decodeURIComponent(source.url).includes(`${kind}_max.zmartview.zarr`))));
      }), { timeout: 60_000 }).toBe(true);
      expect(await page.evaluate(() => window.connectedPicture === window.__thePicture)).toBe(true);
      await expect.poll(async () => fractionLit(await photograph(page, "#picture-host", 1)))
        .toBeGreaterThan(0.01);
      await shot(page, "projection-image");
      /* Under the picture there is no way through a stack: the focus stacks
         are drawn flat, as their projections, whether their eye is on or
         off; and nothing here is a timelapse, so T does not stand either. */
      await expect(page.locator("#canvas-axes")).toBeHidden();
      await setAcquisitionShown(page, "focussing", true);
      await rest(1500);
      await shot(page, "scan-done-with-focus-stacks");
      await expect(page.locator("#canvas-axes")).toBeHidden();
      await setAcquisitionShown(page, "focussing", false);
      /* The row's chips: the overview's channels, each a dot and a name.
         The dot hides the channel; the name chooses it and opens Display
         settings, where its histogram is. */
      await expect(page.locator("#acquisition-name")).toHaveText("overview");
      await expect(page.locator("#acquisition-btn .bar-word")).toHaveText("acquisitions");
      const chips = page.locator("#canvas-chips .chip");
      await expect.poll(() => chips.count(), { timeout: 30_000 }).toBeGreaterThan(1);
      /* The list of acquisitions, with an eye each. Pressed on the name:
         the press also holds the ramp chip, which is a press of its own,
         and a press dead in the middle of the strip lands on it. */
      await page.locator("#acquisition-name").click();
      await expect(page.locator("#acquisition-menu")).toBeVisible();
      await rest(400);
      await shot(page, "scan-done-acquisitions");
      await page.keyboard.press("Escape");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      /* A press on a channel's dot hides the channel at once: the chip
         fades, crossed, no box opens, and the picture changes -- proved on
         the pixels. Again, back. */
      const withEveryChannel = await photograph(page, "#picture-host", 0.6);
      await chips.nth(1).locator(".chip-dot").click();
      await expect(chips.nth(1)).toHaveClass(/\boff\b/);
      await expect(page.locator("#channel-pop")).toBeHidden();
      await rest(800);
      await shot(page, "scan-done-channel-hidden");
      const withoutOne = await photograph(page, "#picture-host", 0.6);
      expect(differenceOf(withEveryChannel, withoutOne), "hiding channel 2 changes the picture").toBeGreaterThan(2);
      await chips.nth(1).locator(".chip-dot").click();
      await expect(chips.nth(1)).toHaveClass(/\bon\b/);
      /* The triangle beside the dot opens the channel's box under the row:
         with its eye and histogram.
         The box's eye and the dot are one state: the eye hides the channel
         and the chip fades, crossed; again, back. */
      await chips.nth(1).locator(".chip-more").click();
      await expect(chips.nth(1)).toHaveClass(/\bchosen\b/);
      await expect(page.locator("#channel-pop")).toBeVisible();
      await rest(1200);
      await shot(page, "scan-done-channel-box");
      const boxEye = page.locator("#channel-pop button[aria-pressed]").first();
      await boxEye.click();
      await expect(chips.nth(1)).toHaveClass(/\boff\b/);
      await boxEye.click();
      await expect(chips.nth(1)).toHaveClass(/\bon\b/);
      await page.keyboard.press("Escape");
      await expect(page.locator("#channel-pop")).toBeHidden();
      /* The column beside the canvas is the step's channel alone; the
         picture's settings are the row's boxes, and nowhere else. */
      await expect(page.locator(".side-tab button.tab")).toHaveCount(0);
      await expect(page.locator("#display-side")).toBeHidden();
      /* Grey on, then off: the same picture in grey and back, by the ramp
         chip inside the acquisition's press; the dots go grey with it. The
         chip is the layer's own switch, so the menu's line for this
         acquisition shows the same state, and pressing the chip there does
         not choose the acquisition or close the menu. */
      /* The eye in the press hides the acquisition the row is on, and the
         same press shows it again; the menu's line follows, and neither
         press opens the menu. */
      await expect(page.locator("#acquisition-eye")).toHaveAttribute("aria-pressed", "true");
      await page.locator("#acquisition-eye").click();
      await expect(page.locator("#acquisition-eye")).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      await page.locator("#acquisition-name").click();
      await expect(page.locator("#acquisition-menu .acquisition-line.chosen .acquisition-eye")).toHaveAttribute("aria-pressed", "false");
      await page.locator("#acquisition-name").click();
      await page.locator("#acquisition-eye").click();
      await expect(page.locator("#acquisition-eye")).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "false");
      await page.locator("#ramp-chip").click();
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      await page.locator("#acquisition-name").click();
      const chosenLineChip = page.locator("#acquisition-menu .acquisition-line.chosen .ramp-chip");
      await expect(chosenLineChip).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("#acquisition-menu .acquisition-count")).toHaveCount(0);
      await chosenLineChip.click();
      await expect(page.locator("#acquisition-menu")).toBeVisible();
      await expect(chosenLineChip).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "false");
      await chosenLineChip.click();
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "true");
      await page.keyboard.press("Escape");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      await rest(1200);
      await shot(page, "scan-done-grayscale");
      /* Grey is one channel: the dots give way to one chip, and its box
         holds one window and one opacity for the sum. */
      await expect(page.locator("#grey-chip")).toBeVisible();
      await expect(page.locator("#canvas-chips")).toBeHidden();
      await page.locator("#grey-chip-more").click();
      await expect(page.locator("#grey-pop")).toBeVisible();
      await rest(600);
      await shot(page, "scan-done-grey-box");
      await page.locator('#grey-pop input[aria-label^="min of"]').evaluate((slider) => {
        slider.value = "20"; slider.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await rest(900);
      await shot(page, "scan-done-grey-windowed");
      /* The box has the same handles as a colour channel's: a number typed
         into the max box moves its slider, the wheel zooms the histogram
         and the axis boxes under it say what is on view. */
      const maxBox = page.locator('#grey-pop input[aria-label^="max value"]');
      await maxBox.fill("80");
      await maxBox.press("Enter");
      await expect(page.locator('#grey-pop input[aria-label^="max of"]')).toHaveValue("80");
      await page.locator("#grey-pop svg").hover();
      await page.mouse.wheel(0, -300);
      await rest(300);
      const axisFrom = parseFloat(await page.locator('#grey-pop input[aria-label^="axis from"]').inputValue());
      const axisTo = parseFloat(await page.locator('#grey-pop input[aria-label^="axis to"]').inputValue());
      expect(axisTo - axisFrom).toBeLessThan(100);
      await page.locator("#grey-pop svg").dblclick();
      await expect(page.locator('#grey-pop input[aria-label^="axis to"]')).toHaveValue("100%");
      await rest(300);
      await shot(page, "scan-done-grey-typed");
      await page.keyboard.press("Escape");
      await expect(page.locator("#grey-pop")).toBeHidden();
      const greyPicture = await photograph(page, "#picture-host", 0.6);
      await page.locator("#ramp-chip").click();
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#canvas-chips")).toBeVisible();
      await expect(page.locator("#grey-chip")).toBeHidden();
      await rest(1200);
      await shot(page, "scan-done-color-again");
      /* Proved on the pixels, not the button: in grey the three channels of
         a pixel agree; in colour they do not. */
      const colourPicture = await photograph(page, "#picture-host", 0.6);
      /* Against each other, not against zero: the plan's blue stands on
         the six tiles the test scan did not take, in both pictures alike. */
      expect(chromaOf(colourPicture) - chromaOf(greyPicture), "grey means grey").toBeGreaterThan(15);
      expect(chromaOf(colourPicture), "colour came back").toBeGreaterThan(20);

      /* Step 6: one tile through the real detection. Running it draws the
         overview in grey, for the masks to stand on quiet ground. */
      await walkTo(page, "Detect objects");
      await rest(800);
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "false");
      await shot(page, "detect-before");
      /* A press on a field on the picture makes it the field the preview
         shows: the picker says which, and the picture is that field's. */
      const shownBefore = await page.evaluate(() => document.querySelector(".tile-picture canvas")?.dataset.picture ?? "");
      const second = await page.evaluate(() => {
        const t = window.__theStageCanvas.plan()[1];
        const p = window.__theStageCanvas.project(t.x, t.y);
        return Array.isArray(p) ? { x: p[0], y: p[1] } : p;
      });
      const stageBox = await page.locator("#stage-canvas").boundingBox();
      await page.mouse.move(stageBox.x + second.x, stageBox.y + second.y);
      await page.mouse.click(stageBox.x + second.x, stageBox.y + second.y);
      await expect(page.locator("#tile-label")).toHaveText(/^2 \//);
      await expect.poll(() => page.evaluate(() => document.querySelector(".tile-picture canvas")?.dataset.picture ?? ""),
        "the preview shows the pressed field").not.toBe(shownBefore);
      await page.getByRole("button", { name: "Test detection on this tile" }).click();
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "true");
      await expect.poll(async () => {
        const state = await ask(page, PORT, "/api/targets/discover");
        return !state.running && (state.error || ((state.fields?.length ?? 0) + (state.failed?.length ?? 0)) >= 1);
      }, { timeout: 900_000, message: "the tile test never answered" }).toBeTruthy();
      const tried = await ask(page, PORT, "/api/targets/discover");
      const blocked = tried.error ?? tried.failed?.[0]?.why ?? null;
      await rest(1000);
      if (blocked) {
        /* The panel shows the analysis's own sentence, not a page error. */
        await expect(page.locator("#detect-readout")).toContainText(/pipeline failed|Cellpose|not examined/);
        await shot(page, "detect-blocked-here");
        console.log(`detection is unavailable on this machine: ${blocked}`);
      } else {
        await shot(page, "detect-tile-tested");
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 1_500_000 });
        await rest(1500);
        const found = await page.evaluate(() => window.__theStageCanvas.targets());
        expect(found.length, "detection placed candidates on the canvas").toBeGreaterThan(0);
        await shot(page, "detect-done");
        /* The masks' bar stands at the right of the row only while
           detection has laid a mask layer on the picture the row shows:
           headed MASK, one cell wearing the layer's dress. The cell hides
           and shows the layer; the triangle beside it opens the layer's
           card, named for what it outlines and how. Hidden and shown again
           from the card's eye and from the cell, then dressed: one colour,
           outline only, fainter. */
        await expect(page.locator("#canvas-masks .bar-word")).toHaveText("masks");
        const maskCell = page.locator("#canvas-masks .mask-cell").first();
        await expect(maskCell).toBeVisible();
        await maskCell.locator(".chip-more").click();
        await expect(page.locator("#mask-pop")).toBeVisible();
        await expect(page.locator("#mask-pop-name")).toHaveText("nuclei, fast");
        await shot(page, "detect-mask-card");
        await page.locator("#mask-eye").click();
        await expect(maskCell).toHaveClass(/\boff\b/);
        await rest(800);
        await shot(page, "detect-mask-hidden");
        await page.locator("#mask-eye").click();
        await expect(maskCell).toHaveClass(/\bon\b/);
        await maskCell.locator(".mask-dot").click();
        await expect(maskCell).toHaveClass(/\boff\b/);
        await maskCell.locator(".mask-dot").click();
        await expect(maskCell).toHaveClass(/\bon\b/);
        await rest(500);
        await page.locator("#mask-picker").fill("#ffd400");
        await page.locator("#mask-line").click();
        await page.locator("#mask-opacity").evaluate((slider) => {
          slider.value = "60";
          slider.dispatchEvent(new Event("input", { bubbles: true }));
        });
        await rest(900);
        await shot(page, "detect-mask-dressed");
        await page.keyboard.press("Escape");
        await expect(page.locator("#mask-pop")).toBeHidden();
        /* The bar follows the picture, not the row: the masks lie on the
           overview, which stays on the picture whichever acquisition the
           row names, so the bar stays with the row on the focus stack and
           on the overview alike. A mask on the picture always has its chip. */
        await page.locator("#acquisition-name").click();
        await page.locator("#acquisition-menu .acquisition-choose", { hasText: "focussing" }).click();
        await expect(page.locator("#canvas-masks")).toBeVisible();
        await page.locator("#acquisition-name").click();
        await page.locator("#acquisition-menu .acquisition-choose", { hasText: "overview" }).click();
        await expect(page.locator("#canvas-masks")).toBeVisible();
        /* Tile: the view brought in on the one field the frame is on. */
        await expect(page.locator("#tile-btn")).toBeEnabled();
        await page.locator("#tile-btn").click();
        await rest(1500);
        await shot(page, "detect-tile-framed");

        /* The masks land on their nuclei. Photographed off the screen, the
           way the operator sees them: once with the masks solid red and
           once without, and the shift that lays the red over the bright
           nuclei has to be nothing. A drawing a few pixels off reads as a
           rim of nucleus beside every mask, and that is exactly what the
           operator reported. */
        await page.locator("#canvas-masks .mask-cell").first().locator(".chip-more").click();
        await expect(page.locator("#mask-pop")).toBeVisible();
        await page.locator("#mask-picker").fill("#ff0000");
        await page.locator("#mask-fill").click();
        await page.locator("#mask-opacity").evaluate((slider) => {
          slider.value = "100";
          slider.dispatchEvent(new Event("input", { bubbles: true }));
        });
        await rest(900);
        /* At the field's own zoom and at zooms either side of it, since the
           engine draws a different stored resolution at each. */
        const framed = await page.evaluate(() => window.__theStageCanvas.view());
        for (const times of [0.5, 1, 2, 4]) {
          await page.evaluate((view) => window.__theStageCanvas.lookAt(view),
            { zoom: framed.zoom * times, centre: framed.centre });
          await rest(1200);
          const withMasks = await photograph(page, "#picture-host", 0.6);
          await page.locator("#mask-eye").click();
          await rest(900);
          const withoutMasks = await photograph(page, "#picture-host", 0.6);
          await page.locator("#mask-eye").click();
          await rest(300);
          const { width, height, channels } = withMasks;
          const masks = new Uint8Array(width * height);
          const nuclei = new Uint8Array(width * height);
          for (let i = 0; i < width * height; i++) {
            const a = i * channels;
            const [r, g, b] = [withMasks.data[a], withMasks.data[a + 1], withMasks.data[a + 2]];
            masks[i] = r > 150 && g < 110 && b < 110 ? 1 : 0;
            const bright = Math.max(withoutMasks.data[a], withoutMasks.data[a + 1], withoutMasks.data[a + 2]);
            nuclei[i] = bright > 90 ? 1 : 0;
          }
          const shift = bestShift(masks, nuclei, width, height, 12);
          console.log(`at ${(framed.zoom * times).toFixed(3)} um/px (${times}x the field zoom): masks over nuclei dx=${shift.dx} dy=${shift.dy} px = ${(shift.dx * framed.zoom * times).toFixed(2)},${(shift.dy * framed.zoom * times).toFixed(2)} um, overlap ${shift.score.toFixed(2)}`);
        }
        await page.evaluate((view) => window.__theStageCanvas.lookAt(view), framed);
        await rest(900);
        const withMasks = await photograph(page, "#picture-host", 0.6);
        await page.locator("#mask-eye").click();
        await rest(900);
        const withoutMasks = await photograph(page, "#picture-host", 0.6);
        await page.locator("#mask-eye").click();
        await page.keyboard.press("Escape");
        await rest(500);
        {
          const { width, height, channels } = withMasks;
          const masks = new Uint8Array(width * height);
          const nuclei = new Uint8Array(width * height);
          for (let i = 0; i < width * height; i++) {
            const a = i * channels;
            const [r, g, b] = [withMasks.data[a], withMasks.data[a + 1], withMasks.data[a + 2]];
            masks[i] = r > 150 && g < 110 && b < 110 ? 1 : 0;
            const bright = Math.max(withoutMasks.data[a], withoutMasks.data[a + 1], withoutMasks.data[a + 2]);
            nuclei[i] = bright > 90 ? 1 : 0;
          }
          const shift = bestShift(masks, nuclei, width, height, 12);
          console.log(`masks over nuclei: best shift dx=${shift.dx} dy=${shift.dy} px, overlap ${shift.score.toFixed(2)}`);
          /* The same question asked of each quarter: a shift that is the
             same everywhere is a displacement; one that grows away from the
             middle is a scale. */
          const hw = Math.floor(width / 2), hh = Math.floor(height / 2);
          for (const [name, x0, y0] of [["top-left", 0, 0], ["top-right", hw, 0], ["bottom-left", 0, hh], ["bottom-right", hw, hh]]) {
            const a = new Uint8Array(hw * hh), b = new Uint8Array(hw * hh);
            for (let y = 0; y < hh; y++) for (let x = 0; x < hw; x++) {
              a[y * hw + x] = masks[(y + y0) * width + x + x0];
              b[y * hw + x] = nuclei[(y + y0) * width + x + x0];
            }
            const q = bestShift(a, b, hw, hh, 12);
            console.log(`  ${name}: dx=${q.dx} dy=${q.dy} overlap ${q.score.toFixed(2)}`);
          }
          expect(shift.score, "the masks lie over nuclei at all").toBeGreaterThan(0.3);
          expect(Math.abs(shift.dx), "masks sit on their nuclei across").toBeLessThanOrEqual(1);
          expect(Math.abs(shift.dy), "masks sit on their nuclei down").toBeLessThanOrEqual(1);
        }
        await framePlan(page);

        /* Step 7: a gate drawn on the feature plot, around most of the cloud. */
        await walkTo(page, "Discover Targets");
        await shot(page, "discover-before");
        const sc = await page.locator("#scatter-canvas").boundingBox();
        const polygon = [[0.2, 0.08], [0.98, 0.08], [0.98, 0.85], [0.2, 0.85]];
        for (const [gx, gy] of polygon) {
          await page.mouse.click(...plotPoint(sc, gx, gy));
          await rest(150);
        }
        await page.mouse.click(...plotPoint(sc, polygon[0][0], polygon[0][1]));
        await rest(600);
        await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
        await shot(page, "discover-gated");
        /* Complex feature dimensions: on screen, greyed out, saying so. A
           gate on those axes could not be carried by a protocol. */
        await expect(page.locator("#reduction .side-group-title")).toHaveText("Complex feature dimensions");
        await expect(page.locator("#reduce-pca")).toBeDisabled();
        await expect(page.locator("#reduce-umap")).toBeDisabled();
        await expect(page.locator("#reduce-compute")).toBeDisabled();
        await expect(page.locator("#reduction .reduce-note")).toHaveText("not available yet");
        await expect(page.locator('#gate-fx option[value="pca_1"]')).toHaveCount(0);
        await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);

        /* Step 8: the target job, its optics recorded, a cap per tileset,
           and the scan areas placed. */
        await walkTo(page, "Target scan area");
        inTheInstrument.choose("Target");
        await shot(page, "target-area-before");
        if (await page.locator("#target-type .setting-box.done").count() === 0) {
          await page.locator("#target-type .setting-box.open button.run").click();
          await rest(700);
        }
        await page.locator("#gate-max").fill("3");
        await page.locator("#gate-max").dispatchEvent("input");
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
        await rest(800);
        await shot(page, "target-area-placed");
        await framePlan(page);
        await shot(page, "target-area-placed-picture");

        /* Step 9: the targets acquired, one capture per scan area placed. */
        const overviewInGrey = () =>
          page.evaluate(() => Boolean(window.__viewerPanel?.acquisitionGrey?.("overview")));
        expect(await overviewInGrey()).toBe(true);
        await walkTo(page, "Acquire Targets");
        await shot(page, "acquire-before");
        /* Focussing before each target: its own job, imported under the
           switch, at the targets' magnification. The mock's focussing job
           is the map's, and the line says so. */
        /* The target acquisition settings are Step 8's; Step 9 does not
           show them again. */
        await expect(page.locator(".panel.on .side-group-title", { hasText: "Target acquisition settings" })).toHaveCount(0);
        await expect(page.locator("#target-focus-recording")).toBeHidden();
        await page.locator("#target-focus-on").check();
        await expect(page.locator("#target-focus-recording")).toBeVisible();
        inTheInstrument.choose("Focussing");
        await record(page, "target-focus-recording", "target af");
        await expect(page.locator("#target-focus-recording .rec-warn").first())
          .toContainText("Same job as the focus map's");
        await shot(page, "acquire-focus-same-job");
        /* The fine job at the targets' magnification, imported over it:
           the warning goes with the job it was about. */
        inTheInstrument.choose("Target focussing");
        await record(page, "target-focus-recording", "target af");
        await expect(page.locator("#target-focus-recording .rec-warn")).toHaveCount(0);
        /* Unticked, the box goes back to how it was before the first tick:
           ticked again, there is no focussing job until one is imported. */
        await expect(page.locator("#target-focus-recording .rec-row")).toHaveCount(1);
        await page.locator("#target-focus-on").uncheck();
        await expect(page.locator("#target-focus-recording")).toBeHidden();
        await page.locator("#target-focus-on").check();
        await expect(page.locator("#target-focus-recording .rec-row")).toHaveCount(0);
        await record(page, "target-focus-recording", "target af");
        await expect(page.locator("#target-focus-recording .rec-row")).toHaveCount(1);
        /* The Z offset, in its own box: every target is taken that much
           above the peak its stack found. */
        await expect(page.locator("#target-offset .side-group-title")).toHaveText("Target Z offset");
        await page.locator("#target-z-offset").fill("2");
        await page.locator("#target-z-offset").dispatchEvent("input");
        await shot(page, "acquire-focus-on");
        /* The overview went grey for the masks; arriving here the operator
           wants to see the sample again, so it is back in colour. */
        expect(await overviewInGrey()).toBe(false);
        /* The overview's masks keep their strip on the acquisition step,
           and the targets' cell is there too, its eye pressed off on the
           way in so the frames' pixels are not hidden under lit shapes. */
        await expect(page.locator("#canvas-masks")).toBeVisible();
        const targetsCell = page.locator('#canvas-masks .mask-cell[data-mask="targets"]');
        await expect(targetsCell).toBeVisible();
        await expect(targetsCell.locator(".mask-dot")).toHaveAttribute("aria-pressed", "false");
        await expect(targetsCell.locator(".chip-more")).toBeVisible();
        const tilesCell = page.locator('#canvas-masks .mask-cell[data-mask="tiles"]');
        await expect(tilesCell).toBeVisible();
        await expect(tilesCell.locator(".mask-dot")).toHaveAttribute("aria-pressed", "false");
        await page.locator(".panel.on button.step-run").click();
        try {
          await expect(page.locator(".panel.on button.step-run")).toHaveText("Rerun all", { timeout: 300_000 });
        } catch (why) {
          /* The box's own account of a run that failed, beside the assertion. */
          console.log(`the acquisition box says: ${await page.locator("#acquire-doing").textContent()}`);
          throw why;
        }
        await rest(2000);
        const run = await page.evaluate(() => window.__theRunState());
        expect(run.acquiredTileKeys.length, "one capture per target tile").toBe(run.targetTiles);
        expect(run.targetTiles).toBeGreaterThan(0);
        /* Every target was focussed first, and its record says at what height. */
        expect(run.targetFocusOn).toBe(true);
        const focussed = Object.values(run.acquiredFocus);
        expect(focussed.length).toBe(run.targetTiles);
        expect(focussed.every((one) => one && one.found === true && Number.isFinite(one.z_peak_um)),
          "each target imaged at a peak of its own stack").toBe(true);
        await page.waitForFunction(() => window.__thePicture.layersForMeasurement().some(
          row => row.name.startsWith("targets/") && row.dims?.length,
        ));
        expect(await page.evaluate(() => window.connectedPicture === window.__thePicture),
          "target rows keep the same viewer and its existing images").toBe(true);
        await expect(page.locator(".layer-fade input")).toHaveValue("100");
        expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);
        const acquired = await ask(page, PORT, "/api/targets/acquire");
        expect(acquired.error).toBeNull();
        expect(acquired.records.filter(record => record.zarr_error)).toEqual([]);
        expect(acquired.records.length, "the ledger holds a record a tile").toBe(run.targetTiles);
        for (const one of acquired.records) {
          expect(one.requested_position_um.z - one.focus.z_peak_um, "taken 2 µm above the peak").toBeCloseTo(2, 6);
        }
        /* A tile chosen in the list is where the operator is looking: the
           picture centres on it at the zoom in hand and Tile frames it; Tile
           set frames the tileset it lies in. Carrier is untouched by any of it. */
        const rowsOfTargets = page.locator("#target-list .point-row");
        if (run.targetTilePositions.length > 1) {
          const [first, second] = run.targetTilePositions;
          await page.evaluate(() => { const v = window.__theStageCanvas.view(); window.__theStageCanvas.lookAt({ zoom: v.zoom * 4, centre: v.centre }); });
          await rest(400);
          const wide = await page.evaluate(() => window.__theStageCanvas.view());
          await rowsOfTargets.first().locator("button").click();
          await rest(400);
          const centred = await page.evaluate(() => window.__theStageCanvas.view());
          expect(Math.hypot(centred.centre.x - first.x, centred.centre.y - first.y),
            "choosing a row centres the picture on its tile").toBeLessThan(1);
          expect(centred.zoom, "at the zoom in hand").toBeCloseTo(wide.zoom, 6);
          await page.locator("#tile-btn").click();
          await rest(400);
          const framed = await page.evaluate(() => window.__theStageCanvas.view());
          expect(framed.zoom, "Tile frames the chosen tile").toBeLessThan(wide.zoom);
          expect(Math.hypot(framed.centre.x - first.x, framed.centre.y - first.y)).toBeLessThan(1);
          /* Pressed again, Tile frames the same field: which field is current
             is chosen in the list or on the canvas, never by the press. */
          await page.locator("#tile-btn").click();
          await rest(400);
          const again = await page.evaluate(() => window.__theStageCanvas.view());
          expect(Math.hypot(again.centre.x - first.x, again.centre.y - first.y),
            "Tile again frames the same field").toBeLessThan(1);
          void second;
          await shot(page, "acquire-tile-from-the-list");
        }
        await expect.poll(async () => (await ask(page, PORT, "/api/viewer")).error,
          { timeout: 60_000 }).toBeNull();
        await expect.poll(async () => (await ask(page, PORT, "/api/viewer")).publications.targets,
          { timeout: 60_000 }).toEqual({ acquired: run.targetTiles, published: run.targetTiles,
            state: "ready", error: null });
        await rest(3000);
        const publication = await ask(page, PORT, "/api/viewer");
        expect(publication.acquisitions.some(a => a.name === "targets")).toBe(true);
        for (const acquisition of publication.acquisitions) for (const row of acquisition.channels) {
          expect(row.sources.length).toBe(1);
          expect(row.view.acquisition).toBe(acquisition.name);
          expect(row.sources.every(source => decodeURIComponent(source).includes(".zmartview.zarr/"))).toBe(true);
        }
        expect(imageRequests.length).toBeGreaterThan(0);
        expect(imageRequests.every(url => decodeURIComponent(url).includes(".zmartview.zarr/"))).toBe(true);
        await shot(page, "acquire-done");
        await framePlan(page);
        await shot(page, "acquire-done-picture");
        await rest(2500);
        const beforeIdle = imageRequests.length;
        await rest(3200);
        expect(imageRequests.length, "idle publication polling does not refetch images").toBe(beforeIdle);
        console.log({ bake, aggregateImageRequests: beforeIdle, idleImageRequests: 0 });
      }

      /* Step 10. Nothing is orange after a run done in order, so the press
         is live. A setting edited above -- the detection threshold -- turns
         every done step below it orange and the press waits on them by
         name; Accept all turns them green again. */
      if (await page.locator('.step.done:has-text("Acquire Targets")').count()) {
        await walkTo(page, "Run protocol");
        await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
        /* The settings can be written as the protocol without a run. */
        await page.locator("#protocol-export").click();
        await expect(page.locator("#protocol-export-note")).toHaveText("protocol written");
        expect((await ask(page, PORT, "/api/protocols")).protocols).toHaveLength(1);
        /* And saved by name into the machine's library: listed with the run's. */
        await page.locator("#protocol-save-name").fill("walk kidney");
        await page.locator("#protocol-save").click();
        await expect(page.locator("#protocol-export-note")).toHaveText("saved as walk kidney");
        expect((await ask(page, PORT, "/api/protocols")).protocols.map((one) => one.id)).toContain("walk kidney");
        await shot(page, "protocol-before");
        await walkTo(page, "Detect objects");
        await page.locator("#detect-threshold").fill("120");
        await page.locator("#detect-threshold").dispatchEvent("input");
        await rest(300);
        await expect(page.locator(".step.stale")).toHaveCount(3);
        await expect(page.locator('.step.stale:has-text("Detect objects")')).toHaveCount(0);
        await expect(page.locator('.step.stale:has-text("Acquire Targets")')).toHaveCount(1);
        await shot(page, "protocol-orange");
        /* No pill on the rail; Step 10 is never orange itself, its press
           waits greyed, and one press in its box confirms everything. */
        await expect(page.locator(".confirm-mini")).toHaveCount(0);
        await expect(page.locator(".step.stale .review-tag")).toHaveCount(3);
        await expect(page.locator('.step.stale:has-text("Run protocol")')).toHaveCount(0);
        await walkTo(page, "Run protocol");
        await expect(page.locator(".panel.on button.step-run")).toBeDisabled();
        await expect(page.locator("#protocol-accept")).toHaveText("Confirm all settings");
        await page.locator("#protocol-accept").click();
        await expect(page.locator(".step.stale")).toHaveCount(0);
        await expect(page.locator("#protocol-accept")).toHaveCount(0);
        await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
        /* The run: the rail follows it step by step, the canvas answers a
           pan while it runs, and it ends green with the protocol written. */
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator('.step:has(.step-name:text-is("Scan the overview")) .spin')).toBeVisible({ timeout: 600_000 });
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Interrupt");
        /* The focus map stands, so the run has four steps; the ones not
           reached yet are not done; the bar under Step 10 says where it is. */
        await expect(page.locator("#protocol-progress-line")).toContainText("step 1 of 4 · Scan the overview");
        await expect(page.locator('.step.done:has-text("Detect objects")')).toHaveCount(0);
        await expect(page.locator('.step.done:has-text("Acquire Targets")')).toHaveCount(0);
        await expect(page.locator('.step.done:has-text("Focus strategy")')).toHaveCount(1);
        await shot(page, "protocol-running-scan");
        const before = await page.evaluate(() => window.__theStageCanvas.view());
        await page.evaluate(() => { const v = window.__theStageCanvas.view();
          window.__theStageCanvas.lookAt({ zoom: v.zoom, centre: { x: v.centre.x + 500, y: v.centre.y } }); });
        await rest(300);
        const moved = await page.evaluate(() => window.__theStageCanvas.view());
        expect(moved.centre.x - before.centre.x, "the canvas answers the hand mid-run").toBeGreaterThan(400);
        await expect(page.locator('.step.done:has-text("Run protocol")')).toBeVisible({ timeout: 1_500_000 });
        await expect(page.locator(".step.stale")).toHaveCount(0);
        /* The numbers, Rerun protocol, and Rerun confetti at its right. */
        await expect(page.locator("#protocol-stats")).toContainText("Targets acquired");
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Rerun protocol");
        await expect(page.locator("#protocol-again")).toHaveText("Rerun confetti");
        /* The burst is on a canvas that has its size, and paints something. */
        await rest(400);
        expect(await page.evaluate(() => {
          const cv = document.querySelector("canvas.protocol-burst");
          if (!cv || !cv.width || !cv.height) return 0;
          const data = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data;
          let lit = 0;
          for (let at = 3; at < data.length; at += 4) if (data[at]) lit += 1;
          return lit;
        }), "confetti on the canvas").toBeGreaterThan(20);
        await shot(page, "protocol-confetti");
        await rest(1800);
        const whole = await ask(page, PORT, "/api/scan");
        expect(whole.done, "the protocol scanned the whole plan").toBe(plan.length);
        const written = await ask(page, PORT, "/api/protocols");
        /* The run's own, and the one saved by name earlier. */
        expect(written.protocols.map((one) => one.id).sort()).toEqual(
          [...written.protocols.filter((one) => one.id.startsWith("target-acquisition_")).map((one) => one.id), "walk kidney"].sort());
        const ofTheRun = written.protocols.find((one) => one.id.startsWith("target-acquisition_"));
        expect(ofTheRun.protocol.testTiles.tiles).toHaveLength(3);
        expect(ofTheRun.protocol.detect.threshold).toBe(120);
        expect(ofTheRun.protocol.targetZOffsetUm).toBe(2);
        await shot(page, "protocol-done");

        /* A fresh session opened on it: every step's settings are back, and
           every step but Connect is orange, to be confirmed on this sample. */
        await walkTo(page, "Connect");
        await page.locator(".panel.on .session-buttons button.danger").click();
        await rest(1500);
        /* The protocol is chosen before the session opens, from the list
           the machine gives without one, and locks with the row after. */
        /* New, the run's, the saved one, and Load from file. */
        await expect(page.locator("#protocol-pick option")).toHaveCount(4, { timeout: 30_000 });
        await expect(page.locator("#protocol-pick")).toBeEnabled();
        /* A file of the operator's own: the saved protocol written to disk
           and picked through the file input. */
        const fromDisk = path.join(home, "mine.json");
        fs.writeFileSync(fromDisk, JSON.stringify(ofTheRun.protocol));
        await page.locator("#protocol-file").setInputFiles(fromDisk);
        await rest(600);
        await expect(page.locator("#protocol-pick")).toHaveValue("mine");
        await page.locator("#protocol-pick").selectOption(ofTheRun.id);
        await rest(500);
        await page.locator(".panel.on .session-buttons button.run").click();
        await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
        await expect(page.locator("#protocol-pick")).toBeDisabled();
        await rest(800);
        await expect(page.locator("#protocol-note")).toBeHidden();
        /* Only Connect is green; 2, 3 and 4 remember the file and turn green
           as they are stepped onto; settling the focus strategy brings 5-10
           back, orange. */
        await expect(page.locator(".step.done")).toHaveCount(1);
        await expect(page.locator(".step.stale")).toHaveCount(0);
        const reopened = await page.evaluate(() => window.__theRunState());
        expect(reopened.testTiles).toHaveLength(3);
        expect(reopened.focus.points).toBeGreaterThan(0);
        await shot(page, "protocol-reopened");
        await walkTo(page, "Define Carrier");
        await expect(page.locator(".step.done")).toHaveCount(2);
        await walkTo(page, "Overview scan area");
        /* No reading comes back from the file: the optical configuration
           is imported afresh, and only then is the area's plan laid. */
        await expect(page.locator("#sf-preset .setting-box.done")).toHaveCount(0);
        await expect(page.locator(".step.done")).toHaveCount(2);
        inTheInstrument.choose("Overview");
        await record(page, "sf-preset", "overview");
        await expect(page.locator(".step.done")).toHaveCount(3);
        await expect(page.locator(".step.stale")).toHaveCount(0);
        await walkTo(page, "Focus strategy");
        await expect(page.locator("#focus-preset .setting-box.done")).toHaveCount(0);
        inTheInstrument.choose("Focussing");
        await record(page, "focus-preset", "af");
        /* Green only once the map has been run: Scan the overview waits. */
        await expect(page.locator(".step.done")).toHaveCount(3);
        await expect(page.locator('.step:has-text("Scan the overview")')).toBeDisabled();
        await expect(page.locator(".step.stale")).toHaveCount(0);
        /* Only a focus map measured on this sample brings the rest back. */
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
        await expect(page.locator(".step.done")).toHaveCount(10);
        await expect(page.locator(".step.stale")).toHaveCount(6);
        await expect(page.locator('.step.stale:has-text("Scan the overview")')).toHaveCount(1);
        /* The loaded gate is on view without a single object on this sample. */
        await walkTo(page, "Discover Targets");
        await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
        await page.locator("#gate-list .gate-open").first().click();
        await expect(page.locator("#gate-fx")).toHaveValue("intensity_mean");
        await expect(page.locator("#gate-fy")).toHaveValue("eccentricity");
        await shot(page, "protocol-reopened-gate");
        await shot(page, "protocol-reopened-rest-orange");
        await walkTo(page, "Scan the overview");
        await expect(page.locator("#test-tiles-count")).toHaveAttribute("data-green", "3");
        await shot(page, "protocol-reopened-test-tiles");
        /* Run on this sample from the loaded settings: the target frame
           comes from the loaded recording, so scan areas are placed. */
        await walkTo(page, "Scan the overview");
        /* Nothing green, nothing to scan: the press waits for tiles. */
        await page.locator("#test-clear").click();
        await expect(page.locator(".panel.on button.step-run")).toBeDisabled();
        await page.locator("#test-n").fill("3");
        await page.locator("#test-random").click();
        await rest(300);
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 400_000 });
        await walkTo(page, "Detect objects");
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
        await walkTo(page, "Discover Targets");
        await expect(page.locator('.step.stale:has-text("Discover Targets")')).toHaveCount(0);
        await walkTo(page, "Target scan area");
        await expect(page.locator(".panel.on button.step-run")).toBeDisabled();
        inTheInstrument.choose("Target");
        await record(page, "target-type", "target");
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
        await rest(800);
        expect((await page.evaluate(() => window.__theRunState())).targetTiles, "tiles placed from loaded settings").toBeGreaterThan(0);
        await shot(page, "protocol-reopened-placed");
      }

      await walkTo(page, "Connect");
      await shot(page, "rail-at-the-end");
      expect(errors, "the page raised no errors").toEqual([]);
    } finally {
      await bridge.stop();
    }
  });
});
