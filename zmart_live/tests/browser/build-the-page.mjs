/**
 * Get the little viewer page ready to be opened.
 *
 * Three things have to be true before the browser test can start, and all three
 * are done here so that running the test is one command rather than a list of
 * things to remember.
 *
 * **The packages have to be findable.** This folder installs nothing of its own —
 * it is a folder of Python tests with one page in it — so a link is made from
 * here to the packages the operator page already has. Node looks for packages by
 * walking up the folders from whichever file asked, and without the link that
 * walk finds nothing at all from here.
 *
 * **Neuroglancer's two background programs have to be compiled.** The package
 * ships each of them as a short list of imports rather than as a finished
 * program, and a browser cannot read the shorthand that list is written in.
 * `webapp-ui/neuroglancer-workers.mjs` explains this at length; what matters
 * here is that skipping it produces a page that loads perfectly, reports no
 * error, and never draws anything.
 *
 * **The page has to be built.** Neuroglancer is a few thousand source files and
 * has to be gathered into one page first. See `page/vite.config.mjs`.
 *
 * Run it directly with `node build-the-page.mjs`; the browser test runs it for
 * you before the first test starts.
 */

import { spawnSync } from "node:child_process";
import { existsSync, symlinkSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OPERATOR_PAGE = path.resolve(
  here, "..", "..", "..", "workflows", "target_acquisition", "webapp-ui",
);

/** Where the finished page lands, and what proves it is finished. */
export const THE_BUILT_PAGE = path.join(here, "page", "built", "index.html");

/** Run one command in the operator page's folder and stop the moment it fails. */
function run(command, args) {
  const finished = spawnSync(command, args, {
    cwd: OPERATOR_PAGE,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (finished.status !== 0) {
    throw new Error(
      `\`${command} ${args.join(" ")}\` stopped with ${finished.status}. The test ` +
      "page could not be built, so there is nothing for the browser to open.",
    );
  }
}

/** Do all three steps. Safe to run again; each step is happy to find its work done. */
export function buildThePage() {
  const packages = path.join(here, "node_modules");
  if (!existsSync(packages)) {
    symlinkSync(path.join(OPERATOR_PAGE, "node_modules"), packages, "dir");
  }
  run("node", ["neuroglancer-workers.mjs"]);
  run("npx", ["vite", "build", "--config", path.join(here, "page", "vite.config.mjs")]);
  if (!existsSync(THE_BUILT_PAGE)) {
    throw new Error(`The build reported success but left no page at ${THE_BUILT_PAGE}.`);
  }
  return THE_BUILT_PAGE;
}

if (import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  console.log(`the test page is ready at ${buildThePage()}`);
}
