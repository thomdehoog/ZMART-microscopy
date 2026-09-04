import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { assembleWorkflows } from "../framework/rules/finding-workflows.js";

/* The workflows, found the way the page finds them: every folder under
 * `workflows/` with a `flow.js` inside it. The page uses the build tool's
 * folder scan; a test running in Node reads the folder itself. Both hand what
 * they found to the same `assembleWorkflows`, so this suite and the page
 * cannot disagree about what the folders mean. */
const workflowsDir = fileURLToPath(new URL("../workflows/", import.meta.url));
const flowFiles = {};
for (const folder of fs.readdirSync(workflowsDir)) {
  const flowPath = path.join(workflowsDir, folder, "flow.js");
  if (fs.existsSync(flowPath)) {
    flowFiles[`${folder}/flow.js`] = await import(pathToFileURL(flowPath).href);
  }
}
const { WORKFLOWS } = assembleWorkflows(flowFiles);

/* Prototyping pace: this is a smoke net, not a specification. It covers the
   layout rules that everything else is built on and one walk of the whole
   flow, because the page is nearly all canvas and reading the source has
   repeatedly missed what driving it catches. Deeper cases — the focus model
   ladder, the metric legend, the drag override — are worth unit tests once
   the maths stops moving; they cost a full run each through the UI. */

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

/** Optional review artifact: ordinary test runs stay read-only, while a
 * reviewer can name a folder and reproduce the documented operator view. */
async function captureOperatorEvidence(page, name) {
  const folder = process.env.OPERATOR_EVIDENCE_DIR;
  if (!folder) return;
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: path.join(folder, name), fullPage: true });
}

/* A step's button sits at the end of whichever panel is showing, so this does
   not need to know which step it is running. */
async function runStep(page, ms = 1000) {
  await page.locator(".panel.on button.step-run").click();
  await page.waitForTimeout(ms);
  /* The wait above matches the rehearsal's pace; this expect covers the slow
     machines, the same way connect() does. `running` is the class the button
     carries while the step is out — read instead of its label, which changes
     with what pressing it means. A finished step may put its button away
     (the focus step does), so a gone button is as good as a still one. */
  const run = page.locator(".panel.on button.step-run");
  if (await run.count()) {
    await expect(run).not.toHaveClass(/\brunning\b/, { timeout: 60_000 });
  }
}

/** Connect has its own button at the end of its card, not one the frame drives. */
async function connect(page, password = "hunter2") {
  await page.locator('.field input[type="password"]').fill(password);
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  /* The wait above matches the rehearsal's pace; this expect covers the slow
     machines. The next step unlocking is what "connected" means to the rail,
     so it is what is waited for — a fixed pause on a loaded container ran out
     while the session was still opening, and the whole walk stalled on a
     locked step. */
  await expect(page.locator('.step:has-text("Define Carrier")').first())
    .toBeEnabled({ timeout: 15_000 });
}

/** Set the instrument up, name it, record it — into the slot in `hostId`.
 * There is no presets step: each recording lives in the step that uses it. */
async function recordSlot(page, hostId, name) {
  const bar = page.locator(`#${hostId} .setting-box.open`);
  /* Some slots take a name and some do not — where what is read names itself,
     the bar is only a button. Naming one that has no field to name it in is
     the test insisting on a control the operator never sees. */
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(650);
}

/** Everything before the sample is touched: session and carrier. Configuring
 * the carrier is the work, so standing on that step settles it. */
async function throughSetup(page) {
  await connect(page);
  await gotoStep(page, "Define Carrier");
  /* The plate this lab runs most, chosen rather than assumed. A fresh run
     starts on one plain area now, and the tests below are about a grid of
     compartments — how the plan follows the plate, where focus points land in
     each well — so the carrier they are about is the one they say. */
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "96-well · Greiner SensoPlate" });
  await page.waitForTimeout(200);
}

/** ...on a plate with real room in each well. A 6-well plate's wells are far
 * wider than a 96-well's 6.6 mm, so a drawn region holds many 676 µm frames
 * and the tests about covering a region have something to count. */
async function throughSetupRoomy(page) {
  await connect(page);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(200);
}

/** ...and the scan fields, which is what opens the steps that touch the
 * sample. The overview's preset is recorded here, where the fields that take
 * their frame from it are laid. */
async function throughFields(page) {
  await throughSetup(page);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(300);
}

async function placeFocusPoints(page) {
  await gotoStep(page, "Focus strategy");
  // the focus preset is recorded beside the sweeps it will measure, and
  // the points belong to a map, which is made and named first
  await recordSlot(page, "focus-preset", "af");
  // one place to a tileset, which for a grid of compartments is one per well
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
}

const targetsOnCanvas = (page) =>
  page.evaluate(() => window.__theStageCanvas.targets());

/* A place on the gate plot, as fractions of its frame: the frame keeps a
   column at the right for the y labels and two lines below for the x axis,
   so a fraction of the whole canvas landed in the margins. The frame's
   inset is the plot's own `PAD`. */
const PLOT_PAD = { l: 1, r: 62, t: 1, b: 38 };
const plotPoint = (sc, gx, gy) => [
  sc.x + PLOT_PAD.l + (sc.width - PLOT_PAD.l - PLOT_PAD.r) * gx,
  sc.y + PLOT_PAD.t + (sc.height - PLOT_PAD.t - PLOT_PAD.b) * gy,
];

const physicalTargetPositions = (targets) => targets.map(({ id, field, x, y }) =>
  ({ id, field, x, y }));

async function expectTargetLayerOnCanvas(page, layer, reason) {
  const canvas = page.locator("#stage-canvas");
  await page.mouse.move(2, 2);
  await page.waitForTimeout(120);
  const shown = await canvas.screenshot();
  await page.evaluate((key) => window.__theStageCanvas.showLayer(key, false), layer);
  await page.waitForTimeout(120);
  const hidden = await canvas.screenshot();
  expect(Buffer.compare(shown, hidden), reason).not.toBe(0);
  await page.evaluate((key) => window.__theStageCanvas.showLayer(key, true), layer);
  await page.waitForTimeout(120);
}

async function expectTargetAtItsProjection(page, target, stepName) {
  const box = await page.locator("#stage-canvas").boundingBox();
  expect(box, `${stepName}: the canvas has a box`).not.toBeNull();
  expect(target.screen.x, `${stepName}: target x is on the canvas`)
    .toBeGreaterThanOrEqual(0);
  expect(target.screen.x, `${stepName}: target x is on the canvas`).toBeLessThan(box.width);
  expect(target.screen.y, `${stepName}: target y is on the canvas`)
    .toBeGreaterThanOrEqual(0);
  expect(target.screen.y, `${stepName}: target y is on the canvas`).toBeLessThan(box.height);
}

test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.errors = errors;
  await page.goto("/?backend=pretend");
  await page.waitForTimeout(250);
});

test.afterEach(async ({ page }) => {
  expect(page.errors, "console and page errors").toEqual([]);
});

test("the rail carries the workflow's declared steps", async ({ page }) => {
  await expect(page.locator("#steps .step")).toHaveCount(9);
  await expect(page.locator(".step.active .step-name")).toHaveText("Connect");
  // the fields are said before the focus that keeps them sharp and the scan
  // that visits them, because both of those are about positions that exist
  await expect(page.locator(".step-name").nth(2)).toHaveText("Overview scan area");
  await expect(page.locator(".step-name").nth(3)).toHaveText("Focus strategy");
});

/* The declaration and the page, held up against each other.
 *
 * The folders under `workflows/` say which workflows exist and what is in
 * them, and this reads those folders and then reads the running page to see
 * whether it agrees.
 * It is the check that a workflow only has to be written down once: add one to
 * the declaration and the chooser grows without anybody touching the shell, and
 * if the page ever goes back to keeping a list of its own, this is what notices.
 *
 * Making sure it can fail: change a step's title in the declaration and this
 * goes red, because the rail is being read rather than described. */
test("the page offers exactly the workflows that are declared", async ({ page }) => {
  const chooser = page.locator("#wf-select option");
  await expect(chooser).toHaveText(Object.values(WORKFLOWS).map((w) => w.name));

  for (const [key, wf] of Object.entries(WORKFLOWS)) {
    await page.locator("#wf-select").selectOption(key);
    await expect(page.locator("#steps .step-name"), `the rail for ${key}`)
      .toHaveText(wf.steps.map((s) => s.title));
    await expect(page.locator("#steps .step-n"), `the numbering for ${key}`)
      .toHaveText(wf.steps.map((s) => s.n));
  }
});

test("a session opens with the password left empty", async ({ page }) => {
  // the page ships with no password at all: a prefilled one is a credential
  // everybody has. And none is demanded either: the field is the instrument's
  // to want, so Connect is ready as soon as an instrument is chosen, and the
  // page says nothing about a password being needed.
  const pw = page.locator('.field input[type="password"]');
  await expect(pw).toHaveValue("");
  await expect(page.locator(".session-foot button.run")).toBeEnabled();
  await expect(page.locator(".session-hint")).toHaveCount(0);
  await expect(page.locator(".session-foot")).not.toContainText("password");
  await pw.fill("hunter2");
  await expect(page.locator(".session-foot button.run")).toBeEnabled();
});

test("canvas layer controls live under Display settings from the start", async ({ page }) => {
  await expect(page.locator(".side-tab button.tab"))
    .toHaveText(["Connect", "Display settings"]);
  await expect(page.locator("#display-side")).toBeHidden();
  await expect(page.locator("#canvas-side")).toBeVisible();
  await page.getByRole("tab", { name: "Display settings", exact: true }).click();
  await expect(page.locator("#display-side")).toBeVisible();
  await expect(page.locator(".display-layer-settings .side-group-title"))
    .toHaveText("Canvas layers");
  await expect(page.locator("#stage-layers .layer-chip")).not.toHaveCount(0);
  await expect(page.locator(".canvas-foot"), "the canvas has no bottom bar").toHaveCount(0);
  await expect(page.locator("#stage-readout"), "there is no live x/y readout").toHaveCount(0);
  await expect(page.locator("#fit-btn")).toBeVisible();
});

