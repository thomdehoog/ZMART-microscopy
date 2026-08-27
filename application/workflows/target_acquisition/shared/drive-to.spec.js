import { test, expect } from "@playwright/test";

/* Double-click the picture and the microscope goes there.
 *
 * The whole of it, end to end: the press becomes a place on the stage, the
 * place is sent to the instrument, the instrument answers with where it
 * ended up, and that answer — not the request — moves the red mark. Anything
 * less and the mark shows where the stage was asked to go rather than where
 * it is, which is the one thing it must never do.
 */

const connect = async (page) => {
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await expect(page.locator('.step:has-text("Define Carrier")').first())
    .toBeEnabled({ timeout: 15_000 });
};

/* Whether the stage mark is under the pointer: the canvas answers with its
   own tooltip, which is the page saying "the stage is here". */
const markIsAt = async (page, at) => {
  await page.mouse.move(at.x, at.y);
  await page.waitForTimeout(200);
  return page.locator("#stage-tip").evaluate((n) => n.classList.contains("on"));
};

test("double-clicking the picture drives the stage there", async ({ page }) => {
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  await page.goto("/?backend=pretend");
  await page.waitForTimeout(300);
  await connect(page);

  const box = await page.locator("#stage-canvas").boundingBox();
  /* Somewhere in the middle of the travel, well away from the corner the
     stage parks in — so "the mark is here" cannot be true by accident. */
  const going = { x: box.x + box.width * 0.55, y: box.y + box.height * 0.42 };

  expect(await markIsAt(page, going), "the stage is not there yet").toBe(false);

  await page.mouse.dblclick(going.x, going.y);
  await page.waitForTimeout(900);

  expect(await markIsAt(page, going), "the stage went where it was sent").toBe(true);
  await expect(page.locator("#stage-tip")).toContainText("mm");
  expect(errs, "console and page errors").toEqual([]);
});
