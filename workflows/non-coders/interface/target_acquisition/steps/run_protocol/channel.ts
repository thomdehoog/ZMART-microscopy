/**
 * The Run protocol step's channel: the press that accepts every orange step
 * at once, the step's own press under it, the run's numbers once it has
 * run, and saving the settings as a protocol.
 *
 * What the run will do is the rail above; the box only says what stands in
 * its way, which the press's hint does.
 */

import { burst } from "./confetti.ts";
import { css, sideGroup, staleSteps } from "zmart-interface/api";
import { protocolFrom } from "../../shared/protocol.ts";
import type { Channel } from "zmart-interface/api";
import type { TaPage, TargetAcquisition } from "../../types.ts";

/** The operator looked at every orange step and agrees with them as they
    stand: one press, in Step 10's box, there only while something is
    orange (Thom, 2026-09-28). */
function confirmAllSettings(page: TaPage): void {
  page.run.stale.clear();
  page.remountChannel();
  page.renderAll();
}

export const protocolChannel: Channel<TargetAcquisition> = {
  id: "protocol",
  label: "Run protocol",
  mount(host, page) {
    const state = page.run;
    const pad = document.createElement("div");
    pad.className = "side-pad-around";
    const { group, body } = sideGroup("Run protocol");
    const stale = staleSteps(page.steps(), state.done, state.stale);
    if (stale.length && !state.running && !state.walk.running) {
      const accept = document.createElement("button");
      accept.type = "button";
      accept.className = "run confirm";
      accept.id = "protocol-accept";
      accept.textContent = "Confirm all settings";
      accept.addEventListener("click", () => confirmAllSettings(page));
      body.append(accept);
    }
    /* What the run came to, once it has: the numbers, and for a run that
       finished, a small burst over them -- once, and again on the press. */
    const summary = state.protocol.summary;
    if (summary && !state.walk.running) {
      const stats = document.createElement("div");
      stats.className = "protocol-stats";
      stats.id = "protocol-stats";
      const rows: [string, string | number][] = [
        ["Tiles scanned", summary.tiles], ["Objects found", summary.objects],
        ["Objects gated", summary.gated], ["Targets acquired", summary.targets],
        ["Time", summary.seconds >= 90
          ? `${Math.floor(summary.seconds / 60)} min ${String(Math.round(summary.seconds % 60)).padStart(2, "0")} s`
          : `${Math.round(summary.seconds)} s`],
      ];
      if (summary.stoppedAt) rows.unshift(["Stopped at", summary.stoppedAt]);
      for (const [k, v] of rows) {
        const key = document.createElement("div"); key.textContent = k;
        const val = document.createElement("div"); val.className = "v"; val.textContent = String(v);
        stats.append(key, val);
      }
      body.append(stats);
      if (summary.ended === "finished") {
        /* The burst covers the whole white box, over the numbers, and is
           gone after three seconds; the press below brings it back. */
        body.classList.add("protocol-box");
        const cv = document.createElement("canvas");
        cv.className = "protocol-burst";
        body.append(cv);
        const colours = ["--accent", "--good", "--confirm-ink", "--mark-selected"].map((t) => css(t));
        let stop = () => {};
        /* Only on a canvas that has its size: the box is mounted before the
           page has laid it out, and a burst on a 0 x 0 canvas is no burst. */
        const play = () => {
          if (!cv.clientWidth || !cv.clientHeight) return false;
          stop();
          stop = burst(cv, colours);
          return true;
        };
        page.shown.playBurst = play;
        /* The box is built again more than once in the moments after the
           run ends; the burst belongs to those three seconds, on whichever
           canvas is on screen then. */
        if (performance.now() - summary.endedAt < 3000) {
          requestAnimationFrame(() => requestAnimationFrame(play));
        }
      }
    }
    const action = document.createElement("div");
    action.className = "protocol-action side-act";
    body.append(action);
    pad.append(group);
    /* The settings as they stand, kept without a run, in a box of their
       own: saved by name into the machine's library, or exported into this
       run's folder beside the acquisition types (Thom, 2026-09-28). */
    const keep = sideGroup("Save protocol");
    keep.group.id = "protocol-keep";
    const saveRow = document.createElement("div");
    saveRow.className = "protocol-save";
    const saveName = document.createElement("input");
    saveName.type = "text";
    saveName.id = "protocol-save-name";
    saveName.placeholder = "name";
    const savePress = document.createElement("button");
    savePress.type = "button";
    savePress.className = "sf-flat sf-doing";
    savePress.id = "protocol-save";
    savePress.textContent = "Save";
    savePress.disabled = !!state.running || state.walk.running || !page.backend.saveProtocolAs;
    saveRow.append(saveName, savePress);
    const exportRow = document.createElement("div");
    exportRow.className = "side-act";
    const exportPress = document.createElement("button");
    exportPress.type = "button";
    exportPress.className = "run";
    exportPress.id = "protocol-export";
    exportPress.textContent = "Export to run folder";
    exportPress.disabled = !state.done.has("connect") || !!state.running || state.walk.running || !page.backend.saveProtocol;
    const exportNote = document.createElement("span");
    exportNote.className = "action-hint";
    exportNote.id = "protocol-export-note";
    exportRow.append(exportPress, exportNote);
    const said = (ok: boolean, text: string) => { exportNote.className = ok ? "action-hint ok" : "action-hint"; exportNote.textContent = text; };
    savePress.addEventListener("click", async () => {
      savePress.disabled = true;
      try {
        const { id } = await page.backend.saveProtocolAs(protocolFrom(state), saveName.value.trim());
        said(true, `saved as ${id}`);
        page.listProtocols();
      } catch (why) {
        said(false, `not saved — ${(why as Error).message}`);
      } finally {
        savePress.disabled = false;
      }
    });
    exportPress.addEventListener("click", async () => {
      exportPress.disabled = true;
      try {
        await page.backend.saveProtocol(protocolFrom(state));
        said(true, "protocol written");
        page.listProtocols();
      } catch (why) {
        said(false, `not written — ${(why as Error).message}`);
      } finally {
        exportPress.disabled = false;
      }
    });
    keep.body.append(saveRow, exportRow);
    pad.append(keep.group);
    host.append(pad);
    return { actionSlot: action };
  },
};

