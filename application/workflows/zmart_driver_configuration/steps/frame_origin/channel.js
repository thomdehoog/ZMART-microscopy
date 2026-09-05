/**
 * Step 5's cell -- the actuators as they stand, the press that reads them,
 * and the press that makes those readings zero.
 *
 * An origin is not three numbers: it is a reading of every drive the
 * instrument has -- on a Leica the motoric X and Y, the Z-wide and the
 * Z-galvo -- and the objective they were read under. So the cell shows
 * the drives one per row, as the instrument reports them, and says plainly
 * that these readings are what will be (0, 0, 0). Nothing here drives the
 * stage: the operator takes the microscope to the origin in its own
 * software and presses Read; the readings are held, and Save and adopt
 * publishes them as the origin from the next connect on.
 */

import { cell, note, press, publishRow, readout } from "../cells.js";

const reading = (a) => `${Number(a.value).toFixed(2)} ${a.unit ?? ""}`.trim();

export default {
  id: "origin",
  label: "Define coordinate system origin",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("Nothing to set on this microscope."));
      host.append(box);
      return { host };
    }

    const origin = cell("Origin",
      "Drive to the origin in the microscope's software, then Read.");
    const adopted = ctx.publishedNote()?.startsWith("Adopted") ?? false;
    const standing = ctx.standing();
    if (!adopted) {
      if (standing?.source === "published") {
        const d = standing.document?.origin ?? standing.document ?? {};
        origin.body.append(note("Published: "
          + `(${Number(d.x_um).toFixed(0)}, ${Number(d.y_um).toFixed(0)}, `
          + `${Number(d.z_um ?? d.z_focus_um).toFixed(1)}) µm.`));
      } else if (standing) {
        origin.body.append(note("No origin published."));
      }
    }

    /* The drives, one per row, and what the row of numbers means: what the
       instrument reports now, the readings held for adopting, or the origin. */
    const held = ctx.held();
    const here = held ?? ctx.here();
    if (here?.actuators) {
      origin.body.append(note(adopted ? "Now (0, 0, 0):" : held ? "Becomes (0, 0, 0):" : "Current position:",
        adopted ? "ok" : ""));
      const rows = Object.entries(here.actuators).map(([name, a]) => [name, reading(a)]);
      if (here.objective?.name || here.objective?.slot !== undefined) {
        rows.push(["objective", `slot ${here.objective.slot ?? "?"} · ${here.objective.name ?? ""}`.trim()]);
      }
      origin.body.append(readout(rows));
    } else if (here) {
      origin.body.append(readout([["X", `${here.x_um} µm`], ["Y", `${here.y_um} µm`], ["Z", `${here.z_um} µm`]]));
    }
    if (ctx.hereProblem()) origin.body.append(note(ctx.hereProblem(), "bad"));

    /* At the bottom of the box: Read takes the readings and holds them,
       nothing written yet; Save and adopt, beside it, publishes them. */
    const row = publishRow({
      label: "Save and adopt",
      published: ctx.publishedNote(),
      disabled: !held,
      onPublish: async () => {
        if (!held) { ctx.settle(null, "Read first."); ctx.refresh(); return; }
        try {
          const where = await ctx.setup.publish("origin", held);
          ctx.settle(`(${Number(held.x_um).toFixed(0)}, ${Number(held.y_um).toFixed(0)}, ${Number(held.z_um).toFixed(1)}) · adopted`,
            "Adopted.");
        } catch (why) {
          ctx.settle(null, `Adopting failed — ${why.message}`);
        }
        ctx.refresh();
      },
    });
    row.prepend(press("Read", async () => {
      try {
        const document = await ctx.setup.measure("origin");
        ctx.hold(document);
        ctx.holdHere(document);
      } catch (why) {
        ctx.holdHere(null, `Reading failed — ${why.message}`);
      }
      ctx.refresh();
    }, { busy: "reading…" }));
    origin.body.append(row);
    host.append(origin.box);
    return { host };
  },
};
