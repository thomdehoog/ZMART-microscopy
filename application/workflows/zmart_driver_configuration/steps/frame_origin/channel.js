/**
 * Step 5's cell — import where the microscope stands, and that is the origin.
 *
 * Nothing here drives the stage. The operator takes the microscope to the
 * point the run should count from in the instrument's own software, the way
 * a job is chosen there, and then presses Import: the page reads the
 * position as it stands and publishes it as the origin, in one press. From
 * the next connect on, that spot is (0, 0, 0).
 */

import { cell, note, press, readout, um } from "../cells.js";

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
      "Move the stage to the origin in the microscope's own software, then import. "
      + "The imported position becomes (0, 0, 0) from the next connect on.");
    const standing = ctx.standing();
    if (standing?.source === "published") {
      const d = standing.document?.origin ?? standing.document ?? {};
      origin.body.append(note(
        `What stands now: (${um(d.x_um, 0)}, ${um(d.y_um, 0)}, ${um(d.z_um ?? d.z_focus_um, 1)}) · published`));
    } else if (standing && !ctx.publishedNote()?.startsWith("Adopted")) {
      origin.body.append(note("No origin published: the frame is the stage's absolute zero."));
    }
    origin.body.append(press("Import", async () => {
      try {
        const document = await ctx.setup.measure("origin");
        const where = await ctx.setup.publish("origin", document);
        ctx.holdHere(document);
        ctx.settle(`(${um(document.x_um, 0)}, ${um(document.y_um, 0)}, ${um(document.z_um, 1)}) · adopted`,
          `Adopted: ${where.snapshot?.split("/").pop() ?? where.path}`);
      } catch (why) {
        ctx.settle(null, `Import failed — ${why.message}`);
      }
      ctx.refresh();
    }, { busy: "importing…" }));
    const here = ctx.here();
    if (ctx.publishedNote() && here) {
      origin.body.append(readout([["X", um(here.x_um, 1)], ["Y", um(here.y_um, 1)], ["Z", um(here.z_um, 2)]]));
      origin.body.append(note(ctx.publishedNote(), ctx.publishedNote().startsWith("Adopted") ? "ok" : "bad"));
    } else if (ctx.publishedNote()) {
      origin.body.append(note(ctx.publishedNote(), "bad"));
    }
    host.append(origin.box);
    return { host };
  },
};
