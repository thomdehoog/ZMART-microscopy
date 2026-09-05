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
import { cell, note, press } from "../cells.js";

/**
 * The configuration: which pass through the workflow this is. Once a driver
 * is connected, the configurations the machine keeps are listed newest
 * first, to reopen one and see and edit what it holds, or a new one is
 * started as a full copy of what stands now. Every step after Connect
 * starts from what the chosen configuration holds, and each Save and adopt
 * writes into it.
 */
const setupConfiguration = {
  id: "setup-configuration",
  label: "Setup",
  mount(host, ctx) {
    if (!ctx.connected()) return { host };
    const box = cell("Configuration",
      "Reopen a configuration, or start a new one as a copy of the newest.");
    const current = ctx.configuration();
    const listed = ctx.configurations();
    const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "");
    const fail = (why) => { box.body.append(note(`Could not open the configuration — ${why.message}`, "bad")); };

    /* One row: the configurations so far, newest first, Open, and New. A
       configuration is known by when it was started. */
    const row = document.createElement("div");
    row.className = "setup-row setup-reference";
    const label = document.createElement("label");
    label.textContent = "Configuration";
    const select = document.createElement("select");
    select.className = "setup-field setup-wide";
    select.setAttribute("aria-label", "configuration");
    if (!listed.length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "none yet"; select.append(o);
      select.disabled = true;
    }
    for (const c of listed) {
      const o = document.createElement("option");
      o.value = c.id;
      const held = Object.entries(c.has ?? {}).filter(([, v]) => v).map(([k]) => k);
      o.textContent = `${when(c.created_at)}` + (held.length ? ` · ${held.join(", ")}` : " · empty");
      o.selected = current?.id === c.id;
      select.append(o);
    }
    const open = press("Open", async () => {
      if (!select.value) return;
      try { await ctx.chooseConfiguration(select.value); } catch (why) { fail(why); return; }
      ctx.refresh();
    }, { busy: "opening…", disabled: !listed.length });
    const fresh = press("New configuration", async () => {
      try { await ctx.startConfiguration(); } catch (why) { fail(why); return; }
      ctx.refresh();
    }, { busy: "starting…" });
    row.append(label, select, open, fresh);
    box.body.append(row);

    if (current) box.body.append(note(`Open · started ${when(current.created_at)}`, "ok"));
    host.append(box.box);
    return { host };
  },
};

export const connect = reworded(connectToTheMicroscope, {
  why: "Choose the microscope, its API and the password, then open the session "
    + "— the settings on the steps below are read from the instrument through it.",
  panels: ["setup"],
  channel: setupConfiguration,
});
