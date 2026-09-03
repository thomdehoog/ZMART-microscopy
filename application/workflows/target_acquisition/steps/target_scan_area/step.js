/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets, in two
 * boxes. The first holds what every run needs: the settings the targets
 * are imaged with, how many targets to sample per tileset, and the step's
 * press, which draws a systematic uniform random sample of what the gates
 * let through and places scan areas over it by the optimisation in
 * `scan-areas.js`. The second, Advanced, holds the levers the optimisation
 * runs under, with their defaults: a margin of one object's size round
 * each, and where two areas meet, an overlap of at least a fifth and at
 * most three tenths. The scan areas are the plan; acquiring them is the
 * step after.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

export const targetScanArea = {
  id: "select",
  title: "Target scan area",
  why: "Import the settings the targets are imaged with, then place scan areas over a sample of the gated targets.",
  btn: "Place scan areas",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};

/**
 * The step's channel.
 *
 * `ctx` carries `recordingSlot(host, opts)`, the page's slot plumbing;
 * `rules()` and `setRule(key, value)`, the levers as `scan-areas.js` reads
 * them plus `objectsMin` and `objectsMax`; `restricted()`, the sample;
 * `tiles()`, the scan areas placed; `plan()`, what the last placing came
 * to; `reset()`, forget sample and areas; `showTiles(on)`, `tilesShown()`,
 * `alpha()`, `setAlpha(a)`; and `changed()`.
 */
export const selectionPanel = {
  id: "select",
  label: "Target scan area",
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "analysis-side";
    const rules = ctx.rules();

    /* A row: the word at the left, the control at the right. A switchable
       row has a checkbox before its number; off, the number is greyed and
       the lever is null. */
    const row = (text, control, id) => {
      const line = document.createElement("div");
      line.className = "gate-draw";
      const label = document.createElement("label");
      label.textContent = text;
      if (id) label.htmlFor = id;
      line.append(label, control);
      return line;
    };
    const number = (id, value, { min = 0, max = null, step = 1 } = {}, take) => {
      const input = document.createElement("input");
      input.type = "number"; input.min = String(min); input.step = String(step);
      if (max != null) input.max = String(max);
      input.id = id;
      input.value = String(value);
      input.addEventListener("input", () => take(Number(input.value)));
      return input;
    };
    const switched = (text, id, value, { min = 0, max = null, step = 1, scale = 1, resting = 10 } = {}, take) => {
      const on = value != null;
      const box = document.createElement("input");
      box.type = "checkbox"; box.id = `${id}-on`; box.checked = on;
      const input = number(id, on ? Math.round(value * scale) : resting, { min, max, step },
        (v) => take(box.checked ? v / scale : null));
      input.disabled = !on;
      box.addEventListener("change", () => {
        input.disabled = !box.checked;
        take(box.checked ? Number(input.value) / scale : null);
      });
      const pair = document.createElement("span");
      pair.className = "switched";
      pair.append(box, input);
      return row(text, pair, id);
    };
    const lever = (key) => (v) => { ctx.setRule(key, v); ctx.changed?.(); };

    /* The step's own press, at the end of the simple box. */
    const act = document.createElement("div");
    act.className = "select-action side-act";

    /* 1. The simple box: the settings, drawn by the recording slot, with
       the targets per tileset and the press seated under them -- again
       after every import, since the slot redraws itself. */
    const recording = document.createElement("div");
    recording.id = "target-type";
    const simple = document.createElement("div");
    simple.className = "tile-controls";
    const alpha = document.createElement("input");
    alpha.type = "range"; alpha.min = "10"; alpha.max = "100"; alpha.step = "5";
    alpha.id = "tiles-alpha";
    alpha.value = String(Math.round(ctx.alpha() * 100));
    alpha.addEventListener("input", () => { ctx.setAlpha(Number(alpha.value) / 100); ctx.changed?.(); });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "ghost tiny";
    reset.id = "reset-tiles";
    reset.textContent = "Reset";
    const hide = document.createElement("button");
    hide.type = "button";
    hide.className = "ghost tiny";
    hide.id = "hide-tiles";
    const placeLine = document.createElement("div");
    placeLine.className = "side-act press-line";
    const placeSpace = document.createElement("span");
    placeSpace.className = "spacer";
    placeLine.append(act, placeSpace, reset, hide);
    const notes = document.createElement("div");
    notes.className = "side-note";
    notes.id = "tiles-notes";
    simple.append(
      switched("Targets per tileset", "gate-max", rules.objectsMax, { min: 1, resting: 50 }, lever("objectsMax")),
      row("Opacity", alpha, "tiles-alpha"),
      placeLine,
      notes,
    );

    /* 2. Advanced: the levers the optimisation runs under. */
    const advanced = sideGroup("Advanced");
    const prefer = document.createElement("select");
    prefer.id = "prefer";
    for (const [value, text] of [["coverage", "Cover every sampled target"], ["areas", "Hold the maximum of areas"]]) {
      const option = document.createElement("option");
      option.value = value; option.textContent = text;
      prefer.append(option);
    }
    prefer.value = rules.prefer;
    prefer.addEventListener("change", () => lever("prefer")(prefer.value));
    const join = document.createElement("input");
    join.type = "checkbox"; join.id = "join-scan"; join.checked = !!rules.join;
    join.addEventListener("change", () => lever("join")(join.checked));
    advanced.body.append(
      row("Margin round an object (% of its size)", number("tiles-margin", Math.round(rules.margin * 100), { min: 0, step: 10 },
        (v) => lever("margin")(Math.max(0, v) / 100)), "tiles-margin"),
      switched("Min overlap where areas meet (%)", "overlap-min", rules.overlapMin, { min: 0, max: 90, step: 5, scale: 100, resting: 20 }, lever("overlapMin")),
      switched("Max overlap (%)", "tiles-overlap", rules.overlapMax, { min: 0, max: 100, step: 5, scale: 100, resting: 30 }, lever("overlapMax")),
      switched("Min targets per tileset", "objects-min", rules.objectsMin, { min: 1 }, lever("objectsMin")),
      switched("Min scan areas", "areas-min", rules.areasMin, { min: 1 }, lever("areasMin")),
      switched("Max scan areas", "areas-max", rules.areasMax, { min: 1, resting: 50 }, lever("areasMax")),
      row("Join into one scan", join, "join-scan"),
      row("When both cannot hold", prefer, "prefer"),
    );

    const say = () => {
      const n = ctx.tiles().length;
      const sampled = ctx.restricted().size;
      const plan = ctx.plan();
      reset.disabled = sampled === 0 && n === 0;
      hide.disabled = n === 0;
      hide.textContent = ctx.tilesShown() ? "Hide" : "Show";
      /* What the press came to is the step's own word beside it; only what
         could not be honoured is said here. */
      notes.textContent = (plan?.notes ?? []).join(" · ");
    };
    reset.addEventListener("click", () => { ctx.reset(); say(); ctx.changed?.(); });
    hide.addEventListener("click", () => { ctx.showTiles(!ctx.tilesShown()); say(); });

    side.append(recording, advanced.group);
    host.append(side);

    const seat = () => recording.querySelector(".side-group-body")?.append(simple);
    ctx.recordingSlot(recording, {
      label: "Place scan areas", key: "targetType",
      unnamed: true,
      takes: "Import target acquisition settings",
      retakes: "Update",
      changed: () => { seat(); ctx.changed?.(); },
    });
    seat();
    say();
    return { redraw: () => { seat(); say(); } };
  },
};
