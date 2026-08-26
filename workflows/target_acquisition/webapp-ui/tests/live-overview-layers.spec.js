import { expect, test } from "@playwright/test";
import { settledPhotograph, startDemoRun, walkToTheScan } from "./live-run.js";
import { litBounds, meanGrid } from "./pixels.js";

/* Two acquisitions of the same sample, drawn as two layers of one picture.
 *
 * This is how a run is really shaped. The writer keeps one image per acquisition
 * type, so a low-power survey of the whole carrier is one image and the
 * high-power scan of the targets picked out of it is another, side by side in
 * the run's folder. They cover the same ground, so the honest way to show them is
 * one over the other: the survey underneath as the map, the target scan over it
 * as it fills in. An operator can then see where in the sample each target came
 * from, which is a question they ask constantly and cannot answer from two
 * pictures side by side.
 *
 * It also asks the transparency question from the other side. The target scan
 * covers the whole declared canvas and has imaged five places in it, so unless
 * the places it has not imaged are see-through, it hides the survey completely
 * and the arrangement is worthless. The measurement below is exactly that: the
 * five imaged squares show the target scan, and the nineteen it has not imaged
 * show the survey underneath.
 */

const PORT = Number(process.env.LIVE_OVERVIEW_LAYERS_PORT ?? 8790);
const ACROSS = 5;
const POSITIONS = 6;
const IMAGED = new Set(["0,0", "0,4", "4,0", "4,4", "2,2"]);

let run = null;

test.beforeAll(async () => {
  run = await startDemoRun({ port: PORT, pattern: "scattered", surveyUnderneath: true });
});
test.afterAll(() => { run?.stop(); });

test("a target scan drawn over the survey it was picked from", async ({ page }) => {
  test.setTimeout(240_000);

  /* The two acquisitions record different colours of light — the survey in the
     561 channel, which the writer draws amber, and the target scan in 488, which
     it draws green — so which of them a square is showing can be read off the
     screen rather than guessed at. */
  await page.goto(
    `/?backend=pretend&overview=${encodeURIComponent(run.survey)}`
    + `&targets=${encodeURIComponent(run.store)}&seethrough=1`,
  );
  await page.waitForTimeout(300);
  await walkToTheScan(page);
  await expect(page.locator("#overview-canvas")).toBeVisible();
  // Both acquisitions are named once both are open.
  await expect(page.locator("#overview-note")).toContainText("561 + 488");
  await page.addStyleTag({ content: ".live-note { display: none !important; }" });

  await run.acquire(POSITIONS);
  const shown = await settledPhotograph(page, "layers-survey-under-target-scan",
    { seconds: 14 });

  const bounds = litBounds(shown.pixels);
  expect(bounds, "something was drawn").not.toBeNull();
  const colours = meanGrid(shown.pixels, ACROSS, { over: bounds });
  const readable = colours
    .map((row) => row.map((c) => c.map((v) => String(v).padStart(3)).join(",")).join("  "))
    .join("\n");
  console.log(`the average colour of each of the 25 squares:\n${readable}`);

  /* Amber has red in it and green has almost none, which is all the telling
     apart this needs. */
  const survey = (colour) => colour[0] > 40;
  const targetScan = (colour) => colour[1] > 40 && colour[0] < 40;

  for (let row = 0; row < ACROSS; row++) {
    for (let col = 0; col < ACROSS; col++) {
      const where = `${row},${col}`;
      const colour = colours[row][col];
      if (IMAGED.has(where)) {
        expect(targetScan(colour),
          `the target scan imaged ${where}, so that is what is on top there. `
          + `Squares:\n${readable}`).toBe(true);
      } else {
        expect(survey(colour),
          `the target scan has not imaged ${where}, so the survey underneath shows `
          + `through. Squares:\n${readable}`).toBe(true);
      }
    }
  }
});
