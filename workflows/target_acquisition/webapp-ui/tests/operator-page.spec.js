import { test, expect } from "@playwright/test";

/* Prototyping pace: this is a smoke net, not a specification. It covers the
   layout rules that everything else is built on and one walk of the whole
   flow, because the page is nearly all canvas and reading the source has
   repeatedly missed what driving it catches. Deeper cases — the focus model
   ladder, the metric legend, the drag override — are worth unit tests once
   the maths stops moving; they cost a full run each through the UI. */

const FOCUS_POINTS = [[0.3, 0.3], [0.68, 0.28], [0.5, 0.5], [0.32, 0.7], [0.7, 0.68]];

const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();

async function runStep(page, ms = 1000) {
  await page.locator("#action-bar button.run").click();
  await page.waitForTimeout(ms);
}

/** Connect is a form with its own button, not a step the action bar drives. */
async function connect(page, password = "hunter2") {
  await page.locator('.field input[type="password"]').fill(password);
  await page.locator(".session-form button.run").click();
  await page.waitForTimeout(2200);
}

/** Set the instrument up, name it, record it — the loop the panel is built on. */
async function record(page, kind, name) {
  // exactly one bar is open at a time; recording turns it into the record and
  // opens a fresh one below
  const bar = page.locator(".setting-box.open");
  await bar.locator("select").selectOption(kind);
  await bar.locator("input").fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(650);
}

/** Everything before the sample is touched: session, optics, carrier. */
async function throughSetup(page) {
  await connect(page);
  await gotoStep(page, "Optical Configuration");
  // recording is the work; there is no button to confirm afterwards
  await record(page, "acquisition", "survey");
  await record(page, "acquisition", "target");
  await gotoStep(page, "Carrier configuration");
  await runStep(page, 900);
}

async function placeFocusPoints(page) {
  await gotoStep(page, "Focus strategy");
  const box = await page.locator("#focus-canvas").boundingBox();
  for (const [fx, fy] of FOCUS_POINTS) {
    await page.mouse.click(box.x + box.width * fx, box.y + box.height * fy);
    await page.waitForTimeout(50);
  }
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
  await expect(page.locator("#steps .step")).toHaveCount(10);
  await expect(page.locator(".step.active .step-name")).toHaveText("Connect");

  await page.locator("#wf-select").selectOption("overview_only");
  await expect(page.locator("#steps .step")).toHaveCount(6);
  await page.locator("#wf-select").selectOption("focus_check");
  await expect(page.locator("#steps .step")).toHaveCount(6);
});

test("a session needs a password before it will open", async ({ page }) => {
  // the mock prefills one so it can be clicked through; empty it and the
  // session refuses to open
  const pw = page.locator('.field input[type="password"]');
  await expect(pw).not.toHaveValue("");
  await pw.fill("");
  await expect(page.locator(".session-form button.run")).toBeDisabled();
  await pw.fill("hunter2");
  await expect(page.locator(".session-form button.run")).toBeEnabled();
});

test("typing the password does not throw the field away", async ({ page }) => {
  const pw = page.locator('.field input[type="password"]');
  await pw.fill("");
  await pw.click();
  await page.keyboard.type("hunter2", { delay: 30 });
  // rebuilding the card on every keystroke destroys the input being typed into
  expect(await pw.inputValue()).toBe("hunter2");
  expect(await page.evaluate(() => document.activeElement?.type === "password")).toBe(true);
  await expect(page.locator(".session-form button.run")).toBeEnabled();
});

test("connecting reports what it checked", async ({ page }) => {
  await connect(page);
  await expect(page.locator(".check-row")).toHaveCount(6);
  await expect(page.locator(".check-row").first()).toContainText("Microscope reachable");
  await expect(page.locator(".session-state").first()).toContainText("Leica Stellaris 5");
});

test("the session can only be changed by disconnecting first", async ({ page }) => {
  const fields = page.locator(".session-form select, .session-form input");
  await connect(page);
  await expect(fields.first(), "an open session is what the run rests on").toBeDisabled();

  // and disconnecting takes the run with it: those settings came off this scope
  await gotoStep(page, "Optical Configuration");
  await record(page, "acquisition", "survey");
  await gotoStep(page, "Connect");
  await page.locator("button.run.danger").click();
  await page.waitForTimeout(300);

  await expect(fields.first()).toBeEnabled();
  await expect(page.locator('.field input[type="password"]'),
    "the credentials stay, since editing them is the reason to disconnect")
    .toHaveValue("hunter2");
  await expect(page.locator(".check-row")).toHaveCount(0);
  await expect(page.locator('.step:has-text("Connect")').first()).not.toHaveClass(/done/);
});

