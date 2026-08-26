import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

/* AppLocker refuses to run executables from user-writable paths, so the
   browsers have to come from the whitelisted tree. Setting it here means
   `npm test` works without the caller remembering; without it Chromium dies
   with a bare `spawn UNKNOWN`. */
process.env.PLAYWRIGHT_BROWSERS_PATH ||=
  "C:\\ProgramData\\MinicondaZMB\\home\\t.de\\ms-playwright";

/**
 * Find a Chromium this machine already has, or hand back nothing if it has none.
 *
 * Playwright will only offer the one exact build it was packaged against, and
 * refuses to launch anything else. So a machine that has a perfectly good
 * Chromium of a slightly different build — and no way to download the expected
 * one — fails every test here with an error about installing browsers, when the
 * browser it needs is sitting right there. Before giving up, we go and look.
 *
 * No build number is written down on purpose: whichever ones are present get
 * found, and the newest is preferred. The viewer's own suite searches in exactly
 * this way, in `zmart-viewer/tests/conftest.py`, and the two are meant to behave
 * the same. Set `PLAYWRIGHT_CHROMIUM` to a browser of your choosing to skip the
 * search entirely.
 */
function findAChromium() {
  const chosenByHand = (process.env.PLAYWRIGHT_CHROMIUM || "").trim();
  if (chosenByHand) return existsSync(chosenByHand) ? chosenByHand : undefined;

  /* Where Playwright unpacks browsers: one folder per build, named for it, such
     as `chromium-1194`. The value `0` is special and means "beside the package",
     which Playwright already knows how to find without help from us. */
  const toldToUse = (process.env.PLAYWRIGHT_BROWSERS_PATH || "").trim();
  const placesToLook = [
    ...(toldToUse && toldToUse !== "0" ? [toldToUse] : []),
    "/opt/pw-browsers",
  ];
  /* The layout inside a build folder, on each operating system. */
  const insideABuildFolder = [
    ["chrome-linux", "chrome"],
    ["chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"],
    ["chrome-win", "chrome.exe"],
  ];

  const found = [];
  for (const place of placesToLook) {
    if (!existsSync(place)) continue;
    for (const buildFolder of readdirSync(place)) {
      for (const layout of insideABuildFolder) {
        const browser = join(place, buildFolder, ...layout);
        if (!existsSync(browser)) continue;
        /* A folder that does not end in a number sorts last rather than
           causing trouble. */
        const trailingDigits = /(\d+)$/.exec(buildFolder);
        found.push({ browser, build: trailingDigits ? Number(trailingDigits[1]) : -1 });
      }
    }
  }
  found.sort((a, b) => b.build - a.build);
  return found.length ? found[0].browser : undefined;
}

const theChromiumToUse = findAChromium();

export default defineConfig({
  testDir: "./tests",
  // tests/unit/**.test.js belongs to vitest; the two runners share a folder
  testMatch: "**/*.spec.js",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    viewport: { width: 1440, height: 900 },
    launchOptions: {
      /* The acquired overview is drawn by the graphics card, and a browser with
         no screen has no card to draw with. These ask it to do the drawing in
         software instead — slower, and identical in what it produces, which is
         what a test needs. Without them the overview canvas comes out blank and
         the live picture cannot be tested at all. */
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
      ],
      /* Whichever Chromium this machine turned out to have. Left as nothing
         when the machine has none in the usual places, so that Playwright falls
         back to its own and says so plainly if that is missing too. */
      executablePath: theChromiumToUse,
    },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