test("the channel folds away to the right and comes back", async ({ page }) => {
  // one press on the strip at the column's edge puts the whole column away
  // and gives the canvas the room; the strip stays as the way back, and the
  // column returns the width it had -- the canvas with it
  await expect(page.locator("#canvas-side")).toBeVisible();
  await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Connect");
  /* Stand well inside a zoomed sample view: preserving the initial fitted
     stage alone would not catch a sidebar resize that pans a tileset. */
  await page.evaluate(() => window.__theStageCanvas.lookAt({
    centre: { x: 11000, y: 7000 }, zoom: 12,
  }));
  await page.waitForTimeout(100);
  const canvasBefore = await page.locator("#stage-canvas").boundingBox();
  const fold = page.locator("#side-fold");
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  await expect(fold).toHaveAttribute("aria-label", "Collapse right sidebar");
  expect((await fold.boundingBox()).width, "the fold has an easy-to-find hit area")
    .toBeGreaterThanOrEqual(28);
  const viewBefore = await page.evaluate(() => window.__theStageCanvas.view());
  await fold.click();
  await expect(page.locator("#canvas-side")).toBeHidden();
  await expect(page.locator("#side-divider")).toBeHidden();
  await expect(page.locator(".side-tab")).toHaveCount(0);
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await expect(fold).toHaveAttribute("aria-label", "Open right sidebar");
  await expect.poll(async () => (await page.locator("#stage-canvas").boundingBox()).width,
    "the canvas takes the room the column gave up").toBeGreaterThan(canvasBefore.width + 100);
  const viewFolded = await page.evaluate(() => window.__theStageCanvas.view());
  expect(viewFolded.centre.x).toBeCloseTo(viewBefore.centre.x, 6);
  expect(viewFolded.centre.y).toBeCloseTo(viewBefore.centre.y, 6);
  expect(viewFolded.zoom).toBeCloseTo(viewBefore.zoom, 9);
  await fold.click();
  await expect(page.locator("#canvas-side")).toBeVisible();
  await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Connect");
  await expect.poll(async () => (await page.locator("#stage-canvas").boundingBox()).width)
    .toBe(canvasBefore.width);
  const viewOpen = await page.evaluate(() => window.__theStageCanvas.view());
  expect(viewOpen.centre.x).toBeCloseTo(viewBefore.centre.x, 6);
  expect(viewOpen.centre.y).toBeCloseTo(viewBefore.centre.y, 6);
  expect(viewOpen.zoom).toBeCloseTo(viewBefore.zoom, 9);
});

test("typing the password does not throw the field away", async ({ page }) => {
  const pw = page.locator('.field input[type="password"]');
  await pw.fill("");
  await pw.click();
  await page.keyboard.type("hunter2", { delay: 30 });
  // rebuilding the card on every keystroke destroys the input being typed into
  expect(await pw.inputValue()).toBe("hunter2");
  expect(await page.evaluate(() => document.activeElement?.type === "password")).toBe(true);
  await expect(page.locator(".session-foot button.run")).toBeEnabled();
});

test("every check is asked at once, and each one ticks as it answers", async ({ page }) => {
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();

  // the whole list arrives with the session; only the marks are waiting on
  // anything, so nothing under them moves as the answers come in
  await expect(page.locator(".check-row")).toHaveCount(6);
  const answered = page.locator(".check-row:not(.pending)");
  expect(await answered.count(), "no answers yet").toBe(0);

  await page.waitForTimeout(700);
  const part = await answered.count();
  expect(part, "some marks have landed").toBeGreaterThan(0);
  expect(part, "and not all of them").toBeLessThan(6);
  await expect(page.locator(".check-row")).toHaveCount(6);

  await page.waitForTimeout(1600);
  await expect(answered).toHaveCount(6);
});

test("connecting reports what it checked, and what that came to", async ({ page }) => {
  await connect(page);
  await expect(page.locator(".check-row")).toHaveCount(6);
  await expect(page.locator(".check-row").first()).toContainText("Microscope reachable");
  /* The ticks are the whole answer. The heading does not label itself with
     what was chosen either — that is in the fields, one line each. */
  await expect(page.locator("#canvas-side .side-group-title").first())
    .not.toContainText("Leica");
  await expect(page.locator(".check-row").last()).toContainText("Storage writable");
});

test("an open session is not editable, and Disconnect is the way out", async ({ page }) => {
  const fields = page.locator(".session-form select, .session-form input");
  await connect(page);
  await expect(fields.first(), "an open session is what the run rests on").toBeDisabled();
  await expect(page.locator(".check-row")).toHaveCount(6);

  // closing it takes the run with it — everything after this was read off this
  // session — but keeps what it was opened with, since editing that is the
  // reason to close one
  await gotoStep(page, "Define Carrier");
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "survey");
  await expect(page.locator("#sf-preset .rec-row")).toHaveCount(1);

  await gotoStep(page, "Connect");
  // the lamp says the session is open; the button beside it is the way out
  await expect(page.locator(".session-state")).toHaveText("Connected");
  await expect(page.locator(".session-state .lamp")).toBeVisible();
  await page.locator(".session-foot button.danger").click();
  await expect(fields.first(), "and the form is answerable again").toBeEnabled();
  await expect(page.locator(".check-row")).toHaveCount(0);
  // the checks box goes with them, leaving the session's own heading alone
  await expect(page.locator("#canvas-side .side-group-title")).toHaveCount(1);
  await expect(page.locator('.field input[type="password"]')).toHaveValue("hunter2");
  await expect(page.locator('.step:has-text("Define Carrier")').first()).toBeDisabled();

  // and the next session starts where any run does: what the closed one
  // recorded is gone, what a run begins with is back
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await gotoStep(page, "Overview scan area");
  await expect(page.locator("#sf-preset .rec-row")).toHaveCount(0);
  /* And the bar is back to offering the first import rather than an update,
     which is the whole of what it carries — there is no name half-typed into
     it to be forgotten. */
  await expect(page.locator("#sf-preset .rec-new button.run"))
    .toHaveText("Import optical configuration");
});

test("the fields wait for the preset they will be taken with",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");

    /* A preset is a reading taken off this instrument today. Nothing is
       seeded, and until it exists there is nothing to lay: a field takes its
       frame from the preset. So the ways of laying fields are not on screen at
       all — the bar waiting to record says what the step is for, and a greyed
       copy of the editor underneath would only say it again. */
    await expect(page.locator("#sf-preset .setting-box.open")).toHaveCount(1);
    await expect(page.locator(".sf-tools")).toBeHidden();
    await expect(page.locator(".sf-apply-grid")).toBeHidden();
    /* Except the reading itself, which is what the rest is waiting on, and is
       taken whether or not it has been given a name. */
    await expect(page.locator("#sf-preset button.run")).toBeEnabled();

    await recordSlot(page, "sf-preset", "overview");
    await expect(page.locator(".sf-tools")).toBeVisible();
    await expect(page.locator(".sf-tool[data-tool='rectangle']")).toBeEnabled();
    await expect(page.locator(".sf-apply-grid")).toBeEnabled();
    /* What was read stands under the bar that took it. It carries no name:
        the optical configuration is whatever the microscope is set to, and one
        reading at a time needs no handle to tell it from another. */
    await expect(page.locator("#sf-preset .rec-row")).toContainText("NA");

    /* And with a preset there, the fields can be laid. A reading cannot be
       thrown away any more — the instrument is set to something whether or not
       the page has looked, so there is no state in which the step has none.
       Taking it again is how it changes, which is the test below. */
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Overview scan area")').first())
      .toHaveClass(/done/);
  });

test("recording again replaces the reading, and re-takes the plan with it",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");

    /* A region rather than the grid: what a region costs is what its preset
       says a frame covers, so re-reading the preset is a number on the
       readout and not only a colour on the stage. */
    const box = await page.locator("#stage-canvas").boundingBox();
    await page.locator(".sf-tool[data-tool='rectangle']").click();
    await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.35);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.40, box.y + box.height * 0.40, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    const positions = async () =>
      Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    const dry = await positions();
    expect(dry, "the region covered at 20x").toBeGreaterThan(0);

    /* The optics get changed in the middle of a session, and saying so is
       recording again: the slot holds one reading — the instrument as it now
       stands — so the new one replaces the old, and the region already drawn
       is re-taken at 63x, a fraction of the frame and many times the tiles.
       Recording is the whole gesture; there is nothing further to press. */
    await recordSlot(page, "sf-preset", "hires");
    await expect(page.locator("#sf-preset .rec-row")).toHaveCount(1);
    const oil = await positions();
    expect(oil, "the same region at 63x").toBeGreaterThan(dry * 10);

    /* No list of presets beside it, nothing to switch back to: the way back
       to the dry optics is setting the instrument dry and recording again. */
    await expect(page.locator(".sf-presets")).toHaveCount(0);
    await expect(page.locator(".sf-flat", { hasText: "Apply to" })).toHaveCount(0);

    // and the one reading on screen unfolds to what was read
    await page.locator("#sf-preset .rec-fold").first().click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(1);
    await expect(page.locator("#sf-preset .rec-fold").first())
      .toHaveAttribute("aria-expanded", "true");
  });

test("the reading on screen is the current one, however many were taken",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    /* Four readings in a row — an operator adjusting the instrument and
       re-reading it as they go. Each replaces the last: the slot answers
       "what will this run be taken with", and that has one answer. */
    for (const name of ["overview", "hires", "tenx", "fortyx"]) {
      await recordSlot(page, "sf-preset", name);
    }
    await expect(page.locator("#sf-preset .rec-row")).toHaveCount(1);

    // and it unfolds to what was read
    await page.locator("#sf-preset .rec-fold").first().click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(1);
  });

