/**
 * How the browser test is run.
 *
 * Two settings here are not the usual ones and both were arrived at by
 * measurement rather than taste, so they are worth explaining.
 *
 * **Which Chromium.** Playwright will normally only launch the one exact build
 * it was packaged against, and refuses anything else. This machine has a
 * perfectly good Chromium of a slightly different build and no way to fetch the
 * expected one, so it is named here directly. `PLAYWRIGHT_CHROMIUM` overrides it
 * for a machine where it lives somewhere else. The operator page's own
 * `playwright.config.js` searches for one instead, which is the friendlier
 * behaviour and the reason it is worth reading if this ever needs changing.
 *
 * **Drawing in software.** The picture is drawn by the graphics card, and a
 * browser with no screen has no card to draw with. The switches below ask it to
 * do the same work in software — slower, and identical in what it produces,
 * which is exactly what a test needs. Without them the box comes out blank and
 * the whole question this test asks cannot be answered at all.
 *
 * **One at a time.** This box has four cores, and running two browsers side by
 * side while measuring what they drew has been recorded here as worthless: the
 * two starve each other and the pictures come out half-drawn for reasons that
 * have nothing to do with what is being tested.
 */

import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Where Chromium is on this machine, unless the caller says otherwise. */
const CHROMIUM = process.env.PLAYWRIGHT_CHROMIUM
  || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

export default defineConfig({
  testDir: here,
  testMatch: "**/*.spec.mjs",
  globalSetup: path.join(here, "get-ready.mjs"),
  fullyParallel: false,
  workers: 1,
  // Long enough for the browser to fetch and draw three times over, and far
  // short of the point where a stuck test would waste somebody's afternoon.
  timeout: 180_000,
  reporter: [["list"]],
  use: {
    // The page is 1024 by 512, and the window is given room around it so that
    // nothing the browser draws for itself — a scrollbar — lands on the picture.
    viewport: { width: 1200, height: 700 },
    launchOptions: {
      args: [
        "--no-sandbox",
        "--use-gl=swiftshader",
        "--enable-unsafe-swiftshader",
        // Chromium's shared memory is small inside a container, and a browser
        // that runs out of it dies partway through drawing rather than saying so.
        "--disable-dev-shm-usage",
      ],
      executablePath: CHROMIUM,
    },
  },
});
