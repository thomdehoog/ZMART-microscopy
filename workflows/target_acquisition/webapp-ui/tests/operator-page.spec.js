import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { assembleWorkflows } from "../src/frame/rules/finding-workflows.js";

/* The workflows, found the way the page finds them: every folder under
 * `src/workflows/` with a `flow.js` inside it. The page uses the build tool's
 * folder scan; a test running in Node reads the folder itself. Both hand what
 * they found to the same `assembleWorkflows`, so this suite and the page
 * cannot disagree about what the folders mean. */
const workflowsDir = fileURLToPath(new URL("../src/workflows/", import.meta.url));
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

/* A step's button sits at the end of whichever panel is showing, so this does
   not need to know which step it is running. */
async function runStep(page, ms = 1000) {
  await page.locator(".panel.on button.step-run").click();
  await page.waitForTimeout(ms);
}

/** Connect has its own button at the end of its card, not one the frame drives. */
async function connect(page, password = "hunter2") {
  await page.locator('.field input[type="password"]').fill(password);
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
}

/** Set the instrument up, name it, record it — into the slot in `hostId`.
 * There is no presets step: each recording lives in the step that uses it. */
async function recordSlot(page, hostId, name) {
  const bar = page.locator(`#${hostId} .setting-box.open`);
  await bar.locator("input").fill(name);
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
  await page.locator(".carrier-preset").selectOption({ label: "96-well" });
  await page.waitForTimeout(200);
}

/** ...on a plate with real room in each well. A 6-well plate's wells are far
 * wider than a 96-well's 6.6 mm, so a drawn region holds many 676 µm frames
 * and the tests about covering a region have something to count. */
async function throughSetupRoomy(page) {
  await connect(page);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well" });
  await page.waitForTimeout(200);
}

/** ...and the scan fields, which is what opens the steps that touch the
 * sample. The overview's preset is recorded here, where the fields that take
 * their frame from it are laid. */
async function throughFields(page) {
  await throughSetup(page);
  await gotoStep(page, "Define scan area");
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

test.beforeEach(async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.errors = errors;
  await page.goto("/");
  await page.waitForTimeout(250);
});

test.afterEach(async ({ page }) => {
  expect(page.errors, "console and page errors").toEqual([]);
});

test("the rail carries the workflow's declared steps", async ({ page }) => {
  await expect(page.locator("#steps .step")).toHaveCount(8);
  await expect(page.locator(".step.active .step-name")).toHaveText("Connect");
  // the fields are said before the focus that keeps them sharp and the scan
  // that visits them, because both of those are about positions that exist
  await expect(page.locator(".step-name").nth(2)).toHaveText("Define scan area");
  await expect(page.locator(".step-name").nth(3)).toHaveText("Focus strategy");

  await page.locator("#wf-select").selectOption("overview_only");
  await expect(page.locator("#steps .step")).toHaveCount(5);
  await page.locator("#wf-select").selectOption("focus_surface_check");
  await expect(page.locator("#steps .step")).toHaveCount(5);
});

/* The declaration and the page, held up against each other.
 *
 * The folders under `src/workflows/` say which workflows exist and what is in
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

test("a session needs a password before it will open", async ({ page }) => {
  // the mock prefills one so it can be clicked through; empty it and the
  // session refuses to open
  const pw = page.locator('.field input[type="password"]');
  await expect(pw).not.toHaveValue("");
  await pw.fill("");
  await expect(page.locator(".session-foot button.run")).toBeDisabled();
  await pw.fill("hunter2");
  await expect(page.locator(".session-foot button.run")).toBeEnabled();
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
  await gotoStep(page, "Define scan area");
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
  await gotoStep(page, "Define scan area");
  await expect(page.locator("#sf-preset .rec-row")).toHaveCount(0);
  await expect(page.locator("#sf-preset .setting-box.open input")).toHaveValue("");
});

test("the fields wait for the preset they will be taken with",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Define scan area");

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
    // the name is stored capitalised, being an identifier the run refers to
    await expect(page.locator("#sf-preset .rec-name")).toHaveText("Overview");
    await expect(page.locator("#sf-preset .rec-row")).toContainText("NA");

    /* Forgetting the last reading puts the editor back to sleep and takes the
       plan with it — the regions and grid positions included. A field says
       what to image and with what, and with no preset left there is no with:
       outlines kept on the canvas would be a picture of a plan the run could
       not run. */
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Define scan area")').first())
      .toHaveClass(/done/);
    await page.locator("#sf-preset .rec-drop").click();
    await page.waitForTimeout(200);
    await expect(page.locator("#sf-preset .rec-row")).toHaveCount(0);
    await expect(page.locator(".sf-tools"),
      "and the ways of laying fields go with it").toBeHidden();
    await expect(page.locator(".sf-apply-grid")).toBeHidden();
    await expect(page.locator(".sf-readout")).toContainText("nothing to scan yet");
    await expect(page.locator('.step:has-text("Define scan area")').first())
      .not.toHaveClass(/done/);
  });