test("a recorded preset unfolds to show everything that was read", async ({ page }) => {
  await throughSetup(page);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "survey");
  const fold = page.locator(".rec-fold").first();

  // folded by default: a recording should stay a line
  await expect(page.locator(".rec-detail")).toHaveCount(0);
  await expect(fold).toHaveAttribute("aria-expanded", "false");

  await fold.click();
  await expect(fold).toHaveAttribute("aria-expanded", "true");
  const labels = await page.locator(".rec-detail dt").allInnerTexts();
  expect(labels, "the detail behind the summary").toContain("Objective");
  expect(labels).toContain("Channel 1");
  await expect(page.locator(".rec-detail dd").first()).toContainText("NA");

  await fold.click();
  await expect(page.locator(".rec-detail")).toHaveCount(0);
});

test("the microscope is the mock or the Leica, and the api follows it", async ({ page }) => {
  const scopes = await page.locator(".field select").first().locator("option").allInnerTexts();
  expect(scopes).toHaveLength(2);
  expect(scopes[0]).toContain("Mock");
  expect(scopes[1]).toContain("Leica Stellaris 5");
  const apis = () => page.locator(".field select").nth(1).locator("option").allInnerTexts();
  expect((await apis()).join()).toContain("Mock API");
  await page.locator(".field select").first().selectOption({ label: "Leica Stellaris 5 · y42h93" });
  await page.waitForTimeout(150);
  expect((await apis()).join()).toContain("Navigator Expert");
});

test("nothing advances by itself, and the next step stays locked until it can run",
  async ({ page }) => {
    await connect(page);
    await expect(page.locator(".step.active .step-name")).toHaveText("Connect");
    await expect(page.locator('.step:has-text("Connect")').first()).toHaveClass(/done/);
    /* The rail stops at the first step that has not been done, and standing
       on the carrier is what settles it — so it opens, and nothing after it
       does yet. */
    await expect(page.locator('.step:has-text("Define Carrier")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Overview scan area")').first()).toBeDisabled();

    await gotoStep(page, "Define Carrier");
    await page.waitForTimeout(200);
    await expect(page.locator('.step:has-text("Overview scan area")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    // positions are what that step needs, and the next one opens behind them
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "survey");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Scan the overview")').first()).toBeDisabled();
  });

test("the canvas is always on the stage, and the channel follows the step",
  async ({ page }) => {
    /* Three rehearsed runs and a dozen waits in one walk: the whole thing
       takes longer than the ordinary budget on a loaded machine. */
    test.slow();
    /* One layout for every step: the picture on the left, the standing step's
       controls in the channel on the right. From the very first step — the
       session card is the channel of Connect. */
    await expect(page.locator("#tabs > .tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Connect");
    // headed the way every other step is headed: the name above the box
    await expect(page.locator("#canvas-side .side-group-title").first())
      .toHaveText("Connect to the microscope");

    await throughSetup(page);
    await expect(page.locator("#tabs > .tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".panel.on button.step-run"),
      "configuring it is the work, so there is nothing to press").toHaveCount(0);
    await expect(page.locator('.step:has-text("Define Carrier")').first(),
      "and standing on it settles it").toHaveClass(/done/);
    // the channel is named over the column it heads, not as a tab you switch to
    await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Define Carrier");
    await expect(page.locator("#canvas-side")).toBeVisible();
    await expect(page.locator(".carrier-card")).toHaveCount(1);

    /* Walking back keeps the canvas: the channel changes hands instead. */
    await gotoStep(page, "Connect");
    await expect(page.locator("#tabs > .tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Connect");
    await expect(page.locator("#canvas-side .side-group-title").first(),
      "and the session comes back when you return")
      .toHaveText("Connect to the microscope");
    await expect(page.locator(".check-row")).toHaveCount(6);
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-card")).toHaveCount(1);

    /* The channel belongs to the step standing in it. Scan fields are about
       the canvas the way the carrier is, so they take the same column and the
       heading says whose it is — rather than a second column beside it holding
       controls for a step nobody is on. */
    await gotoStep(page, "Overview scan area");
    await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Overview scan area");
    await expect(page.locator(".carrier-card")).toHaveCount(0);
    // the editor is in the same channel, dead until the preset it needs exists
    await expect(page.locator(".sf-card")).toHaveCount(1);
    await expect(page.locator(".sf-apply-grid")).toBeDisabled();
    await recordSlot(page, "sf-preset", "overview");
    await expect(page.locator(".sf-apply-grid")).toBeEnabled();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);

    /* Focus is the same shape: it happens on the canvas, so it is not a tab
       either — it takes the channel and names it. */
    await placeFocusPoints(page);
    await expect(page.locator("#tabs > .tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab .tab[aria-selected='true']")).toHaveText("Focus strategy");
    await expect(page.locator("#focus-controls")).toBeVisible();
    await expect(page.locator(".sf-card")).toHaveCount(0);

    await runStep(page, 1600);
    await gotoStep(page, "Scan the overview");
    await expect(page.locator("#tabs > .tab")).toHaveText(["Canvas"]);
    /* The scan consults nothing: the run holds one preset and the focus step's
       generated map, so the channel is a short summary and the press that
       starts it — no boxes to choose from. */
    await expect(page.locator("#canvas-side .side-group-title"))
      .toHaveText(["Scan summary"]);
    await expect(page.locator("#canvas-side .scan-summary .k").first()).toHaveText("Positions");
    await expect(page.locator("#canvas-side .scan-summary .v").first()).toHaveText(/^\d+$/);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Start");
    // walking back to the carrier brings its controls back, and they still
    // work: saying the plate is a different plate is a thing operators do, and
    // only a run actually under way takes that away
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-card")).toHaveCount(1);
    await expect(page.locator(".carrier-num").first()).toBeEnabled();

    await gotoStep(page, "Scan the overview");
    await runStep(page, 3000);

    await gotoStep(page, "Focus strategy");
    await expect(page.locator(".side-tab .tab[aria-selected='true']"), "walking back brings its channel with it")
      .toHaveText("Focus strategy");
    await expect(page.locator("#focus-controls")).toBeVisible();
  });

test("the grid comes from the carrier, so changing the plate changes the plan",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    // nothing to scan yet, so the step is not done and the next one is shut
    await expect(page.locator('.step:has-text("Overview scan area")').first())
      .not.toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    /* 96 areas, and nine positions in each: the block asked for is three by
       three, and a 20x frame is 676 µm across while a well is 6.58 mm, so all
       nine frames sit comfortably inside the well. */
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Overview scan area")').first())
      .toHaveClass(/done/);

    /* And the carrier is still editable. It used to lock here, on the argument
       that these positions were placed relative to areas that must not move out
       from under them — but going back to say the plate is a different plate is
       a thing operators do, and the step knows how to answer it. */
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-preset")).toBeEnabled();

    /* A different plate is a different plan. Six wells 36 mm across hold
       the whole three-by-three block, so the same grid is 54 positions rather
       than the 96 a plate of small wells allowed — the count is read off the
       carrier rather than typed beside it. Disconnecting is what begins again: it
       takes the run with it, and the next session starts clean. */
    await gotoStep(page, "Connect");
    await page.locator(".session-foot button.danger").click();
    await throughSetup(page);
    await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
    await page.waitForTimeout(200);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("54 positions");
  });

test("the stage mark is registered to the stage, and says where it is on hover",
  async ({ page }) => {
    await connect(page);
    await gotoStep(page, "Define Carrier");
    await page.waitForTimeout(300);

    const box = await page.locator("#stage-canvas").boundingBox();
    const mid = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    const tip = page.locator("#stage-tip");
    const answering = () => tip.evaluate((n) => n.classList.contains("on"));

    /** Where a stage position is currently drawn in page pixels. The public
        canvas projection is the same registration contract the layers use;
        the removed coordinate readout is deliberately not recreated here. */
    const pointAt = async (ux, uy) => {
      const projected = await page.evaluate(({ x, y }) => {
        const [ox, oy] = window.__theStageCanvas.carrierOriginUm();
        return window.__theStageCanvas.project(x - ox, y - oy);
      }, { x: ux, y: uy });
      const at = Array.isArray(projected)
        ? { x: projected[0], y: projected[1] }
        : projected;
      const canvas = await page.locator("#stage-canvas").boundingBox();
      return { x: canvas.x + at.x, y: canvas.y + at.y };
    };

    /* Nothing is said until it is asked: a permanent readout would be three
       figures to read past on every step. */
    expect(await answering()).toBe(false);

    /* And the stage is parked out in the margin, so the middle of the picture
       — where the carrier is — answers nothing. */
    await page.mouse.move(mid.x, mid.y);
    await page.waitForTimeout(200);
    expect(await answering()).toBe(false);

    // a twenty-fifth of a 120 x 80 mm travel, which is clear of the plate
    const mark = await pointAt(4800, 3200);
    await page.mouse.move(mark.x, mark.y);
    await page.waitForTimeout(200);
    expect(await answering()).toBe(true);
    await expect(tip).toContainText("4.80 mm");
    await expect(tip).toContainText("3.20 mm");

    /* Registered to the stage and not to the screen. Zooming about the mark
       leaves it over the same micrometre, so it goes on answering with the
       same numbers at a scale six steps in. */
    for (let i = 0; i < 6; i++) await page.mouse.wheel(0, -240);
    await page.waitForTimeout(300);
    expect(await answering()).toBe(true);
    await expect(tip).toContainText("4.80 mm");

    /* And panning carries it: the picture moves under a still pointer, so the
       mark leaves that pointer and is found where the picture put it.

       How far the picture will go is not assumed. The stage is parked near the
       corner of its own travel and the picture can no longer be pushed past
       its own edge, so a drag near that corner is allowed only as far as there
       is picture left to show. What is checked is the property rather than the
       distance: the mark is somewhere else on screen afterwards, and where it
       is, it is still 4.80 mm. */
    await page.mouse.down();
    await page.mouse.move(mark.x + 180, mark.y + 110, { steps: 10 });
    await page.mouse.up();
    await page.mouse.move(mark.x, mark.y);
    await page.waitForTimeout(200);
    expect(await answering()).toBe(false);

    const moved = await pointAt(4800, 3200);
    expect(Math.hypot(moved.x - mark.x, moved.y - mark.y)).toBeGreaterThan(20);
    await page.mouse.move(moved.x, moved.y);
    await page.waitForTimeout(200);
    expect(await answering()).toBe(true);
    await expect(tip).toContainText("4.80 mm");
  });

test("every carrier is designed in one panel, showing what that carrier has",
  async ({ page }) => {
    await connect(page);
    await gotoStep(page, "Define Carrier");

    /* The panel a carrier gets is the one its own geometry asks for. Written
       as what is on screen rather than what is not, so a group that stops
       appearing at all still fails this. */
    const showing = async () => {
      const labels = await page.locator(".carrier-group:visible .carrier-label:visible")
        .allTextContents();
      return labels.map((t) => t.trim());
    };

    await page.locator(".carrier-type[data-type='wellplate']").click();
    await page.waitForTimeout(150);
    // a plate is a grid, so it has rows, a size, a pitch and a corner
    expect(await showing()).toEqual([
      "ROWS", "COLUMNS", "WIDTH (mm)", "HEIGHT (mm)",
      "COLUMN PITCH (mm)", "ROW PITCH (mm)", "CORNER RADIUS (mm)", "AREA (mm²)",
    ]);

    // a chamber is the same kind of thing, so it is the same panel
    await page.locator(".carrier-type[data-type='chamber']").click();
    await page.waitForTimeout(150);
    expect(await showing()).toEqual([
      "ROWS", "COLUMNS", "WIDTH (mm)", "HEIGHT (mm)",
      "COLUMN PITCH (mm)", "ROW PITCH (mm)", "CORNER RADIUS (mm)", "AREA (mm²)",
    ]);

    // a dish is one round area: one diameter, and no corner to choose
    await page.locator(".carrier-type[data-type='dish']").click();
    await page.waitForTimeout(150);
    expect(await showing()).toEqual(["DIAMETER (mm)"]);

    // an area is one flat rectangle: the two numbers that say how big it is
    await page.locator(".carrier-type[data-type='slide']").click();
    await page.waitForTimeout(150);
    expect(await showing()).toEqual(["WIDTH (mm)", "HEIGHT (mm)"]);
  });


test("the tools and the grid are on screen together, over what the grid laid",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Overview scan area");
    /* Both ways of laying tilesets are offered at once, in one box with a word
       apiece over them. A grid laid in every well is a perfectly good thing to
       then draw a tileset over, and there is no mode to leave before doing
       it. */
    await expect(page.locator(".sf-tools")).toBeVisible();
    await expect(page.locator(".sf-apply-grid")).toBeVisible();
    await expect(page.locator(".side-group:has(.sf-tools) .sf-apply-grid"),
      "one box holding both ways of doing it").toHaveCount(1);
    /* One card, its parts each under a word: the two ways of laying a
       tileset, and how they are placed once they are down. */
    await expect(page.locator(".side-group:has(#sf-overlap) .side-sub"))
      .toHaveText(["Manual", "Automatic", "Tile placement"]);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");

    /* What the grid put down is still a set of fields, so it can be picked,
       added to and thrown away. */
    const box = await page.locator("#stage-canvas").boundingBox();
    const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });

    // shift-drag on empty stage marquees a block of positions
    const a = at(0.34, 0.24), b = at(0.46, 0.36);
    await page.keyboard.down("Shift");
    await page.mouse.move(a.x, a.y);
    await page.mouse.down();
    await page.mouse.move(b.x, b.y, { steps: 10 });
    await page.mouse.up();
    await page.keyboard.up("Shift");
    await page.waitForTimeout(200);

    // and Delete takes them out of the plan, which is what says they were held
    const before = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    await page.keyboard.press("Delete");
    await page.waitForTimeout(200);
    const after = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    expect(after, "fewer positions than before").toBeLessThan(before);
  });

