import { test, expect } from "@playwright/test";
import { WORKFLOWS } from "../src/workflows/index.js";

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
  await page.waitForTimeout(200);
}

/** ...and the scan fields, which is what opens the steps that touch the
 * sample. The overview's preset is recorded here, where the fields that take
 * their frame from it are laid. */
async function throughFields(page) {
  await throughSetup(page);
  await gotoStep(page, "Initial scanfields");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-mode[data-mode='grid']").click();
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(300);
}

async function placeFocusPoints(page) {
  await gotoStep(page, "Focus strategy");
  // the autofocus preset is recorded beside the sweeps it will measure
  await recordSlot(page, "focus-preset", "af");
  // the default pattern: the top-left position of every compartment
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
  await expect(page.locator("#steps .step")).toHaveCount(9);
  await expect(page.locator(".step.active .step-name")).toHaveText("Connect");
  // the fields are said before the focus that keeps them sharp and the scan
  // that visits them, because both of those are about positions that exist
  await expect(page.locator(".step-name").nth(3)).toHaveText("Initial scanfields");
  await expect(page.locator(".step-name").nth(4)).toHaveText("Focus strategy");

  await page.locator("#wf-select").selectOption("overview_only");
  await expect(page.locator("#steps .step")).toHaveCount(6);
  await page.locator("#wf-select").selectOption("focus_check");
  await expect(page.locator("#steps .step")).toHaveCount(6);
});

/* The declaration and the page, held up against each other.
 *
 * `src/workflows/index.js` says which workflows exist and what is in them, and
 * this reads that file and then reads the running page to see whether it agrees.
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
  await gotoStep(page, "Define Carrier");
  await gotoStep(page, "Initial scanfields");
  await recordSlot(page, "sf-preset", "survey");
  await expect(page.locator("#sf-preset .rec-row")).toHaveCount(1);

  await gotoStep(page, "Connect");
  await page.locator(".session-foot button").click();
  await expect(fields.first(), "and the form is answerable again").toBeEnabled();
  await expect(page.locator(".check-row")).toHaveCount(0);
  await expect(page.locator(".session-done")).toHaveCount(0);
  await expect(page.locator('.field input[type="password"]')).toHaveValue("hunter2");
  await expect(page.locator('.step:has-text("Define Carrier")').first()).toBeDisabled();

  // and the next session starts where any run does: what the closed one
  // recorded is gone, what a run begins with is back
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await gotoStep(page, "Initial scanfields");
  await expect(page.locator("#sf-preset .rec-row")).toHaveCount(0);
  await expect(page.locator("#sf-preset .setting-box.open input")).toHaveValue("");
});

test("the fields wait for the preset they will be taken with",
  async ({ page }) => {
    await throughSetup(page);
    await gotoStep(page, "Initial scanfields");

    /* A preset is a reading taken off this instrument today. Nothing is
       seeded, and until it exists there is nothing to lay: a field takes its
       frame from the preset, so the editor waits behind the recorder. */
    await expect(page.locator("#sf-preset .setting-box.open")).toHaveCount(1);
    await expect(page.locator(".sf-card")).toHaveCount(0);
    // and an empty name is not a recording
    await expect(page.locator("#sf-preset button.run")).toBeDisabled();

    await recordSlot(page, "sf-preset", "overview");
    await expect(page.locator(".sf-card")).toHaveCount(1);
    // the name is stored capitalised, being an identifier the run refers to
    await expect(page.locator("#sf-preset .rec-name")).toHaveText("Overview");
    await expect(page.locator("#sf-preset .rec-row")).toContainText("NA");

    // forgetting the preset takes the editor away again — and the plan with
    // it, because a field cannot outlive the frame it was drawn for
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .toHaveClass(/done/);
    await page.locator("#sf-preset .rec-drop").click();
    await page.waitForTimeout(200);
    await expect(page.locator(".sf-card")).toHaveCount(0);
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .not.toHaveClass(/done/);
  });

test("a recorded preset unfolds to show everything that was read", async ({ page }) => {
  await throughSetup(page);
  await gotoStep(page, "Initial scanfields");
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
    await expect(page.locator('.step:has-text("Initial scanfields")').first()).toBeDisabled();

    await gotoStep(page, "Define Carrier");
    await page.waitForTimeout(200);
    await expect(page.locator('.step:has-text("Initial scanfields")').first()).toBeEnabled();
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    // positions are what that step needs, and the next one opens behind them
    await gotoStep(page, "Initial scanfields");
    await recordSlot(page, "sf-preset", "survey");
    await page.locator(".sf-mode[data-mode='grid']").click();
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
    await expect(page.locator(".session-title")).toHaveText("Connect to the microscope");

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
    await expect(page.locator(".session-title"), "and the session comes back when you return")
      .toHaveText("Connect to the microscope");
    await expect(page.locator(".check-row")).toHaveCount(6);
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-card")).toHaveCount(1);

    /* The channel belongs to the step standing in it. Scan fields are about
       the canvas the way the carrier is, so they take the same column and the
       heading says whose it is — rather than a second column beside it holding
       controls for a step nobody is on. */
    await gotoStep(page, "Initial scanfields");
    await expect(page.locator(".side-tab")).toHaveText("Initial scanfields");
    await expect(page.locator(".carrier-card")).toHaveCount(0);
    // the editor waits behind the preset recorder, in the same channel
    await expect(page.locator(".sf-card")).toHaveCount(0);
    await recordSlot(page, "sf-preset", "overview");
    await expect(page.locator(".sf-card")).toHaveCount(1);
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
    await gotoStep(page, "Initial scanfields");
    // nothing to scan yet, so the step is not done and the next one is shut
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .not.toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Focus strategy")').first()).toBeDisabled();

    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    // 96 areas, three by three in each
    await expect(page.locator(".sf-readout")).toContainText("864 positions");
    await expect(page.locator('.step:has-text("Initial scanfields")').first())
      .toHaveClass(/done/);

    /* And the carrier stops being editable, because these positions were
       placed relative to areas that must not move out from under them. */
    await gotoStep(page, "Define Carrier");
    await expect(page.locator(".carrier-preset")).toBeDisabled();

    /* A different plate is a different plan. The same three-by-three grid on
       six areas is 54 positions, not 864 — the count is read off the carrier
       rather than typed beside it. Disconnecting is what begins again: it
       takes the run with it, and the next session starts clean. */
    await gotoStep(page, "Connect");
    await page.locator(".session-foot button").click();
    await throughSetup(page);
    await page.locator(".carrier-preset").selectOption({ label: "6-well" });
    await page.waitForTimeout(200);
    await gotoStep(page, "Initial scanfields");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("54 positions");
  });

