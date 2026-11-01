/**
 * The bridge these walks start runs the interface the environment holds, not
 * the folder the walk happens to be started in.
 *
 * Python puts the folder it is started in at the front of its search path.
 * The walks start the bridge from the root of this repository, where a folder
 * called `zmart_interface` sits, so without care the walk tests that folder
 * instead of the package an operator installs -- and stays green while the
 * shipped package is broken. A developer with an editable install still gets
 * their working copy, because the installation itself points there.
 *
 * No page is opened: this asks only where Python finds the interface.
 */

import { execFileSync } from "node:child_process";
import os from "node:os";
import { expect, test } from "@playwright/test";
import { bridgePython, pythonForTheBridge } from "../../testing/python.ts";

const WHERE_FROM = [
  "import json, os, sys, zmart_interface",
  "here = os.path.abspath(os.getcwd())",
  "print(json.dumps({'file': os.path.abspath(zmart_interface.__file__),",
  "  'start_folder_searched': any(os.path.abspath(p or '.') == here for p in sys.path)}))",
].join("\n");

const ask = (command: string, args: string[], cwd: string, env?: NodeJS.ProcessEnv) =>
  JSON.parse(execFileSync(command, args, { cwd, env, encoding: "utf8" }).trim().split("\n").pop()!);

test("the bridge's Python imports the interface from where the environment says", () => {
  const { command, args, cwd, env } = bridgePython("-c", WHERE_FROM);
  const asTheWalkStartsIt = ask(command, args, cwd, env);
  /* Started in an empty folder, nothing can stand in front of the installed
     package: this is where the environment says the interface is. */
  const installed = ask(pythonForTheBridge(), ["-c", WHERE_FROM], os.tmpdir());

  expect(asTheWalkStartsIt.start_folder_searched, "the folder it starts in is not searched").toBe(false);
  expect(asTheWalkStartsIt.file).toBe(installed.file);
});
