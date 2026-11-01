/**
 * Driving a real bridge for the browser tests: a scan taken by the mock
 * microscope, through the controller, with its pictures served as they land.
 *
 * This points the page at the bridge it actually talks to:
 * the package `zmart_interface/framework/bridge/`, running the mock microscope through
 * the ZMART Controller, writing OME-TIFFs into a folder of its own, an
 * OME-Zarr position per field, and one small JPEG per field beside them.
 *
 * Nothing is stood in for. If the pictures do not reach the screen, one of the
 * three joins between a captured plane and a drawn tile is broken, and that is
 * the whole question these tests exist to ask.
 */

import { execFileSync, spawn } from "node:child_process";
import { expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { isTheMock } from "../microscope/instruments.ts";
import { bridgePython } from "./python.ts";
import type { Page } from "@playwright/test";

export const rest = (ms: number) => new Promise((done) => setTimeout(done, ms));

/** The step's channel beside the canvas, on screen. */
export async function showTheChannel(page: Page) {
  await expect(page.locator("#canvas-side")).toBeVisible();
}

/**
 * Show or hide an acquisition the way an operator does: the list of
 * acquisitions opens from the name in the row over the picture, and each
 * line carries the acquisition's eye. Waits for the strip, since it arrives
 * with the picture.
 */
export async function setAcquisitionShown(page: Page, name: string, shown: boolean) {
  const eye = page.locator(`#acquisition-menu button[aria-label="show or hide ${name}"]`);
  await expect(page.locator("#acquisition-name"), "the acquisitions strip is there").toBeVisible({ timeout: 30_000 });
  await page.locator("#acquisition-name").click();
  await expect(page.locator("#acquisition-menu")).toBeVisible();
  await expect(eye, `the ${name} acquisition has an eye`).toHaveCount(1);
  if ((await eye.getAttribute("aria-pressed")) !== String(shown)) await eye.click();
  await expect(eye).toHaveAttribute("aria-pressed", String(shown));
  await page.keyboard.press("Escape");
  await expect(page.locator("#acquisition-menu")).toBeHidden();
}

/**
 * Start a bridge on *port*, connected to the mock microscope.
 *
 * The scan is not started: `image(positions)` drives it one call at a time, so
 * a test can photograph the canvas before a field has landed and again after
 * each one — which is the only way to ask whether tiles appear *as they
 * arrive* rather than all at once at the end.
 *
 * @returns where its pictures are served, how to image more, and how to stop.
 */
/**
 * Ask the mock instrument's window to do what an operator does in the
 * vendor's own software: choose a job. The window cannot open on a test
 * machine, but its `Api` can, and calling it is the same code path its
 * buttons take -- so nothing here writes the instrument's settings behind the
 * driver's back.
 */
export function operateTheInstrument(method: string, ...args: unknown[]) {
  const program = [
    "import json, sys",
    "from target_acquisition.mock_microscope.window import Api",
    `print(json.dumps(getattr(Api(), ${JSON.stringify(method)})(*json.loads(sys.argv[1]))))`,
  ].join("\n");
  const python = bridgePython("-c", program, JSON.stringify(args));
  const said = execFileSync(python.command, python.args, { cwd: python.cwd, env: python.env, encoding: "utf8" });
  return JSON.parse(said);
}

export async function startTheBridge({ port, connect = true }: { port: number; connect?: boolean }) {
  /* A folder of its own, well away from the page's own source: a run written
     inside the project looks to the development server like somebody editing
     the page, which reloads the browser mid-test. */
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-bridge-"));
  const python = bridgePython(
    "-m", "zmart_interface.framework.bridge", "--port", String(port), "--output-root", folder,
  );
  const bridge = spawn(python.command, python.args, { stdio: "inherit", cwd: python.cwd, env: python.env });

  const at = `http://127.0.0.1:${port}`;
  const ask = async (route: string, payload?: unknown) => {
    const answer = await fetch(at + route, payload === undefined ? undefined : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!answer.ok) throw new Error(`${route} answered ${answer.status}`);
    return answer.json();
  };

  const until = Date.now() + 30_000;
  for (;;) {
    try {
      await ask("/api/target_acquisition/instruments");
      break;
    } catch {
      if (Date.now() > until) throw new Error("the bridge never started answering");
      await rest(300);
    }
  }

  const { instruments } = await ask("/api/target_acquisition/instruments");
  const scope = instruments.map((one: { name: string }) => one.name).find(isTheMock);
  if (!scope) throw new Error("the bridge has no mock microscope to connect to");
  const opened = connect ? await ask("/api/target_acquisition/connect", { instrument: scope, experiment: "target-acquisition" }) : null;

  return {
    /* Where the pictures of the overview are served — the same address the
       page asks its backend for, spelt out here because a test points the page
       at it rather than walking the operator's Connect. */
    pictures: `${at}/api/target_acquisition/view/overview`,
    /* Where the bridge serves the built page, for a walk of the page itself. */
    at,
    /* Where this session's run landed. The bridge makes it at connect and
       says so, because a run has to be told from the one before it. */
    run: opened?.run,
    /* Where the newest run landed. Every connect makes a fresh run, so a test
       that walks the page's own Connect opens a second one -- and what it
       captures lands there, not in the run this harness's connect made. */
    currentRun: () => {
      const runs = fs.readdirSync(folder)
        .filter((name) => name.startsWith("target-acquisition_"))
        .map((name) => path.join(folder, name))
        .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
      return runs[0] ?? opened?.run;
    },
    folder,
    async image(positions: { x: number; y: number; z?: number }[]) {
      if ((process.env.LIVE_BRIDGE_SABOTAGE ?? "") === "stalled") return;
      await ask("/api/target_acquisition/scan", { positions });
      for (let waited = 0; waited < 300; waited++) {
        const scan = await ask("/api/target_acquisition/scan");
        if (!scan.running) {
          if (scan.error) throw new Error(`the scan stopped: ${scan.error}`);
          return scan;
        }
        await rest(100);
      }
      throw new Error("the scan never finished");
    },
    async stop() {
      try { await ask("/api/target_acquisition/disconnect", {}); } catch { /* going away anyway */ }
      bridge.kill();
    },
  };
}
