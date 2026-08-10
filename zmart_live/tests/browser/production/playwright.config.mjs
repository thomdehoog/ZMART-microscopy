/**
 * How this browser test is run.
 *
 * It is the settings file one folder up, pointed at this folder instead, and the
 * reasoning behind each unusual choice is written out there in full. The short
 * version, so that nobody has to go and look before changing something here:
 *
 * **Which Chromium.** Playwright will normally only launch the one exact build it
 * was packaged against. This machine has a perfectly good Chromium of a slightly
 * different build and no way to fetch the expected one, so it is named directly.
 * `PLAYWRIGHT_CHROMIUM` overrides it for a machine where it lives elsewhere.
 *
 * **Drawing in software.** The picture is normally drawn by the graphics card,
 * and a browser with no screen has no card to draw with. The switches below ask
 * it to do the same work in software — slower, and identical in what it produces.
 * Without them the box comes out blank and the question this test asks cannot be
 * answered at all.
 *
 * **One at a time.** Running two browsers side by side while measuring what they
 * drew has been recorded here as worthless: they starve each other and the
 * pictures come out half-drawn for reasons that have nothing to do with what is
 * being tested.
 *
 * The page itself is built by `../get-ready.mjs`, which is shared with the older
 * test rather than copied, because it is the same page.
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
  globalSetup: path.join(here, "..", "get-ready.mjs"),
  fullyParallel: false,
  workers: 1,
  // Long enough for the browser to fetch and draw three times over, and far short
  // of the point where a stuck test would waste somebody's afternoon.
  timeout: 180_000,
  reporter: [["list"]],
  use: {
    // The page draws into a box of 1024 by 512, and the window is given room
    // around it so that nothing the browser draws for itself — a scrollbar —
    // lands on the picture.
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
