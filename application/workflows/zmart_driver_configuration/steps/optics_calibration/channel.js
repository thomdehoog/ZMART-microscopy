/**
 * Step 4's cells -- the reference objective, its presets, and the measures
 * of the one chosen.
 *
 * Ideally a microscope is parcentric and parfocal: change the lens and the
 * same spot stays centred and in focus, so every objective's offset from
 * every other is zero. The unfortunate reality is that this is not always
 * the case, so the offsets have to be measured. This step is built on that
 * ideal. Choose the reference objective, and every other lens on the turret
 * gets a preset at once, each starting at the ideal offset of (0, 0, 0).
 * Choose a preset and measure it to replace that ideal with what the
 * microscope actually does. Save and adopt publishes all of them, measured
 * or not, so the driver always has a complete calibration to stand on.
 *
 * The reference is the anchor every offset hangs from, so changing it
 * discards every preset: their offsets were relative to a lens that is no
 * longer the reference, and they start again from zero.
 *
 * Four boxes. **Reference and presets**: the reference, and one preset per
 * other lens. **Focus (Z)** and **X/Y**: the measures of the chosen preset,
 * each showing its own result the way the notebook cell does. **Summary**:
 * every preset's numbers, and Save and adopt, which publishes them in the
 * driver's own calibration shape -- the reference at zero, each target
 * relative to it.
 */

import { cell, note, picture, press, publishRow } from "../cells.js";

