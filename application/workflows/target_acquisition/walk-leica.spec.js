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
import { photograph } from "./steps/scan_the_overview/pixels.js";

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

const PORT = Number(process.env.ACQUISITION_BRIDGE_PORT ?? 8877);
const SIDE = Number(process.env.LEICA_SIDE_PORT ?? 8878);
process.env.LEICA_SIDE_PORT = String(SIDE);
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

/* The Leica's ProgramData, rooted in a folder of its own, and the bridge
   started through the driver's stand-in launcher (see the configuration
   walk's Leica variant for the same arrangement). */
const leicaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-leica-root-"));
process.env.ZMART_MICROSCOPY_ROOT = leicaRoot;
const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "..");
const LAUNCHER = path.join(REPO, "zmart_drivers", "leica", "stellaris5_y42h93", "navigator_expert",
  "tests", "helpers", "page_bridge_standin.py");
const python = process.env.PYTHON ?? "python3";
const wrapper = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "zmart-leica-python-")), "python");
fs.writeFileSync(wrapper, [
  "#!/bin/sh",
  "case \"$1\" in",
  `  */bridge.py) shift; exec ${JSON.stringify(python)} ${JSON.stringify(LAUNCHER)} "$@" ;;`,
  `  *) exec ${JSON.stringify(python)} "$@" ;;`,
  "esac",
  "",
].join("\n"), { mode: 0o755 });
process.env.PYTHON = wrapper;

/* The operator at LAS X, through the stand-in's side door. */
const side = async (route) => {
  const answer = await fetch(`http://127.0.0.1:${SIDE}${route}`);
  if (!answer.ok) throw new Error(`${route} answered ${answer.status}: ${await answer.text()}`);
  return answer.json();
};
const inTheInstrument = {
  choose: (job) => side(`/job?name=${encodeURIComponent(job)}`),
};
const chooseTheLeica = async (page) => {
  const scope = page.locator(".panel.on .session-form select").nth(0);
  const value = await scope.evaluate((sel) => [...sel.options].find((o) => /leica|stellaris/i.test(o.textContent))?.value);
  if (value === undefined) throw new Error("the Leica is not offered on the card");
  await scope.selectOption(value);
};

