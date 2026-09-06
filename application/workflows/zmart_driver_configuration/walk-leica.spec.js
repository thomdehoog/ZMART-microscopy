/**
 * The ZMART driver configuration workflow, walked against the actual Leica
 * driver, with only the CAM socket and the camera stood in for.
 *
 * The page is the built page, served by the real bridge, and the bridge
 * drives the real Leica setup driver: its adapter, gate, limits, orientation,
 * calibration and acquisition code, and its own ProgramData layout (rooted
 * in a folder of its own for the walk). Two things are stood in for, because
 * a developer machine has neither: the CAM socket, played by the driver's
 * MockLasxClient, and the camera's pixels, which LAS X native AutoSave would
 * write to disk -- a picture of a real micrograph is written there instead.
 * The stand-ins are the ones the driver's own configuration-walk test uses,
 * mounted by tests/helpers/page_bridge_standin.py in the driver's tree.
 *
 * What an operator would do at LAS X -- drive the stage to a corner, focus,
 * select the other lens's job -- goes through that launcher's side door.
 * Set `OPERATOR_EVIDENCE_DIR` to keep a screenshot of every screen. The
 * mock's own walk (walk.spec.js) is the one with nothing stood in for.
 */
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { operateTheInstrument, rest, startTheBridge }
  from "../target_acquisition/steps/scan_the_overview/live-bridge.js";

const PORT = Number(process.env.CONFIGURATION_BRIDGE_PORT ?? 8873);
const SIDE = Number(process.env.LEICA_SIDE_PORT ?? 8874);
process.env.LEICA_SIDE_PORT = String(SIDE);

/* The bridge is started through the driver's stand-in launcher instead of
   bridge.py: a small shell wrapper, written here, stands in for the python
   the bridge is started with and swaps the script. Everything else python is
   asked for runs as it is. A developer machine with a POSIX shell, then. */
const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..", "..");
const LAUNCHER = path.join(REPO, "zmart_drivers", "leica", "stellaris5_y42h93", "navigator_expert",
  "tests", "helpers", "page_bridge_standin.py");
const python = process.env.PYTHON ?? "python3";
const wrapper = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "zmart-leica-python-")), "python");
fs.writeFileSync(wrapper, [
  "#!/bin/sh",
  "case \"$1\" in",
  `  */bridge.py) shift; exec ${JSON.stringify(python)} ${JSON.stringify(LAUNCHER)} "$@" ;;`,
  `  *) exec ${JSON.stringify(python)} "$@" ;;`,
  "esac",
  "",
].join("\n"), { mode: 0o755 });
process.env.PYTHON = wrapper;
const A_WHOLE_WALK = 600_000;

/* The mock keeps its machine in a folder named by the environment. A folder
   of its own, made before the bridge starts, so the walk begins from a
   machine nobody has set up and leaves nothing behind in anyone's home. */
const machine = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-configuration-"));
process.env.ZMART_MOCK_MACHINE = path.join(machine, "machine");
process.env.ZMART_MOCK_STATE = path.join(machine, "instrument.json");
/* The Leica's ProgramData, rooted in a folder of its own for this walk. */
const leicaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-leica-root-"));
process.env.ZMART_MICROSCOPY_ROOT = leicaRoot;

let shots = 0;
async function shot(page, name) {
  const folder = process.env.OPERATOR_EVIDENCE_DIR;
  if (!folder) return;
  fs.mkdirSync(folder, { recursive: true });
  shots += 1;
  await page.screenshot({ path: path.join(folder, `${String(shots).padStart(2, "0")}-${name}.png`) });
}

const walkTo = async (page, title) => {
  await page.locator("#steps .step", { has: page.locator(".step-name", { hasText: title }) }).first().click();
  await rest(500);
};

/** Press a button and wait for it to come back from its "…ing" wording. A
 * button that is gone or renamed afterwards -- Start becomes Rerun -- has
 * come back too, so a short look is all that is asked of it each time. */
async function press(page, label, settle = 1500) {
  const button = page.getByRole("button", { name: label, exact: typeof label === "string" }).first();
  await button.click();
  await expect.poll(async () => {
    const text = await button.textContent({ timeout: 300 }).catch(() => "");
    return (text ?? "").endsWith("…");
  }, { timeout: 60_000 }).toBe(false);
  await rest(settle);
}

/* The operator at LAS X, played through the stand-in's side door: the stage
   is driven and focused, and the job for the other lens is selected. */
