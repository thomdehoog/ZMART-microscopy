import { defineConfig } from "@playwright/test";

/* AppLocker refuses to run executables from user-writable paths, so the
   browsers have to come from the whitelisted tree. Setting it here means
   `npm test` works without the caller remembering; without it Chromium dies
   with a bare `spawn UNKNOWN`. */
process.env.PLAYWRIGHT_BROWSERS_PATH ||=
  "C:\\ProgramData\\MinicondaZMB\\home\\t.de\\ms-playwright";

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
      /* Set PLAYWRIGHT_CHROMIUM if this machine keeps its browser somewhere
         Playwright did not put it. Left unset, Playwright uses its own. */
      executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined,
    },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