test("a grid position can be picked and dropped, but not dragged off its grid",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Overview scan area");
    const box = await page.locator("#stage-canvas").boundingBox();
    const shot = () => page.locator("#stage-canvas").screenshot();

    /* Where it is, is what the carrier and the grid settings say. Dragging one
       by hand would leave a position claiming to be in a block it had left,
       and the next Apply would silently undo it.

       Compared with nothing selected at either end: picking one is supposed to
       change the picture — that is the heavier outline — and this is asking
       whether it moved, not whether anything happened. */
    const idle = async () => {
      // nothing selected and nothing under the pointer, or the heavier outline
      // that hover draws would answer for the question being asked
      await page.keyboard.press("Escape");
      await page.mouse.move(box.x + box.width * 0.02, box.y + box.height * 0.97);
      await page.waitForTimeout(250);
      return shot();
    };
    /* Drag from a position rather than from wherever the middle of the canvas
       lands. Empty stage is a pan now, so a miss would move the picture and
       answer a different question than the one being asked. The canvas says
       where one is: over a field the cursor offers to pick it up. */
    const findPosition = async () => {
      for (let fy = 0.25; fy <= 0.75; fy += 0.02) {
        for (let fx = 0.3; fx <= 0.7; fx += 0.01) {
          const at = { x: box.x + box.width * fx, y: box.y + box.height * fy };
          await page.mouse.move(at.x, at.y);
          const cursor = await page.locator("#stage-canvas").evaluate((c) => c.style.cursor);
          if (cursor === "pointer") return at;
        }
      }
      throw new Error("no grid position found under the pointer");
    };
    const onPosition = await findPosition();

    const before = await idle();
    await page.mouse.move(onPosition.x, onPosition.y);
    await page.mouse.down();
    await page.mouse.move(onPosition.x + box.width * 0.12, onPosition.y + box.height * 0.12, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    expect(Buffer.compare(before, await idle()) === 0,
      "back at rest the positions are where they were").toBe(true);

    // arrow keys will not move one either — same reason
    await page.keyboard.press("Control+a");
    await page.waitForTimeout(200);
    const selected = await shot();
    for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
    expect(Buffer.compare(selected, await shot()) === 0, "nudge leaves it alone").toBe(true);

    // but it is a field like any other to pick and to throw away
    await page.keyboard.press("Delete");
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-readout")).toContainText("nothing to scan yet");
  });

test("what the objective sees stays inside the well",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);

    /* Three by three was asked for and nine were laid in each well: a 20x
       frame is 676 µm across and a 96-well plate's wells are 6.6 mm, so the
       whole block fits inside the glass. */
    await expect(page.locator(".sf-readout")).toContainText("864 positions");

    /* Record the 63x preset and the same block fits nine times over, so
       applying the grid again lays all of it. Nothing about the plate or the
       numbers typed changed — only what the objective can see at once. */
    await recordSlot(page, "sf-preset", "hires");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(400);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
  });

test("a position put down on the plastic slides into the well it was nearest",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();

    /* Pressed between wells. It is placed, because the press said where to
       look rather than where a frame happens to fit — but it lands where the
       objective can see something, which is the well it was nearest. If it
       had stayed where the press was, it would be a position on plastic and
       the plan would cover nothing. */
    await page.locator(".sf-tool[data-tool='point']").click();
    await page.mouse.click(box.x + box.width * 0.335, box.y + box.height * 0.395);
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("1 position");
    await expect(page.locator(".sf-readout")).toContainText("1 point");
  });

test("a position dragged across the plate steps from well to well",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();
    const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
    const cursor = () => page.locator("#stage-canvas").evaluate((c) => c.style.cursor);

    /* Where the canvas offers to pick something up. A position is small and
       seated in the middle of whatever well it was nearest, so it has to be
       looked for rather than assumed to be where the press was. */
    const findField = async (cx, cy, span = 0.05) => {
      for (let fy = cy - span; fy <= cy + span; fy += 0.005) {
        for (let fx = cx - span; fx <= cx + span; fx += 0.005) {
          const p = at(fx, fy);
          await page.mouse.move(p.x, p.y);
          if (await cursor() === "pointer") return { fx, fy };
        }
      }
      return null;
    };

    await page.locator(".sf-tool[data-tool='point']").click();
    await page.mouse.click(at(0.35, 0.40).x, at(0.35, 0.40).y);
    await page.waitForTimeout(300);
    await page.locator(".sf-tool[data-tool='pointer']").click();
    const from = await findField(0.35, 0.40);
    expect(from, "the position was placed").not.toBeNull();

    /* Dragged a long way across the plate. It has to arrive: the drag is
       measured from where it began, not stepped on from where the position
       has got to — worked out the second way, every step is seated back into
       the middle of the well before the next one is added, and the position
       never leaves the well it started in while the pointer walks off. */
    const to = { fx: from.fx + 0.2, fy: from.fy };
    await page.mouse.move(at(from.fx, from.fy).x, at(from.fx, from.fy).y);
    await page.mouse.down();
    await page.mouse.move(at(to.fx, to.fy).x, at(to.fx, to.fy).y, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(300);

    // still one position, and it is where the pointer let go rather than where
    // it was picked up
    await expect(page.locator(".sf-readout")).toContainText("1 position");
    const landed = await findField(to.fx, to.fy, 0.04);
    expect(landed, "it followed the pointer").not.toBeNull();
    expect(Math.abs(landed.fx - to.fx), "into the well it was let go over")
      .toBeLessThan(0.04);
    expect(await findField(from.fx, from.fy, 0.02),
      "and it is not still where it started").toBeNull();
  });

