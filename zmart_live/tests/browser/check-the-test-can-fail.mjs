/**
 * Breaking the rule on purpose, to see whether the browser test notices.
 *
 * A passing test tells you nothing until you have watched it fail for the right
 * reason, and the test beside this one is unusually easy to fool. Its middle
 * step makes two claims at once — position B is not on the screen, and position
 * A still is — and each of them can go quietly wrong in a different way.
 *
 * "B is not on the screen" is perfectly true of a completely black screen: of a
 * page that never opened, an engine that never started, a run that was never
 * served. And "A is still on the screen" would be satisfied by a viewer that
 * simply drew whatever it found on disk and paid no attention to commits at all.
 * So each claim is checked here against a fault aimed squarely at it.
 *
 * **B is committed early.** The publication record is made to say, during the
 * very step that expects B hidden, that B may be seen. The server hands its
 * pixels over and the engine draws them. The claim that B is not on the screen
 * ought to catch this.
 *
 * **The run refuses everything.** The server is made to behave as though nothing
 * had ever been committed, so the whole screen goes black. B is still not drawn,
 * so the first claim still holds — and the claim that A is still there ought to
 * catch it. This is the one that proves the middle step is not passing over an
 * empty screen, which is the failure that would be hardest to spot by reading.
 *
 * Run it deliberately, from the operator page's folder so that the packages are
 * found::
 *
 *     cd workflows/target_acquisition/webapp-ui
 *     node ../../../zmart_live/tests/browser/check-the-test-can-fail.mjs
 *
 * It takes a couple of minutes. A fault that passes is the bad answer here,
 * which reads backwards, so the result is printed in words rather than left as
 * an exit code for somebody to interpret.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_PAGE = path.resolve(
  here, "..", "..", "..", "workflows", "target_acquisition", "webapp-ui",
);

/** Each fault, and the claim in the middle step that ought to catch it. */
const FAULTS = [
  {
    name: "commit-b-early",
    what: "position B is committed during the step that expects it hidden",
    caughtBy: "the claim that B is not on the screen",
  },
  {
    name: "black-screen",
    what: "the run refuses everything, so nothing at all is drawn",
    caughtBy: "the claim that A is still on the screen, and still as bright",
  },
];

function runBrowserTest(sabotage) {
  const environment = { ...process.env };
  delete environment.ZMART_SABOTAGE;
  if (sabotage) environment.ZMART_SABOTAGE = sabotage;
  return spawnSync(
    "npx",
    ["playwright", "test", "--config", path.join(here, "playwright.config.mjs")],
    {
      cwd: OPERATOR_PAGE,
      stdio: "inherit",
      env: environment,
      shell: process.platform === "win32",
    },
  );
}

console.log("\n--- first prove the unmodified browser test is green\n");
const baseline = runBrowserTest(null);
if (baseline.status !== 0) {
  console.error(
    "\nThe unmodified browser test is not green, so a red sabotage run would " +
    "prove nothing. Fix the browser, build, or Playwright environment before " +
    "trusting this fault check.",
  );
  process.exit(2);
}

const missed = [];
for (const fault of FAULTS) {
  console.log(`\n--- with this broken on purpose: ${fault.what}\n`);
  const finished = runBrowserTest(fault.name);
  const caught = finished.status === 1;
  if (finished.status !== 0 && finished.status !== 1) {
    console.error(
      `\nThe test runner stopped with status ${finished.status}; this is not ` +
      "evidence that an assertion caught the fault.",
    );
    process.exit(2);
  }
  console.log(
    caught
      ? `\ncaught: the test went red, as it should have. ${fault.caughtBy} did its job.`
      : `\nMISSED: the test stayed green with ${fault.what}.`,
  );
  if (!caught) missed.push(fault);
}

console.log("");
if (missed.length === 0) {
  console.log(
    "Every fault was caught. Both halves of the middle step are making a real\n" +
    "claim: a screen showing B would fail it, and so would a screen showing\n" +
    "nothing at all.",
  );
  process.exit(0);
}
console.log(
  `${missed.length} of ${FAULTS.length} faults went unnoticed:\n` +
  missed.map((fault) => `  - ${fault.what}\n    should have been caught by ${fault.caughtBy}`)
    .join("\n") + "\n\n" +
  "Whatever those claims are measuring, it is not what they say they are, and\n" +
  "they should not be trusted until they can be made to fail here.",
);
process.exit(1);