const side = async (route) => {
  const answer = await fetch(`http://127.0.0.1:${SIDE}${route}`);
  if (!answer.ok) throw new Error(`${route} answered ${answer.status}: ${await answer.text()}`);
  return answer.json();
};
const inTheInstrument = {
  drive: (x, y) => side(`/drive?x=${x}&y=${y}`),
  dropMarker: async () => {},
  changeLens: () => side("/job?name=HiRes"),
};
const chooseTheLeica = async (page) => {
  const scope = page.locator(".panel.on .session-form select").nth(0);
  const value = await scope.evaluate((sel) => [...sel.options].find((o) => /leica|stellaris/i.test(o.textContent))?.value);
  if (value === undefined) throw new Error("the Leica is not offered on the card");
  await scope.selectOption(value);
};

test.describe("the driver configuration workflow, walked against the Leica driver with the CAM and camera stood in", () => {
  test.setTimeout(A_WHOLE_WALK);

  test("every step publishes into one configuration the driver then stands on", async ({ page }) => {
    const bridge = await startTheBridge({ port: PORT, connect: false });
    const errors = [];
    page.on("pageerror", (why) => errors.push(why.message));
    try {
      await page.goto(`${bridge.at}/`);
      await rest(2500);
      /* A machine nobody has set up yet opens on the configuration workflow:
         there is no configuration a session could stand on. */
      await expect(page.locator("#wf-select")).toHaveValue("zmart_driver_configuration");
      await shot(page, "opened-on-a-bare-machine");

      /* Step 1: the card, with New configuration chosen in its fourth field. */
      await chooseTheLeica(page);
      await rest(600);
      await page.locator('.panel.on .session-form input[type="password"]').fill("x");
      await rest(600);
      await page.locator(".panel.on .session-form select").nth(2).selectOption("new");
      await rest(300);
      await shot(page, "connect-card");
      await page.locator(".panel.on .session-buttons button.run").click();
      await expect(page.locator('#steps .step:has-text("Define limits")')).toBeEnabled({ timeout: 30_000 });
      await rest(1500);
      await shot(page, "connected");

      /* Step 2: the operator drives to each corner in the instrument's own
         software and drops a marker there; the page imports each reading. */
      await walkTo(page, "Define limits");
      await shot(page, "limits-before");
      const corners = [[5000, 6000], [110000, 6000], [5000, 70000], [110000, 70000]];
      const imports = page.getByRole("button", { name: /^(Import|Update)$/ });
      for (const [i, [x, y]] of corners.entries()) {
        await inTheInstrument.drive(x, y);
        await imports.nth(i).click();
        await rest(900);
      }
      await shot(page, "limits-read");
      await page.getByRole("button", { name: "Save and adopt", exact: true }).last().click();
      await rest(2500);
      await shot(page, "limits-published");

      /* Step 3: back to a field with structure, in focus, and read the drives. */
      await inTheInstrument.drive(60000, 40000);
      await walkTo(page, "Define coordinate system origin");
      await shot(page, "origin-before");
      await press(page, "Read");
      await shot(page, "origin-read");
      await press(page, "Save and adopt");
      await shot(page, "origin-published");

      /* Step 4: three pictures and a known move, all through the driver. */
      await walkTo(page, "Image-to-stage calibration");
      await shot(page, "orientation-before");
      await press(page, "Start", 2500);
      await shot(page, "orientation-measured");
      await press(page, "Save and adopt");
      await shot(page, "orientation-published");

      /* Step 5: the reference lens, then the operator changes the lens in
         the instrument's software, then the target. */
      await walkTo(page, "Objective calibration");
      await shot(page, "optics-before");
      /* The reference is the lens the reference view is taken under: the
         selected job's, the 10x. */
      const referenceSelect = page.getByLabel("reference objective");
      const tenX = await referenceSelect.evaluate((sel) => [...sel.options].find((o) => /10x/.test(o.textContent))?.value);
      await referenceSelect.selectOption(tenX);
      await rest(600);
      await shot(page, "optics-presets");
      await page.locator(".setup-set", { hasText: "40x" }).first().click();
      await rest(600);
      await press(page, /^Measure reference/, 2500);
      await shot(page, "optics-reference");
      await inTheInstrument.changeLens(2);
      await press(page, /^Measure target/, 2500);
      await shot(page, "optics-target");
      await press(page, "Measure X/Y", 2500);
      await shot(page, "optics-measured");
      await page.locator(".setup-notebook").evaluate((el) => {
        const head = [...el.querySelectorAll(".setup-part")]
          .find((h) => h.querySelector(".setup-part-title").textContent.includes("X/Y"));
        el.scrollTop = head.offsetTop - 24;
      });
      await rest(600);
      await shot(page, "optics-xy-result");
      await press(page, "Save and adopt");
      await page.locator(".setup-notebook").evaluate((el) => {
        const head = [...el.querySelectorAll(".setup-part")]
          .find((h) => h.querySelector(".setup-part-title").textContent.includes("Confirmation"));
        el.scrollTop = head.offsetTop - 24;
      });
      await rest(400);
      await shot(page, "optics-published");

      await walkTo(page, "Connect");
      await shot(page, "all-done-rail");

      /* What the walk left on disk: one configuration the driver stands on,
         each subsystem with its document and its evidence beside it. */
      const root = path.join(leicaRoot, "leica", "stellaris5_y42h93", "navigator_expert");
      const configurations = fs.readdirSync(root).filter((n) => n.startsWith("configuration_")).sort();
      expect(configurations.length, "the walk's own configuration, beside the seeded one").toBeGreaterThanOrEqual(1);
      const made = path.join(root, configurations[configurations.length - 1]);
      const newest = (subsystem) => {
        const tree = path.join(made, subsystem);
        const snaps = fs.readdirSync(tree).sort();
        return path.join(tree, snaps[snaps.length - 1]);
      };
      const limits = JSON.parse(fs.readFileSync(path.join(newest("limits"), "limits.json"), "utf8"));
      expect(limits.x_um.range).toEqual([5000, 110000]);
      expect(limits.y_um.range).toEqual([6000, 70000]);
      const origin = JSON.parse(fs.readFileSync(path.join(newest("origin"), "origin.json"), "utf8"));
      expect(origin.origin.x_um).toBe(60000);
      const orientation = JSON.parse(fs.readFileSync(path.join(newest("orientation"), "orientation.json"), "utf8"));
      expect(orientation.rotation_deg).toBe(90);
      expect(orientation.reflection).toBe(false);
      expect(fs.existsSync(path.join(newest("orientation"), "orientation.png"))).toBe(true);
      const calibration = JSON.parse(fs.readFileSync(path.join(newest("calibration"), "calibration.json"), "utf8"));
      const [dx, dy, dz] = calibration.objectives["2"].translation_um;
      /* The mock's 40x looks (-18, +11, +3.5) µm off its 10x; the 10x's
         pixel is 4 µm, so the answer is expected within that. */
      expect(Math.abs(dx - -18)).toBeLessThanOrEqual(4);
      expect(Math.abs(dy - 11)).toBeLessThanOrEqual(4);
      expect(Math.abs(dz - 3.5)).toBeLessThanOrEqual(0.6);
      expect(fs.readdirSync(newest("calibration")).some((n) => n.endsWith("objective_pair.png"))).toBe(true);

      /* Reopened on the card, the steps show what the configuration holds. */
      await page.locator(".panel.on .session-buttons button.danger").click();
      await rest(1200);
      await page.locator(".panel.on .session-form select").nth(2).selectOption({ index: 1 });
      await rest(300);
      await page.locator(".panel.on .session-buttons button.run").click();
      await expect(page.locator('#steps .step:has-text("Objective calibration")')).toBeEnabled({ timeout: 30_000 });
      await rest(1500);
      await shot(page, "reconnected");
      await walkTo(page, "Define limits");
      await expect(page.locator(".setup-column")).toContainText("From the published limits");
      await shot(page, "limits-reopened");
      await walkTo(page, "Image-to-stage calibration");
      await expect(page.locator(".setup-column")).toContainText("In the configuration: 90°");
      await shot(page, "orientation-reopened");
      await walkTo(page, "Objective calibration");
      await page.locator(".setup-set", { hasText: "40x" }).first().click();
      await rest(600);
      await expect(page.locator(".setup-column")).toContainText("held");
      await shot(page, "optics-reopened");

      /* And target acquisition connects on the same configuration: the
         card offers it, the controller accepts it, the canvas comes. */
      await page.selectOption("#wf-select", { label: "Target acquisition" });
      await rest(800);
      await shot(page, "target-acquisition-again");
      await chooseTheLeica(page);
      await rest(400);
      await page.locator('.panel.on .session-form input[type="password"]').fill("x");
      await rest(400);
      const offered = page.locator(".panel.on .session-form select").nth(2);
      await expect(offered).toBeEnabled();
      await page.locator(".panel.on .session-buttons button.run").click();
      await expect(page.locator('#steps .step:has-text("Define Carrier")')).toBeEnabled({ timeout: 30_000 });
      await rest(2000);
      await shot(page, "target-acquisition-connected");

      expect(errors, "the page raised no errors").toEqual([]);
    } finally {
      await bridge.stop();
    }
  });
});
