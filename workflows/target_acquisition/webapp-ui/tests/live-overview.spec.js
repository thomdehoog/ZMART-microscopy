import { expect, test } from "@playwright/test";
import { fullestOver, said, startDemoRun, walkToTheScan } from "./live-run.js";

/* Does the overview really appear on screen as it is acquired?
 *
 * This is the one question worth asking about a live picture, and it is a
 * question about pixels. So that is what is measured here: the canvas is
 * photographed before any tile has been saved, again while tiles are arriving,
 * and again at the end, and what has to be true is that *more of the screen is
 * lit each time*. Nothing else is asserted — not that a loader resolved, not
 * that the console stayed quiet, not what the step's own counter says. A viewer
 * that reports itself perfectly loaded while drawing nothing has happened here
 * more than once, and every one of those checks passed while it did.
 *
 * The run it watches is written by the project's own writer; see `live-run.js`.
 *
 * Making sure it can fail
 * -----------------------
 *
 * A test that cannot go red is worse than no test, and this project has shipped
 * several. Set `LIVE_OVERVIEW_SABOTAGE=stalled` and no tile is ever written,
 * which is what an acquisition that died looks like from here: the page still
 * opens the run, the canvas is still there, the step still counts to the end,
 * and the picture stays black. The assertions below then fail, which is the
 * proof that they are measuring the picture and not the plumbing around it.
 */

const PORT = Number(process.env.LIVE_OVERVIEW_PORT ?? 8788);

let run = null;

test.beforeAll(async () => { run = await startDemoRun({ port: PORT }); });
test.afterAll(() => { run?.stop(); });

test("the overview appears on screen tile by tile as the run writes it", async ({ page }) => {
  test.setTimeout(180_000);

  await page.goto(`/?overview=${encodeURIComponent(run.store)}`);
  await page.waitForTimeout(300);
  await walkToTheScan(page);

  // The picture is where the plan was, because the scan is what is being looked
  // at now. Waiting for it to be there is not the test — what it is showing is.
  await expect(page.locator("#overview-canvas")).toBeVisible();
  await expect(page.locator("#overview-note")).toContainText("overview open");
  expect((await run.state()).written, "nothing has been imaged yet").toBe(0);

  /* Before anything has been acquired. The run has been declared at its full
     size, so the page has a canvas of the right shape and dimensions to draw —
     and nothing to draw in it. That is what an empty picture has to look like,
     and measuring it here is what makes the rise afterwards mean something. */
  const before = await fullestOver(page, "1-before-any-tile", { seconds: 4 });
  expect(before.lit, `the overview is not empty before the run starts: ${before.lit}`)
    .toBeLessThan(0.01);
  expect(before.distinct, "and it is a single flat colour").toBeLessThanOrEqual(2);

  /* Now run the scan, and let ten positions land while it is running. This is
     the path the step itself drives: every position it reports is a reason to
     read the run again. */
  await page.locator(".panel.on button.step-run").click();
  await run.acquire(10);
  await page.waitForTimeout(3000);
  const partway = await fullestOver(page, "2-partway");

  /* And the rest of them. A real acquisition takes longer than this page's
     rehearsal of it, so these land after the step has stopped reporting — which
     is exactly the case a picture driven only by the counter would miss. */
  await run.acquire(15);
  const finished = await fullestOver(page, "3-finished", { seconds: 10 });

  /* Said out loud, because the numbers are the result. A run of this reads
     something like "0.000 -> 0.307 -> 0.960", and those three photographs are
     kept beside them in test-results/live-overview. */
  console.log(`share of the overview lit: ${said([before, partway, finished])}`);
  const story = said([before, partway, finished]);

  expect(partway.lit, `more of the overview is on screen once tiles have landed: ${story}`)
    .toBeGreaterThan(before.lit + 0.05);
  expect(finished.lit, `and more again by the end of the run: ${story}`)
    .toBeGreaterThan(partway.lit + 0.05);

  /* A finished overview covers the view it is framed in, so most of the middle
     of the picture is specimen. And it is a picture rather than a wash of one
     colour: a flat fill would be indistinguishable from an empty panel, which is
     the whole reason the demo run writes something with structure in it. */
  expect(finished.lit, `the finished overview fills the view: ${finished.lit}`)
    .toBeGreaterThan(0.5);
  expect(finished.distinct, "with real detail in it").toBeGreaterThan(20);
  expect(finished.dominantFraction, "and no single colour taking it over")
    .toBeLessThan(0.9);
});
