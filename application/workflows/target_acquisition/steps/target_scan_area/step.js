/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets, in three
 * boxes: the settings the targets are imaged with; the restriction, which
 * holds what the gates let through under a per-tileset ceiling; and the
 * tiles, laid round every restricted target in the settings' frame. The
 * tiles are the plan; acquiring them is the step after.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

export const targetScanArea = {
  id: "select",
  title: "Target scan area",
  why: "Record the settings the targets are imaged with, restrict them to so many per tileset, then add the tiles.",
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
 * `restricted()`, the ids the ceiling kept; `tiles()`, the tiles laid;
 * `addTiles()`, lay one round every restricted target; `alpha()` and
 * `setAlpha(a)`, how solid the tiles are drawn; and `changed()`.
 */
export const selectionPanel = {
  id: "select",
  label: "Target scan area",
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "analysis-side";

    /* The step's own press, under the ceiling it applies. */
    const act = document.createElement("div");
    act.className = "select-action side-act";

    /* 1. The settings, in the box the recording slot brings. */
    const recording = document.createElement("div");
    recording.id = "target-type";

    /* 2. The restriction: a spatial SURS draw over EACH tileset's own extent,
       so what survives is spread evenly across the compartment. Typed here,
       applied by the press under it. */
    const restrict = sideGroup("Restrict targets per tileset");
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
    restrict.body.append(refine, act);

    /* 3. The tiles: one round every restricted target, in the settings'
       frame, drawn in green at whatever strength the slider says. */
    const tiles = sideGroup("Add tiles");
    const lay = document.createElement("div");
    lay.className = "gate-draw";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "run";
    add.id = "add-tiles";
    add.textContent = "Add tiles";
    const laid = document.createElement("span");
    laid.className = "action-hint";
    laid.id = "tiles-laid";
    lay.append(add, laid);
    const strength = document.createElement("div");
    strength.className = "gate-draw";
    const alphaLabel = document.createElement("label");
    alphaLabel.textContent = "Tile opacity";
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
    tiles.body.append(lay, strength);

    const sayTheTiles = () => {
      const n = ctx.tiles().length;
      const kept = ctx.restricted().size;
      add.disabled = kept === 0;
      laid.textContent = n ? `${n} tile${n === 1 ? "" : "s"}` : (kept ? `${kept} restricted, no tiles yet` : "restrict first");
    };
    add.addEventListener("click", () => {
      ctx.addTiles();
      sayTheTiles();
      ctx.changed?.();
    });

    side.append(recording, restrict.group, tiles.group);
    host.append(side);

    ctx.recordingSlot(recording, {
      label: "Target acquisition settings", key: "targetType",
      unnamed: true,
      takes: "Import target acquisition settings",
      retakes: "Update",
      changed: () => ctx.changed?.(),
    });
    sayTheTiles();
    return { redraw: sayTheTiles };
  },
};
