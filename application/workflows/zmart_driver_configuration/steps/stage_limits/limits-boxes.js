/**
 * Step 2's cells — two boxes: what the instrument says, and what you publish.
 *
 * The set_limits notebook does this in two moves, and the step keeps them
 * apart for the same reason the notebook does.
 *
 * **Read from the stage** is a question put to the microscope. On the Leica
 * you place four Point markers at the safe X and Y corners in the active
 * LAS X template; on the mock you drop them in the mock instrument's window.
 * The driver reads that rectangle back. It replaces X and Y and touches
 * nothing else, so it is a measurement rather than a decision.
 *
 * **The limits** is the document you are about to publish: the stage ranges,
 * which objective slots automation may turn to, and one line per setting the
 * driver is able to change. Most of it is a judgement rather than a reading —
 * the other axes and every setting are typed rather than measured — which is
 * why it is a box you edit rather than a readout.
 *
 * Keeping them separate is what makes the step honest about where each number
 * came from. A figure that was measured and a figure that was decided look
 * identical once they are in the same file, and only one of them can be
 * checked by asking the instrument again.
 *
 * What goes in the boxes is the driver's, not this file's: the axes and the
 * list of settings arrive in `ctx.document()`, because a Leica's two Z ranges
 * and twenty setters are a Leica's, and a mock's three axes and two settings
 * are a mock's.
 */

import { cell, note, press, publishRow, readout, um } from "../cells.js";

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
   * `ctx` carries, beside the common `setup`, `supported`, `standing`,
   * `settle`, `publishedNote` and `refresh`:
   *   `document()`   the driver's account of its own limits file — the axes,
   *                  the objective slots, and the settings it can fence
   *   `limits()`     the document as it stands on the page, which is what
   *                  publishing sends; starts as what the driver read
   *   `edit(key, value)`  one field changed by hand
   *   `held()` / `hold()` what the last boundary read came to
   */
  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope", "This driver publishes no limits.");
      body.append(note("Nothing to do here on this instrument."));
      host.append(box);
      return { host };
    }
    const doc = ctx.document();
    if (!doc) {
      const { box, body } = cell("Set up limits", "Connect first: the driver says what its limits document holds.");
      body.append(note("Waiting for the driver's description."));
      host.append(box);
      return { host };
    }
    const measuredLabels = doc.measured.map((k) => doc.axes.find((a) => a.key === k)?.label ?? k);

    /* ---- Box one: what the instrument says ------------------------------ */
    const read = cell("Measure",
      `Place exactly four Point markers at the safe ${measuredLabels.join("/")} boundaries, then press. `
      + `This reads the rectangle without changing the active template; it replaces ${measuredLabels.join(" and ")} below.`);
    read.body.append(press("Measure", async () => {
      try {
        const answer = await ctx.setup.measure("boundary");
        ctx.hold(answer);
        for (const key of doc.measured) if (answer[key]) ctx.edit(key, answer[key]);
      } catch (why) {
        ctx.hold({ failed: why.message });
      }
      ctx.refresh();
    }, { busy: "reading…" }));
    const answer = ctx.held();
    if (answer?.failed) {
      read.body.append(note(`Could not read the boundary — ${answer.failed}`, "bad"));
    } else if (answer) {
      read.body.append(readout(doc.measured.map((key) => {
        const axis = doc.axes.find((a) => a.key === key);
        return [axis?.label ?? key, `${asRange(answer[key])} ${axis?.unit ?? ""}`.trim()];
      })));

    }
    host.append(read.box);

    /* ---- Box two: what you are about to publish -------------------------- */
    const edit = cell("Configure",
      "Review the limits. Ranges include both endpoints; an empty setting means reviewed and unrestricted.");
    const held = ctx.limits();
    const standing = ctx.standing();
    if (standing) edit.body.append(note(`Starting from the ${standing.source === "published" ? "published" : "default"} limits.`));

    /* The stage ranges. */
    for (const axis of doc.axes) {
      const row = document.createElement("div");
      row.className = "setup-row";
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
        box.setAttribute("aria-label", `${axis.label} ${end === 0 ? "lowest" : "highest"} position`);
        box.addEventListener("change", () => {
          const range = [...(held?.[axis.key]?.range ?? [null, null])];
          range[end] = box.value === "" ? null : Number(box.value);
          ctx.edit(axis.key, { range });
        });
        row.append(box);
      }
      edit.body.append(row);
      if (axis.note) edit.body.append(note(axis.note));
    }

    /* Which objective slots automation may turn to. */
    if (doc.slots) {
      const slots = document.createElement("div");
      slots.className = "setup-row";
      const slotName = document.createElement("label");
      slotName.textContent = doc.slots.label;
      const slotBox = document.createElement("input");
      slotBox.type = "text";
      slotBox.className = "side-text";
      slotBox.placeholder = "every slot";
      const heldSlots = held?.[doc.slots.key];
      slotBox.value = (Array.isArray(heldSlots) ? heldSlots : heldSlots?.allowed ?? []).join(", ");
      slotBox.setAttribute("aria-label", doc.slots.label);
      slotBox.addEventListener("change", () => {
        const list = slotBox.value.split(",").map((s) => s.trim()).filter(Boolean).map(Number);
        ctx.edit(doc.slots.key, list.length ? { allowed: list } : []);
      });
      slots.append(slotName, slotBox);
      edit.body.append(slots);
      if (doc.slots.note) edit.body.append(note(doc.slots.note));
    }

    /* The settings the driver can change. */
    for (const key of doc.settings ?? []) {
      const row = document.createElement("div");
      row.className = "setup-row";
      const name = document.createElement("label");
      /* The driver's own key with the set_ prefix dropped and the underscores
         opened out: recognisably the file's name, reading as words. */
      name.textContent = key.replace(/^set_/, "").replaceAll("_", " ");
      row.append(name);
      const value = document.createElement("input");
      value.type = "text";
      value.className = "side-text";
      value.placeholder = "no limit";
      const entry = held?.[key];
      value.value = Array.isArray(entry) && entry.length === 0 ? "" : (entry === undefined ? "" : JSON.stringify(entry));
      value.setAttribute("aria-label", key);
      value.addEventListener("change", () => {
        const text = value.value.trim();
        if (!text) { ctx.edit(key, []); return; }
        try { ctx.edit(key, JSON.parse(text)); } catch { ctx.edit(key, { allowed: text.split(",").map((s) => s.trim()) }); }
      });
      row.append(value);
      edit.body.append(row);
    }

    /* What the notebook prints once the document is valid: the ranges, as
       the driver read them back from what was published. */
    if (ctx.publishedNote() && standing?.source === "published") {
      edit.body.append(note("Limits are valid:", "ok"));
      edit.body.append(readout(doc.axes.map((axis) =>
        [axis.label, `${asRange(standing.document?.[axis.key])} ${axis.unit}`])));
    }
    edit.body.append(publishRow({
      label: "Save and adopt",
      published: ctx.publishedNote(),
      onPublish: async () => {
        try {
          const where = await ctx.setup.publish("limits", ctx.limits());
          const x = ctx.limits()?.[doc.measured[0]];
          await ctx.restand?.();
          ctx.settle(`${measuredLabels[0]} ${asRange(x)} · adopted`, `Adopted: ${where.path}`);
        } catch (why) {
          ctx.settle(null, `Publishing failed — ${why.message}`);
        }
        ctx.refresh();
      },
    }));
    host.append(edit.box);
    return { host };
  },
};
