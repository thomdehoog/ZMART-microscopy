/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets. The target
 * acquisition settings stand in their own box. Once one has been imported,
 * Add scan areas appears under it with the four placement controls and the
 * step's press. It draws a systematic uniform random sample of what the gates
 * let through and places the fewest target tiles it can over that sample.
 * The target tiles are the plan; acquiring them is the step after.
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
 * `rules()` and `setRule(key, value)`, the four placement controls;
 * `restricted()`, the sample;
 * `tiles()`, the scan areas placed; `plan()`, what the last placing came
 * to; `reset()`, forget sample and areas; `showTiles(on)`, `tilesShown()`;
 * and `changed()`.
 */
export const selectionPanel = {
  id: "select",
  label: "Target scan area",
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "analysis-side";
    const rules = ctx.rules();

    /* A checkbox leads what it switches, as it does in Step 3. With a number
       as well, that number stays in the controls column at the right. */
    const checked = (text, box) => {
      const line = document.createElement("div");
      line.className = "gate-draw check-first";
      const label = document.createElement("label");
      label.textContent = text;
      label.htmlFor = box.id;
      line.append(box, label);
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
      const line = checked(text, box);
      line.append(input);
      return line;
    };
    const lever = (key) => (v) => { ctx.setRule(key, v); ctx.changed?.(); };

    /* The step's own press, at the end of the simple box. */
    const act = document.createElement("div");
    act.className = "select-action side-act";

    /* 1. The target acquisition settings, drawn by the recording slot in
       their own box. Add scan areas below stays absent until this has one. */
    const recording = document.createElement("div");
    recording.id = "target-type";

    const adding = sideGroup("Add scan areas");
    const summary = sideGroup("Target tile summary");
    const summaryRows = document.createElement("div");
    summaryRows.className = "scan-summary";
    const summaryValue = (label, id) => {
      const key = document.createElement("span");
      key.className = "k";
      key.textContent = label;
      const value = document.createElement("span");
      value.className = "v";
      value.id = id;
      summaryRows.append(key, value);
      return { key, value };
    };
    const areaCount = summaryValue("Target tiles", "scan-area-count");
    const sampledCount = summaryValue("Sampled targets", "scan-area-sampled");
    const coveredCount = summaryValue("Covered targets", "scan-area-coverage");
    const simple = document.createElement("div");
    simple.className = "tile-controls";
    const mainSettingsTitle = document.createElement("div");
    mainSettingsTitle.className = "target-main-settings-title";
    mainSettingsTitle.textContent = "Main settings";
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
      mainSettingsTitle,
      switched("Max targets per overview tileset", "gate-max", rules.objectsMax, { min: 1, resting: 50 }, lever("objectsMax")),
      switched("Max target tiles per overview tileset", "tiles-max", rules.tilesMax, { min: 1, resting: 50 }, lever("tilesMax")),
      switched("Margin around a target (% of its size)", "tiles-margin", rules.margin,
        { min: 0, step: 10, scale: 100, resting: 100 }, lever("margin")),
      switched("Tile overlap for big targets (%)", "overlap-min", rules.overlapMin,
        { min: 0, max: 90, step: 5, scale: 100, resting: 20 }, lever("overlapMin")),
      placeLine,
    );
    adding.body.append(simple);
    summary.body.append(summaryRows, notes);

    const say = () => {
      const n = ctx.tiles().length;
      const sampled = ctx.restricted().size;
      const plan = ctx.plan();
      const covered = Math.max(0, sampled - (plan?.uncovered?.length ?? 0));
      reset.disabled = sampled === 0 && n === 0;
      hide.disabled = n === 0;
      hide.textContent = ctx.tilesShown() ? "Hide" : "Show";
      summary.group.hidden = !plan;
      areaCount.value.textContent = String(n);
      sampledCount.key.textContent = rules.objectsMax == null ? "Gated targets" : "Sampled targets";
      sampledCount.value.textContent = String(sampled);
      coveredCount.value.textContent = `${covered} of ${sampled}`;
      /* What the press came to is the step's own word beside it; only what
         could not be honoured is said here. */
      notes.textContent = (plan?.notes ?? []).join(" · ");
    };
    reset.addEventListener("click", () => { ctx.reset(); say(); ctx.changed?.(); });
    hide.addEventListener("click", () => { ctx.showTiles(!ctx.tilesShown()); say(); });

    side.append(recording, adding.group, summary.group);
    host.append(side);

    const seat = () => { adding.group.hidden = !recording.querySelector(".setting-box.done"); };
    ctx.recordingSlot(recording, {
      label: "Acquisition settings", key: "targetType",
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