test("activating a second reading re-takes the whole plan with it",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Define scan area");
    await recordSlot(page, "sf-preset", "overview");

    /* A region rather than the grid: what a region costs is what its preset
       says a frame covers, so switching between presets is a number on the
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

    /* The optics get changed in the middle of a session, and saying so must
       not cost the reading already taken: the second one stands beside the
       first, and recording it makes it the active one — so the region already
       drawn is taken at 63x, a fraction of the frame and many times the
       tiles. Recording is activating; there is nothing further to press. */
    await recordSlot(page, "sf-preset", "hires");
    await expect(page.locator("#sf-preset .rec-row")).toHaveCount(2);
    await expect(page.locator("#sf-preset .rec-name").first()).toHaveText("Overview");
    await expect(page.locator("#sf-preset .rec-pick").nth(1))
      .toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#sf-preset .rec-pick").first())
      .toHaveAttribute("aria-pressed", "false");
    const oil = await positions();
    expect(oil, "the same region at 63x").toBeGreaterThan(dry * 10);

    /* And back, by activating the first reading. The row is the whole of it:
       no list of presets beside it, and nothing that would take half the plan
       with one reading and half with the other. */
    await expect(page.locator(".sf-presets")).toHaveCount(0);
    await expect(page.locator(".sf-flat", { hasText: "Apply to" })).toHaveCount(0);
    await page.locator("#sf-preset .rec-pick").first().click();
    await page.waitForTimeout(300);
    await expect(page.locator("#sf-preset .rec-pick").first())
      .toHaveAttribute("aria-pressed", "true");
    expect(await positions(), "taken with the dry preset again").toBe(dry);

    /* Both readings can be open at once, since comparing them is reading
       both. */
    await page.locator("#sf-preset .rec-fold").first().click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(1);
    await page.locator("#sf-preset .rec-fold").nth(1).click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(2);
    await expect(page.locator("#sf-preset .rec-fold").first())
      .toHaveAttribute("aria-expanded", "true");
  });

test("every reading taken is on screen, and any of them can be unfolded",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Define scan area");
    for (const name of ["overview", "hires", "tenx", "fortyx"]) {
      await recordSlot(page, "sf-preset", name);
    }
    await expect(page.locator("#sf-preset .rec-row")).toHaveCount(4);

    // the slot is as tall as what it holds; nothing is hidden behind a bar
    const list = page.locator("#sf-preset .rec-list");
    const [scrollH, clientH] = await list.evaluate((el) => [el.scrollHeight, el.clientHeight]);
    expect(clientH, "nothing to scroll to").toBe(scrollH);

    /* And two readings can be open at once: comparing them means reading
       both, and folding one away to look at the other asks the operator to
       hold it in their head. */
    await page.locator("#sf-preset .rec-fold").first().click();
    await page.locator("#sf-preset .rec-fold").nth(2).click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(2);
    await page.locator("#sf-preset .rec-fold").first().click();
    await expect(page.locator("#sf-preset .rec-detail")).toHaveCount(1);
  });

