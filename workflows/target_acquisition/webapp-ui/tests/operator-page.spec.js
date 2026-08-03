import { test, expect } from "@playwright/test";

/* Prototyping pace: this is a smoke net, not a specification. It covers the
   layout rules that everything else is built on and one walk of the whole
   flow, because the page is nearly all canvas and reading the source has
   repeatedly missed what driving it catches. Deeper cases — the focus model
   ladder, the metric legend, the drag override — are worth unit tests once
   the maths stops moving; they cost a full run each through the UI. */

const FOCUS_POINTS = [[0.3, 0.3], [0.68, 0.28], [0.5, 0.5], [0.32, 0.7], [0.7, 0.68]];

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
  /* Nothing is seeded, so the presets have to be recorded — a run cannot say
     where to scan until something says what a frame is. Configuring the carrier
     is the work, so standing on that step settles it. */
  await gotoStep(page, "Optical configuration");
  await record(page, "acquisition", "overview");
  await record(page, "acquisition", "target");
  await record(page, "autofocus", "af");
  await gotoStep(page, "Carrier configuration");
  await page.waitForTimeout(200);
}

/** ...and the scan fields, which is what opens the steps that touch the sample. */
async function throughFields(page) {
  await throughSetup(page);
  await gotoStep(page, "Initial scanfields");
  await page.locator(".sf-mode[data-mode='grid']").click();
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(300);
}

async function placeFocusPoints(page) {
  await gotoStep(page, "Focus strategy");
  // the focus map is the canvas now, not a map of its own
  const box = await page.locator("#stage-canvas").boundingBox();
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
  await expect(page.locator("#steps .step")).toHaveCount(11);
  await expect(page.locator(".step.active .step-name")).toHaveText("Microscope configuration");
  // the fields are said before the focus that keeps them sharp and the scan
  // that visits them, because both of those are about positions that exist
  await expect(page.locator(".step-name").nth(3)).toHaveText("Initial scanfields");
  await expect(page.locator(".step-name").nth(4)).toHaveText("Focus strategy");

  await page.locator("#wf-select").selectOption("overview_only");
  await expect(page.locator("#steps .step")).toHaveCount(7);
  await page.locator("#wf-select").selectOption("focus_check");
  await expect(page.locator("#steps .step")).toHaveCount(7);
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
  // the card ends on the answer rather than labelling itself in the corner
  await expect(page.locator(".session-head")).not.toContainText("Leica");
  await expect(page.locator(".session-done"))
    .toHaveText("Successfully connected to the Leica Stellaris 5 over CAM");
});

test("an open session is not editable, and Disconnect is the way out", async ({ page }) => {
  const fields = page.locator(".session-form select, .session-form input");
  await connect(page);
  await expect(fields.first(), "an open session is what the run rests on").toBeDisabled();
  await expect(page.locator(".check-row")).toHaveCount(6);

  // closing it takes the run with it — everything after this was read off this
  // session — but keeps what it was opened with, since editing that is the
  // reason to close one
  await gotoStep(page, "Optical configuration");
  const started = await page.locator(".rec-row").count();
  await record(page, "acquisition", "survey");
  await expect(page.locator(".rec-row")).toHaveCount(started + 1);

  await gotoStep(page, "Microscope configuration");
  await page.locator(".session-foot button").click();
  await expect(fields.first(), "and the form is answerable again").toBeEnabled();
  await expect(page.locator(".check-row")).toHaveCount(0);
  await expect(page.locator(".session-done")).toHaveCount(0);
  await expect(page.locator('.field input[type="password"]')).toHaveValue("hunter2");
  await expect(page.locator('.step:has-text("Optical configuration")').first()).toBeDisabled();

  // and the next session starts where any run does: what the closed one
  // recorded is gone, what a run begins with is back
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Optical configuration");
  await expect(page.locator(".rec-row")).toHaveCount(started);
});

