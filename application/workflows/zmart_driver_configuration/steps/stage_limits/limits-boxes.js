/**
 * Step 2's cells — Configure, then Import stage limits.
 *
 * **Configure** is the limits document itself, every field of it: the stage
 * ranges, which objective slots automation may turn to, and one line per
 * setting the driver is able to change. It is drawn from the document the
 * driver read back -- published or its default -- so whatever keys that file
 * has are the rows here, and nothing in the file is hidden from the operator
 * who is about to publish it.
 *
 * **Import stage limits** is the one thing read off the instrument: the
 * operator drives to the four corners of the safe area in the microscope's
 * own software and captures each, and the four readings become the X and Y
 * ranges above. Which drive supplies X and which Y is chosen here, because
 * an instrument may report several and only one of them moves the stage.
 * Nothing else is touched, which is what keeps a measured number and a
 * decided number apart.
 *
 * What the rows are called is the driver's (`ctx.document()` says which keys
 * are axes, which is the slot list, and which are settings); what they hold
 * is the file's.
 */

import { cell, note, press, publishRow } from "../cells.js";

/** A range as the file holds it, in words an operator can check at a glance. */
const asRange = (entry) => {
  const range = entry?.range;
  if (!Array.isArray(range) || range.length !== 2) return "not set";
  const end = (v) => (v === null || v === undefined ? "open" : v);
  return `${end(range[0])} … ${end(range[1])}`;
};

/** What kind of limit an entry is: a numeric range, a list of allowed
    values, or none. An open end of a range is `null` in the file. */
const kindOf = (entry) => {
  if (!entry || (Array.isArray(entry) && entry.length === 0)) return "none";
  if (entry.range) return "range";
  if (entry.allowed) return "allowed";
  return "none";
};

/** An end of a range as its field shows it: blank when open. */
const endText = (entry, end) => {
  const v = entry?.range?.[end];
  return v === null || v === undefined ? "" : String(v);
};

/** Allowed values as one field shows them: comma-separated. */
const allowedText = (entry) => (entry?.allowed ?? []).join(", ");

/** Comma-separated text back into a list, numbers as numbers. */
const allowedFrom = (text) => text.split(",").map((t) => t.trim()).filter(Boolean)
  .map((t) => (Number.isFinite(Number(t)) && t !== "" ? Number(t) : t));

