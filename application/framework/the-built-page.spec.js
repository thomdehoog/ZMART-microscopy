/**
 * The page the microscope is given looks like the page that was designed.
 *
 * These are two different files. In development the page is served by Vite,
 * a module at a time, and a drawing engine's stylesheet only arrives when the
 * engine is opened. The build folds everything into one file, so every
 * engine's CSS lands whether or not it draws -- and an engine is built to be a
 * whole application, with a stylesheet that says so. Neuroglancer's sets
 * `body { color: #fff; background: #000 }`, which is how the built page came
 * to draw white text on white panels while the one being worked on was fine.
 *
 * So this loads the built page the way the microscope will -- served by the
 * bridge, from `zmart-interface.py` -- and asks what it actually looks like.
 * Nothing here is about the design; it is about the two agreeing.
 */

import path from "node:path";

import { expect, test } from "@playwright/test";
import { rest, startTheBridge }
  from "../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";

const PORT = Number(process.env.BUILT_PAGE_PORT ?? 8825);

let bridge = null;

test.beforeAll(async () => { bridge = await startTheBridge({ port: PORT }); });
test.afterAll(async () => { await bridge?.stop(); });

/** What the page looks like where it is served from *url*. */
async function howItLooks(page, url) {
  const complaints = [];
  page.on("pageerror", (e) => complaints.push(e.message));
  await page.goto(url);
  await rest(2500);
  const looks = await page.evaluate(() => {
    const of = (sel) => {
      const node = document.querySelector(sel);
      return node ? getComputedStyle(node) : null;
    };
    const body = of("body");
    const step = of(".step.locked .step-name") ?? of(".step-name");
    return {
      ink: body.color,
      paper: body.backgroundColor,
      stepName: step.color,
      // The tokens themselves, so a mismatch says which half moved.
      tokenInk: getComputedStyle(document.documentElement)
        .getPropertyValue("--ink").trim(),
    };
  });
  page.removeAllListeners();
  return { ...looks, complaints };
}

test("the built page and the one being worked on look the same", async ({ page }) => {
  test.setTimeout(180_000);
  const at = `http://127.0.0.1:${PORT}`;

  const built = await howItLooks(page, `${at}/`);
  if (process.env.PANEL_UX_EVIDENCE_DIR) {
    await page.screenshot({
      path: path.join(process.env.PANEL_UX_EVIDENCE_DIR, "smart-operator-production-build.png"),
      fullPage: true,
    });
  }
  const dev = await howItLooks(page, `/?bridge=${encodeURIComponent(at)}`);

  expect(built.ink, "the page's own text colour").toBe(dev.ink);
  expect(built.paper, "the page's own background").toBe(dev.paper);
  expect(built.stepName, "a step's name in the rail").toBe(dev.stepName);
  // And it is the page's own token, not something a dependency imposed.
  expect(built.ink).toBe("rgb(15, 23, 42)");
  expect(built.complaints, "the built page complained on opening").toEqual([]);
});
