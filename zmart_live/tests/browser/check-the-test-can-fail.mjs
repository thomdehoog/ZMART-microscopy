/**
 * Breaking the rule on purpose, to see whether the browser test notices.
 *
 * A passing test tells you nothing until you have watched it fail for the right
 * reason, and the test beside this one is unusually easy to fool. Its middle
 * step says "position B is not on the screen" — a claim that is perfectly true
 * of a completely black screen, of a page that never opened, of an engine that
 * never started. Left to itself that step could go green every morning while
 * measuring nothing at all.
 *
 * So this runs the same test with one thing changed: position B is committed
 * during the very step that expects it to be invisible. The publication record
 * now says B may be seen, the server hands its pixels over, and the engine draws
 * them. If the test is doing its job it goes red at exactly that step and says
 * so. If it stays green, the middle step is decoration and should be believed by
 * nobody.
 *
 * Run it deliberately, from the operator page's folder so that the packages are
 * found::
 *
 *     cd workflows/target_acquisition/webapp-ui
 *     node ../../../zmart_live/tests/browser/check-the-test-can-fail.mjs
 *
 * It takes about a minute. Green here means the test is broken; red means it
 * works — which reads backwards, so this prints the answer in words rather than
 * leaving anybody to interpret an exit code.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_PAGE = path.resolve(
  here, "..", "..", "..", "workflows", "target_acquisition", "webapp-ui",
);

/** What is broken, and which claim in the test ought to catch it. */
const THE_FAULT = "commit-b-early";
const WHAT_SHOULD_CATCH_IT =
  "the middle step, where B's pixels are on disk but nobody has published them";

const finished = spawnSync(
  "npx",
  ["playwright", "test", "--config", path.join(here, "playwright.config.mjs")],
  {
    cwd: OPERATOR_PAGE,
    stdio: "inherit",
    env: { ...process.env, ZMART_SABOTAGE: THE_FAULT },
    shell: process.platform === "win32",
  },
);

console.log("");
if (finished.status === 0) {
  console.log(
    `The test PASSED with the rule deliberately broken. That is the bad answer.\n` +
    `B was committed during ${WHAT_SHOULD_CATCH_IT}, so B really was on the\n` +
    `screen, and the test said nothing. Whatever that step is measuring, it is\n` +
    `not whether a commit decides what is drawn, and it should not be trusted\n` +
    `until it can be made to fail here.`,
  );
  process.exit(1);
}
console.log(
  `The test FAILED with the rule deliberately broken, which is the good answer.\n` +
  `B was committed during ${WHAT_SHOULD_CATCH_IT}; B appeared on the screen, and\n` +
  `the test noticed. The claim it makes about commits is a real one.`,
);