export default {
  id: "limits",
  label: "Define limits",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("This driver publishes no limits. Walk on."));
      host.append(box);
      return { host };
    }
    const doc = ctx.document();
    const held = ctx.limits();
    if (!doc || !held) {
      const { box, body } = cell("Configure", "Connect first: the driver says what its limits file holds.");
      body.append(note("Waiting for the driver."));
      host.append(box);
      return { host };
    }
    const axes = new Map(doc.axes.map((a) => [a.key, a]));
    const measured = doc.measured ?? [];
    const measuredLabels = measured.map((k) => axes.get(k)?.label ?? k);

    /* ---- Configure: every field of the file ------------------------------ */
    const edit = cell("Configure",
      "Review the limits. Ranges include both endpoints. Ticked, a limit is applied; unticked, it is reviewed and unrestricted.");
    const standing = ctx.standing();
    if (standing) edit.body.append(note(`Starting from the ${standing.source === "published" ? "published" : "default"} limits.`));

    const required = new Set(doc.required ?? []);

    /* One row per key: a tick saying whether this limit is applied, the
       name, and the fields. Unticked writes `[]` to the file -- reviewed,
       and no limit enforced -- which is a different thing from never having
       looked, so the row stays visible either way. A key the driver cannot
       leave open (the stage ranges) shows its tick set and fixed. */
    const row = (key, label, fields, { applied, onTick }) => {
      const r = document.createElement("div");
      r.className = "setup-row setup-limit";
      const tick = document.createElement("input");
      tick.type = "checkbox";
      tick.checked = applied || required.has(key);
      tick.disabled = required.has(key);
      if (required.has(key)) tick.title = "always enforced";
      tick.setAttribute("aria-label", `apply a limit to ${label}`);
      tick.addEventListener("change", () => onTick(tick.checked));
      const name = document.createElement("label");
      name.textContent = label;
      for (const f of fields) f.disabled = !tick.checked;
      r.append(tick, name, ...fields);
      edit.body.append(r);
      return { tick, fields };
    };
    const numberField = (key, end, label, { open = false } = {}) => {
      const box = document.createElement("input");
      box.type = "number"; box.className = "setup-field setup-number";
      box.value = endText(held[key], end);
      box.placeholder = open ? (end === 0 ? "no minimum" : "no maximum") : "";
      box.setAttribute("aria-label", label);
      box.addEventListener("change", () => {
        const range = [...(held[key]?.range ?? [null, null])];
        range[end] = box.value === "" ? null : Number(box.value);
        ctx.edit(key, { range });
      });
      return box;
    };
    const allowedField = (key, label, placeholder) => {
      const box = document.createElement("input");
      box.type = "text"; box.className = "setup-field";
      box.placeholder = placeholder;
      box.value = allowedText(held[key]);
      box.setAttribute("aria-label", `${label}, allowed values`);
      box.addEventListener("change", () => ctx.edit(key, { allowed: allowedFrom(box.value) }));
      return box;
    };
    /* A setting is fenced one of two ways, and the operator says which: a
       range -- either end may be left open, so "at most 10" is a range with
       no minimum -- or a list of the values that are allowed, which is how a
       choice such as the objective is fenced. Changing the kind starts the
       fields empty; the file holds one kind at a time. */
    const kindChooser = (key, label, current) => {
      const select = document.createElement("select");
      select.className = "setup-kind";
      select.setAttribute("aria-label", `how ${label} is limited`);
      for (const [value, words] of [["range", "range"], ["allowed", "allowed values"]]) {
        const o = document.createElement("option");
        o.value = value; o.textContent = words; o.selected = value === current;
        select.append(o);
      }
      select.addEventListener("change", () => {
        ctx.edit(key, select.value === "range" ? { range: [null, null] } : { allowed: [] });
        ctx.refresh();
      });
      return select;
    };
    const fieldsFor = (key, label, kind, { open }) => (kind === "allowed"
      ? [allowedField(key, label, "values, e.g. 0, 2 or a, b")]
      : [numberField(key, 0, `${label} minimum`, { open }), numberField(key, 1, `${label} maximum`, { open })]);
    const untick = (fields, key, kind) => (on) => {
      for (const f of fields) { f.disabled = !on; if (!on) f.value = ""; }
      if (!on) ctx.edit(key, []);
      else { ctx.edit(key, kind === "allowed" ? { allowed: [] } : { range: [null, null] }); fields[0]?.focus(); }
    };

    /* The rows are the file's keys, in the file's order, each drawn the way
       the driver says that key is: an axis, the slot list, a setting -- and a
       key the driver did not describe still gets a row, as itself. */
    for (const key of Object.keys(held)) {
      if (key === "published_at") continue;
      const isAxis = axes.has(key);
      const isSlots = Boolean(doc.slots) && key === doc.slots.key;
      const label = isAxis ? `${axes.get(key).label} (${axes.get(key).unit})`
        : isSlots ? doc.slots.label
        : (doc.settings ?? []).includes(key) ? key.replace(/^set_/, "").replaceAll("_", " ") : key;
      const applied = kindOf(held[key]) !== "none";
      /* A stage range is a range, both ends closed; the slot list is a list;
         any other setting may be either, and says which. */
      const kind = isAxis ? "range" : isSlots ? "allowed" : (applied ? kindOf(held[key]) : "range");
      const fields = fieldsFor(key, label, kind, { open: !isAxis });
      const before = (isAxis || isSlots) ? [] : [kindChooser(key, label, kind)];
      row(key, label, [...before, ...fields], { applied, onTick: untick(fields, key, kind) });
      if (isAxis && axes.get(key).note) edit.body.append(note(axes.get(key).note));
      if (isSlots && doc.slots.note) edit.body.append(note(doc.slots.note));
    }
    /* Both boxes end in Save and adopt, and both publish the same document:
       the limits as they stand above, with whatever the import filled in. */
    const adopt = async () => {
      try {
        const where = await ctx.setup.publish("limits", ctx.limits());
        const first = measured[0] ?? doc.axes[0]?.key;
        ctx.settle(`${axes.get(first)?.label ?? first} ${asRange(ctx.limits()[first])} · adopted`,
          `Adopted: ${where.snapshot?.split("/").pop() ?? where.path}`);
      } catch (why) {
        ctx.settle(null, `Adopting failed — ${why.message}`);
      }
      ctx.refresh();
    };
    edit.body.append(publishRow({ label: "Save and adopt", published: ctx.publishedNote(), onPublish: adopt }));
    host.append(edit.box);

    /* ---- Import stage limits: the four corners, read from the drives ------ */
    const held2 = ctx.held() ?? {};
    const corners = held2.corners ?? {};
    const here = ctx.here();
    const names = Object.keys(here?.actuators ?? {});
    const guess = (axis) => names.find((n) => n.toLowerCase().startsWith(axis)) ?? names[0] ?? null;
    const chosen = { x: held2.actuators?.x ?? guess("x"), y: held2.actuators?.y ?? guess("y") };
    const [xKey, yKey] = measured;

    const imp = cell("Import X/Y stage limits",
      "Drive the stage to each corner of the safe area in the microscope's own software and capture it "
      + "there. Only X and Y are imported, from the drives chosen below; the four captures become the "
      + "X and Y ranges above.");
    if (names.length) {
      for (const axis of ["x", "y"]) {
        const r = document.createElement("div");
        r.className = "setup-row";
        const label = document.createElement("label");
        label.textContent = `${axis.toUpperCase()} from`;
        const select = document.createElement("select");
        select.className = "setup-field";
        for (const n of names) {
          const o = document.createElement("option");
          o.value = n; o.textContent = n; o.selected = n === chosen[axis];
          select.append(o);
        }
        select.addEventListener("change", () => {
          ctx.hold({ ...held2, actuators: { ...chosen, [axis]: select.value }, corners: {} });
          ctx.refresh();
        });
        r.append(label, select);
        imp.body.append(r);
      }
    } else {
      imp.body.append(note("The driver reports no drives to read; connect first.", "bad"));
    }
    const CORNERS = [["top_left", "Top left"], ["top_right", "Top right"],
                     ["bottom_left", "Bottom left"], ["bottom_right", "Bottom right"]];
    for (const [key, label] of CORNERS) {
      const r = document.createElement("div");
      r.className = "setup-row";
      const name = document.createElement("label");
      name.textContent = label;
      const said = document.createElement("span");
      said.className = "setup-note";
      const got = corners[key];
      said.textContent = got ? `x ${Number(got.x).toFixed(1)} · y ${Number(got.y).toFixed(1)} µm` : "not captured";
      r.append(name, said, press(got ? "Update" : "Import", async () => {
        try {
          const now = await ctx.setup.where();
          const a = now.actuators ?? {};
          const x = a[chosen.x]?.value ?? now.x_um;
          const y = a[chosen.y]?.value ?? now.y_um;
          const next = { ...corners, [key]: { x: Number(x), y: Number(y) } };
          ctx.hold({ ...held2, actuators: chosen, corners: next });
          if (CORNERS.every(([k]) => next[k])) {
            const xs = CORNERS.map(([k]) => next[k].x), ys = CORNERS.map(([k]) => next[k].y);
            ctx.edit(xKey, { range: [Math.min(...xs), Math.max(...xs)] });
            ctx.edit(yKey, { range: [Math.min(...ys), Math.max(...ys)] });
          }
        } catch (why) {
          ctx.hold({ ...held2, actuators: chosen, corners, failed: why.message });
        }
        ctx.refresh();
      }, { busy: "reading…", disabled: !names.length }));
      imp.body.append(r);
    }
    if (held2.failed) imp.body.append(note(`Could not read the drives — ${held2.failed}`, "bad"));
    if (CORNERS.every(([k]) => corners[k])) {
      imp.body.append(note(
        `Imported: ${axes.get(xKey)?.label ?? xKey} ${asRange(held[xKey])} · `
        + `${axes.get(yKey)?.label ?? yKey} ${asRange(held[yKey])} — replaced above.`, "ok"));
    }
    imp.body.append(publishRow({ label: "Save and adopt", published: ctx.publishedNote(), onPublish: adopt,
      disabled: !CORNERS.every(([k]) => corners[k]) }));
    host.append(imp.box);
    return { host };
  },
};