test("a region is drawn on the canvas and covered by its preset's frame",
  async ({ page }) => {
    await throughSetupRoomy(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();

    await page.locator(".sf-tool[data-tool='rectangle']").click();
    await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.35);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.55, { steps: 10 });
    await page.mouse.up();
    await page.waitForTimeout(200);

    // one region, and the positions covering it are the tiles the preset takes
    await expect(page.locator(".sf-readout")).toContainText("1 region");
    const readout = await page.locator(".sf-readout").innerText();
    expect(Number(readout.match(/^(\d+) position/)[1]),
      "a region the size of several frames takes several tiles").toBeGreaterThan(1);

    // drawing hands the tool back, so the next drag moves rather than draws a
    // second one — and the row says so by lighting Select instead
    /* In this row. The focus step has tools of its own, parked in the markup
       while another step is standing — hidden, but still in the document and
       still answering to the same class. */
    await expect(page.locator(".sf-tools .sf-tool.on")).toHaveCount(1);
    await expect(page.locator(".sf-tool[data-tool='pointer']")).toHaveClass(/\bon\b/);

    // undo has no button of its own; the shortcut list is where it is said
    await page.locator("#stage-canvas").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Control+z");
    await page.waitForTimeout(200);
    await expect(page.locator(".sf-readout")).toContainText("nothing to scan yet");
  });

test("a polygon is closed by a double-click, and keeps the vertices it was given",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();
    const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });

    await page.locator(".sf-tool[data-tool='polygon']").click();
    for (const [fx, fy] of [[0.3, 0.3], [0.5, 0.28], [0.55, 0.5]]) {
      await page.mouse.click(at(fx, fy).x, at(fx, fy).y);
      await page.waitForTimeout(120);
    }
    // still being drawn: nothing is in the plan yet
    await expect(page.locator(".sf-readout")).toContainText("nothing to scan yet");

    const last = at(0.32, 0.52);
    await page.mouse.dblclick(last.x, last.y);
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("1 region");

    // and the tool hands itself back, like every other shape
    await expect(page.locator(".sf-tool[data-tool='pointer']")).toHaveClass(/\bon\b/);

    // the duplicate vertex the second press leaves behind is dropped by
    // withoutTrailingDuplicate — which the unit suite pins, not this
  });

test("walking back to the carrier takes the plan off the canvas, and keeps it",
  async ({ page }) => {
    await throughSetup(page);
    const shot = async () => {
      await page.locator("#fit-btn").click();
      await page.mouse.move(10, 10);
      await page.waitForTimeout(250);
      return page.locator("#stage-canvas").screenshot();
    };

    // the carrier alone, before there is any plan to draw over it
    const bare = await shot();

    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(400);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    expect(Buffer.compare(bare, await shot()) === 0,
      "the plan is on the canvas here").toBe(false);

    /* Back on the carrier the plan is not drawn: it is an answer to a question
       being asked again, and these areas are what it was placed against. */
    await gotoStep(page, "Define Carrier");
    await page.waitForTimeout(300);
    expect(Buffer.compare(bare, await shot()) === 0,
      "the carrier is back to how it looked before any fields existed").toBe(true);

    // taken off the canvas, not thrown away
    await gotoStep(page, "Overview scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
  });

test("the plan stays editable until the overview has been scanned",
  async ({ page }) => {
    /* Two rehearsed runs, a focus map and a scan, in one test: it runs right
       at the ordinary budget on a loaded machine, so it is given more. */
    test.slow();
    await throughFields(page);
    await placeFocusPoints(page);
    await runStep(page, 1600);

    /* Back past the focus map, the plan is still the operator's to change: a
       fitted surface is a statement about the plate, measured at points that
       stay where they were put whatever the scan fields do. */
    await gotoStep(page, "Overview scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeEnabled();
    await expect(page.locator(".sf-tool[data-tool='rectangle']")).toBeEnabled();

    await gotoStep(page, "Scan the overview");
    await runStep(page, 3000);

    // and now it is not: the tiles are pictures taken at those positions
    await gotoStep(page, "Overview scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeDisabled();
    await expect(page.locator(".sf-tool[data-tool='rectangle']")).toBeDisabled();
  });

test("a press on empty canvas lets go of the selection, and the canvas shows it",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();
    const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
    const shot = () => page.locator("#stage-canvas").screenshot();

    await page.locator(".sf-tool[data-tool='rectangle']").click();
    await page.mouse.move(at(0.3, 0.3).x, at(0.3, 0.3).y);
    await page.mouse.down();
    await page.mouse.move(at(0.45, 0.5).x, at(0.45, 0.5).y, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(250);

    // drawn and selected: grips on the canvas say so
    const selected = await shot();

    /* The press that deselects is also the press that starts a pan, so the
       editor never claims it — which is exactly how it once cleared the
       selection without the canvas ever being told to repaint. */
    const empty = at(0.85, 0.85);
    await page.mouse.move(empty.x, empty.y);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(250);
    expect(Buffer.compare(selected, await shot()) === 0,
      "the grips are gone from the picture, not just from the panel").toBe(false);
  });

test("a region can be copied, and a second paste lands clear of the first",
  async ({ page }) => {
    await throughSetupRoomy(page);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "overview");
    const box = await page.locator("#stage-canvas").boundingBox();

    await page.locator(".sf-tool[data-tool='rectangle']").click();
    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.5, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(200);
    await expect(page.locator(".sf-readout")).toContainText("1 region");

    // drawing leaves the new region selected, so that is what is copied
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-readout")).toContainText("2 regions");

    /* The copy becomes what is held, so pasting again offsets from it rather
       than landing back on the original. Three distinct regions, and the tile
       count grows with each — two on top of each other would not. */
    const two = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    await page.keyboard.press("Control+v");
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-readout")).toContainText("3 regions");
    const three = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    expect(three, "a third region adds its own tiles").toBeGreaterThan(two);

    // and a paste is one step, so one undo takes it back
    await page.keyboard.press("Control+z");
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-readout")).toContainText("2 regions");
  });

test("a pasted position is hand-made, so the next Apply leaves it alone",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Overview scan area");
    await expect(page.locator(".sf-readout")).toContainText("864 positions");

    /* Copying is how a grid position is kept: the copy sheds the grid tag, so
       it stops being the grid's to replace. Without that, Apply would sweep
       away a field the operator had deliberately made a copy of. */
    await page.keyboard.press("Control+a");
    await page.keyboard.press("Control+c");
    await page.keyboard.press("Control+v");
    await page.waitForTimeout(500);
    await expect(page.locator(".sf-readout")).toContainText("1728 positions");

    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(500);
    await expect(page.locator(".sf-readout")).toContainText("1728 positions");
  });

/** Where the run will image, read off the page rather than off its sentence. */
const planOf = (page) => page.evaluate(() => window.__plan.map((t) => ({
  x: t.x, y: t.y, frameUm: t.frameUm,
})));

/** How far the nearest other position is from each — the pitch of a grid. */
const closestGap = (tiles) => Math.min(...tiles.map((t, i) => Math.min(
  ...tiles.filter((_, j) => j !== i).map((o) => Math.hypot(o.x - t.x, o.y - t.y)),
)));

test("a grid is laid again under a preset whose frame is a different size",
  async ({ page }) => {
    /* A grid has no outline of its own — only positions worked out from the
       frame — so a change of preset has to work them out again. Laid once and
       left, a grid put down under a 20x objective would keep its 676 µm pitch
       when the 63x reading replaced it, and its nine positions would come back
       as nine acquisitions of overlapping ground. The slot holds one reading,
       so changing preset is recording again: the new reading replaces the old
       and the plan follows it. */
    await connect(page);
    await gotoStep(page, "Define Carrier");
    await page.locator(".carrier-type[data-type='slide']").click();
    await page.waitForTimeout(200);
    await gotoStep(page, "Overview scan area");
    await recordSlot(page, "sf-preset", "wide");     // 20x, a 676 µm frame

    // laid under the 20x, at the pitch the boxes offer for that frame
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(400);
    const wide = await planOf(page);
    expect(wide, "three by three").toHaveLength(9);
    expect(wide[0].frameUm).toBe(676);
    expect(closestGap(wide), "a frame apart, and no closer")
      .toBeGreaterThanOrEqual(676);

    // re-recording replaces the reading — and the grid is laid again for it
    await recordSlot(page, "sf-preset", "close");    // 63x, a 102 µm frame
    await page.waitForTimeout(400);
    const tight = await planOf(page);
    expect(tight, "still three by three").toHaveLength(9);
    expect(tight[0].frameUm).toBe(102);
    expect(closestGap(tight), "nine positions, not nine takes of one")
      .toBeGreaterThanOrEqual(102);
  });

test("the recording finishes the step, and either kind can be given a map",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Focus strategy");

    /* The first reading the stand hands back is a software autofocus: it
       focuses by taking a short stack and scoring it at every position it is
       sent to, which is already a complete answer — so the step is finished by
       the recording, with nothing to press. */
    await recordSlot(page, "focus-preset", "software");
    await expect(page.locator("#focus-preset .rec-state").first()).toContainText("µm stack");
    await expect(page.locator('.step:has-text("Focus strategy")').first())
      .toHaveClass(/done/);
    /* The press that measures the map stands in its box from the moment the
       box is there — greyed while there is nothing to measure. It used to
       disappear instead, which made clearing the points look like it had
       broken the step. */
    await expect(page.locator(".panel.on button.step-run"),
      "nothing to run until there are points to measure").toBeDisabled();

    /* The map is the optional extra, and there is only one of them: a run
       focuses one way, so there is one surface to fit and nothing to name or
       choose between. Points laid, the run has something to do — and once it
       has run, the traces box opens with a row for every point measured,
       because a row is a reading and a freshly laid point has none yet. */
    await expect(page.locator("#fp-place"), "somewhere to lay points").toBeVisible();
    await page.locator("#fp-place").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
    await page.locator(".panel.on button.step-run").click();
    await page.waitForTimeout(1600);
    await expect(page.locator(".point-row").first()).toBeVisible();

    /* The second is a hardware autofocus: the stand holds focus off the
       coverslip at every position it is sent to. That too is a complete answer
       on its own — and it can be given a map just the same, because driving to
       a point and reading the height it settles at measures a surface as well
       as a scored stack does. */
    /* Recording again replaces the reading — the slot holds one — and a fresh
       reading brings a fresh map, because points measured under the old
       preset belong to it. */
    await recordSlot(page, "focus-preset", "hardware");
    await expect(page.locator("#focus-preset .rec-state").first()).toContainText("Hardware");
    await expect(page.locator("#fp-place"), "the same points to lay").toBeVisible();
    await expect(page.locator('.step:has-text("Focus strategy")').first())
      .toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Scan the overview")').first()).toBeEnabled();
  });

