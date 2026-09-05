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
  return `${range[0]} … ${range[1]}`;
};

/** A setting's constraint as text for its field: empty for unrestricted. */
const asText = (entry) => {
  if (entry === undefined || entry === null) return "";
  if (Array.isArray(entry) && entry.length === 0) return "";
  if (Array.isArray(entry)) return entry.join(", ");
  if (entry.allowed) return entry.allowed.join(", ");
  if (entry.range) return `${entry.range[0]} … ${entry.range[1]}`;
  return JSON.stringify(entry);
};

/** Text typed into a setting's field, back into the file's shape. */
const fromText = (text, kind) => {
  const t = text.trim();
  if (!t) return [];
  const range = t.match(/^\s*(-?[\d.]+)\s*(?:…|\.\.\.?|to|-)\s*(-?[\d.]+)\s*$/);
  if (range && kind !== "allowed") return { range: [Number(range[1]), Number(range[2])] };
  const parts = t.split(",").map((s) => s.trim()).filter(Boolean);
  return { allowed: parts.map((s) => (Number.isFinite(Number(s)) ? Number(s) : s)) };
};

export default {
  id: "limits",
  label: "Set up limits",

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
      "Review the limits. Ranges include both endpoints; an empty setting means reviewed and unrestricted.");
    const standing = ctx.standing();
    if (standing) edit.body.append(note(`Starting from the ${standing.source === "published" ? "published" : "default"} limits.`));

    const row = (label, ...fields) => {
      const r = document.createElement("div");
      r.className = "setup-row";
      const name = document.createElement("label");
      name.textContent = label;
      r.append(name, ...fields);
      edit.body.append(r);
    };
    const numberField = (key, end, label) => {
      const box = document.createElement("input");
      box.type = "number"; box.className = "side-number";
      box.value = held[key]?.range?.[end] ?? "";
      box.setAttribute("aria-label", label);
      box.addEventListener("change", () => {
        const range = [...(held[key]?.range ?? [null, null])];
        range[end] = box.value === "" ? null : Number(box.value);
        ctx.edit(key, { range });
      });
      return box;
    };
    const textField = (key, label, placeholder, kind) => {
      const box = document.createElement("input");
      box.type = "text"; box.className = "side-text";
      box.placeholder = placeholder;
      box.value = asText(held[key]);
      box.setAttribute("aria-label", label);
      box.addEventListener("change", () => ctx.edit(key, fromText(box.value, kind)));
      return box;
    };

    /* The rows are the file's keys, in the file's order, each drawn the way
       the driver says that key is: an axis, the slot list, a setting -- and a
       key the driver did not describe still gets a row, as itself. */
    for (const key of Object.keys(held)) {
      if (axes.has(key)) {
        const axis = axes.get(key);
        row(`${axis.label} (${axis.unit})`,
          numberField(key, 0, `${axis.label} lowest`), numberField(key, 1, `${axis.label} highest`));
        if (axis.note) edit.body.append(note(axis.note));
      } else if (doc.slots && key === doc.slots.key) {
        row(doc.slots.label, textField(key, doc.slots.label, "every slot", "allowed"));
        if (doc.slots.note) edit.body.append(note(doc.slots.note));
      } else if ((doc.settings ?? []).includes(key)) {
        row(key.replace(/^set_/, "").replaceAll("_", " "), textField(key, key, "no limit"));
      } else if (key !== "published_at") {
        row(key, textField(key, key, ""));
      }
    }
    edit.body.append(publishRow({
      label: "Save and adopt",
      published: ctx.publishedNote(),
      onPublish: async () => {
        try {
          const where = await ctx.setup.publish("limits", ctx.limits());
          const first = measured[0] ?? doc.axes[0]?.key;
          ctx.settle(`${axes.get(first)?.label ?? first} ${asRange(ctx.limits()[first])} · adopted`,
            `Adopted: ${where.snapshot?.split("/").pop() ?? where.path}`);
        } catch (why) {
          ctx.settle(null, `Adopting failed — ${why.message}`);
        }
        ctx.refresh();
      },
    }));
    host.append(edit.box);

    /* ---- Import stage limits: the four corners, read from the drives ------ */
    const held2 = ctx.held() ?? {};
    const corners = held2.corners ?? {};
    const here = ctx.here();
    const names = Object.keys(here?.actuators ?? {});
    const guess = (axis) => names.find((n) => n.toLowerCase().startsWith(axis)) ?? names[0] ?? null;
    const chosen = { x: held2.actuators?.x ?? guess("x"), y: held2.actuators?.y ?? guess("y") };
    const [xKey, yKey] = measured;

    const imp = cell("Import stage limits",
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
        select.className = "side-text";
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
      r.append(name, said, press("Capture", async () => {
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
        + `${axes.get(yKey)?.label ?? yKey} ${asRange(held[yKey])} — replaced above. Save and adopt when the rest is reviewed.`, "ok"));
    }
    host.append(imp.box);
    return { host };
  },
};
