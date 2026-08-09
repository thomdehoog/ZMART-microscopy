/**
 * Breaking the rule on purpose, to see whether the browser tests notice.
 *
 * A passing test tells you nothing until you have watched it fail for the right
 * reason, and the tests in this folder are unusually easy to fool. Each one has a
 * middle step that makes two claims at once — the thing being written is not on
 * the screen, and everything already published still is — and each of those claims
 * can go quietly wrong in a different way.
 *
 * "It is not on the screen" is perfectly true of a completely black screen: of a
 * page that never opened, an engine that never started, a run that was never
 * served. And "the rest is still on the screen" would be satisfied by a viewer
 * that drew whatever it found on disk and paid no attention to commits at all. So
 * every claim is checked here against a fault aimed squarely at it.
 *
 * There are two kinds of fault, and each is used against every test.
 *
 * **Something is committed early.** During the very step that expects it hidden,
 * it is published — by the real publisher, which goes and inspects what is on disk
 * and moves the run's record only because what it finds justifies it. Not one byte
 * of image changes; the commit is the whole difference. The server then hands the
 * pixels over and the engine draws them. The claim that they are not on the screen
 * ought to catch this, and if it does, it has shown something worth knowing:
 * whether they appear is decided by the commit alone.
 *
 * **The run refuses everything.** The server is made to behave as though nothing
 * had ever been published, so the whole screen goes black. The thing under test is
 * still not drawn, so the first claim still holds — and the claim that everything
 * else is still there ought to catch it. This is the one that proves a middle step
 * is not quietly passing over an empty screen, which is the failure that would be
 * hardest to spot by reading.
 *
 * Each fault is run against the one test it is aimed at, rather than against the
 * whole folder, because a fault that makes one test go red tells you nothing about
 * the two it never touched — and running all of them each time would take three
 * times as long for no more evidence.
 *
 * Run it deliberately, from the operator page's folder so that the packages are
 * found::
 *
 *     cd workflows/target_acquisition/webapp-ui
 *     node ../../../zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs
 *
 * It takes several minutes: one honest run of the whole folder to show the tests
 * are green to begin with, and then one run per fault. A fault that passes is the
 * bad answer here, which reads backwards, so the result is printed in words rather
 * than left as an exit code for somebody to interpret.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_PAGE = path.resolve(
  here, "..", "..", "..", "..", "workflows", "target_acquisition", "webapp-ui",
);

/**
 * Each fault: which test it is aimed at, what it breaks, and the claim in that
 * test's middle step that ought to catch it.
 *
 * `test` is enough of the test's own title to pick it out and no more, so that a
 * reworded title does not silently start running nothing. A run that matches no
 * test at all is treated as a failure of this check rather than as a fault nobody
 * caught, because the two look identical from the outside and mean opposite
 * things.
 */
const FAULTS = [
  {
    name: "commit-b-early",
    test: "published by the real writer",
    what: "position B is published during the step that expects it hidden",
    caughtBy: "the claim that B is not on the screen",
  },
  {
    name: "black-screen",
    test: "published by the real writer",
    what: "the server refuses everything, so nothing at all is drawn",
    caughtBy: "the claim that A is still on the screen, and still as bright",
  },
  {
    name: "commit-c-early",
    test: "sharing a slider stop",
    what: "the third tile of the row is published during the step that expects "
      + "it hidden, while it sits at the same stop on the tile slider as the "
      + "first tile, which is published",
    caughtBy: "the claim that the third tile is not on the screen",
  },
  {
    name: "black-screen-with-three-tiles",
    test: "sharing a slider stop",
    what: "the server refuses everything, so nothing at all is drawn",
    caughtBy: "the claim that the first tile is still on the screen, and still "
      + "as bright",
  },
  {
    name: "commit-the-later-moment-early",
    test: "later moment",
    what: "the second moment of an already published position is committed "
      + "during the step that expects it hidden",
    caughtBy: "the claim that that moment is not on the screen",
  },
  {
    name: "black-screen-at-a-later-moment",
    test: "later moment",
    what: "the server refuses everything, so nothing at all is drawn",
    caughtBy: "the claim that the neighbour's second moment is still on the "
      + "screen, and still as bright",
  },
];

function runBrowserTest(sabotage, only) {
  const environment = { ...process.env };
  delete environment.ZMART_SABOTAGE;
  if (sabotage) environment.ZMART_SABOTAGE = sabotage;
  return spawnSync(
    "npx",
    [
      "playwright", "test",
      "--config", path.join(here, "playwright.config.mjs"),
      ...(only ? ["--grep", only] : []),
    ],
    {
      cwd: OPERATOR_PAGE,
      stdio: "inherit",
      env: environment,
      shell: process.platform === "win32",
    },
  );
}

/**
 * The titles of every test in this folder, asked of the runner rather than
 * remembered here.
 *
 * This exists because of a trap. The runner reports "no test matched" the same
 * way it reports "a test failed": both come back as a plain failure. So a fault
 * aimed at a test whose title has since been reworded would quietly be recorded
 * below as *caught*, when in truth nothing ran at all — which is the most
 * comfortable and most misleading answer this file could give. Checking the
 * titles up front turns that into an error somebody can act on.
 */
function everyTestTitle() {
  const listed = spawnSync(
    "npx",
    [
      "playwright", "test",
      "--config", path.join(here, "playwright.config.mjs"),
      "--list", "--reporter", "list",
    ],
    {
      cwd: OPERATOR_PAGE,
      encoding: "utf8",
      env: (({ ZMART_SABOTAGE, ...rest }) => rest)(process.env),
      shell: process.platform === "win32",
    },
  );
  return (listed.stdout ?? "")
    .split("\n")
    .filter((line) => /\.spec\.mjs:\d+:\d+/.test(line))
    .map((line) => line.trim());
}

const titles = everyTestTitle();
if (titles.length === 0) {
  console.error(
    "\nThe runner listed no tests at all, so nothing below would mean anything. " +
    "Check that the Playwright settings file still points at this folder.",
  );
  process.exit(2);
}
const aimedAtNothing = FAULTS.filter(
  (fault) => !titles.some((title) => title.includes(fault.test)),
);
if (aimedAtNothing.length > 0) {
  console.error(
    "\nThese faults name a test that no longer exists, so running them would " +
    "prove nothing while looking exactly like success:\n" +
    aimedAtNothing.map((fault) => `  - ${fault.name} looks for "${fault.test}"`)
      .join("\n") +
    "\n\nThe tests the runner found are:\n" +
    titles.map((title) => `  ${title}`).join("\n"),
  );
  process.exit(2);
}

console.log("\n--- first prove the unmodified browser tests are green\n");
const baseline = runBrowserTest(null, null);
if (baseline.status !== 0) {
  console.error(
    "\nThe unmodified browser tests are not green, so a red sabotage run would " +
    "prove nothing. Fix the browser, the build or the Playwright environment " +
    "before trusting this fault check.",
  );
  process.exit(2);
}

const missed = [];
for (const fault of FAULTS) {
  console.log(`\n--- with this broken on purpose: ${fault.what}\n`);
  const finished = runBrowserTest(fault.name, fault.test);
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
    "Every fault was caught. Both halves of every middle step are making a real\n" +
    "claim: a screen showing the unpublished thing would fail it, and so would a\n" +
    "screen showing nothing at all.",
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
