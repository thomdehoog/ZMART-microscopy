/**
 * Step 5's cell — the actuators as they stand, and the press that makes
 * those readings zero.
 *
 * An origin is not three numbers: it is a reading of every drive the
 * instrument has -- on a Leica the motoric X and Y, the Z-wide and the
 * Z-galvo -- and the objective they were read under. So the cell shows
 * the drives one per row, as the instrument reports them, and says plainly
 * that these readings are what will be (0, 0, 0). Nothing here drives the
 * stage: the operator takes the microscope to the origin in its own
 * software and presses Read, and the readings are the origin from then on.
 */

import { cell, note, press, readout } from "../cells.js";

const reading = (a) => `${Number(a.value).toFixed(2)} ${a.unit ?? ""}`.trim();

export default {
  id: "origin",
  label: "Set up origin",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("This driver keeps no origin of its own. Walk on."));
      host.append(box);
      return { host };
    }

    const origin = cell("Set origin",
      "Move the stage to the origin in the microscope's own software, then read. "
      + "The readings become (0, 0, 0) from the next connect on.");
    const adopted = ctx.publishedNote()?.startsWith("Adopted") ?? false;
    const standing = ctx.standing();
    if (!adopted) {
      if (standing?.source === "published") {
        const d = standing.document?.origin ?? standing.document ?? {};
        origin.body.append(note(`Published origin: (${Number(d.x_um).toFixed(0)}, ${Number(d.y_um).toFixed(0)}, `
          + `${Number(d.z_um ?? d.z_focus_um).toFixed(1)}) µm. Reading replaces it.`));
      } else if (standing) {
        origin.body.append(note("No origin published: the frame is the stage's absolute zero."));
      }
    }

    /* One press. Reading the drives is adopting them: what the instrument
       reports at the moment of the press is the origin, published at once. */
    origin.body.append(press("Read", async () => {
      try {
        const document = await ctx.setup.measure("origin");
        const where = await ctx.setup.publish("origin", document);
        ctx.holdHere(document);
        ctx.settle(`(${Number(document.x_um).toFixed(0)}, ${Number(document.y_um).toFixed(0)}, ${Number(document.z_um).toFixed(1)}) · adopted`,
          `Adopted: ${where.snapshot?.split("/").pop() ?? where.path}`);
      } catch (why) {
        ctx.settle(null, `Reading failed — ${why.message}`);
      }
      ctx.refresh();
    }, { busy: "reading…" }));

    /* The drives, one per row, and what the row of numbers means. */
    const here = ctx.here();
    if (here?.actuators) {
      origin.body.append(note(adopted
        ? "These readings are now (0, 0, 0):"
        : "These readings will become (0, 0, 0):", adopted ? "ok" : ""));
      const rows = Object.entries(here.actuators).map(([name, a]) => [name, reading(a)]);
      if (here.objective?.name || here.objective?.slot !== undefined) {
        rows.push(["objective", `slot ${here.objective.slot ?? "?"} · ${here.objective.name ?? ""}`.trim()]);
      }
      origin.body.append(readout(rows));
    } else if (here) {
      origin.body.append(readout([["X", `${here.x_um} µm`], ["Y", `${here.y_um} µm`], ["Z", `${here.z_um} µm`]]));
    }
    if (ctx.hereProblem()) origin.body.append(note(ctx.hereProblem(), "bad"));
    if (ctx.publishedNote()) origin.body.append(note(ctx.publishedNote(), adopted ? "ok" : "bad"));
    host.append(origin.box);
    return { host };
  },
};