/* The protocol's progress, at the top of the column beside the canvas,
   over whichever step's box the run is standing in: which step of how
   many, and how far that step is. Put there when the box mounts and
   brought up to date in place as the run reports. */
export function renderProtocolProgress(page: TaPage): void {
  const state = page.run;
  const host = page.panels[page.shownPanel() ?? ""]?.channel;
  if (!host) return;
  let box = host.querySelector<HTMLElement>("#protocol-progress-box");
  if (!state.walk.running) { box?.remove(); return; }
  if (!box) {
    const made = sideGroup("Protocol progress");
    box = made.group;
    box.id = "protocol-progress-box";
    const bar = document.createElement("div");
    bar.className = "progress-bar";
    bar.id = "protocol-progress";
    const fill = document.createElement("div");
    fill.className = "progress-fill";
    bar.append(fill);
    const line = document.createElement("div");
    line.className = "progress-line";
    line.id = "protocol-progress-line";
    made.body.append(bar, line);
    const pad = document.createElement("div");
    pad.className = "side-pad-around";
    pad.append(box);
    host.prepend(pad);
  }
  const p = state.protocol;
  const within = p.within && p.within.of ? p.within.done / p.within.of : 0;
  const filled = p.of ? ((p.at - 1) + within) / p.of : 0;
  /* Both were made with the box. */
  box.querySelector<HTMLElement>(".progress-fill")!.style.width = `${Math.round(Math.min(1, Math.max(0, filled)) * 100)}%`;
  const doing = page.step(state.activeIdx);
  box.querySelector("#protocol-progress-line")!.textContent =
    `step ${p.at} of ${p.of} · ${doing.title}` + (p.within && p.within.of ? ` · ${p.within.done} of ${p.within.of}` : "");
}
