/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets, in two
 * boxes. Sample targets: what the gates let through is drawn under a
 * per-tileset ceiling by the step's press, Restrict -- a systematic
 * uniform random sample. Place scan areas: the settings the targets are
 * imaged with are imported, and scan areas are placed over the sampled
 * targets by the optimisation in `scan-areas.js`, under the levers set
 * here. The scan areas are the plan; acquiring them is the step after.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

export const targetScanArea = {
  id: "select",
  title: "Target scan area",
  why: "Sample the gated targets to so many per tileset, then import the settings and place scan areas over the sample.",
  btn: "Restrict",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};

/**
 * The step's channel.
 *
 * `ctx` carries `recordingSlot(host, opts)`, the page's slot plumbing;
 * `cap()` and `setCap(n)`, the per-tileset ceiling; `restricted()`, the
 * ids the ceiling kept, and `reset()`, forget them; `rules()` and
 * `setRule(key, value)`, the placing levers as `scan-areas.js` reads them
 * plus `objectsMin`; `tiles()`, the scan areas placed, `plan()`, what the
 * last placing came to, `placeTiles()`, `resetTiles()`, `showTiles(on)`,
 * `tilesShown()`, `alpha()`, `setAlpha(a)`; and `changed()`.
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

    /* The step's own press, beside the ceiling it applies. */
    const act = document.createElement("div");
    act.className = "select-action side-act";

    /* 1. Sample targets. */
    const sample = sideGroup("Sample targets");
    const maxN = number("gate-max", ctx.cap(), { min: 1 }, (v) => { ctx.setCap(Math.max(1, Math.round(v || 0))); ctx.changed?.(); });
    const resetSample = document.createElement("button");
    resetSample.type = "button";
    resetSample.className = "ghost tiny";
    resetSample.id = "reset-restriction";
    resetSample.textContent = "Reset";
    resetSample.addEventListener("click", () => { ctx.reset(); ctx.changed?.(); });
    const sampleLine = document.createElement("div");
    sampleLine.className = "side-act press-line";
    const sampleSpace = document.createElement("span");
    sampleSpace.className = "spacer";
    sampleLine.append(act, sampleSpace, resetSample);
    sample.body.append(
      switched("Min objects per tileset", "objects-min", rules.objectsMin, { min: 1 }, (v) => ctx.setRule("objectsMin", v)),
      row("Max objects per tileset", maxN, "gate-max"),
      sampleLine,
    );

    /* 2. Place scan areas: the settings first -- the recording slot draws
       this box, and the rows under them are seated into it, again after
       every import, since the slot redraws itself. */
    const recording = document.createElement("div");
    recording.id = "target-type";
    const controls = document.createElement("div");
    controls.className = "tile-controls";
    const alpha = document.createElement("input");
    alpha.type = "range"; alpha.min = "10"; alpha.max = "100"; alpha.step = "5";
    alpha.id = "tiles-alpha";
    alpha.value = String(Math.round(ctx.alpha() * 100));
    alpha.addEventListener("input", () => { ctx.setAlpha(Number(alpha.value) / 100); ctx.changed?.(); });
    const prefer = document.createElement("select");
    prefer.id = "prefer";
    for (const [value, text] of [["coverage", "Cover every sampled target"], ["areas", "Hold the maximum of areas"]]) {
      const option = document.createElement("option");
      option.value = value; option.textContent = text;
      prefer.append(option);
    }
    prefer.value = rules.prefer;
    prefer.addEventListener("change", () => ctx.setRule("prefer", prefer.value));
    const join = document.createElement("input");
    join.type = "checkbox"; join.id = "join-scan"; join.checked = !!rules.join;
    join.addEventListener("change", () => ctx.setRule("join", join.checked));

    const place = document.createElement("button");
    place.type = "button";
    place.className = "run";
    place.id = "add-tiles";
    place.textContent = "Place scan areas";
    const laid = document.createElement("span");
    laid.className = "action-hint";
    laid.id = "tiles-laid";
    const resetTiles = document.createElement("button");
    resetTiles.type = "button";
    resetTiles.className = "ghost tiny";
    resetTiles.id = "reset-tiles";
    resetTiles.textContent = "Reset";
    const hide = document.createElement("button");
    hide.type = "button";
    hide.className = "ghost tiny";
    hide.id = "hide-tiles";
    const placeLine = document.createElement("div");
    placeLine.className = "side-act press-line";
    const placeSpace = document.createElement("span");
    placeSpace.className = "spacer";
    placeLine.append(place, laid, placeSpace, resetTiles, hide);
    const notes = document.createElement("div");
    notes.className = "side-note";
    notes.id = "tiles-notes";

    controls.append(
      row("Margin round an object (% of its size)", number("tiles-margin", Math.round(rules.margin * 100), { min: 0, step: 10 },
        (v) => ctx.setRule("margin", Math.max(0, v) / 100)), "tiles-margin"),
      switched("Min scan areas", "areas-min", rules.areasMin, { min: 1 }, (v) => ctx.setRule("areasMin", v)),
      switched("Max scan areas", "areas-max", rules.areasMax, { min: 1, resting: 50 }, (v) => ctx.setRule("areasMax", v)),
      switched("Max overlap (%)", "tiles-overlap", rules.overlapMax, { min: 0, max: 100, step: 5, scale: 100, resting: 50 }, (v) => ctx.setRule("overlapMax", v)),
      switched("Min overlap (%)", "overlap-min", rules.overlapMin, { min: 0, max: 90, step: 5, scale: 100, resting: 10 }, (v) => ctx.setRule("overlapMin", v)),
      row("Join into one scan", join, "join-scan"),
      row("When both cannot hold", prefer, "prefer"),
      row("Opacity", alpha, "tiles-alpha"),
      placeLine,
      notes,
    );

    const say = () => {
      const n = ctx.tiles().length;
      const kept = ctx.restricted().size;
      const plan = ctx.plan();
      place.disabled = kept === 0;
      resetTiles.disabled = n === 0;
      hide.disabled = n === 0;
      hide.textContent = ctx.tilesShown() ? "Hide" : "Show";
      resetSample.disabled = kept === 0;
      if (n) {
        const covered = kept - (plan?.uncovered?.length ?? 0);
        laid.textContent = `${n} scan area${n === 1 ? "" : "s"} · ${covered} of ${kept} covered`;
      } else {
        laid.textContent = kept ? `${kept} sampled` : "sample first";
      }
      notes.textContent = (plan?.notes ?? []).join(" · ");
    };
    place.addEventListener("click", () => { ctx.placeTiles(); say(); ctx.changed?.(); });
    resetTiles.addEventListener("click", () => { ctx.resetTiles(); say(); ctx.changed?.(); });
    hide.addEventListener("click", () => { ctx.showTiles(!ctx.tilesShown()); say(); });

    side.append(sample.group, recording);
    host.append(side);

    const seat = () => recording.querySelector(".side-group-body")?.append(controls);
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
