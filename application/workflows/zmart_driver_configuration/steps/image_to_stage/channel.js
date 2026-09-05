/**
 * Step 3's cells — measure which way the picture is turned, then publish it.
 *
 * The instrument's part is small and the driver supplies it: image the field
 * where the stage stands, move a known distance along +X, image again, come
 * back, move along +Y, image again, come back. The analysis's part is to look
 * at the three pictures and say which of the eight ways of laying an image
 * down fits — and, from how far the features moved, how much specimen one
 * pixel covers. This channel only asks, shows, and publishes.
 *
 * The one thing it cannot check is what the pictures need: a specimen under
 * the objective with structure in it, in focus. So it says so in words.
 */

import { cell, note, picture, press, publishRow } from "../cells.js";

export default {
  id: "orientation",
  label: "Image-to-stage calibration",

  /**
   * `ctx` carries: `setup` (the seam), `supported()` (whether this driver
   * has this to measure), `held()` / `hold(answer)` (the last measurement,
   * kept on the run), `publishedNote()` / `settle(note)` (mark the step
   * done and say what it came to), `refresh()`.
   */
  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("This driver has no stage-to-image turn to measure. Walk on."));
      host.append(box);
      return { host };
    }

    const measure = cell("Set orientation",
      "Use a field with recognisable structure, in focus. This acquires images at home, +X and +Y "
      + "and compares four rotations with reflection absent or present.");
    measure.body.append(press(ctx.held() ? "Rerun" : "Start", async () => {
      try { ctx.hold(await ctx.setup.measure("orientation", { stage_move_um: ctx.moveUm() })); }
      catch (why) { ctx.hold({ failed: why.message }); }
      ctx.refresh();
    }, { busy: "measuring…" }));
    const held = ctx.held();
    if (held?.failed) measure.body.append(note(`Failed — ${held.failed}`, "bad"));
    else if (held?.diagnostic_url) {
      measure.body.append(picture(held.diagnostic_url, "the detected correction and the eight candidates"));
    } else if (held?.why) measure.body.append(note(held.why, held.accepted ? "" : "bad"));
    host.append(measure.box);

    const publish = cell("Save and adopt", "Activates the measured orientation for this machine.");
    publish.body.append(publishRow({
      label: "Adopt orientation",
      published: ctx.publishedNote(),
      onPublish: async () => {
        const answer = ctx.held();
        if (!answer?.accepted) { ctx.settle(null, "Nothing accepted to adopt — measure first."); ctx.refresh(); return; }
        try {
          const where = await ctx.setup.publish("orientation", {
            rotation_deg: answer.orientation.rotation_deg, reflection: answer.orientation.reflection,
          });
          ctx.settle(`${answer.orientation.rotation_deg}°${answer.orientation.reflection ? " mirrored" : ""} · adopted`,
            `Adopted: ${where.path}`);
        } catch (why) { ctx.settle(null, `Adopting failed — ${why.message}`); }
        ctx.refresh();
      },
    }));
    host.append(publish.box);
    return { host };
  },
};
