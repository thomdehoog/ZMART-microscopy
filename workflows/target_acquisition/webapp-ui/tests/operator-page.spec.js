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

async function throughJobs(page) {
  await runStep(page, 950);
  for (const name of ["Set origin", "Capture overview job", "Capture target job"]) {
    await gotoStep(page, name);
    await runStep(page, 800);
  }
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
  await expect(page.locator("#steps .step")).toHaveCount(11);
  await expect(page.locator(".step.active .step-name")).toHaveText("Connect");

  await page.locator("#wf-select").selectOption("overview_only");
  await expect(page.locator("#steps .step")).toHaveCount(6);
  await page.locator("#wf-select").selectOption("focus_check");
  await expect(page.locator("#steps .step")).toHaveCount(5);
});

test("nothing advances by itself, and the next step stays locked until it can run",
  async ({ page }) => {
    await runStep(page, 950);
    await expect(page.locator(".step.active .step-name")).toHaveText("Connect");
    await expect(page.locator('.step:has-text("Connect")').first()).toHaveClass(/done/);
    await expect(page.locator('.step:has-text("Capture target job")').first()).toBeDisabled();
  });

test("setup holds the base until there is data, then the canvas takes over",
  async ({ page }) => {
    // an empty stage is not worth a tab; the configuration is
    await expect(page.locator(".tab")).toHaveText(["Setup"]);
    await throughJobs(page);
    await expect(page.locator(".tab")).toHaveText(["Setup"]);
    await expect(page.locator(".setup-row")).toHaveCount(5);
    await expect(page.locator(".setup-row").first()).toContainText("session open");

    await placeFocusPoints(page);
    await expect(page.locator(".tab")).toHaveText(["Setup", "Focus strategy"]);
    await expect(page.locator('.tab[aria-selected="true"]')).toHaveText("Focus strategy");

    await runStep(page, 1600);
    await gotoStep(page, "Scan the overview");
    await expect(page.locator(".tab")).toHaveText(["Setup"]);

    await runStep(page, 3000);
    await expect(page.locator(".tab"), "the first tile is what earns the canvas")
      .toHaveText(["Canvas"]);

    await gotoStep(page, "Focus strategy");
    await expect(page.locator(".tab"), "walking back reopens that step's panel")
      .toHaveText(["Canvas", "Focus strategy"]);
  });

test("one walk of the whole run", async ({ page }) => {
  await throughJobs(page);

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