test("focus points are laid so many to a tileset", async ({ page }) => {
  /* Six wells 34.8 mm across, and a tileset drawn in one of them: a tileset is
     one field with many positions in it, which is what the number is about. */
  await connect(page);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(200);
  await gotoStep(page, "Overview scan area");
  await recordSlot(page, "sf-preset", "overview");
  const box = await page.locator("#stage-canvas").boundingBox();
  /* Fractions of the stage picture, not of the box: Fit puts the 120 x 80 mm
     travel at the top with a 26 px margin on every side, so the picture is
     the box's width less the margins and 2/3 as tall. */
  const pad = 26, picW = box.width - 2 * pad, picH = picW * 80 / 120;
  const at = (fx, fy) => ({ x: box.x + pad + picW * fx, y: box.y + pad + picH * fy });
  // in the middle of the top-centre well, where a region has positions to hold
  await page.locator(".sf-tool[data-tool='rectangle']").click();
  await page.mouse.move(at(0.46, 0.26).x, at(0.46, 0.26).y);
  await page.mouse.down();
  await page.mouse.move(at(0.54, 0.34).x, at(0.54, 0.34).y, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(page.locator(".sf-readout"), "the region covers positions")
    .not.toContainText(/\b0 positions/);

  await gotoStep(page, "Focus strategy");
  await recordSlot(page, "focus-preset", "coarse");

  /* Where the points are, read off the list rather than off the canvas. The
     rows carry millimetres, which is what the claims are about — and a row is
     a reading, so the list holds nothing until the map has been measured.
     Each laying below is therefore followed by the press that measures it. */
  /* Waits for the readings to land rather than for a stopwatch. Measuring
     three points takes longer than measuring one, and longer again on a loaded
     machine — a fixed pause that was long enough on the day it was written
     turned into a test that failed about half the time and, worse, one nobody
     believed. It went red on a real regression and was read as noise. */
  const measure = async (readings) => {
    await page.locator(".panel.on button.step-run").click();
    if (typeof readings === "number") {
      await expect(page.locator(".point-row")).toHaveCount(readings, { timeout: 30_000 });
      return;
    }
    /* When how many there will be is the thing being asked, wait for them to
       stop arriving instead. */
    let before = -1;
    await expect.poll(async () => {
      const now = await page.locator(".point-row").count();
      const settled = now > 0 && now === before;
      before = now;
      return settled;
    }, { timeout: 30_000, intervals: [500, 500, 500, 500, 500, 500] }).toBe(true);
  };
  const placed = async () => {
    const rows = await page.locator(".point-row").allInnerTexts();
    return rows.map((t) => {
      const m = t.match(/(-?[\d.]+),\s*(-?[\d.]+)\s*mm/);
      return { x: Number(m[1]), y: Number(m[2]) };
    });
  };

  // one to a tileset, which for one drawn tileset is one point
  await expect(page.locator("#fp-count")).toHaveValue("1");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await measure(1);
  expect(await placed()).toHaveLength(1);

  /* Three to a tileset, each in its own share of it — and a fresh set rather
     than three more on top, because the three are settled against each other
     and a second set laid through the first would leave neither true. */
  /* A measured map holds the box that laid it: the points and the surface
     through them are one answer, so a fresh set goes down only after Reset has
     thrown the old one away. */
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  await page.locator("#fp-count").fill("3");
  await page.locator("#fp-count").dispatchEvent("input");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await measure(3);
  const three = await placed();
  expect(three, "three asked for, three there").toHaveLength(3);
  expect(new Set(three.map((p) => `${p.x},${p.y}`)).size,
    "no place measured twice").toBe(3);

  // laid in the tileset, which is the small square drawn inside the one well
  const spanX = Math.max(...three.map((p) => p.x)) - Math.min(...three.map((p) => p.x));
  const spanY = Math.max(...three.map((p) => p.y)) - Math.min(...three.map((p) => p.y));
  expect(Math.max(spanX, spanY), "spread out, not stacked on one spot")
    .toBeGreaterThan(0.2);

  // and pressing it again with the same number lays the same three
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  await page.locator("#fp-count").fill("3");
  await page.locator("#fp-count").dispatchEvent("input");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await measure(3);
  const again = await placed();
  expect(again).toHaveLength(3);
  expect(again).toEqual(three);

  /* More than the tileset holds is what it holds: a number is a wish, and the
     positions are what there is to measure. */
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  await page.locator("#fp-count").fill("99");
  await page.locator("#fp-count").dispatchEvent("input");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await measure("as many as it holds");
  const all = await placed();
  expect(all.length, "as many as the tileset has positions").toBeGreaterThan(3);

  /* One press for the whole way back: Clear all empties the measured map --
     the points and the surface through them are one answer, thrown away
     together. (Reset, which once owned this half, is gone.) */
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  expect(await page.locator(".point-row").count()).toBe(0);

  /* And an unmeasured set goes the same way: laid, thrown away, gone. The
     press stays offered either way -- one button, one meaning. */
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  expect(await page.locator(".point-row").count()).toBe(0);
});

test("one walk of the whole run", async ({ page }) => {
  /* The whole run, honestly waited for: 96 focus points measured and 864
     positions marched, with runStep holding until each run truly ends. On a
     slower machine that is more than the 30-second default — the same
     allowance the live specs give themselves. */
  test.setTimeout(300_000);
  await throughFields(page);

  await placeFocusPoints(page);
  await runStep(page, 1600);
  /* What the focus step came to is the box it opens, not a sentence beside its
     button: the traces, and a height for every point measured. */
  await expect(page.locator("#focus-traces")).toBeVisible();
  await expect(page.locator("#focus-traces .point-row")).toHaveCount(96);
  await expect(page.locator(".action-hint.ok")).toHaveCount(0);

  /* Everything after the plan is measured against the plan. The grid put 864
     positions down — nine 20x frames in each of the 96 wells — so that is what
     the scan drives through and what the tile picker counts; a step reading a
     list of its own would disagree here. */
  await gotoStep(page, "Scan the overview");
  await runStep(page, 3000);

  await gotoStep(page, "Detect objects");
  /* Detection starts from the first field. The scan's moving highlight is
     transient progress, not the operator's lasting field selection. */
  await expect(page.locator("#tile-label")).toHaveText("1 / 864");
  /* Discovery runs on the operator's say-so, tested or not -- the tile test
     is an offer. This walk still takes it, the way an operator would -- and
     first stops one by hand: the press that started the test becomes
     Interrupt, the readout says the field was not examined, and the press
     is ready again. */
  await page.getByRole("button", { name: "Test this tile" }).click();
  await expect(page.locator("#detect-try"), "the press that started the test becomes Interrupt").toHaveText("Interrupt");
  await page.locator("#detect-try").click();
  await expect(page.locator("#detect-readout")).toContainText("stopped by hand");
  await expect(page.locator("#detect-try")).toHaveText("Test this tile");
  await expect(page.locator("#detect-try")).toBeEnabled();
  await page.getByRole("button", { name: "Test this tile" }).click();
  /* What the test found rides on the press that made it. */
  await expect(page.locator("#detect-try")).toContainText(/\(\d+ objects/);
  /* Every field's targets land as the backend reports them; the pretend one
     reports 864 fields in a few seconds. */
  await expect(page.getByRole("button", { name: "Detect objects", exact: true })).toBeVisible();
  await runStep(page, 6000);

  const discovered = await targetsOnCanvas(page);
  expect(discovered.length, "Step 6 placed discovered targets on the canvas")
    .toBeGreaterThan(0);
  expect(discovered.every((target) => !target.selected && !target.acquired),
    "newly discovered targets are candidates, not silently selected").toBe(true);
  const plan = await page.evaluate(() => window.__theStageCanvas.plan());
  expect(discovered.every((target) => {
    const field = plan[target.field];
    return field
      && Math.abs(target.x - field.x) <= field.frameUm / 2
      && Math.abs(target.y - field.y) <= field.frameUm / 2;
  }), "every target is inside the overview field that discovered it").toBe(true);
  /* No marker per candidate: the masks show the population on the
     discovery step, and the cells layer draws only what is chosen. */
  await expectTargetAtItsProjection(page, discovered[0], "Step 6");

  await gotoStep(page, "Discover Targets");
  await expect(page.locator("#canvas-side .side-group-title").first())
    .toHaveText("Discovery method");
  await expect(page.locator("#refine-method")).toHaveValue("gating");
  await expect(page.locator("#refine-method option")).toHaveText("Feature gating");
  await expect(page.locator("#canvas-side .side-group-title").nth(1))
    .toHaveText("Feature gating");
  const beforeGate = await targetsOnCanvas(page);
  expect(physicalTargetPositions(beforeGate),
    "Step 7 keeps every discovered target at its carrier-local position")
    .toEqual(physicalTargetPositions(discovered));
  expect(beforeGate.every((target) => !target.selected),
    "Step 7 begins with candidates visible but no implicit gate").toBe(true);
  await expectTargetAtItsProjection(page, beforeGate[0], "Step 7 before gating");
  const sc = await page.locator("#scatter-canvas").boundingBox();
  /* A polygon gate on the largest, brightest corner — laid point by point
     and closed on its first vertex, the way the scan-area polygon is. The
     fractions are of the plot's frame, which stops short of the canvas's
     right edge where the y labels stand. */
  const corner = [[0.86, 0.08], [0.96, 0.08], [0.96, 0.22], [0.86, 0.22]];
  /* The plot must not move under the hand while a gate is laid: the readout
     under it wraps to a second line at the first point, and the column
     used to let the browser's scroll anchoring push the plot up by that
     line, so the closing press missed the first point by exactly it. The
     canvas is measured once, before the first point, on purpose. */
  for (const [gx, gy] of corner) {
    await page.mouse.click(...plotPoint(sc, gx, gy));
    await page.waitForTimeout(120);
  }
  expect(await page.locator("#scatter-canvas").boundingBox(),
    "the plot stands where it stood before the first point").toEqual(sc);
  await page.mouse.click(...plotPoint(sc, 0.86, 0.08));
  await page.waitForTimeout(300);
  await expect(page.locator("#gate-readout")).toContainText("selected");
  await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
  const refined = await targetsOnCanvas(page);
  /* The gate rings what it lets through as it is drawn: on the plot, in the
     readout, and on the shared canvas. */
  const inTheGate = refined.filter((target) => target.selected).length;
  expect(inTheGate, "the gate marks selected targets on the shared canvas").toBeGreaterThan(0);
  expect(physicalTargetPositions(refined)).toEqual(physicalTargetPositions(discovered));
  await expectTargetLayerOnCanvas(
    page, "cells", "Step 7 selected and context targets materially change the canvas");

  // the gate and its ceiling belong to the run, not to the panels that
  // drew them: the gates stand on Discover Targets, the ceiling on the
  // target scan area, and coming back each shows what the run holds
  await gotoStep(page, "Target scan area");
  const adding = page.locator(".side-group", {
    has: page.locator(".side-group-title", { hasText: "Add scan areas" }),
  });
  const scanAreaSummary = page.locator(".side-group", {
    has: page.locator(".side-group-title", { hasText: "Target tile summary" }),
  });
  await expect(page.locator("#target-type .side-group-title"))
    .toHaveText("Acquisition settings");
  await expect(adding, "nothing can be added before acquisition settings exist")
    .toBeHidden();
  await expect(scanAreaSummary, "there is no result to summarise before areas are placed")
    .toBeHidden();
  await expect(page.locator("#tiles-alpha"), "scan-area opacity is not an operator setting")
    .toHaveCount(0);
  await page.locator("#target-type .setting-box.open button.run").click();
  await page.waitForTimeout(650);
  await expect(page.locator("#target-type .setting-box.done")).toHaveCount(1);
  await expect(adding).toBeVisible();
  await expect(scanAreaSummary).toBeHidden();
  await expect(adding.locator(".side-group-body"))
    .toContainText("Max targets per overview tileset");
  await expect(adding.locator(".side-group-body"))
    .toContainText("Max target tiles per overview tileset");
  await expect(adding.locator(".target-main-settings-title"))
    .toHaveText("Main settings");
  await expect(page.locator("#tiles-margin"), "the coverage margin stays in the top box")
    .toBeVisible();
  await expect(page.locator("#overlap-min"), "big-target overlap is one of the four controls")
    .toBeVisible();
  await expect(adding.locator(".target-configuration"), "there is no secondary settings fold")
    .toHaveCount(0);
  await expect(adding.locator(".gate-draw"), "the placement contract is exactly four controls")
    .toHaveCount(4);
  expect(await adding.locator(".gate-draw").evaluateAll((rows) => rows.every(
    (row) => row.firstElementChild?.matches('input[type="checkbox"]'),
  )), "every setting has a switch before its words").toBe(true);
  /* With the ceiling switched off there is no sample: every gated target
     goes to placement. */
  await page.locator("#gate-max-on").uncheck();
  await expect(page.locator("#gate-max")).toBeDisabled();
  await runStep(page, 1000);
  expect((await targetsOnCanvas(page)).filter((target) => target.restricted).length,
    "sampling off sends every gated target to placement").toBe(inTheGate);
  await expect(scanAreaSummary).toBeVisible();
  await expect(scanAreaSummary.locator(".scan-summary .k"))
    .toContainText(["Target tiles", "Gated targets", "Covered targets"]);
  await expect(scanAreaSummary.locator("#scan-area-sampled")).toHaveText(String(inTheGate));
  await expect(scanAreaSummary.locator("#scan-area-coverage"))
    .toHaveText(`${inTheGate} of ${inTheGate}`);
  await expect(scanAreaSummary).not.toContainText("left out for overlap");
  const unrestrictedPlan = await page.evaluate(() => window.__theRunState());
  const heldByAreas = new Set(unrestrictedPlan.targetTilePositions
    .flatMap((tile) => tile.covers));
  expect(unrestrictedPlan.restricted.filter((id) => !heldByAreas.has(id)),
    "every target reported as covered is held with its margin by the placed areas")
    .toEqual([]);
  /* The second ceiling is tile accounting, independently per overview
     tileset. It may leave targets uncovered, but no tileset can spend a
     neighbour's allowance. */
  await page.locator("#tiles-max-on").check();
  await page.locator("#tiles-max").fill("1");
  await page.locator("#tiles-max").dispatchEvent("input");
  await runStep(page, 1000);
  const tileLimited = await page.evaluate(() => window.__theRunState());
  const tilesPerOverview = new Map();
  for (const tile of tileLimited.targetTilePositions) {
    tilesPerOverview.set(tile.overviewTileset,
      (tilesPerOverview.get(tile.overviewTileset) ?? 0) + 1);
  }
  expect([...tilesPerOverview.values()].every((count) => count <= 1),
    "the target-tile ceiling is applied to each overview tileset").toBe(true);
  await page.locator("#tiles-max-on").uncheck();
  await page.locator("#gate-max-on").check();
  await page.locator("#gate-max").fill("1");
  await page.locator("#gate-max").dispatchEvent("input");
  await page.waitForTimeout(200);
  expect((await targetsOnCanvas(page)).filter((target) => target.selected).length,
    "a ceiling typed is not a ceiling applied: the gate's whole catch stays selected").toBe(inTheGate);
  // standing on another step and coming back builds the panels afresh
  await gotoStep(page, "Scan the overview");
  await page.waitForTimeout(250);
  await gotoStep(page, "Discover Targets");
  await expect(page.locator("#gate-list .gate-row")).toHaveCount(1);
  expect((await targetsOnCanvas(page)).filter((target) => target.selected).length,
    "walking away and back restricts nothing").toBe(inTheGate);
  await gotoStep(page, "Target scan area");
  await expect(page.locator("#gate-max")).toHaveValue("1");

  /* The press samples, one per tileset under this ceiling, and places scan
     areas over the sample -- which needs the settings, imported first. */
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Place scan areas");
  await expect(page.locator("#target-type .setting-box.done")).toHaveCount(1);
  /* The ceiling is per tileset -- a well of the pretend plate -- so what
     survives is so many in each tileset the gate reaches into. */
  const tilesetOf = (target) => plan[target.field]?.tileset ?? target.field;
  const underCeiling = (targets, max) => {
    const perTileset = new Map();
    for (const target of targets) {
      const key = tilesetOf(target);
      perTileset.set(key, (perTileset.get(key) ?? 0) + 1);
    }
    return [...perTileset.values()].reduce((sum, n) => sum + Math.min(max, n), 0);
  };
  const gatedTargets = refined.filter((target) => target.selected);
  expect(underCeiling(gatedTargets, 1), "the gate reaches into fewer cells than it holds")
    .toBeLessThan(inTheGate);
  await runStep(page, 1000);
  const firstLaid = await page.evaluate(() => window.__theRunState().targetTiles);
  await expect(scanAreaSummary).toBeVisible();
  await expect(scanAreaSummary.locator("#scan-area-count")).toHaveText(String(firstLaid));
  await expect(scanAreaSummary.locator("#scan-area-sampled"))
    .toHaveText(String(underCeiling(gatedTargets, 1)));
  await expect(scanAreaSummary.locator("#scan-area-coverage"))
    .toHaveText(`${underCeiling(gatedTargets, 1)} of ${underCeiling(gatedTargets, 1)}`);
  expect((await targetsOnCanvas(page)).filter((target) => target.restricted).length,
    "Restrict holds the selection to the ceiling the box shows, per tileset")
    .toBe(underCeiling(gatedTargets, 1));
  expect((await targetsOnCanvas(page)).filter((target) => target.selected).length,
    "later steps show only the targets retained for this run")
    .toBe(underCeiling(gatedTargets, 1));
  await captureOperatorEvidence(page, "after-target-tiles.png");
  await gotoStep(page, "Discover Targets");
  await expect(page.locator("#gate-readout")).toContainText(`${underCeiling(gatedTargets, 1)} kept of ${inTheGate}`);
  await gotoStep(page, "Target scan area");
  /* A lever moved after the press is a plan not yet placed: the sample
     goes and the step asks for its press again. */
  await page.locator("#gate-max").fill("2");
  await page.locator("#gate-max").dispatchEvent("input");
  await page.waitForTimeout(200);
  await expect(scanAreaSummary, "changing a setting removes the old result")
    .toBeHidden();
  expect((await targetsOnCanvas(page)).filter((target) => target.restricted).length,
    "a new ceiling typed lifts the old one until the press").toBe(0);
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Place scan areas");
  await runStep(page, 1000);
  expect((await targetsOnCanvas(page)).filter((target) => target.restricted).length)
    .toBe(underCeiling(gatedTargets, 2));
  /* The scan areas are the plan: placed by the press over the sample, in
     the settings' frame, and what Acquire images. */
  await gotoStep(page, "Acquire Targets");
  const readyToAcquire = await targetsOnCanvas(page);
  expect(physicalTargetPositions(readyToAcquire),
    "Step 8 keeps the same targets at the same physical positions")
    .toEqual(physicalTargetPositions(discovered));
  expect(readyToAcquire.filter((target) => target.selected).length,
    "Step 8 receives the refined selection").toBeGreaterThan(0);
  /* No lit shapes here: on the acquisition step the frames are the picture,
     and a shape over a frame hid the pixels it was imaged for. */
  await expectTargetAtItsProjection(page, readyToAcquire[0], "Step 8 before acquisition");
  /* The scan areas were placed by the step before, over the sample and in
     the settings' frame: neighbours that fit in one frame share an area, so
     there are at most as many areas as sampled targets, and every sampled
     target is covered. The press here is ready. */
  const laid = await page.evaluate(() => window.__theRunState().targetTiles);
  expect(laid).toBeGreaterThan(0);
  expect(laid).toBeLessThanOrEqual(underCeiling(gatedTargets, 2));
  await gotoStep(page, "Target scan area");
  await expect(scanAreaSummary).toBeVisible();
  await expect(scanAreaSummary.locator("#scan-area-count")).toHaveText(String(laid));
  await expect(scanAreaSummary.locator("#scan-area-coverage"))
    .toHaveText(`${underCeiling(gatedTargets, 2)} of ${underCeiling(gatedTargets, 2)}`);
  await gotoStep(page, "Acquire Targets");
  await expect(page.locator(".panel.on button.step-run")).toBeEnabled();
  /* Stopped by hand after the first pair: what was taken stands everywhere
     the page accounts for it -- the rings, the gallery, the sentence beside
     the button -- and the step is not done, only run. */
  /* What the acquisition images is the scan areas placed, one capture each. */
  const gatedCount = await page.evaluate(() => window.__theRunState().targetTiles);
  await page.locator(".panel.on button.step-run").click();
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Interrupt");
  await expect.poll(async () => (await targetsOnCanvas(page)).filter((target) => target.acquired).length,
    { timeout: 10_000, message: "the first pair never landed" }).toBeGreaterThanOrEqual(1);
  /* Pressed on the button as it stands: the pretend run redraws the action
     bar every animation frame, and a click that waits for the button to hold
     still waits until the run is over -- and then presses Rerun all. */
  await page.evaluate(() => document.querySelector(".panel.on button.step-run").click());
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Rerun all", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Rerun current", exact: true })).toBeVisible();
  const taken = (await page.evaluate(() => window.__theRunState())).acquiredTileKeys.length;
  expect(taken, "the run was stopped before it finished, or the interruption proves nothing").toBeLessThan(gatedCount);
  await expect(page.locator("#target-list .point-row"), "the gallery lists every acquired tile, stopped or not").toHaveCount(taken);
  await expect(page.locator(".pair"), "and shows one pair, the chosen target's").toHaveCount(1);
  await expect(page.locator(".gallery-about"), "the target list needs no instruction strip").toHaveCount(0);
  await expect(page.locator(".pair .verdict, #target-list .z"), "Step 9 has no approval or rejection controls").toHaveCount(0);
  const comparison = await page.locator(".pair .imgs canvas").evaluateAll((canvases) =>
    canvases.map((canvas) => {
      const box = canvas.getBoundingClientRect();
      return { y: box.y, width: box.width, height: box.height };
    }));
  expect(comparison).toHaveLength(2);
  expect(comparison[1].y, "the high-resolution frame is below the overview crop")
    .toBeGreaterThanOrEqual(comparison[0].y + comparison[0].height);
  expect(comparison[1].width, "both images use the full comparison width")
    .toBeCloseTo(comparison[0].width, 0);
  const pairGeometry = await page.locator(".pair .imgs canvas").evaluateAll((canvases) =>
    canvases.map((canvas) => ({
      role: canvas.dataset.comparison,
      frameUm: Number(canvas.dataset.frameUm),
      x: Number(canvas.dataset.centreX),
      y: Number(canvas.dataset.centreY),
      display: new URL(canvas.dataset.picture, location.href).searchParams.get("display"),
    })));
  expect(pairGeometry.map(({ role }) => role)).toEqual(["overview", "target"]);
  expect(pairGeometry[0].frameUm, "both halves cover the same physical width")
    .toBeCloseTo(pairGeometry[1].frameUm, 8);
  expect(pairGeometry[0].x, "both halves are centred on the acquired scan area")
    .toBeCloseTo(pairGeometry[1].x, 8);
  expect(pairGeometry[0].y).toBeCloseTo(pairGeometry[1].y, 8);
  expect(pairGeometry[0].display, "both halves use the target frame's colour and count windows")
    .toBe(pairGeometry[1].display);
  await expect(page.locator(".action-hint"),
    "the two rerun actions are not crowded by a duplicate result sentence").toHaveCount(0);
  const afterTheHand = await page.evaluate(() => window.__theRunState());
  expect(afterTheHand.done, "an interrupted step is not done").not.toContain("acquire");
  expect(afterTheHand.ran, "but it ran, so it can be run again").toContain("acquire");
  await runStep(page, 3000);
  const acquired = await targetsOnCanvas(page);
  expect(physicalTargetPositions(acquired),
    "acquisition changes target state, never target placement")
    .toEqual(physicalTargetPositions(discovered));
  expect(acquired.filter((target) => target.acquired).length,
    "the acquired tiles mark the targets their real geometry covers")
    .toBeGreaterThan(0);
  expect((await page.evaluate(() => window.__theRunState())).acquiredTileKeys.length,
    "every planned target tile has one reachable acquisition")
    .toBe(await page.evaluate(() => window.__theRunState().targetTiles));
  await expectTargetLayerOnCanvas(
    page, "targets", "Step 8 acquired-target rings materially change the canvas");
  /* A press inside an acquired frame chooses that physical tile: the list
     says so and its pair comes up. Not the one already chosen, so the change
     shows. */
  {
    const run = await page.evaluate(() => window.__theRunState());
    const chosenBefore = run.selectedTarget;
    const other = run.targetTilePositions.find((tile) => tile.key !== chosenBefore);
    expect(other, "more than one target tile was acquired").toBeTruthy();
    const [x, y] = await page.evaluate(({ x, y }) => window.__theStageCanvas.project(x, y), other);
    const box = await page.locator("#stage-canvas").boundingBox();
    await page.mouse.click(box.x + x, box.y + y);
    await page.waitForTimeout(250);
    expect(await page.evaluate(() => window.__theRunState().selectedTarget),
      "a press inside the frame chooses the tile that was acquired there").toBe(other.key);
    await expect(page.locator(`#target-list .point-row[aria-current="true"]`)).toHaveCount(1);
  }
  /* The ground opens over each acquired frame as it does over each overview
     field: one window per planned scan area, centred on that area rather than
     silently returning to the anchor target. */
  const windows = await page.evaluate(() => window.__theStageCanvas.groundWindows());
  const { targetFrameUm: frameUm, targetTilePositions } = await page.evaluate(
    () => window.__theRunState());
  expect(frameUm, "the recording says how wide an acquired frame is").toBeGreaterThan(0);
  for (const tile of targetTilePositions) {
    const window = windows.find((one) =>
      Math.abs(one.x + one.w / 2 - tile.x) < 1e-6
      && Math.abs(one.y + one.h / 2 - tile.y) < 1e-6);
    expect(window, `the ground is open over the planned area for ${tile.targetId}`).toBeTruthy();
    expect(window.w).toBeCloseTo(frameUm, 6);
    expect(window.h).toBeCloseTo(frameUm, 6);
  }
  /* The two repeat choices live under the current comparison. Current means
     precisely the selected scan area; rerunning it preserves every other
     acquired pair, while the full-run action remains on the right. */
  const rerunCurrent = page.getByRole("button", { name: "Rerun current", exact: true });
  const rerunAll = page.getByRole("button", { name: "Rerun all", exact: true });
  const [pairBox, currentBox, allBox] = await Promise.all([
    page.locator(".pair").boundingBox(), rerunCurrent.boundingBox(), rerunAll.boundingBox(),
  ]);
  expect(currentBox.y, "repeat controls are below the image comparison")
    .toBeGreaterThanOrEqual(pairBox.y + pairBox.height);
  expect(allBox.x, "Rerun all is the right-hand action").toBeGreaterThan(currentBox.x);
  const acquiredBeforeCurrent = (await targetsOnCanvas(page)).filter((target) => target.acquired).length;
  const rowsBeforeCurrent = await page.locator("#target-list .point-row").count();
  await rerunCurrent.click();
  await expect(page.locator(".panel.on button.step-run")).toHaveText("Interrupt");
  await expect(page.locator(".panel.on button.step-run"))
    .toHaveText("Rerun all", { timeout: 10_000 });
  expect((await targetsOnCanvas(page)).filter((target) => target.acquired).length,
    "rerunning current preserves the other acquired targets").toBe(acquiredBeforeCurrent);
  await expect(page.locator("#target-list .point-row")).toHaveCount(rowsBeforeCurrent);
  await expect(page.locator(".side-tab .tab[aria-selected='true']"),
    "inspection continues after the run finishes").toContainText("Acquire Targets");
});