test("settings are recorded off the instrument, and the list grows", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical Configuration");

  // nothing is preconfigured: the only choice is what kind of thing to record
  await expect(page.locator("#action-bar"),
    "recording is the work, so there is nothing to confirm").toBeHidden();
  await expect(page.locator(".rec-row")).toHaveCount(0);
  await expect(page.locator('.step:has-text("Optical Configuration")').first())
    .not.toHaveClass(/done/);

  await record(page, "acquisition", "survey");
  await record(page, "acquisition", "target");
  await record(page, "autofocus", "af-coarse");

  await expect(page.locator(".rec-row")).toHaveCount(3);
  // grouped by kind rather than by the order record happened to be pressed
  await expect(page.locator(".setting-group:has(.setting-box.done)")).toHaveCount(2);
  // names are stored capitalised, being identifiers the run refers to
  await expect(page.locator(".rec-name").first()).toHaveText("Survey");
  await expect(page.locator(".rec-row").first()).toContainText("NA");
  await expect(page.locator(".rec-row").last()).toContainText("NA");
  // a setting existing is what completes the step
  await expect(page.locator('.step:has-text("Optical Configuration")').first())
    .toHaveClass(/done/);

  // a recorded setting and the next open bar are separate boxes
  await expect(page.locator(".setting-box.done")).toHaveCount(3);
  await expect(page.locator(".setting-box.open"), "and one bar is always waiting")
    .toHaveCount(1);
  await expect(page.locator(".setting-box.open").locator("input")).toHaveValue("");
});

test("the optical settings panel lines up", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical Configuration");
  await record(page, "acquisition", "survey");
  await record(page, "acquisition", "target");
  await record(page, "autofocus", "af coarse");

  const seen = await page.evaluate(() => {
    const round = (n) => Math.round(n);
    const boxes = [...document.querySelectorAll(".setting-box")]
      .map((e) => e.getBoundingClientRect());
    const labels = [...document.querySelectorAll(".group-label")]
      .map((e) => round(e.getBoundingClientRect().x));
    // whatever opens a row: the fold triangle, or the kind selector
    const starts = [
      ...[...document.querySelectorAll(".rec-fold")].map((e) => round(e.getBoundingClientRect().x)),
      round(document.querySelector(".rec-new select").getBoundingClientRect().x),
    ];
    // whatever closes it: the remove button, or Record
    const ends = [
      ...[...document.querySelectorAll(".rec-drop")].map((e) => round(e.getBoundingClientRect().right)),
      round(document.querySelector(".rec-new button.run").getBoundingClientRect().right),
    ];
    const heightsOf = (sel) => [...document.querySelectorAll(sel)]
      .map((e) => round(e.getBoundingClientRect().height));

    return {
      widths: boxes.map((b) => round(b.width)),
      // a recorded preset is a line of text; the open bar holds controls. Each
      // kind is uniform, and they differ by what they hold
      recordedHeights: heightsOf(".setting-box.done"),
      openHeights: heightsOf(".setting-box.open"),
      lefts: boxes.map((b) => round(b.x)),
      rights: boxes.map((b) => round(b.right)),
      labels, starts, ends,
    };
  });

  const one = (xs, what) => expect(new Set(xs).size, what).toBe(1);
  one(seen.widths, "every bar the same width");
  one(seen.recordedHeights, "every recorded bar the same height");
  one(seen.openHeights, "and the open bar consistent with itself");
  expect(seen.openHeights[0],
    "the open bar carries the same fields a session does, so it stands taller "
    + "than the line of text a recorded preset is")
    .toBeGreaterThan(seen.recordedHeights[0]);
  one(seen.lefts, "every bar on the same left edge");
  one(seen.rights, "every bar on the same right edge");
  one(seen.labels, "every label on that edge too");
  one(seen.starts, "every row opens in the same column");
  one(seen.ends, "and closes in the same one");
  expect(seen.lefts[0], "labels flush with the bars").toBe(seen.labels[0]);
});

test("a recorded preset unfolds to show everything that was read", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical Configuration");
  await record(page, "acquisition", "survey");

  // folded by default: a list of presets should stay a list
  await expect(page.locator(".rec-detail")).toHaveCount(0);
  await expect(page.locator(".rec-fold")).toHaveAttribute("aria-expanded", "false");

  await page.locator(".rec-fold").first().click();
  await expect(page.locator(".rec-fold")).toHaveAttribute("aria-expanded", "true");
  const labels = await page.locator(".rec-detail dt").allInnerTexts();
  expect(labels, "the detail behind the summary").toContain("Objective");
  expect(labels).toContain("Channel 1");
  await expect(page.locator(".rec-detail dd").first()).toContainText("NA");

  await page.locator(".rec-fold").first().click();
  await expect(page.locator(".rec-detail")).toHaveCount(0);
});