const lensLabel = (lens) => (lens ? `slot ${lens.slot} · ${lens.name}` : "—");
const signed = (v, d = 2) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(d)}`);
const offsetText = (t) => `(${signed(t?.x)}, ${signed(t?.y)}, ${signed(t?.z)}) µm`;
const stateText = (preset) => ({
  default: "default (0, 0, 0)",
  published: "published, not measured here",
  measured: "measured",
}[preset.state] ?? preset.state);

export default {
  id: "calibration",
  label: "Optics calibration",

  mount(host, ctx) {
    if (!ctx.supported()) {
      const { box, body } = cell("Not on this microscope");
      body.append(note("This driver has no objective pair to calibrate. Walk on."));
      host.append(box);
      return { host };
    }
    const lenses = ctx.objectives();
    const cal = ctx.calibration();
    const bySlot = (slot) => lenses.find((l) => String(l.slot) === String(slot)) ?? null;
    const reference = cal.reference === null ? null : bySlot(cal.reference);
    const slots = Object.keys(cal.presets);
    const current = cal.current !== null && cal.presets[cal.current] ? cal.presets[cal.current] : null;

    /* ---- 1. the reference, and the presets it gives ---------------------- */
    const presets = cell("Reference and presets",
      "Every offset is measured against one reference objective. Choosing it gives one preset per "
      + "other lens, each at the ideal offset of zero; choosing another reference starts them over.");
    if (!lenses.length) {
      presets.body.append(note("The driver lists no objectives; connect first.", "bad"));
    } else {
      const row = document.createElement("div");
      row.className = "setup-row";
      const label = document.createElement("label");
      label.textContent = "Reference objective";
      const select = document.createElement("select");
      select.className = "setup-field";
      select.setAttribute("aria-label", "reference objective");
      const none = document.createElement("option");
      none.value = ""; none.textContent = "choose…"; none.selected = !reference;
      select.append(none);
      for (const l of lenses) {
        const o = document.createElement("option");
        o.value = String(l.slot); o.textContent = lensLabel(l); o.selected = reference?.slot === l.slot;
        select.append(o);
      }
      select.addEventListener("change", () => {
        ctx.setReference(select.value === "" ? null : Number(select.value));
        ctx.refresh();
      });
      row.append(label, select);
      presets.body.append(row);
    }
    /* One preset per other lens; pressing one chooses it for the cells below. */
    if (slots.length) {
      const list = document.createElement("div");
      list.className = "setup-sets";
      for (const slot of slots) {
        const preset = cal.presets[slot];
        const r = document.createElement("button");
        r.type = "button";
        r.className = "setup-set" + (slot === cal.current ? " chosen" : "") + (preset.state === "default" ? " default" : "");
        r.innerHTML = `<b></b><span class="setup-set-pair"></span><span class="setup-set-state"></span>`;
        r.querySelector("b").textContent = lensLabel(bySlot(preset.target));
        r.querySelector(".setup-set-pair").textContent = offsetText(preset.translation_um);
        r.querySelector(".setup-set-state").textContent = stateText(preset);
        r.addEventListener("click", () => { ctx.choosePreset(slot === cal.current ? null : slot); ctx.refresh(); });
        list.append(r);
      }
      presets.body.append(list);
    } else if (reference) {
      presets.body.append(note("The turret has no other lens to measure against the reference.", "bad"));
    } else if (lenses.length) {
      presets.body.append(note("Choose the reference objective to see its presets."));
    }
    host.append(presets.box);

    if (!current) {
      const { box, body } = cell("Focus (Z) and X/Y");
      body.append(note(slots.length ? "Choose a preset above to measure it." : "Choose the reference first."));
      host.append(box);
    } else {
      const target = bySlot(current.target);
      const viewKey = (side) => `${cal.reference}-${cal.current}:${side}`;

      /* ---- 2. focus: the reference and the target, each its own curve ------ */
      const focus = cell(`Focus (Z) — ${target?.name ?? "target"}`,
        `With the ${side_(reference)} in and the field in focus, measure; switch only to the `
        + `${side_(target)}, refocus without moving X/Y, and measure again.`);
      for (const [side, lens] of [["reference", reference], ["target", target]]) {
        const view = current.views?.[side];
        const r = document.createElement("div");
        r.className = "setup-row";
        r.style.justifyContent = "flex-start";
        r.append(press(`Measure ${side} (${lens?.name ?? side})`, async () => {
          try {
            ctx.holdPresetView(cal.current, side,
              await ctx.setup.measure("lens", { name: viewKey(side), orientation: ctx.orientation() }));
          } catch (why) {
            ctx.holdPresetView(cal.current, side, { failed: why.message });
          }
          ctx.refresh();
        }, { busy: "measuring…" }));
        focus.body.append(r);
        if (view?.failed) focus.body.append(note(`Failed — ${view.failed}`, "bad"));
        else if (view) {
          const bracketed = view.bracketed !== false;
          const seen = view.lens;
          const wrong = seen && lens && String(seen.slot) !== String(lens.slot);
          focus.body.append(note(
            `${lensLabel(seen)} · ${view.pixel_um} µm/px · `
            + (bracketed ? `peak z = ${Number(view.peak_z_um).toFixed(3)} um` : "no focus peak within the stack — refocus and measure again")
            + (wrong ? ` — expected ${lensLabel(lens)}: change the lens and measure again` : ""),
            bracketed && !wrong ? "ok" : "bad"));
          if (view.diagnostic_url) focus.body.append(picture(view.diagnostic_url, `${side} focus curve and sharpest slice`));
        }
      }
      host.append(focus.box);

      /* ---- 3. X/Y ------------------------------------------------------------- */
      const xy = cell(`X/Y — ${target?.name ?? "target"}`, "The X/Y offset, from matching the two images pixel by pixel.");
      const ready = current.views?.reference && current.views?.target
        && !current.views.reference.failed && !current.views.target.failed;
      xy.body.append(press("Measure X/Y", async () => {
        try {
          ctx.holdPresetAnswer(cal.current, await ctx.setup.measure("objective_pair",
            { reference: viewKey("reference"), target: viewKey("target") }));
        } catch (why) {
          ctx.holdPresetAnswer(cal.current, { failed: why.message });
        }
        ctx.refresh();
      }, { busy: "measuring…", disabled: !ready }));
      const held = current.answer;
      if (held?.failed) xy.body.append(note(`Failed — ${held.failed}`, "bad"));
      else if (held) {
        const t = held.translation_um ?? {};
        xy.body.append(note(
          `${lensLabel(reference)} → ${lensLabel(target)} · translation XY (${signed(t.x)}, ${signed(t.y)}) um · `
          + `Z ${signed(t.z)} um · ${held.accepted ? "trusted" : "WEAK VOTE"}`, held.accepted ? "ok" : "bad"));
        if (held.why) xy.body.append(note(held.why, "bad"));
        if (held.diagnostic_url) xy.body.append(picture(held.diagnostic_url, "the two objectives overlaid, as acquired and after the correction"));
      }
      host.append(xy.box);
    }

    /* ---- 4. the summary, and adopting ---------------------------------------- */
    const summary = cell("Summary",
      "Every preset against the reference. Save and adopt publishes them all, measured or still at "
      + "zero, as the driver's calibration: the reference at zero, each target relative to it.");
    const standing = ctx.standing();
    if (standing?.source === "published") {
      const n = Object.keys(standing.document?.objectives ?? {}).length;
      summary.body.append(note(`What stands now: ${n} objective(s) published.`));
    }
    if (slots.length) {
      const table = document.createElement("table");
      table.className = "setup-table";
      table.innerHTML = "<thead><tr><th>Objective</th><th>X</th><th>Y</th><th>Z</th><th>State</th></tr></thead><tbody></tbody>";
      const body = table.querySelector("tbody");
      const rows = [[reference, { translation_um: { x: 0, y: 0, z: 0 }, state: "reference" }]]
        .concat(slots.map((slot) => [bySlot(cal.presets[slot].target), cal.presets[slot]]));
      for (const [lens, preset] of rows) {
        const t = preset.translation_um;
        const tr = document.createElement("tr");
        if (preset.state === "default") tr.className = "default";
        for (const text of [lensLabel(lens), signed(t.x), signed(t.y), signed(t.z),
          preset.state === "reference" ? "reference" : stateText(preset)]) {
          const td = document.createElement("td"); td.textContent = text; tr.append(td);
        }
        body.append(tr);
      }
      summary.body.append(table);
    } else {
      summary.body.append(note("No presets yet."));
    }
    summary.body.append(publishRow({
      label: "Save and adopt",
      published: ctx.publishedNote(),
      onPublish: async () => {
        if (!reference) { ctx.settle(null, "Choose the reference objective first."); ctx.refresh(); return; }
        const objectives = {
          [String(reference.slot)]: { name: reference.name, translation_um: [0, 0, 0] },
        };
        for (const slot of slots) {
          const preset = cal.presets[slot];
          const t = preset.translation_um;
          const lens = bySlot(preset.target);
          objectives[slot] = { name: lens?.name ?? `slot ${slot}`, translation_um: [t.x, t.y, t.z ?? 0] };
        }
        const schema = standing?.document?.schema_version;
        const document_ = schema !== undefined ? { schema_version: schema, objectives } : { objectives };
        const measured = slots.filter((slot) => cal.presets[slot].state === "measured").length;
        try {
          const where = await ctx.setup.publish("calibration", document_);
          ctx.settle(`${reference.name} reference · ${slots.length} preset(s), ${measured} measured · adopted`,
            `Adopted: ${where.snapshot?.split("/").pop() ?? where.path}`);
        } catch (why) { ctx.settle(null, `Adopting failed — ${why.message}`); }
        ctx.refresh();
      },
    }));
    host.append(summary.box);
    return { host };
  },
};

const side_ = (lens) => (lens ? `${lens.name} (slot ${lens.slot})` : "lens");
