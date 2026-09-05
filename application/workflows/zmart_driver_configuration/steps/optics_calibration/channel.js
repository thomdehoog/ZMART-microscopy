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

import { cell, note, picture, press, publishRow } from "../cells.js";

export default {
  id: "calibration",
  label: "Optics calibration",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("This driver has no objective pair to calibrate. Walk on."));
      host.append(box);
      return { host };
    }
    const views = ctx.views();
    const lensCell = (name, title, prose) => {
      const c = cell(title, prose);
      c.body.append(press(`Measure ${name}`, async () => {
        try { ctx.holdView(name, await ctx.setup.measure("lens", { name, orientation: ctx.orientation() })); }
        catch (why) { ctx.holdView(name, { failed: why.message }); }
        ctx.refresh();
      }, { busy: "measuring…" }));
      const view = views[name];
      if (view?.failed) c.body.append(note(`Failed — ${view.failed}`, "bad"));
      else if (view) {
        c.body.append(note(`slot ${view.lens?.slot ?? "?"} · ${view.lens?.name ?? "?"} · ${view.pixel_um} µm/px · peak z = ${Number(view.peak_z_um).toFixed(3)} um`, "ok"));
        if (view.diagnostic_url) c.body.append(picture(view.diagnostic_url, `${name} focus curve and the sharpest slice`));
      }
      return c.box;
    };
    host.append(lensCell("reference", "Measure 1: reference",
      "With the reference objective in and the field in focus, press."));
    host.append(lensCell("target", "Measure 2: target",
      "Switch only to the target objective. Do not move X/Y."));

    const measure = cell("Measure 3: X/Y", "The X/Y offset, from matching the two images pixel by pixel.");
    measure.body.append(press("Measure the pair", async () => {
      try { ctx.hold(await ctx.setup.measure("objective_pair", { reference: "reference", target: "target" })); }
      catch (why) { ctx.hold({ failed: why.message }); }
      ctx.refresh();
    }, { busy: "measuring…", disabled: !(views.reference && views.target && !views.reference.failed && !views.target.failed) }));
    const held = ctx.held();
    if (held?.failed) measure.body.append(note(`Failed — ${held.failed}`, "bad"));
    else if (held) {
      const t = held.translation_um ?? {}; const lenses = held.lenses ?? {};
      const z = t.z === null || t.z === undefined ? "—" : `${t.z >= 0 ? "+" : ""}${t.z.toFixed(2)}`;
      measure.body.append(note(
        `slot ${lenses.reference?.slot} → slot ${lenses.target?.slot} · translation XY (${t.x >= 0 ? "+" : ""}${t.x.toFixed(2)}, `
        + `${t.y >= 0 ? "+" : ""}${t.y.toFixed(2)}) um · Z ${z} um · ${held.accepted ? "trusted" : "WEAK VOTE"}`,
        held.accepted ? "ok" : "bad"));
      if (held.diagnostic_url) measure.body.append(picture(held.diagnostic_url, "the two objectives overlaid, as acquired and after the correction"));
      if (held.why) measure.body.append(note(held.why, "bad"));
    }
    host.append(measure.box);

    const publish = cell("Save and adopt", "Publishes the calibration. To calibrate another pair, measure again with the same reference.");
    publish.body.append(publishRow({
      label: "Adopt calibration",
      published: ctx.publishedNote(),
      onPublish: async () => {
        const answer = ctx.held();
        if (!answer?.accepted || !answer.document) { ctx.settle(null, "Nothing accepted to adopt — measure first."); ctx.refresh(); return; }
        try {
          const where = await ctx.setup.publish("calibration", answer.document);
          const lenses = answer.lenses ?? {};
          ctx.settle(`slot ${lenses.target?.slot} against slot ${lenses.reference?.slot} · adopted`, `Calibration adopted: ${where.path}`);
        } catch (why) { ctx.settle(null, `Adopting failed — ${why.message}`); }
        ctx.refresh();
      },
    }));
    host.append(publish.box);
    return { host };
  },
};