test("a volume is recorded off the stage, and holds the run until complete",
  async ({ page }) => {
    await connect(page);
    await gotoStep(page, "Define Carrier");
    await page.locator(".carrier-type[data-type='volume']").click();
    await page.waitForTimeout(150);

    // no catalogue controls: a volume is measured, not designed
    await expect(page.locator(".carrier-preset")).toBeHidden();
    await expect(page.locator(".carrier-vol-row")).toHaveCount(3);

    /* Standing settles every other carrier; an unfinished volume does not —
       the step is not done and nothing after it opens. */
    await expect(page.locator('.step:has-text("Define Carrier")').first())
      .not.toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Initial scanfields")').first()).toBeDisabled();

    /* Six recordings — drive to each extreme, record the bound. Re-queried
       per press, because the recorder redraws itself with every reading. */
    for (let axis = 0; axis < 3; axis++) {
      for (const name of ["Set min", "Set max"]) {
        await page.locator(".carrier-vol-row").nth(axis)
          .getByRole("button", { name }).click();
        await page.waitForTimeout(80);
      }
    }
    await expect(page.locator('.step:has-text("Define Carrier")').first())
      .toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Initial scanfields")').first()).toBeEnabled();

    // and the run reads it as the one area the bounds enclose
    await gotoStep(page, "Initial scanfields");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-mode[data-mode='grid']").click();
    await page.locator(".sf-apply-grid").click();
    await page.waitForTimeout(300);
    await expect(page.locator(".sf-readout")).toContainText("positions");
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
    await gotoStep(page, "Initial scanfields");
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

    await gotoStep(page, "Initial scanfields");
    await recordSlot(page, "sf-preset", "overview");
    await page.locator(".sf-mode[data-mode='grid']").click();
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
    await gotoStep(page, "Initial scanfields");
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

test("focus points follow the chosen pattern, laid per compartment",
  async ({ page }) => {
    await throughFields(page);
    await gotoStep(page, "Focus strategy");

    /* Where the points are, read off the list rather than off the canvas. The
       rows carry millimetres, which is what the claims are about. */
    const placed = async () => {
      const rows = await page.locator(".point-row").allInnerTexts();
      return rows.map((t) => {
        const m = t.match(/(-?[\d.]+),\s*(-?[\d.]+)\s*mm/);
        return { x: Number(m[1]), y: Number(m[2]) };
      });
    };

    /* First is the default: the top-left position of every well, and no
       number to type because the pattern already says it all. */
    await expect(page.locator("#fp-count-row")).toBeHidden();
    await expect(page.locator("#fp-hint")).toHaveText("96 points");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(300);
    expect(await placed()).toHaveLength(96);

    // every 3rd of the 9 positions in a well is 3 per well
    await page.locator("#fp-mode button[data-mode='interval']").click();
    await expect(page.locator("#fp-count-row")).toBeVisible();
    await page.locator("#fp-count").fill("3");
    await expect(page.locator("#fp-hint")).toHaveText("288 points");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(300);
    expect(await placed()).toHaveLength(288);

    // the centre asks for nothing either: one middle position per well
    await page.locator("#fp-mode button[data-mode='center']").click();
    await expect(page.locator("#fp-count-row")).toBeHidden();
    await expect(page.locator("#fp-hint")).toHaveText("96 points");

    /* Random draws without replacement, so two per well is two different
       positions in every one of the 96 — never the same spot measured twice. */
    await page.locator("#fp-mode button[data-mode='random']").click();
    await page.locator("#fp-count").fill("2");
    await expect(page.locator("#fp-hint")).toHaveText("192 points");
    await page.locator("#fp-place").click();
    await page.waitForTimeout(600);
    const pts = await placed();
    expect(pts).toHaveLength(192);
    expect(new Set(pts.map((p) => `${p.x},${p.y}`)).size,
      "no position measured twice").toBe(192);

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
  // the rail stays clean; what the step produced is said beside its button
  await expect(page.locator(".action-hint.ok")).toContainText("spline from 96 points");

  /* Everything after the plan is measured against the plan. The grid put 864
     positions down, so that is what the scan drives through and what the tile
     picker counts — a step reading a list of its own would disagree here. */
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
