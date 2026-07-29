import { defineConfig } from "vitest/config";

/* Only the pure modules. tests/*.spec.js belongs to Playwright, which needs a
   browser and a dev server; running it here would just fail confusingly. */
export default defineConfig({
  test: {
    include: ["tests/unit/**/*.test.js"],
    environment: "node",
  },
});
