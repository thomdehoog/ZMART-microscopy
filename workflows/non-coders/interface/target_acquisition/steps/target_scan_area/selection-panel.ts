/**
 * The Target scan area step's box: the target acquisition settings, the
 * four placement levers, and the summary of what the last placing came to.
 *
 * The box is handed what it shows and what to change through `ctx`, and
 * knows nothing about the run beyond that; `channel.ts` beside it does the
 * handing.
 */

import { sideGroup } from "zmart-interface/api";
import type { SlotKey } from "../../shared/page-helpers.ts";
import type { SlotOptions } from "../../shared/recording-slot.ts";
import type { Placing, TargetTile, TilePlan } from "../../shared/run-document.ts";

/** What the box asks of the recording slot: which of the run's slots it
    shows, and what the slot says and does when it changes. */
type SlotAsked = Pick<SlotOptions, "label" | "changed" | "unnamed" | "takes" | "retakes"> & { key: SlotKey };

/** What the box is handed: see `mount` below. */
interface SelectionContext {
  recordingSlot(host: HTMLElement, opts: SlotAsked): void;
  rules(): Placing;
  setRule<K extends keyof Placing>(key: K, value: Placing[K]): void;
  restricted(): Set<string>;
  tiles(): TargetTile[];
  plan(): TilePlan | null;
  changed?(): void;
}

/** How a number box may be set: its least, its most, and its step. */
interface NumberRange {
  min?: number;
  max?: number | null;
  step?: number;
}

/**
 * The step's box.
 *
 * `ctx` carries `recordingSlot(host, opts)`, the page's slot plumbing;
 * `rules()` and `setRule(key, value)`, the four placement controls;
 * `restricted()`, the sample;
 * `tiles()`, the scan areas placed; `plan()`, what the last placing came
 * to; and `changed()`.
 */
export const selectionPanel = {
  id: "select",
  label: "Target scan area",
  mount(host: HTMLElement, ctx: SelectionContext): { actionSlot: HTMLElement; redraw: () => void } {
    const side = document.createElement("div");
    side.className = "analysis-side";
    const rules = ctx.rules();

    /* A checkbox leads what it switches, as it does in Step 3. With a number
       as well, that number stays in the controls column at the right. */
    const checked = (text: string, box: HTMLInputElement) => {
      const line = document.createElement("div");
      line.className = "gate-draw check-first";
      const label = document.createElement("label");
      label.textContent = text;
      label.htmlFor = box.id;
      line.append(box, label);
      return line;
    };
    const number = (id: string, value: number, { min = 0, max = null, step = 1 }: NumberRange = {},
      take: (v: number) => void) => {
      const input = document.createElement("input");
      input.type = "number"; input.min = String(min); input.step = String(step);
      if (max != null) input.max = String(max);
      input.id = id;
      input.value = String(value);
      input.addEventListener("input", () => take(Number(input.value)));
      return input;
    };
    const switched = (text: string, id: string, value: number | null,
      { min = 0, max = null, step = 1, scale = 1, resting = 10 }: NumberRange & { scale?: number; resting?: number } = {},
      take: (v: number | null) => void) => {
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
    const lever = <K extends keyof Placing>(key: K) => (v: Placing[K]) => { ctx.setRule(key, v); ctx.changed?.(); };
    /* A choice between two ways, drawn as the page draws every such choice:
       a segmented strip, the chosen side in accent, on the controls column
       where the numbers above it stand. Exactly one side is chosen. */
    const chosen = <V>(text: string, id: string, sides: [V, string][], which: V, take: (value: V) => void) => {
      const line = document.createElement("div");
      line.className = "gate-draw";
      const label = document.createElement("label");
      label.textContent = text;
      const strip = document.createElement("div");
      strip.className = "seg"; strip.id = id;
      strip.setAttribute("role", "radiogroup");
      strip.setAttribute("aria-label", text);
      const buttons = sides.map(([value, words]): [V, HTMLButtonElement] => {
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("role", "radio");
        button.textContent = words;
        button.addEventListener("click", () => {
          for (const [other, side] of buttons) side.setAttribute("aria-checked", String(other === value));
          take(value);
        });
        return [value, button];
      });
      for (const [value, button] of buttons) {
        button.setAttribute("aria-checked", String(value === which));
        strip.append(button);
      }
      line.append(label, strip);
      return line;
    };

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
    const summaryValue = (label: string, id: string) => {
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
    const placeLine = document.createElement("div");
    placeLine.className = "side-act press-line";
    placeLine.append(act);
    const notes = document.createElement("div");
    notes.className = "side-note";
    notes.id = "tiles-notes";
    simple.append(
      mainSettingsTitle,
      switched("Max targets per overview tileset", "gate-max", rules.objectsMax, { min: 1, resting: 50 }, lever("objectsMax")),
      switched("Margin around a target (% of its size)", "tiles-margin", rules.margin,
        { min: 0, step: 10, scale: 100, resting: 100 }, lever("margin")),
      switched("Tile overlap for big targets (%)", "overlap-min", rules.overlapMin,
        { min: 0, max: 90, step: 5, scale: 100, resting: 20 }, lever("overlapMin")),
      /* Fewest: the placing looks for the fewest tiles that cover every
         sampled target, so neighbours share one. One per target: every
         target gets a tile of its own, centred on it. */
      chosen("Number of tiles", "tiles-count", [[true, "Fewest"], [false, "One per target"]],
        rules.minimise !== false, lever("minimise")),
      placeLine,
    );
    adding.body.append(simple);
    summary.body.append(summaryRows, notes);

    const say = () => {
      const n = ctx.tiles().length;
      const sampled = ctx.restricted().size;
      const plan = ctx.plan();
      const covered = Math.max(0, sampled - (plan?.uncovered?.length ?? 0));
      summary.group.hidden = !plan;
      areaCount.value.textContent = String(n);
      sampledCount.key.textContent = rules.objectsMax == null ? "Gated targets" : "Sampled targets";
      sampledCount.value.textContent = String(sampled);
      coveredCount.value.textContent = `${covered} of ${sampled}`;
      /* What the press came to is the step's own word beside it; only what
         could not be honoured is said here. */
      notes.textContent = (plan?.notes ?? []).join(" · ");
    };

    side.append(recording, adding.group, summary.group);
    host.append(side);

    const seat = () => { adding.group.hidden = !recording.querySelector(".setting-box.done"); };
    ctx.recordingSlot(recording, {
      label: "Target acquisition settings", key: "targetType",
      unnamed: true,
      takes: "Import target acquisition settings",
      retakes: "Update",
      changed: () => { seat(); ctx.changed?.(); },
    });
    seat();
    say();
    return { actionSlot: act, redraw: () => { seat(); say(); } };
  },
};