test("every label sits the same distance off its box", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical Configuration");
  await record(page, "acquisition", "survey");
  await record(page, "autofocus", "af coarse");

  const gaps = await page.evaluate(() =>
    [...document.querySelectorAll(".setting-group")].map((g) => {
      const label = g.querySelector(".group-label").getBoundingClientRect();
      const box = g.querySelector(".setting-box").getBoundingClientRect();
      return Math.round(box.top - label.bottom);
    }));
  expect(gaps.length, "add-new, plus one per kind").toBe(3);
  expect(new Set(gaps).size, "one spacing, not one per group").toBe(1);
});

test("a recording will not reuse a name", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical Configuration");
  await record(page, "acquisition", "survey");

  const bar = page.locator(".setting-box.open");
  await bar.locator("input").fill("survey");
  await expect(bar.locator("button.run")).toBeDisabled();
  await expect(bar.locator(".session-hint")).toHaveText("that name is already used");

  // and case is not a way around it: a name is a name
  await bar.locator("input").fill("SURVEY");
  await expect(bar.locator("button.run")).toBeDisabled();

  await bar.locator("input").fill("");
  await expect(bar.locator("button.run"),
    "and will not take an empty one either").toBeDisabled();
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
    await expect(page.locator('.step:has-text("Carrier configuration")').first()).toBeDisabled();
  });

test("the carrier sets the canvas up, and from then on it is always there",
  async ({ page }) => {
    // Its own panel and nothing else, so no tab bar at all: one tab is not a
    // choice, and the rail already says which step this is.
    await expect(page.locator(".tab")).toHaveCount(0);
    await throughSetup(page);
    await expect(page.locator(".tab"), "the run reached the carrier, so the canvas exists")
      .toHaveText(["Canvas", "Carrier configuration"]);
    // Only what the run has established, plus what is being done now. Nothing
    // up to here owns a row: the session and the carrier have their own cards,
    // and the focus surface is neither measured nor the step being stood on.
    await expect(page.locator(".setup-row")).toHaveCount(0);
    // a panel belongs to its step: standing on the carrier, its own is shown
    // and the session's is not
    await expect(page.locator(".carrier-card")).toHaveCount(1);
    await expect(page.locator(".session-card")).toHaveCount(0);
    await gotoStep(page, "Connect");
    await expect(page.locator(".session-title"), "and the session comes back when you return")
      .toHaveText("Session");
    await expect(page.locator(".check-row")).toHaveCount(6);

    await placeFocusPoints(page);
    await expect(page.locator(".tab")).toHaveText(["Canvas", "Focus strategy"]);
    await expect(page.locator('.tab[aria-selected="true"]')).toHaveText("Focus strategy");

    await runStep(page, 1600);
    // a step that owns no panel is the canvas alone — setup does not follow it
    await gotoStep(page, "Scan the overview");
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);

    await runStep(page, 3000);

    await gotoStep(page, "Focus strategy");
    await expect(page.locator(".tab"), "walking back reopens that step's panel")
      .toHaveText(["Canvas", "Focus strategy"]);
  });

test("one walk of the whole run", async ({ page }) => {
  await throughSetup(page);

  await placeFocusPoints(page);
  await runStep(page, 1600);
  await expect(page.locator("#focus-readout")).toContainText("spline · 5 points");

  await gotoStep(page, "Scan the overview");
  await runStep(page, 3000);

  await gotoStep(page, "Detect cells");
  await expect(page.locator("#action-bar button.run"),
    "detection may not run on settings nobody has seen work").toBeDisabled();
  await page.getByRole("button", { name: "Test on this tile" }).click();
  await page.waitForTimeout(250);
  await runStep(page, 2200);
  await expect(page.locator('.step:has-text("Detect cells") .step-note')).toContainText("cells");

  await gotoStep(page, "Select cells");
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
  await gotoStep(page, "Select cells");
  await expect(page.locator("#gate-readout")).toContainText("detected gated");

  await runStep(page, 1000);
  await gotoStep(page, "Acquire and curate");
  await runStep(page, 3000);
  await page.locator(".pair").first().locator("button.pick-good").click();
  await expect(page.locator("#gallery-readout")).toContainText("1 marked");
  await expect(page.locator('.tab[aria-selected="true"]'),
    "curation continues after the run finishes").toContainText("Gallery");
});
