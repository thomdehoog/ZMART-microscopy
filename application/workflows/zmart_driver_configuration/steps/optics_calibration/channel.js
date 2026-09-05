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
 * Two boxes. **Reference and presets**: the reference, and one preset per
 * other lens, to click on and refine; each row shows the offset it stands
 * at. **Calibration**, which appears once a preset is chosen: one card in
 * three parts -- focus (Z), X/Y, and the confirmation, where the chosen
 * set's X, Y and Z stand as three plain tiles above Save and adopt. Adopting
 * publishes the whole calibration, every preset at its current offset, in
 * the driver's own shape: the reference at zero, each target relative to it.
 */

import { cell, note, picture, press, publishRow } from "../cells.js";

const lensLabel = (lens) => (lens ? `slot ${lens.slot} · ${lens.name}` : "—");
const signed = (v, d = 2) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(d)}`);
const offsetText = (t) => `(${signed(t?.x)}, ${signed(t?.y)}, ${signed(t?.z)}) µm`;
const stateText = (preset) => ({
  default: "default (0, 0, 0)",
  published: "held, not measured here",
  measured: "measured",
}[preset.state] ?? preset.state);

/** A part of the second card: a tinted sub-box with a numbered heading, so
    the three parts -- focus, X/Y, confirmation -- read as three things at a
    glance. Returns the element to put the part's contents in. */
function part(host, number, title, prose = null) {
  const box = document.createElement("div");
  box.className = "setup-part";
  const h = document.createElement("div");
  h.className = "setup-part-title";
  h.innerHTML = `<span class="setup-part-number"></span><span></span>`;
  h.firstChild.textContent = String(number);
  h.lastChild.textContent = title;
  box.append(h);
  if (prose) {
    const p = document.createElement("p");
    p.className = "side-note";
    p.textContent = prose;
    box.append(p);
  }
  host.append(box);
  return box;
}

export default {
  id: "calibration",
  label: "Objective calibration",

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
      /* The dropdown sits on the left beside its label, and Reset, once
         there is something to reset, right beside the dropdown. */
      const row = document.createElement("div");
      row.className = "setup-row setup-reference";
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
      /* Once chosen, the reference is locked: the presets below hang from
         it. Reset clears it, and them, to choose again. */
      select.disabled = Boolean(reference);
      select.addEventListener("change", () => {
        ctx.setReference(select.value === "" ? null : Number(select.value));
        ctx.refresh();
      });
      row.append(label, select);
      if (reference) row.append(press("Reset", async () => { ctx.setReference(null); ctx.refresh(); }));
      presets.body.append(row);
    }
    /* One preset per other lens, each read as the pair it measures --
       "10x dry vs 40x dry" -- one under the other; pressing one chooses it
       for the cells below. */
    if (slots.length) {
      const list = document.createElement("div");
      list.className = "setup-sets";
      for (const slot of slots) {
        const preset = cal.presets[slot];
        const r = document.createElement("button");
        r.type = "button";
        r.className = "setup-set" + (slot === cal.current ? " chosen" : "") + (preset.state === "default" ? " default" : "");
        r.innerHTML = `<b></b><span class="setup-set-pair"></span><span class="setup-set-state"></span>`;
        r.querySelector("b").textContent = `${reference?.name ?? "reference"} vs ${bySlot(preset.target)?.name ?? `slot ${slot}`}`;
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

    /* ---- 2. the chosen preset: focus, X/Y, and the confirmation ------------ */
    if (!current) return { host };
    const target = bySlot(current.target);
    const work = cell(`Calibration — ${reference?.name ?? "reference"} vs ${target?.name ?? "target"}`);
    {
      const viewKey = (side) => `${cal.reference}-${cal.current}:${side}`;

      /* focus: the reference and the target, each its own curve */
      const focus = part(work.body, 1, "Focus (Z)",
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
        focus.append(r);
        if (view?.failed) focus.append(note(`Failed — ${view.failed}`, "bad"));
        else if (view) {
          const bracketed = view.bracketed !== false;
          const seen = view.lens;
          const wrong = seen && lens && String(seen.slot) !== String(lens.slot);
          focus.append(note(
            `${lensLabel(seen)} · ${view.pixel_um} µm/px · `
            + (bracketed ? `peak z = ${Number(view.peak_z_um).toFixed(3)} um` : "no focus peak within the stack — refocus and measure again")
            + (wrong ? ` — expected ${lensLabel(lens)}: change the lens and measure again` : ""),
            bracketed && !wrong ? "ok" : "bad"));
          if (view.diagnostic_url) focus.append(picture(view.diagnostic_url, `${side} focus curve and sharpest slice`));
        }
      }

      /* X/Y: the offset, from matching the two images pixel by pixel */
      const xy = part(work.body, 2, "X/Y", "The X/Y offset, from matching the two images pixel by pixel.");
      const ready = current.views?.reference && current.views?.target
        && !current.views.reference.failed && !current.views.target.failed;
      xy.append(press("Measure X/Y", async () => {
        try {
          ctx.holdPresetAnswer(cal.current, await ctx.setup.measure("objective_pair",
            { reference: viewKey("reference"), target: viewKey("target") }));
        } catch (why) {
          ctx.holdPresetAnswer(cal.current, { failed: why.message });
        }
        ctx.refresh();
      }, { busy: "measuring…", disabled: !ready }));
      const held = current.answer;
      if (held?.failed) xy.append(note(`Failed — ${held.failed}`, "bad"));
      else if (held) {
        const t = held.translation_um ?? {};
        xy.append(note(
          `${lensLabel(reference)} → ${lensLabel(target)} · translation XY (${signed(t.x)}, ${signed(t.y)}) um · `
          + `Z ${signed(t.z)} um · ${held.accepted ? "trusted" : "WEAK VOTE"}`, held.accepted ? "ok" : "bad"));
        if (held.why) xy.append(note(held.why, "bad"));
        if (held.diagnostic_url) xy.append(picture(held.diagnostic_url, "the two objectives overlaid, as acquired and after the correction"));
      }
    }

    /* the confirmation: this set's X, Y and Z, and adopting */
    const standing = ctx.standing();
    {
      const confirm = part(work.body, 3, "Confirmation",
        `Where the ${target?.name ?? "target"} looks relative to the ${reference?.name ?? "reference"}. `
        + "Save and adopt publishes the whole calibration, every preset at its current offset.");
      const tiles = document.createElement("div");
      tiles.className = "setup-xyz";
      const t = current.translation_um;
      for (const [axis, value] of [["X", t.x], ["Y", t.y], ["Z", t.z]]) {
        const tile = document.createElement("div");
        tile.className = "setup-xyz-tile" + (current.state === "default" ? " default" : "");
        tile.innerHTML = `<span class="setup-xyz-axis"></span><span class="setup-xyz-value"></span><span class="setup-xyz-unit">µm</span>`;
        tile.querySelector(".setup-xyz-axis").textContent = axis;
        tile.querySelector(".setup-xyz-value").textContent = signed(value);
        tiles.append(tile);
      }
      confirm.append(tiles);
      confirm.append(note(current.state === "measured" ? "Measured in this session."
        : current.state === "published" ? "As published; not measured in this session."
        : "Still the ideal of zero; measure above to replace it with what the microscope does."));
      if (standing?.source === "published" || standing?.source === "session") {
        const n = Object.keys(standing.document?.objectives ?? {}).length;
        confirm.append(note(standing.source === "session"
          ? `This session holds ${n} objective(s).` : `What stands now: ${n} objective(s) published.`));
      }
      confirm.append(publishRow({
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
    }
    host.append(work.box);
    return { host };
  },
};

const side_ = (lens) => (lens ? `${lens.name} (slot ${lens.slot})` : "lens");