test("a recorded preset unfolds to show everything that was read", async ({ page }) => {
  await throughSetup(page);
  await gotoStep(page, "Define scan area");
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

test("the api offered follows the microscope chosen", async ({ page }) => {
  const apis = () => page.locator(".field select").nth(1).locator("option").allInnerTexts();
  expect((await apis()).join()).toContain("CAM");
  await page.locator(".field select").first().selectOption("mesospim");
  await page.waitForTimeout(150);
  expect((await apis()).join()).toContain("Remote Control");
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
    await expect(page.locator('.step:has-text("Define scan area")').first()).toBeDisabled();

    await gotoStep(page, "Define Carrier");
    await page.waitForTimeout(200);
    await expect(page.locator('.step:has-text("Define scan area")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    // positions are what that step needs, and the next one opens behind them
    await gotoStep(page, "Define scan area");
    await recordSlot(page, "sf-preset", "survey");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Scan the overview")').first()).toBeDisabled();
  });

test("the canvas is always on the stage, and the channel follows the step",
  async ({ page }) => {
    /* One layout for every step: the picture on the left, the standing step's
       controls in the channel on the right. From the very first step — the
       session card is the channel of Connect. */
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab")).toHaveText("Connect");
    // headed the way every other step is headed: the name above the box
    await expect(page.locator("#canvas-side .side-group-title").first())
      .toHaveText("Connect to the microscope");

    await throughSetup(page);
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".panel.on button.step-run"),
      "configuring it is the work, so there is nothing to press").toHaveCount(0);
    await expect(page.locator('.step:has-text("Define Carrier")').first(),
      "and standing on it settles it").toHaveClass(/done/);
    // the channel is named over the column it heads, not as a tab you switch to
    await expect(page.locator(".side-tab")).toHaveText("Define Carrier");
    await expect(page.locator("#canvas-side")).toBeVisible();
    await expect(page.locator(".carrier-card")).toHaveCount(1);

    /* Walking back keeps the canvas: the channel changes hands instead. */
    await gotoStep(page, "Connect");
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab")).toHaveText("Connect");
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
    await gotoStep(page, "Define scan area");
    await expect(page.locator(".side-tab")).toHaveText("Define scan area");
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
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    await expect(page.locator(".side-tab")).toHaveText("Focus strategy");
    await expect(page.locator("#focus-controls")).toBeVisible();
    await expect(page.locator(".sf-card")).toHaveCount(0);

    await runStep(page, 1600);
    await gotoStep(page, "Scan the overview");
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    /* The scan records nothing; it chooses. Two boxes naming what the run is
       taken with, and the press that starts it at the end of them. */
    await expect(page.locator("#canvas-side .side-group-title"))
      .toHaveText(["Select acquisition preset", "Select focussing preset"]);
    await expect(page.locator(".panel.on button.step-run")).toHaveText("Start");
    // walking back to the carrier brings its controls back, locked now,
    // because something has been done inside the frame it set
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-card")).toHaveCount(1);
    await expect(page.locator(".carrier-num").first()).toBeDisabled();

    await gotoStep(page, "Scan the overview");
    await runStep(page, 3000);

    await gotoStep(page, "Focus strategy");
    await expect(page.locator(".side-tab"), "walking back brings its channel with it")
      .toHaveText("Focus strategy");
    await expect(page.locator("#focus-controls")).toBeVisible();
  });

test("the grid comes from the carrier, so changing the plate changes the plan",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Define scan area");
    // nothing to scan yet, so the step is not done and the next one is shut
    await expect(page.locator('.step:has-text("Define scan area")').first())
      .not.toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    /* 96 areas, and nine positions in each: the block asked for is three by
       three, and a 20x frame is 676 µm across while a well is 6.6 mm, so all
       nine frames sit comfortably inside the well. */
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Define scan area")').first())
      .toHaveClass(/done/);

    /* And the carrier stops being editable, because these positions were
       placed relative to areas that must not move out from under them. */
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-preset")).toBeDisabled();

    /* A different plate is a different plan. Six wells 34.8 mm across hold
       the whole three-by-three block, so the same grid is 54 positions rather
       than the 96 a plate of small wells allowed — the count is read off the
       carrier rather than typed beside it. Disconnecting is what begins again: it
       takes the run with it, and the next session starts clean. */
    await gotoStep(page, "Connect");
    await page.locator(".session-foot button.danger").click();
    await throughSetup(page);
    await page.locator(".carrier-preset").selectOption({ label: "6-well" });
    await page.waitForTimeout(200);
    await gotoStep(page, "Define scan area");
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

    /* Where the pointer is, in the stage's own units, read off the page rather
       than worked out here: the canvas already says it, and a test that did
       the projection itself would be checking its own arithmetic. */
    const underThePointer = async () => {
      const said = await page.locator("#stage-readout").textContent();
      const m = /x (-?\d+) µm · y (-?\d+) µm · ([\d.]+) px\/mm/.exec(said);
      return { x: Number(m[1]), y: Number(m[2]), pxPerMm: Number(m[3]) };
    };

    /** Put the pointer on a stage position, by correcting towards it. */
    const pointAt = async (ux, uy, from) => {
      let at = { ...from };
      for (let i = 0; i < 5; i++) {
        await page.mouse.move(at.x, at.y);
        await page.waitForTimeout(60);
        const now = await underThePointer();
        const dx = ((ux - now.x) / 1000) * now.pxPerMm;
        const dy = ((uy - now.y) / 1000) * now.pxPerMm;
        if (Math.abs(dx) < 1 && Math.abs(dy) < 1) break;
        at = { x: at.x + dx, y: at.y + dy };
      }
      return at;
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
    const mark = await pointAt(4800, 3200, mid);
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
       mark leaves that pointer and is found where the picture put it. */
    await page.mouse.down();
    await page.mouse.move(mark.x + 180, mark.y + 110, { steps: 10 });
    await page.mouse.up();
    await page.mouse.move(mark.x, mark.y);
    await page.waitForTimeout(200);
    expect(await answering()).toBe(false);
    await page.mouse.move(mark.x + 180, mark.y + 110);
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

test("a carrier made up here can be saved to a file and loaded back",
  async ({ page }, testInfo) => {
    await connect(page);
    await gotoStep(page, "Define Carrier");
    await page.locator(".carrier-type[data-type='chamber']").click();
    await page.waitForTimeout(150);

    const width = page.locator("input[data-field='w']");
    const rows = page.locator("input[data-field='rows']");

    /* A chamber this lab made up: not the catalogue part it started as, which
       is the whole reason there is anywhere to put it. */
    await rows.fill("3");
    await rows.blur();
    await width.fill("17.5");
    await width.blur();
    await page.waitForTimeout(200);
    await expect(page.locator(".carrier-preset")).toHaveValue("-1");

    const saved = testInfo.outputPath("carrier.json");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator(".carrier-files button", { hasText: "Save" }).click(),
    ]);
    await download.saveAs(saved);

    // Reset puts the catalogue part back, so there is something to load over
    await page.locator(".carrier-files button", { hasText: "Reset" }).click();
    await page.waitForTimeout(200);
    await expect(page.locator(".carrier-preset")).toHaveValue("0");
    await expect(rows).not.toHaveValue("3");

    /* Loading is the save read back: the same numbers, and the carrier is
       once more not a catalogue part. */
    await page.locator(".carrier-files input[type=file]").setInputFiles(saved);
    await page.waitForTimeout(300);
    await expect(rows).toHaveValue("3");
    await expect(width).toHaveValue("17.50");
    await expect(page.locator(".carrier-preset")).toHaveValue("-1");

    // a file that is not a carrier leaves the one on screen exactly as it was
    await page.locator(".carrier-files input[type=file]").setInputFiles({
      name: "junk.json", mimeType: "application/json",
      buffer: Buffer.from('{"type":"not-a-carrier"}'),
    });
    await page.waitForTimeout(300);
    await expect(rows).toHaveValue("3");
    await expect(width).toHaveValue("17.50");
  });

test("the tools and the grid are on screen together, over what the grid laid",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Define scan area");
    /* Both ways of laying tilesets are offered at once, in one box with a word
       apiece over them. A grid laid in every well is a perfectly good thing to
       then draw a tileset over, and there is no mode to leave before doing
       it. */
    await expect(page.locator(".sf-tools")).toBeVisible();
    await expect(page.locator(".sf-apply-grid")).toBeVisible();
    await expect(page.locator(".side-group:has(.sf-tools) .sf-apply-grid"),
      "one box holding both ways of doing it").toHaveCount(1);
    await expect(page.locator(".side-group:has(.sf-tools) .side-sub"))
      .toHaveText(["Manually", "Automatically"]);
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
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
    await expect(page.locator(".sf-tool.on")).toHaveCount(1);
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
    await gotoStep(page, "Define scan area");
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

    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
  });

test("the plan stays editable until the overview has been scanned",
  async ({ page }) => {
    await throughFields(page);
    await placeFocusPoints(page);
    await runStep(page, 1600);

    /* Back past the focus map, the plan is still the operator's to change: a
       fitted surface is a statement about the plate, measured at points that
       stay where they were put whatever the scan fields do. */
    await gotoStep(page, "Define scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeEnabled();
    await expect(page.locator(".sf-tool[data-tool='rectangle']")).toBeEnabled();

    await gotoStep(page, "Scan the overview");
    await runStep(page, 3000);

    // and now it is not: the tiles are pictures taken at those positions
    await gotoStep(page, "Define scan area");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeDisabled();
    await expect(page.locator(".sf-tool[data-tool='rectangle']")).toBeDisabled();
  });

test("a press on empty canvas lets go of the selection, and the canvas shows it",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
    await gotoStep(page, "Define scan area");
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
       left, a grid put down under a 63x objective kept its 102 µm pitch when a
       20x was activated, and its nine positions came back as nine acquisitions
       of one square of sample stacked on top of each other. */
    await connect(page);
    await gotoStep(page, "Define Carrier");
    await page.locator(".carrier-type[data-type='slide']").click();
    await page.waitForTimeout(200);
    await gotoStep(page, "Define scan area");
    await recordSlot(page, "sf-preset", "wide");     // 20x, a 676 µm frame
    await recordSlot(page, "sf-preset", "close");    // 63x, a 102 µm frame

    // laid under the 63x, at the pitch the boxes offer for that frame
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(400);
    const tight = await planOf(page);
    expect(tight, "three by three").toHaveLength(9);
    expect(tight[0].frameUm).toBe(102);
    expect(closestGap(tight), "a frame apart, and no closer")
      .toBeGreaterThanOrEqual(102);

    // and activating the 20x lays it again rather than leaving it where it was
    await page.locator("#sf-preset .rec-pick").first().click();
    await page.waitForTimeout(600);
    const wide = await planOf(page);
    expect(wide, "still three by three").toHaveLength(9);
    expect(wide[0].frameUm).toBe(676);
    expect(closestGap(wide), "nine positions, not nine takes of one")
      .toBeGreaterThanOrEqual(676);
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
    await expect(page.locator("#focus-preset .rec-state").first()).toContainText("Software");
    await expect(page.locator('.step:has-text("Focus strategy")').first())
      .toHaveClass(/done/);
    await expect(page.locator(".panel.on button.step-run"),
      "nothing to run until there are points to measure").toHaveCount(0);

    /* The map is the optional extra, and there is only one of them: a run
       focuses one way, so there is one surface to fit and nothing to name or
       choose between. Points laid, the run has something to do. */
    await expect(page.locator("#fp-place"), "somewhere to lay points").toBeVisible();
    await page.locator("#fp-place").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".point-row").first()).toBeVisible();
    await expect(page.locator(".panel.on button.step-run")).toHaveCount(1);

    /* The second is a hardware autofocus: the stand holds focus off the
       coverslip at every position it is sent to. That too is a complete answer
       on its own — and it can be given a map just the same, because driving to
       a point and reading the height it settles at measures a surface as well
       as a scored stack does. */
    await recordSlot(page, "focus-preset", "hardware");
    await expect(page.locator("#focus-preset .rec-state").nth(1)).toContainText("Hardware");
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
  await page.locator(".carrier-preset").selectOption({ label: "6-well" });
  await page.waitForTimeout(200);
  await gotoStep(page, "Define scan area");
  await recordSlot(page, "sf-preset", "overview");
  const box = await page.locator("#stage-canvas").boundingBox();
  const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
  // in the middle of the top-centre well, where a region has positions to hold
  await page.locator(".sf-tool[data-tool='rectangle']").click();
  await page.mouse.move(at(0.46, 0.30).x, at(0.46, 0.30).y);
  await page.mouse.down();
  await page.mouse.move(at(0.54, 0.38).x, at(0.54, 0.38).y, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(page.locator(".sf-readout"), "the region covers positions")
    .not.toContainText("0 positions");

  await gotoStep(page, "Focus strategy");
  await recordSlot(page, "focus-preset", "coarse");

  /* Where the points are, read off the list rather than off the canvas. The
     rows carry millimetres, which is what the claims are about. */
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
  expect(await placed()).toHaveLength(1);

  /* Three to a tileset, each in its own share of it — and a fresh set rather
     than three more on top, because the three are settled against each other
     and a second set laid through the first would leave neither true. */
  await page.locator("#fp-count").fill("3");
  await page.locator("#fp-count").dispatchEvent("input");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
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
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  const again = await placed();
  expect(again).toHaveLength(3);
  expect(again).toEqual(three);

  /* More than the tileset holds is what it holds: a number is a wish, and the
     positions are what there is to measure. */
  await page.locator("#fp-count").fill("99");
  await page.locator("#fp-count").dispatchEvent("input");
  await page.locator("#fp-place").click();
  await page.waitForTimeout(300);
  const all = await placed();
  expect(all.length, "as many as the tileset has positions").toBeGreaterThan(3);

  // Clear empties it, and says so by refusing to be pressed again
  await page.locator("#fp-clear").click();
  await page.waitForTimeout(250);
  expect(await page.locator(".point-row").count()).toBe(0);
  await expect(page.locator("#fp-clear")).toBeDisabled();
});

