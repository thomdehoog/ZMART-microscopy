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
import { operateTheInstrument, rest, showTheChannel, startTheBridge }
  from "./steps/scan_the_overview/live-bridge.js";
import { fractionLit, photograph } from "./steps/scan_the_overview/pixels.js";

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

      /* Step 4: the focus job, points placed, every one measured. */
      await walkTo(page, "Focus strategy");
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
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 60_000 });
      await rest(3000);
      await shot(page, "scan-done");
      await page.evaluate(() => window.__theStageCanvas.fadeTo(0.15));
      await framePlan(page);
      await shot(page, "scan-done-picture");
      /* Under the picture: the focus stacks give it a depth, so the Z
         slider stands across its foot; nothing here is a timelapse, so T
         does not. Moved to the top of the stack and back. */
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
      /* The row's chips: the overview's channels, each a dot and a name.
         The dot hides the channel; the name chooses it and opens Display
         settings, where its histogram is. */
      await expect(page.locator("#acquisition-name")).toHaveText("overview");
      const chips = page.locator("#canvas-chips .chip");
      await expect.poll(() => chips.count(), { timeout: 30_000 }).toBeGreaterThan(1);
      /* The list of acquisitions, with an eye each. */
      await page.locator("#acquisition-btn").click();
      await expect(page.locator("#acquisition-menu")).toBeVisible();
      await rest(400);
      await shot(page, "scan-done-acquisitions");
      await page.keyboard.press("Escape");
      await expect(page.locator("#acquisition-menu")).toBeHidden();
      /* A press on a channel's dot opens its box under the row: the very
         box Display settings shows, with its eye and histogram. The eye
         hides the channel and the chip fades, crossed; again, back. */
      await chips.nth(1).locator(".chip-dot").click();
      await expect(chips.nth(1)).toHaveClass(/\bchosen\b/);
      await expect(page.locator("#channel-pop")).toBeVisible();
      await rest(1200);
      await shot(page, "scan-done-channel-box");
      const boxEye = page.locator("#channel-pop button[aria-pressed]").first();
      await boxEye.click();
      await expect(chips.nth(1)).toHaveClass(/\boff\b/);
      await rest(800);
      await shot(page, "scan-done-channel-hidden");
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
      /* Grey on, then off: the same picture in grey and back, by the switch
         in the canvas's row, tinted while on; the dots go grey with it. */
      await expect(page.locator("#grey-btn")).toHaveAttribute("aria-pressed", "false");
      await page.locator("#grey-btn").click();
      await expect(page.locator("#grey-btn")).toHaveAttribute("aria-pressed", "true");
      await rest(1200);
      await shot(page, "scan-done-grayscale");
      /* Grey is one channel: the dots give way to one chip, and its box
         holds one window and one opacity for the sum. */
      await expect(page.locator("#grey-chip")).toBeVisible();
      await expect(page.locator("#canvas-chips")).toBeHidden();
      await page.locator("#grey-chip-btn").click();
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
      await page.locator("#colour-btn").click();
      await expect(page.locator("#grey-btn")).toHaveAttribute("aria-pressed", "false");
      await expect(page.locator("#colour-btn")).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("#canvas-chips")).toBeVisible();
      await expect(page.locator("#grey-chip")).toBeHidden();
      await rest(1200);
      await shot(page, "scan-done-color-again");
      /* Proved on the pixels, not the button: in grey the three channels of
         a pixel agree; in colour they do not. */
      const colourPicture = await photograph(page, "#picture-host", 0.6);
      expect(chromaOf(greyPicture), "grey means grey").toBeLessThan(4);
      expect(chromaOf(colourPicture), "colour came back").toBeGreaterThan(20);

      /* Step 6: one tile through the real detection. */
      await walkTo(page, "Detect objects");
      await rest(800);
      await shot(page, "detect-before");
      await page.getByRole("button", { name: "Test this tile" }).click();
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
        /* The masks' chip stands in the row only while detection has laid
           them; its dot opens their card. Hidden and shown again, then
           dressed: one colour, outline only, fainter. */
        await expect(page.locator("#mask-btn")).toBeVisible();
        await page.locator("#mask-btn").click();
        await expect(page.locator("#mask-pop")).toBeVisible();
        await shot(page, "detect-mask-card");
        await page.locator("#mask-eye").click();
        await expect(page.locator("#mask-btn")).toHaveAttribute("aria-pressed", "false");
        await rest(800);
        await shot(page, "detect-mask-hidden");
        await page.locator("#mask-eye").click();
        await expect(page.locator("#mask-btn")).toHaveAttribute("aria-pressed", "true");
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
        /* Tile: the view brought in on the one field the frame is on. */
        await expect(page.locator("#tile-btn")).toBeEnabled();
        await page.locator("#tile-btn").click();
        await rest(1500);
        await shot(page, "detect-tile-framed");
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
        await walkTo(page, "Acquire Targets");
        await shot(page, "acquire-before");
        await page.locator(".panel.on button.step-run").click();
        await expect(page.locator(".panel.on button.step-run")).toHaveText("Rerun all", { timeout: 300_000 });
        await rest(2000);
        const run = await page.evaluate(() => window.__theRunState());
        expect(run.acquiredTileKeys.length, "one capture per target tile").toBe(run.targetTiles);
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
