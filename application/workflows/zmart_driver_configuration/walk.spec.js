/**
 * A walk of the whole ZMART driver configuration workflow, with nothing stood
 * in for.
 *
 * The page is the built page, served by the real bridge. The bridge drives
 * the mock microscope through the setup seam, exactly as it would drive a
 * Leica. Everything an operator would do in the vendor's own software --
 * drive the stage to a corner, drop a marker, change the lens, refocus --
 * goes through the mock instrument window's own methods, the same code its
 * buttons run. Nothing here writes a file the driver reads.
 *
 * So what this walk proves is the joins: page to bridge, bridge to seam, seam
 * to driver, driver to the configuration folder on disk -- the same joins a
 * real microscope will stand on. Set `OPERATOR_EVIDENCE_DIR` to keep a
 * screenshot of every screen the operator sees.
 */
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { operateTheInstrument, rest, startTheBridge }
  from "../target_acquisition/steps/scan_the_overview/live-bridge.js";

const PORT = Number(process.env.CONFIGURATION_BRIDGE_PORT ?? 8831);
const A_WHOLE_WALK = 600_000;

/* The mock keeps its machine in a folder named by the environment. A folder
   of its own, made before the bridge starts, so the walk begins from a
   machine nobody has set up and leaves nothing behind in anyone's home. */
const machine = fs.mkdtempSync(path.join(os.tmpdir(), "zmart-configuration-"));
process.env.ZMART_MOCK_MACHINE = path.join(machine, "machine");
process.env.ZMART_MOCK_STATE = path.join(machine, "instrument.json");

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

const inTheInstrument = {
  drive: (x, y, z) => operateTheInstrument("drive_stage", x, y, z),
  dropMarker: () => operateTheInstrument("drop_marker"),
  changeLens: (slot) => operateTheInstrument("change_lens", slot),
};

test.describe("the driver configuration workflow, walked end to end", () => {
  test.setTimeout(A_WHOLE_WALK);

  test("every step publishes into one configuration the driver then stands on", async ({ page }) => {
    const bridge = await startTheBridge({ port: PORT, connect: false });
    const errors = [];
    page.on("pageerror", (why) => errors.push(why.message));
    try {
      await page.goto(`${bridge.at}/`);
      await rest(1500);
      await shot(page, "target-acquisition-as-opened");

      await page.selectOption("#wf-select", { label: "ZMART driver configuration" });
      await rest(800);
      await shot(page, "driver-configuration-chosen");

      /* Step 1: the card, with New configuration chosen in its fourth field. */
      await page.locator('.panel.on .session-form input[type="password"]').fill("mock");
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
        inTheInstrument.drive(x, y, 16.0);
        inTheInstrument.dropMarker();
        await imports.nth(i).click();
        await rest(900);
      }
      await shot(page, "limits-read");
      await page.getByRole("button", { name: "Save and adopt", exact: true }).last().click();
      await rest(2500);
      await shot(page, "limits-published");

      /* Step 3: back to a field with structure, in focus, and read the drives. */
      inTheInstrument.drive(60000, 40000, 16.0);
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
      await page.getByLabel("reference objective").selectOption("0");
      await rest(600);
      await shot(page, "optics-presets");
      await page.locator(".setup-set", { hasText: "40x" }).first().click();
      await rest(600);
      await press(page, /^Measure reference/, 2500);
      await shot(page, "optics-reference");
      inTheInstrument.changeLens(2);
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
      const root = process.env.ZMART_MOCK_MACHINE;
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
      expect(origin.x_um).toBe(60000);
      const orientation = JSON.parse(fs.readFileSync(path.join(newest("orientation"), "orientation.json"), "utf8"));
      expect(orientation.rotation_deg).toBe(90);
      expect(orientation.reflection).toBe(false);
      expect(fs.existsSync(path.join(newest("orientation"), "data", "orientation.png"))).toBe(true);
      expect(fs.existsSync(path.join(newest("orientation"), "data", "orientation.yaml"))).toBe(true);
      const calibration = JSON.parse(fs.readFileSync(path.join(newest("calibration"), "calibration.json"), "utf8"));
      const [dx, dy, dz] = calibration.objectives["2"].translation_um;
      /* The mock's 40x looks (-18, +11, +3.5) µm off its 10x; the 10x's
         pixel is 4 µm, so the answer is expected within that. */
      expect(Math.abs(dx - -18)).toBeLessThanOrEqual(4);
      expect(Math.abs(dy - 11)).toBeLessThanOrEqual(4);
      expect(Math.abs(dz - 3.5)).toBeLessThanOrEqual(0.6);
      expect(fs.existsSync(path.join(newest("calibration"), "data", "0-2-objective_pair.png"))).toBe(true);

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
      await page.locator('.panel.on .session-form input[type="password"]').fill("mock");
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
