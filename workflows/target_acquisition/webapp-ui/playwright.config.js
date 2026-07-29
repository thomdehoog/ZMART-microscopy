import { defineConfig } from "@playwright/test";

/* AppLocker refuses to run executables from user-writable paths, so the
   browsers have to come from the whitelisted tree. Setting it here means
   `npm test` works without the caller remembering; without it Chromium dies
   with a bare `spawn UNKNOWN`. */
process.env.PLAYWRIGHT_BROWSERS_PATH ||=
  "C:\\ProgramData\\MinicondaZMB\\home\\t.de\\ms-playwright";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
