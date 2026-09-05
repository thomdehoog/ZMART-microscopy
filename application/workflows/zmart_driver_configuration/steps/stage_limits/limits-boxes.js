/**
 * Step 2's channel — two boxes: what the instrument says, and what you publish.
 *
 * The set_limits notebook does this in two moves, and the step keeps them
 * apart for the same reason the notebook does.
 *
 * **Read from the stage** is a question put to the microscope. You place four
 * Point markers at the safe X and Y corners in the active LAS X template, and
 * the driver reads that rectangle back. It replaces X and Y and touches
 * nothing else, so it is a measurement rather than a decision.
 *
 * **The limits** is the document you are about to publish: the stage ranges,
 * which objective slots automation may turn to, and one line per setting the
 * driver is able to change. Most of it is a judgement rather than a reading —
 * the two Z ranges and every setting are typed rather than measured — which is
 * why it is a box you edit rather than a readout.
 *
 * Keeping them separate is what makes the step honest about where each number
 * came from. A figure that was measured and a figure that was decided look
 * identical once they are in the same file, and only one of them can be
 * checked by asking the instrument again.
 *
 * What goes in the boxes is the driver's, not this file's: the axes and the
 * list of settings arrive in `ctx.document()`, because a Leica's two Z ranges
 * and twenty setters are a Leica's. See `../../drivers/what-a-driver-declares.js`.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

/** A range as the file holds it, in words an operator can check at a glance. */
const asRange = (entry) => {
  const range = entry?.range;
  if (!Array.isArray(range) || range.length !== 2) return "not set";
  return `${range[0]} … ${range[1]}`;
};

export default {
  id: "limits",
  label: "Set up limits",

  /**
   * `ctx` carries:
   *   `document()`   the driver's account of its own limits file — the axes,
   *                  the objective slots, and the settings it can fence
   *   `limits()`     the document as it stands, which is what publishing sends
   *   `edit(key, value)`  one field changed by hand
   *   `readBoundary()`    ask the instrument for the four corners; resolves
   *                  with the X and Y it read, and the step folds them in
   *   `reading()`    whether that question is out with the instrument now
   *   `lastRead()`   what came back last time, or null before the first ask
   */
  mount(host, ctx) {
    const doc = ctx.document();

    /* ---- Box one: what the instrument says ------------------------------ */
    const read = sideGroup("Read from the stage");

    const how = document.createElement("p");
    how.className = "side-note";
    how.textContent =
      "Place exactly four Point markers at the safe X and Y corners in the "
      + "active LAS X template, then read the rectangle back. The template trio "
      + "is saved with the measurement, and the active template is left as it is.";
    read.body.append(how);

    const ask = document.createElement("button");
    ask.className = "run";
    ask.type = "button";
    ask.textContent = ctx.reading() ? "reading…" : "Read the boundary";
    ask.disabled = Boolean(ctx.reading());
    ask.addEventListener("click", () => ctx.readBoundary());
    read.body.append(ask);

    /* What came back, and what it did to the document. Shown only once there
       is an answer: an empty readout before the first ask would look like a
       measurement that returned nothing. */
    const answer = ctx.lastRead();
    if (answer) {
      const said = document.createElement("dl");
      said.className = "side-readout";
      for (const key of doc.measured) {
        const axis = doc.axes.find((a) => a.key === key);
        const dt = document.createElement("dt");
        dt.textContent = axis?.label ?? key;
        const dd = document.createElement("dd");
        dd.textContent = `${asRange(answer[key])} ${axis?.unit ?? ""}`.trim();
        said.append(dt, dd);
      }
      read.body.append(said);

      const only = document.createElement("p");
      only.className = "side-note";
      only.textContent =
        "This replaced " + doc.measured
          .map((k) => doc.axes.find((a) => a.key === k)?.label ?? k).join(" and ")
        + " in the box below. Everything else there is yours to decide.";
      read.body.append(only);
    }

    /* ---- Box two: what you are about to publish -------------------------- */
    const edit = sideGroup("The limits");
    const held = ctx.limits();

    /* The stage ranges. Both endpoints count as inside the envelope. */
    for (const axis of doc.axes) {
      const row = document.createElement("div");
      row.className = "side-row";

      const name = document.createElement("label");
      name.textContent = `${axis.label} (${axis.unit})`;
      row.append(name);

      /* A low and a high, side by side, because a range read as one field is
         a range somebody will mistype into a single number. */
      for (const end of [0, 1]) {
        const box = document.createElement("input");
        box.type = "number";
        box.className = "side-number";
        box.value = held?.[axis.key]?.range?.[end] ?? "";
        box.setAttribute("aria-label",
          `${axis.label} ${end === 0 ? "lowest" : "highest"} position`);
        box.addEventListener("change", () => ctx.edit(axis.key, {
          end, value: box.value === "" ? null : Number(box.value),
        }));
        row.append(box);
      }
      edit.body.append(row);

      if (axis.note) {
        const note = document.createElement("p");
        note.className = "side-note";
        note.textContent = axis.note;
        edit.body.append(note);
      }
    }

    /* Which objective slots automation may turn to. */
    const slots = document.createElement("div");
    slots.className = "side-row";
    const slotName = document.createElement("label");
    slotName.textContent = doc.slots.label;
    const slotBox = document.createElement("input");
    slotBox.type = "text";
    slotBox.className = "side-text";
    slotBox.placeholder = "every slot";
    slotBox.value = (held?.[doc.slots.key] ?? []).join(", ");
    slotBox.setAttribute("aria-label", doc.slots.label);
    slotBox.addEventListener("change", () => ctx.edit(doc.slots.key, {
      list: slotBox.value.split(",").map((s) => s.trim()).filter(Boolean).map(Number),
    }));
    slots.append(slotName, slotBox);
    edit.body.append(slots);

    const slotNote = document.createElement("p");
    slotNote.className = "side-note";
    slotNote.textContent = doc.slots.note;
    edit.body.append(slotNote);

    /* The settings the driver can change. Every one stays visible even while
       unrestricted, because "reviewed, and no limit is enforced" is a
       statement worth being able to see, and it is not the same statement as
       having never looked. */
    for (const key of doc.settings) {
      const row = document.createElement("div");
      row.className = "side-row side-setting";

      const name = document.createElement("label");
      /* The driver's own key, with the set_ prefix dropped and the
         underscores opened out: it stays recognisably the same name as the
         one in the file, while reading as words. */
      name.textContent = key.replace(/^set_/, "").replaceAll("_", " ");
      row.append(name);

      const value = document.createElement("input");
      value.type = "text";
      value.className = "side-text";
      value.placeholder = "no limit";
      value.value = Array.isArray(held?.[key]) && held[key].length === 0
        ? "" : JSON.stringify(held?.[key] ?? "");
      value.setAttribute("aria-label", key);
      value.addEventListener("change", () => ctx.edit(key, { raw: value.value }));
      row.append(value);

      edit.body.append(row);
    }

    host.append(read.group, edit.group);

    /* The step's own button stands under the boxes rather than in the strip at
       the foot, so publishing reads as the end of the form it publishes. */
    const foot = document.createElement("div");
    foot.className = "limits-action";
    host.append(foot);

    return { host };
  },
};