test("a run starts with no presets, and one recording completes the step",
  async ({ page }) => {
    await connect(page);
    await gotoStep(page, "Optical configuration");

    /* A preset is a reading taken off this instrument today. Starting with
       three would be the mock telling the operator something untrue, and the
       step is not done until one has actually been taken. */
    await expect(page.locator(".rec-row")).toHaveCount(0);
    await expect(page.locator('.step:has-text("Optical configuration")').first())
      .not.toHaveClass(/done/);

    await record(page, "acquisition", "overview");
    await expect(page.locator(".rec-row")).toHaveCount(1);
    await expect(page.locator('.step:has-text("Optical configuration")').first())
      .toHaveClass(/done/);
  });

test("settings are recorded off the instrument, and the list grows", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical configuration");

  // recording is the work, so there is nothing to confirm afterwards
  await expect(page.locator(".panel.on button.step-run")).toHaveCount(0);
  await expect(page.locator(".rec-row")).toHaveCount(0);

  await record(page, "acquisition", "survey");
  await record(page, "autofocus", "af-coarse");

  await expect(page.locator(".rec-row")).toHaveCount(2);
  // grouped by kind rather than by the order record happened to be pressed
  await expect(page.locator(".setting-group:has(.setting-box.done)")).toHaveCount(2);
  // names are stored capitalised, being identifiers the run refers to
  await expect(page.locator(".rec-name").first()).toHaveText("Survey");
  await expect(page.locator(".rec-row").first()).toContainText("NA");
  await expect(page.locator(".rec-row").last()).toContainText("NA");

  // forgetting every preset undoes the step, since a preset existing is what
  // completed it. Re-queried each time: dropping one rebuilds the list, and a
  // handle taken before that points at an element no longer on the page
  while (await page.locator(".rec-drop").count()) {
    await page.locator(".rec-drop").first().click();
    await page.waitForTimeout(60);
  }
  await expect(page.locator(".rec-row")).toHaveCount(0);
  await expect(page.locator('.step:has-text("Optical configuration")').first())
    .not.toHaveClass(/done/);

  // a recorded setting and the next open bar are separate boxes, and one bar
  // is always waiting
  await expect(page.locator(".setting-box.open")).toHaveCount(1);
  await expect(page.locator(".setting-box.open").locator("input")).toHaveValue("");
});

test("the optical settings panel lines up", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical configuration");
  // names of their own: the mock already starts with an Overview, a Target and
  // an AF, and a name is a name whatever its case
  await record(page, "acquisition", "wide");
  await record(page, "acquisition", "zoom");
  await record(page, "autofocus", "af coarse");

  const seen = await page.evaluate(() => {
    const round = (n) => Math.round(n);
    const boxes = [...document.querySelectorAll(".setting-box")]
      .map((e) => e.getBoundingClientRect());
    const labels = [...document.querySelectorAll(".group-label")]
      .map((e) => round(e.getBoundingClientRect().x));
    // what opens a recorded row: its fold triangle
    const starts = [...document.querySelectorAll(".rec-fold")]
      .map((e) => round(e.getBoundingClientRect().x));
    // and the open bar, which is not a box, opens on the edge the boxes are on
    const openStart = round(document.querySelector(".rec-new input").getBoundingClientRect().x);
    /* A recorded row runs the width of its box and closes with the remove
       button. The open bar does not: its controls sit together at the start
       and the slack collects after Record, so there is nothing to line the
       far edge up with. */
    const ends = [...document.querySelectorAll(".rec-drop")]
      .map((e) => round(e.getBoundingClientRect().right));
    const heightsOf = (sel) => [...document.querySelectorAll(sel)]
      .map((e) => round(e.getBoundingClientRect().height));

    return {
      widths: boxes.map((b) => round(b.width)),
      recordedHeights: heightsOf(".setting-box.done"),
      lefts: boxes.map((b) => round(b.x)),
      rights: boxes.map((b) => round(b.right)),
      labels, starts, ends, openStart,
    };
  });

  const one = (xs, what) => expect(new Set(xs).size, what).toBe(1);
  one(seen.widths, "every bar the same width");
  one(seen.recordedHeights, "every recorded bar the same height");
  one(seen.lefts, "every bar on the same left edge");
  one(seen.rights, "every bar on the same right edge");
  one(seen.labels, "every label on that edge too");
  one(seen.starts, "every recorded row opens in the same column");
  one(seen.ends, "and closes in the same one");
  expect(seen.lefts[0], "labels flush with the bars").toBe(seen.labels[0]);
  expect(seen.openStart,
    "the open bar has no box of its own, so its field starts on the edge the "
    + "boxes stand on rather than inside one")
    .toBe(seen.lefts[0]);
});

