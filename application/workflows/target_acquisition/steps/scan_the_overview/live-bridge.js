/**
 * Driving a real bridge for the browser tests: a scan taken by the mock
 * microscope, through the controller, with its pictures served as they land.
 *
 * The other live helper next door (`live-run.js`) points the page at a run
 * written by the project's own writer. This one points it at the bridge the
 * operator page actually talks to: `application/framework/bridge.py`, running
 * the mock driver through `zmart_controller`, writing OME-TIFFs into a folder
 * of its own and one small JPEG per field beside them.
 *
 * Nothing is stood in for. If the pictures do not reach the screen, one of the
 * three joins between a captured plane and a drawn tile is broken, and that is
 * the whole question these tests exist to ask.
 */

import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..", "..", "..", "..");
const BRIDGE = path.join(REPO, "application", "framework", "bridge.py");

export const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/**
 * Bring the picture's display settings on screen, the way an operator does:
 * they stand in the column beside the canvas, a tab away from the step's
 * channel, and until that tab is pressed the panel's eyes and windows are
 * not there to be pressed. Waits for the tab, since the settings arrive with
 * the picture; a page that never offers one (a JPEG copy) is left alone.
 */
export async function showTheChannel(page) {
  const tab = page.locator(".side-tab button.tab").first();
  if (await tab.count() && (await tab.getAttribute("aria-selected")) !== "true") await tab.click();
  await expect(page.locator("#canvas-side")).toBeVisible();
}

export async function showDisplaySettings(page) {
  const tab = page.locator(".side-tab button.tab", { hasText: "Display settings" });
  await expect(tab, "the display settings are offered as a tab").toHaveCount(1, { timeout: 30_000 });
  if ((await tab.getAttribute("aria-selected")) !== "true") await tab.click();
  await expect(page.locator("#display-side .viewer-panel")).toBeVisible();
}

/**
 * The Python the operator's window runs the bridge with.
 *
 * Not "whatever python is on PATH". These tests were green for a day while
 * the shipped window could not focus at all, because the harness launched the
 * bridge from a test environment that happened to have a package the
 * operator's did not. A test of the real thing runs it where it really runs.
 * `PYTHON=` overrides, for a machine that keeps it elsewhere.
 */
const THE_OPERATORS_PYTHON =
  "C:/ProgramData/MinicondaZMB/envs/zmart-microscopy/python.exe";

export const pythonForTheBridge = () =>
  process.env.PYTHON ?? (existsSync(THE_OPERATORS_PYTHON) ? THE_OPERATORS_PYTHON : "python");

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
 * Ask the mock instrument window to do what an operator does in the vendor's
 * own software: drive the stage, change the lens, drop a marker. The window
 * cannot open on a test machine, but its `Api` can, and calling it is the
 * same code path its buttons take -- so nothing here writes the rig file
 * behind the driver's back.
 */
export function operateTheInstrument(method, ...args) {
  const program = [
    "import importlib.util, json, sys",
    `spec = importlib.util.spec_from_file_location("mock_instrument_window", ${JSON.stringify(path.join(REPO, "application", "mock-instrument.py"))})`,
    "module = importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    `print(json.dumps(getattr(module.Api(), ${JSON.stringify(method)})(*json.loads(sys.argv[1]))))`,
  ].join("\n");
  const said = execFileSync(pythonForTheBridge(), ["-c", program, JSON.stringify(args)],
    { cwd: REPO, encoding: "utf8" });
  return JSON.parse(said);
}

/** A configuration with the mock's default limits, so a session can stand on
 *  it: what the ZMART driver configuration workflow makes on a real machine. */
export function aConfiguredMock() {
  return execFileSync(pythonForTheBridge(), ["-c",
    "from zmart_drivers.mock import mock_setup; print(mock_setup.configured())"],
    { cwd: REPO, encoding: "utf8" }).trim();
}

export async function startTheBridge({ port, connect = true } = {}) {
  /* A folder of its own, well away from the page's own source: a run written
     inside the project looks to the development server like somebody editing
     the page, which reloads the browser mid-test. */
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-bridge-"));
  const bridge = spawn(
    pythonForTheBridge(),
    [BRIDGE, "--port", String(port), "--output-root", folder],
    { stdio: "inherit", cwd: REPO },
  );

  const at = `http://127.0.0.1:${port}`;
  const ask = async (route, payload) => {
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
      await ask("/api/instruments");
      break;
    } catch {
      if (Date.now() > until) throw new Error("the bridge never started answering");
      await rest(300);
    }
  }

  const { instruments } = await ask("/api/instruments");
  const scope = instruments.find((one) => one.vendor === "mock");
  if (!scope) throw new Error("the bridge has no mock microscope to connect to");
  /* A session always stands on a configuration with limits, so the mock is
     given one first -- the configuration workflow's job on a real machine.
     A walk of that workflow starts from nothing and connects on its own. */
  const opened = connect
    ? await ask("/api/connect", { connection: { ...scope, configuration: aConfiguredMock() } })
    : null;

  return {
    /* Where the pictures of the overview are served — the same address the
       page asks its backend for, spelt out here because a test points the page
       at it rather than walking the operator's Connect. */
    pictures: `${at}/view/overview`,
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
    async image(positions) {
      if ((process.env.LIVE_BRIDGE_SABOTAGE ?? "") === "stalled") return;
      await ask("/api/scan", { positions });
      for (let waited = 0; waited < 300; waited++) {
        const scan = await ask("/api/scan");
        if (!scan.running) {
          if (scan.error) throw new Error(`the scan stopped: ${scan.error}`);
          return scan;
        }
        await rest(100);
      }
      throw new Error("the scan never finished");
    },
    async stop() {
      try { await ask("/api/disconnect", {}); } catch { /* going away anyway */ }
      bridge.kill();
    },
  };
}

/**
 * Walk the page as far as having a plan, and hand back where it means to look.
 *
 * The scan has to be taken where the page is looking, or the pictures land
 * somewhere off the edge of the canvas and the photographs come back blank
 * whether the wiring works or not. So the plan is asked for first and the
 * stage is sent to its own positions -- which is what an operator does anyway.
 */
export async function throughToAPlan(page) {
  const gotoStep = (name) => page.locator(`.step:has-text("${name}")`).first().click();
  const record = async (host, name) => {
    const bar = page.locator(`#${host} .setting-box.open`);
    const field = bar.locator("input");
    if (await field.count()) await field.fill(name);
    await bar.locator("button.run").click();
    await page.waitForTimeout(650);
  };

  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep("Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await page.waitForTimeout(300);
  await gotoStep("Overview scan area");
  await record("sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();
  await page.waitForTimeout(400);

  /* The plan draws on the canvas above the picture — pale ground, field
     outlines, a grid glyph — which would cover every photograph before a
     single field had landed. So it is switched off here, the way a
     microscopist turns one channel off to look at another. */
  await page.addStyleTag({ content: ".stagecv { visibility: hidden !important; }" });
  return page.evaluate(() => window.__theStageCanvas.plan());
}

/** The first *count* places of a plan, as positions to send the stage to. */
export const theFirst = (count, plan, { z = 0 } = {}) =>
  plan.slice(0, count).map((at) => ({ x: at.x, y: at.y, z }));