test.describe("the target acquisition workflow, walked on the Leica driver with the CAM and camera stood in", () => {
  test.setTimeout(A_WHOLE_WALK);

  test("from Connect to acquired targets on a configured Leica", async ({ page }) => {
    const bridge = await startTheBridge({ port: PORT, connect: false });
    const errors = [];
    page.on("pageerror", (why) => { errors.push(why.message); console.log(`page error: ${why.message}`); });
    try {
      /* The machine is configured first, through the setup seam: limits,
         origin, orientation and the 10x-40x pair, the way the configuration
         walk publishes them. */
      const configured = await side("/configure");
      console.log(`configured: ${JSON.stringify(configured)}`);
      await page.goto(`${bridge.at}/`);
      await rest(2500);
      if (await page.locator("#wf-select").inputValue() !== "target_acquisition") {
        await page.selectOption("#wf-select", { label: "Target acquisition" });
        await rest(800);
      }
      await shot(page, "opened");

      /* Step 1: the Leica, its configuration offered, connected. */
      await chooseTheLeica(page);
      await rest(600);
      await page.locator('.panel.on .session-form input[type="password"]').fill("x");
      await rest(400);
      const offered = page.locator(".panel.on .session-form select").nth(2);
      await expect(offered).toBeEnabled();
      await expect(offered).not.toHaveValue("");
      await page.locator(".panel.on .session-buttons button.run").click();
      await expect(page.locator('.step.done:has-text("Connect")')).toBeVisible({ timeout: 60_000 });
      await expect(page.locator(".check-row.pending")).toHaveCount(0);
      await expect(page.locator(".check-row.failed")).toHaveCount(0);
      await rest(1200);
      await shot(page, "connected");

      /* Step 2: a slide. */
      await walkTo(page, "Define Carrier");
      await page.locator(".carrier-type[data-type='slide']").click();
      await rest(800);
      await shot(page, "carrier-slide");

      /* Step 3: the overview job, read off the instrument, and a grid. */
      await walkTo(page, "Overview scan area");
      await inTheInstrument.choose("Overview");
      await record(page, "sf-preset", "overview");
      await shot(page, "overview-area-recorded");
      await page.locator(".sf-apply-grid").click();
      await rest(800);
      const plan = await page.evaluate(() => window.__theStageCanvas.plan());
      expect(plan.length, "the slide was tiled").toBeGreaterThan(0);
      await shot(page, "overview-area-planned");

      /* Step 4: the focussing job with its z-stack, points placed, measured. */
      await walkTo(page, "Focus strategy");
      await inTheInstrument.choose("Focussing");
      await record(page, "focus-preset", "af");
      await page.locator("#fp-place").click();
      await rest(500);
      await shot(page, "focus-points-placed");
      await page.locator(".panel.on button.step-run").click();
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 600_000 });
      const focus = await ask(page, PORT, "/api/focus/measure");
      expect(focus.points?.length, "a focus point was measured through the bridge").toBeGreaterThan(0);
      expect(focus.points.filter((p) => !p.lost).length, "at least one point found a height").toBeGreaterThan(0);
      await rest(1500);
      await shot(page, "focus-measured");

      /* Step 5: the overview, scanned through the driver onto the picture. */
      await walkTo(page, "Scan the overview");
      await rest(1500);
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
      await page.locator("#plane").evaluate((s) => { s.value = s.max; s.dispatchEvent(new Event("input", { bubbles: true })); });
      await rest(1500);
      await shot(page, "scan-done-z-top");
      await page.locator("#plane").evaluate((s) => { s.value = s.min; s.dispatchEvent(new Event("input", { bubbles: true })); });
      await rest(800);
      await expect(page.locator("#acquisition-name")).toHaveText("overview");
      await expect.poll(() => page.locator("#canvas-chips .chip").count(), { timeout: 30_000 }).toBeGreaterThan(0);

      /* Step 6: one tile through the real detection, then all of them. */
      await walkTo(page, "Detect objects");
      await rest(800);
      await page.getByRole("button", { name: "Test this tile" }).click();
      await expect.poll(async () => {
        const state = await ask(page, PORT, "/api/targets/discover");
        return !state.running && (state.error || ((state.fields?.length ?? 0) + (state.failed?.length ?? 0)) >= 1);
      }, { timeout: 900_000, message: "the tile test never answered" }).toBeTruthy();
      const tried = await ask(page, PORT, "/api/targets/discover");
      const blocked = tried.error ?? tried.failed?.[0]?.why ?? null;
      await rest(1000);
      expect(blocked, "detection ran on this machine").toBeNull();
      await shot(page, "detect-tile-tested");
      await page.locator(".panel.on button.step-run").click();
      await expect(page.locator(".panel.on button.step-run")).toHaveText("Run again", { timeout: 1_500_000 });
      await rest(1500);
      const found = await page.evaluate(() => window.__theStageCanvas.targets());
      expect(found.length, "detection placed candidates on the canvas").toBeGreaterThan(0);
      await shot(page, "detect-done");

      /* Step 7: a gate drawn round most of the scatter. */
      await walkTo(page, "Discover Targets");
      await rest(800);
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

      /* Step 8: the target job on the 40x, its settings recorded, areas placed. */
      await walkTo(page, "Target scan area");
      await inTheInstrument.choose("Target");
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

      /* Step 9: the targets acquired under the 40x, through the driver, with
         the lens's own offset compensated from the published pair. */
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

      await walkTo(page, "Connect");
      await shot(page, "rail-at-the-end");
      expect(errors, "the page raised no errors").toEqual([]);
    } finally {
      await bridge.stop();
    }
  });
});
