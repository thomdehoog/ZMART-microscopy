/**
 * Step 1 — Connect.
 *
 * Nothing about a microscope can be measured until there is a session to
 * measure it through, so a configuration run starts exactly where an imaging
 * run does. Rather than describe the same step a second time, this borrows the
 * one target acquisition already owns and changes only the sentence under its
 * title, which is what `reworded` is for: what the step *does* stays written
 * down in one place, so a fix to connecting reaches both workflows at once.
 *
 * Two things are changed here. The wording says why you are connecting on this
 * run — to read the instrument's own settings rather than to image anything.
 * And the panel is this workflow's own column of controls instead of the
 * canvas, because there is no picture in a configuration run.
 */

import { connect as connectToTheMicroscope }
  from "../../../target_acquisition/steps/connect/step.js";
import { reworded } from "../../../../framework/rules/steps.js";
import { cell, note } from "../cells.js";

/**
 * The one decision that belongs before anything is read: whether this setup
 * edits what the machine already has published, or starts over from the
 * driver's defaults. Made here, under the connect card, because the steps
 * after Connect fill themselves in from the answer.
 */
const setupSession = {
  id: "setup-session",
  label: "Setup",
  mount(host, ctx) {
    const box = cell("Setup session");
    const choices = document.createElement("div");
    choices.className = "setup-choices";
    for (const [mode, label, said] of [
      ["edit", "Edit the current setup", "start from what this machine has published"],
      ["new", "Start a new setup", "start from the driver's defaults; what is published stays until a step adopts"],
    ]) {
      const row = document.createElement("label");
      row.className = "setup-choice";
      const radio = document.createElement("input");
      radio.type = "radio"; radio.name = "setup-mode"; radio.value = mode;
      radio.checked = ctx.mode() === mode;
      radio.addEventListener("change", async () => { await ctx.setMode(mode); ctx.refresh(); });
      const words = document.createElement("span");
      words.innerHTML = `<b></b> <span class="setup-choice-said"></span>`;
      words.querySelector("b").textContent = label;
      words.querySelector(".setup-choice-said").textContent = `— ${said}`;
      row.append(radio, words);
      choices.append(row);
    }
    box.body.append(choices);
    host.append(box.box);
    return { host };
  },
};

export const connect = reworded(connectToTheMicroscope, {
  why: "Choose the microscope, its API and the password, then open the session "
    + "— the settings on the steps below are read from the instrument through it.",
  panels: ["setup"],
  channel: setupSession,
});
