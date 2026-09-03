/**
 * Step 8 — Target scan area.
 *
 * The counterpart of the overview's scan area, for the targets: what the
 * gates let through is held under a per-tileset ceiling here, and the
 * settings the targets are imaged with are recorded here. The picture shows
 * the frame each target will be taken with, laid where it will be taken.
 * The frames are the plan; acquiring them is the step after.
 */

import { sideGroup } from "../../../../framework/window/panels.js";

export const targetScanArea = {
  id: "select",
  title: "Target scan area",
  why: "Restrict the gated targets to so many per tileset, and record the settings they are imaged with.",
  btn: "Restrict",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};

/**
 * The step's channel: the Selection box -- the shared recording slot for
 * the target settings, the ceiling, and the step's own press under them.
 *
 * `ctx` carries `recordingSlot(host, opts)`, the page's slot plumbing;
 * `cap()` and `setCap(n)`, the per-tileset ceiling the run holds; and
 * `changed()`, what to do when either changes.
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

    /* The settings first, in the box the recording slot brings, then the
       scan area: the ceiling -- a spatial SURS draw over EACH tileset's own
       extent, so what survives is spread evenly across the compartment --
       typed here and applied by the press under it. */
    const recording = document.createElement("div");
    recording.id = "target-type";
    const curate = sideGroup("Scan area");
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
    curate.body.append(refine, act);
    side.append(recording, curate.group);
    host.append(side);

    ctx.recordingSlot(recording, {
      label: "Target acquisition settings", key: "targetType",
      unnamed: true,
      takes: "Import target acquisition settings",
      retakes: "Update",
      changed: () => ctx.changed?.(),
    });
    return {};
  },
};
