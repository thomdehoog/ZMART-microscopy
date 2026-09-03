/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets, in two
 * boxes. Sample targets: what the gates let through is held under a
 * per-tileset ceiling by the step's press, Restrict. Place scan areas: the
 * settings the targets are imaged with are imported, and a scan area is
 * placed round every sampled target in that frame. The scan areas are the
 * plan; acquiring them is the step after.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

export const targetScanArea = {
  id: "select",
  title: "Target scan area",
  why: "Sample the gated targets to so many per tileset, then import the settings and place a scan area round each.",
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
 * `cap()` and `setCap(n)`, the per-tileset ceiling the run holds;
 * `restricted()`, the ids the ceiling kept, and `reset()`, forget them;
 * `tiles()`, the scan areas placed, `placeTiles()`, place one round every
 * sampled target, `resetTiles()`, take them away, `showTiles(on)` and
 * `tilesShown()`, whether they are drawn; `alpha()` and `setAlpha(a)`,
 * how solid; `overlapLimited()`, `setOverlapLimited(on)`, `maxOverlap()`,
 * `setMaxOverlap(share)` and `leftOut()`, the overlap rule and what it
 * left out; and `changed()`.
 */
export const selectionPanel = {
  id: "select",
  label: "Target scan area",
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "analysis-side";

    /* The step's own press, beside the ceiling it applies. */
    const act = document.createElement("div");
    act.className = "select-action side-act";

    /* 1. Sample targets: a systematic draw over EACH tileset's own extent,
       so what survives is spread evenly across the compartment. Typed here,
       applied by the press; Reset forgets the draw. */
    const sample = sideGroup("Sample targets");
    const refine = document.createElement("div");
    refine.className = "gate-draw";
    const maxLabel = document.createElement("label");
    maxLabel.textContent = "Max objects per tileset";
    maxLabel.htmlFor = "gate-max";
    const maxN = document.createElement("input");
    maxN.type = "number"; maxN.min = "1"; maxN.step = "1";
    maxN.id = "gate-max";
    maxN.value = String(ctx.cap());
    maxN.addEventListener("input", () => {
      ctx.setCap(Math.max(1, Math.round(Number(maxN.value) || 0)));
      ctx.changed?.();
    });
    refine.append(maxLabel, maxN);
    const resetSample = document.createElement("button");
    resetSample.type = "button";
    resetSample.className = "ghost tiny";
    resetSample.id = "reset-restriction";
    resetSample.textContent = "Reset";
    resetSample.title = "Forget the sample; the gated targets stand whole again";
    resetSample.addEventListener("click", () => { ctx.reset(); ctx.changed?.(); });
    const sampleLine = document.createElement("div");
    sampleLine.className = "side-act";
    sampleLine.append(act, resetSample);
    sample.body.append(refine, sampleLine);

    /* 2. Place scan areas: the settings first -- the recording slot draws
       this box, and the controls under them are seated into it, again after
       every import, since the slot redraws itself. */
    const recording = document.createElement("div");
    recording.id = "target-type";
    const controls = document.createElement("div");
    controls.className = "tile-controls";
    const lay = document.createElement("div");
    lay.className = "gate-draw";
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
    lay.append(place, laid, resetTiles, hide);
    const strength = document.createElement("div");
    strength.className = "gate-draw";
    const alphaLabel = document.createElement("label");
    alphaLabel.textContent = "Opacity";
    alphaLabel.htmlFor = "tiles-alpha";
    const alpha = document.createElement("input");
    alpha.type = "range"; alpha.min = "10"; alpha.max = "100"; alpha.step = "5";
    alpha.id = "tiles-alpha";
    alpha.value = String(Math.round(ctx.alpha() * 100));
    alpha.addEventListener("input", () => {
      ctx.setAlpha(Number(alpha.value) / 100);
      ctx.changed?.();
    });
    strength.append(alphaLabel, alpha);
    /* The overlap rule: a scan area that would cover more than this share
       of one already placed is left out -- or every one is placed, when
       the rule is switched off. */
    const overlapRow = document.createElement("div");
    overlapRow.className = "gate-draw";
    const limit = document.createElement("input");
    limit.type = "checkbox";
    limit.id = "limit-overlap";
    limit.checked = ctx.overlapLimited();
    const limitLabel = document.createElement("label");
    limitLabel.htmlFor = "limit-overlap";
    limitLabel.append(limit, " Max overlap (%)");
    const overlap = document.createElement("input");
    overlap.type = "number"; overlap.min = "0"; overlap.max = "100"; overlap.step = "5";
    overlap.id = "tiles-overlap";
    overlap.value = String(Math.round(ctx.maxOverlap() * 100));
    limit.addEventListener("change", () => { ctx.setOverlapLimited(limit.checked); overlap.disabled = !limit.checked; });
    overlap.addEventListener("input", () => {
      ctx.setMaxOverlap(Math.min(100, Math.max(0, Number(overlap.value) || 0)) / 100);
    });
    overlap.disabled = !limit.checked;
    overlapRow.append(limitLabel, overlap);
    controls.append(overlapRow, lay, strength);

    const say = () => {
      const n = ctx.tiles().length;
      const kept = ctx.restricted().size;
      place.disabled = kept === 0;
      resetTiles.disabled = n === 0;
      hide.disabled = n === 0;
      hide.textContent = ctx.tilesShown() ? "Hide" : "Show";
      const out = ctx.leftOut().length;
      laid.textContent = n
        ? `${n} scan area${n === 1 ? "" : "s"}${out ? ` · ${out} left out for overlap` : ""}`
        : (kept ? `${kept} sampled` : "sample first");
      resetSample.disabled = kept === 0;
    };
    place.addEventListener("click", () => { ctx.placeTiles(); say(); ctx.changed?.(); });
    resetTiles.addEventListener("click", () => { ctx.resetTiles(); say(); ctx.changed?.(); });
    hide.addEventListener("click", () => { ctx.showTiles(!ctx.tilesShown()); say(); });

    side.append(sample.group, recording);
    host.append(side);

    /* Under the settings, inside their box: the slot redraws its host on
       every import, so the controls are seated again after each. */
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
