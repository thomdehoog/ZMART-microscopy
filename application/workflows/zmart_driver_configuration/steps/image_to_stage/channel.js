/**
 * Step 4's cells — measure which way the picture is turned, then publish it.
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

import { cell, note, part, picture, press, publishRow } from "../cells.js";

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
      body.append(note("Nothing to measure on this microscope."));
      host.append(box);
      return { host };
    }

    const measure = cell("Orientation",
      "Focus on a field with structure, then Start. Three images, eight candidates.");
    /* What came back, above the buttons: the sheet with the detected
       correction and the eight candidates, or why there is none. */
    const held = ctx.held();
    const standing = ctx.standing();
    if (held?.failed) measure.body.append(note(`Failed — ${held.failed}`, "bad"));
    else if (held?.diagnostic_url) {
      /* The result in a sub-box of its own, so the sheet stands white on
         a tinted ground the way step 5's figures do. */
      const result = part(measure.body, "Result");
      result.append(picture(held.diagnostic_url,
        "the detected correction and the eight candidates, each with the Pearson correlation of its overlay"));
    } else if (held?.why) measure.body.append(note(held.why, held.accepted ? "" : "bad"));
    else if (standing?.source === "published" && standing.evidence_urls?.["orientation.png"]) {
      /* Nothing measured in this run: what the configuration holds, and the
         sheet that was measured for it. */
      const d = standing.document ?? {};
      const result = part(measure.body, "Result", { prose: `In the configuration: ${d.rotation_deg}°${d.reflection ? ", mirrored" : ""}.` });
      result.append(picture(standing.evidence_urls["orientation.png"], "the sheet measured for the configuration"));
    }

    /* At the bottom of the box: Start, which becomes Rerun once there is a
       result, and beside it, only then, Save and adopt, which activates the
       measured orientation for this machine. */
    const run = press(held ? "Rerun" : "Start", async () => {
      try { ctx.hold(await ctx.setup.measure("orientation", { stage_move_um: ctx.moveUm() })); }
      catch (why) { ctx.hold({ failed: why.message }); }
      ctx.refresh();
    }, { busy: "measuring…" });
    if (!held) {
      const row = document.createElement("div");
      row.className = "setup-publish";
      row.append(run);
      measure.body.append(row);
    } else {
      const row = publishRow({
        label: "Save and adopt",
        published: ctx.publishedNote(),
        disabled: !held?.accepted,
        onPublish: async () => {
          const answer = ctx.held();
          if (!answer?.accepted) { ctx.settle(null, "Measure first."); ctx.refresh(); return; }
          try {
            const { images, ...numbers } = answer;
            const where = await ctx.setup.publish("orientation", {
              rotation_deg: answer.orientation.rotation_deg, reflection: answer.orientation.reflection,
            }, [
              ...(answer.diagnostic_url ? [{ name: "orientation.png", picture: answer.diagnostic_url }] : []),
              { name: "orientation_measurement.json", note: numbers },
              { name: "orientation_frames", raw: "orientation" },
              { name: "orientation.yaml", pipeline: "measure_orientation" },
            ]);
            ctx.settle(`${answer.orientation.rotation_deg}°${answer.orientation.reflection ? " mirrored" : ""} · adopted`,
              "Adopted.");
          } catch (why) { ctx.settle(null, `Adopting failed — ${why.message}`); }
          ctx.refresh();
        },
      });
      row.prepend(run);
      measure.body.append(row);
    }
    host.append(measure.box);
    return { host };
  },
};