test("a recorded preset unfolds to show everything that was read", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical configuration");
  await record(page, "acquisition", "survey");
  const fold = page.locator(".rec-fold").first();

  // folded by default: a list of presets should stay a list
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

test("every label sits the same distance off its box", async ({ page }) => {
  await connect(page);
  await gotoStep(page, "Optical configuration");
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
  await gotoStep(page, "Optical configuration");
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
    await expect(page.locator(".step.active .step-name")).toHaveText("Microscope configuration");
    await expect(page.locator('.step:has-text("Microscope configuration")').first()).toHaveClass(/done/);
    /* The rail stops at the first step that has not been done, and nothing is
       seeded, so Optical configuration is as far as it opens. */
    await expect(page.locator('.step:has-text("Optical configuration")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Carrier configuration")').first()).toBeDisabled();

    // one preset is what that step needs, and the next one opens behind it
    await gotoStep(page, "Optical configuration");
    await record(page, "acquisition", "survey");
    await expect(page.locator('.step:has-text("Carrier configuration")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();
  });

test("the canvas belongs to the steps that happen inside it, and to no others",
  async ({ page }) => {
    // a tab names what is loaded, even when it is the only one
    await expect(page.locator(".tab")).toHaveText(["Microscope configuration"]);
    await throughSetup(page);
    await expect(page.locator(".tab"), "the run reached the carrier, so the canvas exists")
      .toHaveText(["Canvas"]);
    await expect(page.locator(".panel.on button.step-run"),
      "configuring it is the work, so there is nothing to press").toHaveCount(0);
    await expect(page.locator('.step:has-text("Carrier configuration")').first(),
      "and standing on it settles it").toHaveClass(/done/);
    // the channel is named over the column it heads, not as a tab you switch to
    await expect(page.locator(".side-tab")).toHaveText("Carrier configuration");
    // the carrier is not a tab of its own: its controls dock beside the drawing
    // they change, and the canvas is the only picture of it
    await expect(page.locator("#canvas-side")).toBeVisible();
    await expect(page.locator(".carrier-card")).toHaveCount(1);
    // Only what the run has established, plus what is being done now. Nothing
    // up to here owns a row: the session has its own card, the carrier its own
    // channel, and the focus surface is neither measured nor being stood on.
    await expect(page.locator(".setup-row")).toHaveCount(0);

    // Walking back to a step that is not about the stage leaves the canvas
    // behind. The session and the instrument are not in the frame, so parking
    // a tab for it on those steps offers something they have nothing to do
    // with — the rule every other panel already follows.
    await gotoStep(page, "Optical configuration");
    await expect(page.locator(".tab")).toHaveText(["Optical configuration"]);
    await gotoStep(page, "Microscope configuration");
    await expect(page.locator(".tab")).toHaveText(["Microscope configuration"]);
    await expect(page.locator(".session-title"), "and the session comes back when you return")
      .toHaveText("Connect to the microscope");
    await expect(page.locator(".check-row")).toHaveCount(6);
    await expect(page.locator("#canvas-side"),
      "which is not the canvas, so the channel is not there either").toBeHidden();

    // and it is there again the moment the operator is back inside the frame
    await gotoStep(page, "Carrier configuration");
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);

    /* The channel belongs to the step standing in it. Scan fields are about
       the canvas the way the carrier is, so they take the same column and the
       heading says whose it is — rather than a second column beside it holding
       controls for a step nobody is on. */
    await gotoStep(page, "Initial scanfields");
    await expect(page.locator(".side-tab")).toHaveText("Initial scanfields");
    await expect(page.locator(".sf-card")).toHaveCount(1);
    await expect(page.locator(".carrier-card")).toHaveCount(0);
    await page.locator(".sf-mode[data-mode='grid']").click();
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
    // a step that owns no panel is the canvas alone — setup does not follow it
    await gotoStep(page, "Scan the overview");
    await expect(page.locator(".tab")).toHaveText(["Canvas"]);
    // and no channel, because no step is standing in it: the canvas keeps the
    // whole width for the picture that is about to fill it
    await expect(page.locator("#canvas-side")).toBeHidden();
    // walking back to the carrier brings its controls back, locked now,
    // because something has been done inside the frame it set
    await gotoStep(page, "Carrier configuration");
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
    await gotoStep(page, "Initial scanfields");
    // nothing to scan yet, so the step is not done and the next one is shut
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .not.toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    // 96 areas, three by three in each
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .toHaveClass(/done/);

    /* And the carrier stops being editable, because these positions were
       placed relative to areas that must not move out from under them. */
    await gotoStep(page, "Carrier configuration");
    await expect(page.locator(".carrier-preset")).toBeDisabled();

    /* A different plate is a different plan. The same three-by-three grid on
       six areas is 54 positions, not 864 — the count is read off the carrier
       rather than typed beside it. */
    await page.locator("#restart-btn").click();
    await throughSetup(page);
    await page.locator(".carrier-preset").selectOption({ label: "6-well" });
    await page.waitForTimeout(200);
    await gotoStep(page, "Initial scanfields");
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("54 positions");
  });

test("grid mode hides the drawing tools without freezing the canvas",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Initial scanfields");
    // still in grid mode, where there is nothing to draw with
    await expect(page.locator(".sf-mode[data-mode='grid']")).toHaveClass(/on/);
    await expect(page.locator(".sf-tools")).toBeHidden();
    await expect(page.locator(".sf-readout")).toContainText("864 positions");

    /* What the grid put down is still a set of fields, so it can be picked,
       added to and thrown away — a mode says what can be made, not whether
       what is already there can be touched. */
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
    await expect(page.locator(".sf-flat", { hasText: "Apply to selected" }),
      "a selection exists, so it can be given a preset").toBeEnabled();

    // and Delete takes them out of the plan
    const before = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    await page.keyboard.press("Delete");
    await page.waitForTimeout(200);
    const after = Number((await page.locator(".sf-readout").innerText()).match(/^(\d+)/)[1]);
    expect(after, "fewer positions than before").toBeLessThan(before);
  });

test("a grid position can be picked and dropped, but not dragged off its grid",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Initial scanfields");
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
      for (const fy of [0.5, 0.44, 0.56]) {
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
    await expect(page.locator(".sf-flat", { hasText: "Apply to selected" })).toBeEnabled();
    await page.keyboard.press("Delete");
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-readout")).toContainText("nothing to scan yet");
  });

test("a region is drawn on the canvas and covered by its preset's frame",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Initial scanfields");
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
    await gotoStep(page, "Initial scanfields");
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

    await gotoStep(page, "Initial scanfields");
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(400);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    expect(Buffer.compare(bare, await shot()) === 0,
      "the plan is on the canvas here").toBe(false);

    /* Back on the carrier the plan is not drawn: it is an answer to a question
       being asked again, and these areas are what it was placed against. */
    await gotoStep(page, "Carrier configuration");
    await page.waitForTimeout(300);
    expect(Buffer.compare(bare, await shot()) === 0,
      "the carrier is back to how it looked before any fields existed").toBe(true);

    // taken off the canvas, not thrown away
    await gotoStep(page, "Initial scanfields");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
  });

