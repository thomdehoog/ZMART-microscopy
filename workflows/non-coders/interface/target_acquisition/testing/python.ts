/**
 * Starting the interface's Python from a browser test.
 *
 * The browser tests that need a bridge, or a small server of their own, start
 * it in the Python the interface is installed in.
 */

import path from "node:path";
import { fileURLToPath } from "node:url";

/* The folder of workflows this workflow sits in: `examples/` in the
   interface's repository, or a folder of your own, such as ZMART Microscopy's
   `workflows/non-coders/interface/`. */
const WORKFLOWS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * The Python the bridge runs in: the one the interface is installed in.
 *
 * `PYTHON=` names it; otherwise it is whichever `python` is on the path. It
 * has to be the operator's own environment, with this package and its
 * dependencies installed: these tests were once green for a day while the
 * shipped window could not focus at all, because the harness ran the bridge
 * from an environment that had a package the operator's did not.
 */
export const pythonForTheBridge = () => process.env.PYTHON ?? "python";

/**
 * How the walks start that Python: the command, its arguments, the folder and
 * the environment.
 *
 * `-P` keeps the folder Python starts in off its search path, so nothing in it
 * can stand in front of the installed package, and the walk tests what an
 * operator installs. A developer with an editable install still gets their
 * working copy, since the installation itself points Python there.
 *
 * The workflow itself is not installed: it is imported by its own folder's
 * name (`target_acquisition`), from its folder of workflows, the way the
 * bridge imports it. So that folder goes on the search path of every Python
 * the walks start, through `PYTHONPATH`, and the bridge is told which folder
 * of workflows to run (`ZMART_INTERFACE_WORKFLOWS`).
 */
export const bridgePython = (...args: string[]) => ({
  command: pythonForTheBridge(), args: ["-P", ...args], cwd: WORKFLOWS, env: forThisWorkflow(),
});

/** This process's environment, with the folder of workflows on Python's search path and named to the bridge. */
function forThisWorkflow(): NodeJS.ProcessEnv {
  const searched = [WORKFLOWS, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  return { ...process.env, PYTHONPATH: searched, ZMART_INTERFACE_WORKFLOWS: WORKFLOWS };
}
