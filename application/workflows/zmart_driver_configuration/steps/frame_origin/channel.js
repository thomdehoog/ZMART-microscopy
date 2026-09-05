/**
 * Step 5's cells — drive to the point the run should count from, and say "here".
 *
 * The step is two cells. The first shows where the stage stands, as the
 * driver reads it, and lets the operator type a position to drive to — moves
 * are verified by readback and fenced by the physical backstop whatever has
 * been published. The second makes the current position the origin and
 * publishes that as a dated record, which the driver stands on at its next
 * connect.
 */

import { cell, note, press, publishRow, readout, um } from "../cells.js";

export default {
  id: "origin",
  label: "Set up origin",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope", "This driver keeps no origin of its own.");
      body.append(note("Nothing to do here on this instrument."));
      host.append(box);
      return { host };
    }

    /* ---- where the stage is, and driving it ----------------------------- */
    const where = cell("Where the stage stands",
      "Read from the instrument, in absolute stage micrometres. Type a position and press "
      + "Drive to go there; the driver reads the position back after the move and refuses "
      + "anything outside the stage's physical travel.");
    const here = ctx.here();
    if (here) {
      where.body.append(readout([
        ["X", um(here.x_um, 1)], ["Y", um(here.y_um, 1)], ["Z", um(here.z_um, 2)],
      ]));
    }
    const row = document.createElement("div");
    row.className = "setup-row";
    const boxes = {};
    for (const axis of ["x_um", "y_um", "z_um"]) {
      const label = document.createElement("label");
      label.textContent = axis[0].toUpperCase();
      const input = document.createElement("input");
      input.type = "number";
      input.className = "side-number";
      input.value = here?.[axis] ?? "";
      input.setAttribute("aria-label", `${axis[0].toUpperCase()} to drive to, in micrometres`);
      boxes[axis] = input;
      row.append(label, input);
    }
    where.body.append(row);
    const actions = document.createElement("div");
    actions.className = "setup-row";
    actions.append(press("Read position", async () => {
      try { ctx.holdHere(await ctx.setup.where()); } catch (why) { ctx.holdHere(null, why.message); }
      ctx.refresh();
    }, { busy: "reading…" }));
    actions.append(press("Drive", async () => {
      try {
        ctx.holdHere(await ctx.setup.move({
          x_um: Number(boxes.x_um.value), y_um: Number(boxes.y_um.value), z_um: Number(boxes.z_um.value),
        }));
      } catch (why) {
        ctx.holdHere(ctx.here(), why.message);
      }
      ctx.refresh();
    }, { busy: "moving…" }));
    where.body.append(actions);
    if (ctx.hereProblem()) where.body.append(note(ctx.hereProblem(), "bad"));
    host.append(where.box);

    /* ---- the origin ------------------------------------------------------- */
    const origin = cell("Make this the origin",
      "The current position becomes (0, 0, 0). Every position a run records from the next "
      + "connect on is micrometres from here — so choose a place you can find again, and one "
      + "you will not want to move later: changing the origin quietly changes what every "
      + "recorded position means.");
    const standing = ctx.standing();
    if (standing?.source === "published") {
      const d = standing.document?.origin ?? standing.document ?? {};
      origin.body.append(note(
        `What stands now: (${um(d.x_um, 0)}, ${um(d.y_um, 0)}, ${um(d.z_um ?? d.z_focus_um, 1)}) · published`));
    } else if (standing) {
      origin.body.append(note("No origin has been published: the frame counts from the stage's absolute zero."));
    }
    origin.body.append(publishRow({
      label: "Set origin here",
      published: ctx.publishedNote(),
      onPublish: async () => {
        try {
          const document = await ctx.setup.measure("origin");
          const where = await ctx.setup.publish("origin", document);
          await ctx.restand?.();
          ctx.settle(`(${um(document.x_um, 0)}, ${um(document.y_um, 0)}, ${um(document.z_um, 1)}) · published`,
            `Published to ${where.path}`);
        } catch (why) {
          ctx.settle(null, `Publishing failed — ${why.message}`);
        }
        ctx.refresh();
      },
    }));
    host.append(origin.box);
    return { host };
  },
};