test("the plan stays editable until the overview has been scanned",
  async ({ page }) => {
    await throughFields(page);
    await placeFocusPoints(page);
    await runStep(page, 1600);
    // the toolbar that used to say so is gone; the rail row carries it now
    await expect(page.locator(".step", { hasText: "Focus strategy" }))
      .toContainText("from 5 points");

    /* Back past the focus map, the plan is still the operator's to change: a
       fitted surface is a statement about the plate, measured at points that
       stay where they were put whatever the scan fields do. */
    await gotoStep(page, "Initial scanfields");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeEnabled();
    await expect(page.locator(".sf-mode[data-mode='geometry']")).toBeEnabled();

    await gotoStep(page, "Scan the overview");
    await runStep(page, 3000);

    // and now it is not: the tiles are pictures taken at those positions
    await gotoStep(page, "Initial scanfields");
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-apply-grid")).toBeDisabled();
    await expect(page.locator(".sf-mode[data-mode='geometry']")).toBeDisabled();
  });

test("a press on empty canvas lets go of the selection, and the canvas shows it",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Initial scanfields");
    const box = await page.locator("#stage-canvas").boundingBox();
    const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
    const shot = () => page.locator("#stage-canvas").screenshot();

    await page.locator(".sf-tool[data-tool='rectangle']").click();
    await page.mouse.move(at(0.3, 0.3).x, at(0.3, 0.3).y);
    await page.mouse.down();
    await page.mouse.move(at(0.45, 0.5).x, at(0.45, 0.5).y, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(250);

    // drawn and selected: grips on the canvas, and the panel can reassign it
    await expect(page.locator(".sf-flat", { hasText: "Apply to selected" })).toBeEnabled();
    const selected = await shot();

    /* The press that deselects is also the press that starts a pan, so the
       editor never claims it — which is exactly how it once cleared the
       selection without the canvas ever being told to repaint. */
    const empty = at(0.85, 0.85);
    await page.mouse.move(empty.x, empty.y);
    await page.mouse.down();
    await page.mouse.up();
    await page.waitForTimeout(250);
    await expect(page.locator(".sf-flat", { hasText: "Apply to selected" })).toBeDisabled();
    expect(Buffer.compare(selected, await shot()) === 0,
      "the grips are gone from the picture, not just from the panel").toBe(false);
  });

