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
 * All nine steps are walked: connect, the carrier, the overview plan, the
 * focus map measured through the analysis, the overview scanned onto the
 * picture, objects detected on it with the page's fast method, a gate drawn
 * on the feature plot, scan areas placed under a cap, and the targets
 * acquired. Where detection cannot run on the machine the walk keeps the
 * page's own reason on screen and stops there, since the last three steps
 * stand on what detection finds. Set `OPERATOR_EVIDENCE_DIR` to keep a
 * screenshot of every screen the operator sees.
 */
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { operateTheInstrument, rest, showDisplaySettings, showTheChannel, startTheBridge }
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
const A_WHOLE_WALK = 900_000;

/* The mock keeps its instrument state in a file named by the environment. A
   folder of its own, so the walk starts from a machine nobody has touched
   and leaves nothing behind in anyone's home. The machine folder is left to
   the mock's default: the bridge connects on the configuration it holds. */
const home = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-acquisition-"));
process.env.ZMART_MOCK_STATE = path.join(home, "instrument.json");

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

  test("from Connect to acquired targets, every screen on the way", async ({ page }) => {
    const bridge = await startTheBridge({ port: PORT });
    const errors = [];
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
         the plan's first field, and pressed again while that field is in
         the middle walks on to the next in reading order. */
      await expect(page.locator("#tile-btn")).toBeEnabled();
      await page.locator("#tile-btn").click();
      await rest(400);
      const onTheFirst = await page.evaluate(() => window.__theStageCanvas.view());
      expect(Math.hypot(onTheFirst.centre.x - plan[0].x, onTheFirst.centre.y - plan[0].y),
        "Tile frames the first field").toBeLessThan(1);
      await page.locator("#tile-btn").click();
      await rest(400);
      const onTheSecond = await page.evaluate(() => window.__theStageCanvas.view());
      const next = plan[Math.min(1, plan.length - 1)];
      expect(Math.hypot(onTheSecond.centre.x - next.x, onTheSecond.centre.y - next.y),
        "Tile again walks to the next field").toBeLessThan(1);
      expect(onTheSecond.zoom).toBeCloseTo(onTheFirst.zoom, 6);
      await shot(page, "overview-area-second-tile");

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
      await page.locator(".panel.on button.step-run").click();
      await expect.poll(async () => (await ask(page, PORT, "/api/scan")).done, { timeout: 400_000 }).toBe(plan.length);
      await expect.poll(async () => !(await ask(page, PORT, "/api/scan")).running, { timeout: 400_000 }).toBe(true);
      const overview = await ask(page, PORT, "/api/scan");
      expect(overview).toMatchObject({ error: null, stopped: false, done: plan.length, of: plan.length });
      expect(overview.records).toHaveLength(plan.length);
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
      /* Under the picture: the picture is one room, as deep as the deepest
         stack shown in it. On the way to the scan the page pressed the focus
         stacks' eye off -- over the overview they are a square of other
         pixels -- so with only the flat overview shown there is no depth and
         no Z slider. Their eye pressed on gives the room its depth and the
         slider stands across the picture's foot; nothing here is a
         timelapse, so T does not. Moved to the top of the stack and back. */
      await expect(page.locator("#axis-z")).toBeHidden();
      await showDisplaySettings(page);
      const focusEye = page.locator('button[aria-label="toggle group focussing"]');
      await expect(focusEye).toHaveAttribute("aria-pressed", "false");
      await focusEye.click();
      await showTheChannel(page);
      await expect(page.locator("#axis-z")).toBeVisible({ timeout: 30_000 });
      await expect(page.locator("#axis-t")).toBeHidden();
      /* Every stack stands on the table, so the picture opens at the bottom
         plane; and the flat overview stays in view at the top of the stacks,
         as it lies on the table too. */
      await expect(page.locator("#plane-readout")).toContainText("plane 1 of");
      const atTheBottom = fractionLit(await photograph(page, "#picture-host", 1));
      expect(atTheBottom, "the overview is lit at the bottom").toBeGreaterThan(0.01);
      await page.locator("#plane").evaluate((s) => { s.value = s.max; s.dispatchEvent(new Event("input", { bubbles: true })); });
      await rest(1500);
      await shot(page, "scan-done-z-top");
      const atTheTop = fractionLit(await photograph(page, "#picture-host", 1));
      expect(atTheTop, "the overview is still lit at the top of the stacks").toBeGreaterThan(atTheBottom * 0.5);
      await page.locator("#plane").evaluate((s) => { s.value = s.min; s.dispatchEvent(new Event("input", { bubbles: true })); });
      await rest(800);
      /* And their eye pressed off again takes the depth with it: the room is
         only as deep as what is shown in it. */
      await showDisplaySettings(page);
      await focusEye.click();
      await showTheChannel(page);
      await expect(page.locator("#axis-z")).toBeHidden({ timeout: 10_000 });
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
         the very box Display settings shows, with its eye and histogram.
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
      /* The box is back in Display settings once the card has closed. */
      await page.locator(".side-tab .tab", { hasText: "Display settings" }).click();
      await rest(600);
      await expect(page.locator('#display-side input[type="range"]').first()).toBeVisible();
      await shot(page, "scan-done-channel-settings");
      await showTheChannel(page);
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
      expect(chromaOf(greyPicture), "grey means grey").toBeLessThan(4);
      expect(chromaOf(colourPicture), "colour came back").toBeGreaterThan(20);

      /* Step 6: one tile through the real detection. Running it draws the
         overview in grey, for the masks to stand on quiet ground. */
      await walkTo(page, "Detect objects");
      await rest(800);
      await expect(page.locator("#ramp-chip")).toHaveAttribute("aria-pressed", "false");
      await shot(page, "detect-before");
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
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Rerun all", { timeout: 300_000 });
        await rest(2000);
        const run = await page.evaluate(() => window.__theRunState());
        expect(run.acquiredTileKeys.length, "one capture per target tile").toBe(run.targetTiles);
        expect(run.targetTiles).toBeGreaterThan(0);
        await page.waitForFunction(() => window.__thePicture.layersForMeasurement().some(
          row => row.name.startsWith("targets/") && row.dims?.length,
        ));
        expect(await page.evaluate(() => window.connectedPicture === window.__thePicture),
          "target rows keep the same viewer and its existing images").toBe(true);
        await expect(page.locator(".layer-fade input")).toHaveValue("100");
        expect(await page.evaluate(() => window.__theStageCanvas.layerShown("ground"))).toBe(true);
        const acquired = await ask(page, PORT, "/api/scan");
        expect(acquired.error).toBeNull();
        expect(acquired.records.filter(record => record.zarr_error)).toEqual([]);
        await shot(page, "acquire-done");
        await framePlan(page);
        await shot(page, "acquire-done-picture");
      }

      await walkTo(page, "Connect");
      await shot(page, "rail-at-the-end");
      expect(errors, "the page raised no errors").toEqual([]);
    } finally {
      await bridge.stop();
    }
  });
});
