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
 * The setup session: which pass through the workflow this is. Once a driver
 * is connected, the sessions kept for that machine are listed newest first,
 * to reopen one and see and edit what it holds, or a new one is started
 * from what the machine has now. Every step after Connect starts from what
 * the chosen session holds, and each Save and adopt is recorded into it.
 */
const setupSession = {
  id: "setup-session",
  label: "Setup",
  mount(host, ctx) {
    if (!ctx.connected()) return { host };
    const box = cell("Setup session",
      "Reopen a session to see and edit what it holds, or start a new one from what this machine has now.");
    const current = ctx.session();
    const sessions = ctx.sessions();
    const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "");
    const fail = (why) => { box.body.append(note(`Could not open the session — ${why.message}`, "bad")); };

    /* One row: the sessions so far, newest first, Open, and New session.
       A session is known by when it was started; it needs no name. */
    const row = document.createElement("div");
    row.className = "setup-row setup-reference";
    const label = document.createElement("label");
    label.textContent = "Session";
    const select = document.createElement("select");
    select.className = "setup-field setup-wide";
    select.setAttribute("aria-label", "setup session");
    if (!sessions.length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "none yet"; select.append(o);
      select.disabled = true;
    }
    for (const s of sessions) {
      const o = document.createElement("option");
      o.value = s.id;
      const adopted = s.updated_at && s.updated_at !== s.created_at ? ` · adopted ${when(s.updated_at)}` : "";
      o.textContent = `${when(s.created_at)}${adopted}`;
      o.selected = current?.id === s.id;
      select.append(o);
    }
    const open = press("Open", async () => {
      if (!select.value) return;
      try { await ctx.chooseSession(select.value); } catch (why) { fail(why); return; }
      ctx.refresh();
    }, { busy: "opening…", disabled: !sessions.length });
    const fresh = press("New session", async () => {
      try { await ctx.startSession(""); } catch (why) { fail(why); return; }
      ctx.refresh();
    }, { busy: "starting…" });
    row.append(label, select, open, fresh);
    box.body.append(row);

    if (current) {
      box.body.append(note(`Working in the session started ${when(current.created_at)}`
        + (current.updated_at && current.updated_at !== current.created_at ? `, last adopted ${when(current.updated_at)}` : "") + ".", "ok"));
    } else {
      box.body.append(note("The steps below open once a session is chosen."));
    }
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
