/**
 * Step 4's cells — the same field through two lenses, and what that says.
 *
 * Three moves, in this order, with the operator changing lenses by hand in
 * the vendor's own software between the first two:
 *
 * 1. Under the reference lens (the low-power one an overview is taken with),
 *    capture its view of the field and a short focus stack.
 * 2. Change to the target lens, and capture the same.
 * 3. Measure: the analysis lays the two views over one another and returns
 *    where the target lens looks and focuses relative to the reference.
 *
 * The driver only ever *observes* which lens is in; nothing here can change
 * it, and the answer records which two lenses were measured.
 */

import { cell, note, press, publishRow, readout, um } from "../cells.js";

export default {
  id: "calibration",
  label: "Optics calibration",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope",
        "This driver has no objective pair to calibrate. Walk on to the next step.");
      body.append(note("Nothing to do here on this instrument."));
      host.append(box);
      return { host };
    }
    const views = ctx.views();

    const lensCell = (name, title, prose) => {
      const c = cell(title, prose);
      c.body.append(press(`Capture under the ${name} lens`, async () => {
        try {
          const view = await ctx.setup.measure("lens", { name, orientation: ctx.orientation() });
          ctx.holdView(name, view);
        } catch (why) {
          ctx.holdView(name, { failed: why.message });
        }
        ctx.refresh();
      }, { busy: "capturing…" }));
      const view = views[name];
      if (view?.failed) c.body.append(note(`The capture failed — ${view.failed}`, "bad"));
      else if (view) {
        c.body.append(readout([
          ["Lens", `slot ${view.lens?.slot ?? "?"} · ${view.lens?.name ?? "unknown"}`],
          ["Pixel size", um(view.pixel_um, 4)],
          ["Stage at", `x ${um(view.position?.x_um, 0)} · y ${um(view.position?.y_um, 0)} · z ${um(view.position?.z_um, 1)}`],
          ["Stack", `${view.z_um?.length ?? 0} planes`],
        ]));
      }
      return c.box;
    };

    host.append(lensCell("reference", "1 · The reference lens",
      "With the low-power lens in — the one overviews are taken with — bring a structured "
      + "field into focus and press. The driver captures its view and a short focus stack "
      + "around the current height. Leave the stage where it is afterwards."));
    host.append(lensCell("target", "2 · The target lens",
      "Change to the high-power lens in the microscope's own software, refocus without "
      + "moving the stage in X or Y, and press. The same field, through the other lens."));

    /* ---- the measurement ---------------------------------------------- */
    const measure = cell("3 · Measure the pair",
      "The analysis brings the two views to one scale and lays them over one another. "
      + "The shift is where the target lens looks relative to the reference; the two focus "
      + "stacks say how far apart they focus.");
    measure.body.append(press("Measure the pair", async () => {
      try {
        ctx.hold(await ctx.setup.measure("objective_pair", { reference: "reference", target: "target" }));
      } catch (why) {
        ctx.hold({ failed: why.message });
      }
      ctx.refresh();
    }, { busy: "measuring…", disabled: !(views.reference && views.target && !views.reference.failed && !views.target.failed) }));
    const held = ctx.held();
    if (held?.failed) measure.body.append(note(`The measurement failed — ${held.failed}`, "bad"));
    else if (held) {
      const t = held.translation_um ?? {};
      measure.body.append(readout([
        ["Target looks", `${um(t.x)} in X, ${um(t.y)} in Y from the reference`],
        ["Target focuses", t.z === null || t.z === undefined ? "— (no stacks)" : `${um(t.z)} from the reference`],
        ["Pixel sizes", `reference ${um(held.pixel_um?.reference, 4)} · target ${um(held.pixel_um?.target, 4)}`],
        ["Agreement", `${(held.registration?.agreement ?? 0).toFixed(2)} where the views overlap`],
      ]));
      if (held.why) measure.body.append(note(held.why, held.accepted ? "" : "bad"));
    }
    host.append(measure.box);

    /* ---- publishing ----------------------------------------------------- */
    const publish = cell("Publish",
      "Publishing folds this pair into the machine's calibration: the reference lens is the "
      + "anchor at zero and the target lens is placed relative to it. Run the three moves "
      + "again for every other pair of lenses you use.");
    publish.body.append(publishRow({
      label: "Publish calibration",
      published: ctx.publishedNote(),
      onPublish: async () => {
        const answer = ctx.held();
        if (!answer?.accepted || !answer.document) {
          ctx.settle(null, "measure first — nothing accepted to publish");
          ctx.refresh();
          return;
        }
        try {
          const where = await ctx.setup.publish("calibration", answer.document);
          const lenses = answer.lenses ?? {};
          await ctx.restand?.();
          ctx.settle(`slot ${lenses.target?.slot} against slot ${lenses.reference?.slot} · published`,
            `Published to ${where.path}`);
        } catch (why) {
          ctx.settle(null, `Publishing failed — ${why.message}`);
        }
        ctx.refresh();
      },
    }));
    host.append(publish.box);
    return { host };
  },
};
