/**
 * How the framework finds the workflows, and what it makes of a folder's name.
 *
 * Every folder in `workflows/` that contains a `flow.js` is a workflow the
 * chooser offers. The folder's name is the workflow's name: underscores read
 * as spaces and the first letter capitalised, so `target_acquisition` appears
 * as "Target acquisition". Adding a workflow is adding a folder — nothing in
 * the framework is edited, which is the whole arrangement being aimed at: the
 * frame is an engine, and the workflows plug into it.
 *
 * The finding itself — reading the folder listing — happens where the code
 * runs. The page uses the build tool's folder scan (`import.meta.glob`, in
 * `window/main.js`); the tests read the same folders their own way. Both hand what
 * they found to `assembleWorkflows` below, so the page and the tests cannot
 * disagree about what a folder full of workflows means.
 */

import { numbered } from "./steps.js";

/** The name the chooser shows for a workflow folder: underscores become
 * spaces, and the first letter is capitalised. */
export function workflowName(folder) {
  const words = folder.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The folder a flow was found in, out of the path it was found under. */
const folderOf = (path) => path.match(/([^/]+)\/flow\.js$/)?.[1];

/**
 * Turn a set of found `flow.js` files into the workflows the page offers.
 *
 * Takes an object mapping each flow's path to its loaded module — the shape
 * `import.meta.glob(..., { eager: true })` produces — and returns the chooser's
 * list plus which workflow a fresh page opens on. The workflow that declares
 * `opensFirst` is listed first and opened first; the rest follow in alphabetical
 * order of their folder names.
 */
export function assembleWorkflows(flowFiles) {
  const found = Object.entries(flowFiles)
    .map(([path, flow]) => ({ folder: folderOf(path), flow }))
    .filter(({ folder }) => folder)
    .sort((a, b) =>
      (b.flow.opensFirst ? 1 : 0) - (a.flow.opensFirst ? 1 : 0)
      || a.folder.localeCompare(b.folder));

  const WORKFLOWS = {};
  for (const { folder, flow } of found) {
    WORKFLOWS[folder] = {
      name: workflowName(folder),
      blurb: flow.blurb,
      steps: numbered(flow.steps),
      /* What the workflow offers to put on the right-hand side. A workflow
         that declares none runs on its steps' own panels alone. */
      panels: flow.panels ?? [],
    };
  }

  const first = found.find(({ flow }) => flow.opensFirst) ?? found[0];
  return { WORKFLOWS, DEFAULT_WORKFLOW: first?.folder };
}
