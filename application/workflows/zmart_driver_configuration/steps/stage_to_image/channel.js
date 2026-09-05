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

import { cell, note, press, publishRow, readout, um } from "../cells.js";

export default {
  id: "orientation",
  label: "Stage-to-image calibration",

  /**
   * `ctx` carries: `setup` (the seam), `supported()` (whether this driver
   * has this to measure), `held()` / `hold(answer)` (the last measurement,
   * kept on the run), `publishedNote()` / `settle(note)` (mark the step
   * done and say what it came to), `refresh()`.
   */
  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope",
        "This driver has no stage-to-image turn to measure. The step is here so the "
        + "workflow reads the same on every instrument; there is nothing to do on this one.");
      body.append(note("Walk on to the next step."));
      host.append(box);
      return { host };
    }

    /* ---- the measurement ---------------------------------------------- */
    const measure = cell("Measure the turn",
      "Put a specimen with structure in it under the objective — nuclei, or anything "
      + "with edges — and bring it into focus. Then press: the stage images the field, "
      + "moves a short way along X and along Y, images each, and comes back. The "
      + "analysis works out which way the picture is turned from where the features went.");
    const moveRow = document.createElement("div");
    moveRow.className = "setup-row";
    const moveLabel = document.createElement("label");
    moveLabel.textContent = "How far to move (µm)";
    const moveBox = document.createElement("input");
    moveBox.type = "number";
    moveBox.className = "side-number";
    moveBox.value = ctx.moveUm();
    moveBox.min = 1;
    moveBox.addEventListener("change", () => ctx.setMoveUm(Number(moveBox.value)));
    moveRow.append(moveLabel, moveBox);
    measure.body.append(moveRow);
    measure.body.append(press("Measure orientation", async () => {
      try {
        const answer = await ctx.setup.measure("orientation", { stage_move_um: ctx.moveUm() });
        ctx.hold(answer);
      } catch (why) {
        ctx.hold({ failed: why.message });
      }
      ctx.refresh();
    }, { busy: "measuring…" }));

    const held = ctx.held();
    if (held?.failed) {
      measure.body.append(note(`The measurement failed — ${held.failed}`, "bad"));
    } else if (held) {
      const o = held.orientation;
      measure.body.append(readout([
        ["Turn", `${o.rotation_deg}°${o.reflection ? ", mirrored" : ""}`],
        ["Pixel size", `${um(held.pixel_um?.mean, 4)} (X ${um(held.pixel_um?.x, 4)}, Y ${um(held.pixel_um?.y, 4)})`],
        ["Fit", `${held.residual.toFixed(3)} from a whole quarter-turn (limit ${held.residual_max})`],
        ["Stage moved", um(held.stage_move_um, 0)],
      ]));
      if (held.why) measure.body.append(note(held.why, held.accepted ? "" : "bad"));
      if (held.accepted) {
        measure.body.append(note(
          `The picture is turned ${o.rotation_deg}°${o.reflection ? " and mirrored" : ""} relative to the stage: `
          + `stage X comes from image ${o.sign_convention.stage_x_from_image}, `
          + `stage Y from image ${o.sign_convention.stage_y_from_image}.`, "ok"));
      }
    }
    host.append(measure.box);

    /* ---- publishing ----------------------------------------------------- */
    const publish = cell("Publish",
      "Publishing writes the turn to a dated folder under this machine's orientation tree. "
      + "From the next connect on, every saved picture is laid down the way the stage sees it, "
      + "and no workflow above the driver has to think about it again.");
    const standing = ctx.standing();
    if (standing) {
      publish.body.append(note(
        `What stands now: ${standing.document?.rotation_deg ?? 0}°`
        + `${standing.document?.reflection ? ", mirrored" : ""}`
        + `${standing.document?.measured ? " (measured)" : " (unmeasured — the driver assumes no turn)"}`
        + ` · ${standing.source}`));
    }
    publish.body.append(publishRow({
      label: "Publish orientation",
      published: ctx.publishedNote(),
      onPublish: async () => {
        const answer = ctx.held();
        if (!answer?.accepted) {
          ctx.settle(null, "measure first — nothing accepted to publish");
          ctx.refresh();
          return;
        }
        try {
          const where = await ctx.setup.publish("orientation", {
            rotation_deg: answer.orientation.rotation_deg,
            reflection: answer.orientation.reflection,
          });
          await ctx.restand?.();
          ctx.settle(`${answer.orientation.rotation_deg}°${answer.orientation.reflection ? " mirrored" : ""} · published`,
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