test("a region can be copied, and a second paste lands clear of the first",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Initial scanfields");
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
    await gotoStep(page, "Initial scanfields");
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

test("focus points are laid out on a random lattice, not scattered",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Focus strategy");

    /* Where the points are, read off the list rather than off the canvas. The
       rows carry millimetres, which is what the claim is about. */
    const placed = async () => {
      const rows = await page.locator(".point-row").allInnerTexts();
      return rows.map((t) => {
        const m = t.match(/(-?[\d.]+),\s*(-?[\d.]+)\s*mm/);
        return { x: Number(m[1]), y: Number(m[2]) };
      });
    };
    const closestPair = (pts) => {
      let min = Infinity;
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          min = Math.min(min, Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y));
        }
      }
      return min;
    };

    await page.locator("#fp-count").fill("12");
    await expect(page.locator("#fp-hint")).toHaveText("12 points");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(300);

    const pts = await placed();
    expect(pts).toHaveLength(12);
    /* Twelve points over a 105 × 70 mm plate sit on a 4 × 3 lattice, so the
       pitch is over 20 mm and nothing can be near anything. Independent random
       points would put some pair inside 10 mm most of the time — that clumping
       is the whole reason for sampling this way. */
    expect(closestPair(pts), "no two points crowd each other").toBeGreaterThan(10);

    // and one lattice per compartment, so every well is measured
    await page.locator("#fp-scope button[data-scope='area']").click();
    await page.locator("#fp-count").fill("2");
    await expect(page.locator("#fp-hint")).toHaveText("192 points");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(600);
    expect(await page.locator(".point-row").count()).toBe(192);

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
  await expect(page.locator(".step", { hasText: "Focus strategy" }))
    .toContainText("spline from 5 points");

  /* Everything after the plan is measured against the plan. The grid put 864
     positions down, so that is what the scan drives through and what the tile
     picker counts — a step reading a list of its own would disagree here. */
  await gotoStep(page, "Scan the overview");
  await runStep(page, 3000);
  await expect(page.locator('.step:has-text("Scan the overview") .step-note'))
    .toContainText("864 / 864 tiles");

  await gotoStep(page, "Detect cells");
  await expect(page.locator("#tile-label")).toHaveText("1 / 864");
  await expect(page.locator(".panel.on button.step-run"),
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
