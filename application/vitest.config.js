import { defineConfig } from "vitest/config";

/* Every test stands beside what it tests — a part's in the part, a step's in
   the step — so there is no tests folder to point at. What separates the two
   kinds is what they need: a `.test.js` runs on nothing but Node, and a
   `.spec.js` needs a browser and a dev server, which is Playwright's business
   and would only fail confusingly here. */
export default defineConfig({
  test: {
    include: ["{framework,parts,workflows}/**/*.test.js"],
    environment: "node",
  },
});