test("one walk of the whole run", async ({ page }) => {
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

  await gotoStep(page, "Discover Targets");
  await expect(page.locator("#tile-label")).toHaveText("1 / 864");
  await expect(page.locator(".panel.on button.step-run"),
    "discovery may not run on settings nobody has seen work").toBeDisabled();
  await page.getByRole("button", { name: "Test on this tile" }).click();
  await page.waitForTimeout(250);
  await runStep(page, 2200);

  await gotoStep(page, "Refine Targets");
  const sc = await page.locator("#scatter-canvas").boundingBox();
  await page.mouse.move(sc.x + sc.width * 0.42, sc.y + sc.height * 0.18);
  await page.mouse.down();
  await page.mouse.move(sc.x + sc.width * 0.85, sc.y + sc.height * 0.62, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(page.locator("#gate-readout")).toContainText("detected gated");

  // the gate belongs to the run, not to the panel that drew it
  await page.locator('.tab:has-text("Canvas")').click();
  await page.waitForTimeout(250);
  await gotoStep(page, "Refine Targets");
  await expect(page.locator("#gate-readout")).toContainText("detected gated");

  await runStep(page, 1000);
  await gotoStep(page, "Acquire Targets");
  /* Nothing is imaged until the run knows what with: the acquisition type is
     recorded off the instrument in this step's own channel, and the button
     waits for it. */
  await expect(page.locator(".panel.on button.step-run")).toBeDisabled();
  const tt = page.locator("#target-type .setting-box.open");
  await tt.locator("input").fill("hires");
  await tt.locator("button.run").click();
  await page.waitForTimeout(650);
  await expect(page.locator("#target-type .rec-name")).toHaveText("Hires");
  await runStep(page, 3000);
  await page.locator(".pair").first().locator("button.pick-good").click();
  await expect(page.locator("#gallery-readout")).toContainText("1 marked");
  await expect(page.locator(".side-tab"),
    "curation continues after the run finishes").toContainText("Acquire Targets");
});
