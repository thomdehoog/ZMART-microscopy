/**
 * The run without presses: the steps from the focus map to the targets,
 * in turn, each awaited, over the whole scan area. Stops at the first
 * step that does not finish -- stopped by hand, failed, or not ready --
 * and leaves the steps after it as they were. Finishing writes the
 * protocol.
 *
 * This step does not run through the page's runner like the others: it is
 * the one that runs them. So its press calls `runProtocol` directly;
 * `run.walk` says whether it is walking (the framework reads it), and
 * `run.protocol` how far it has got and what it came to.
 */

import { whyGatesNotCarried, protocolFrom } from "../../shared/protocol.ts";
import { hasRecording } from "../../microscope/recordings.ts";
import type { TaPage } from "../../types.ts";

/* The steps the protocol walks, in order. */
const PROTOCOL_STEPS = ["focus", "scan", "detect", "gate", "select", "acquire"];

export async function runProtocol(page: TaPage): Promise<void> {
  const state = page.run;
  const { step, indexOfStep } = page;
  if (state.running || state.walk.running) return;
  /* Which steps the run will take: the focus map only when there is none
     measured on this sample yet; the gate is applied by the discovery. */
  const walk = PROTOCOL_STEPS.filter((id) => !(id === "focus" && state.focus.applied) && id !== "gate");
  state.walk = { running: true, interrupted: false };
  state.protocol = { at: 0, of: walk.length, within: null, summary: null };
  /* Grey until reached: the rail says what the run has done, not what
     the rehearsal did. Each step turns green as its own finish puts it
     back. */
  for (const id of [...walk, "gate", "protocol"]) { state.done.delete(id); state.stale.delete(id); }
  const startedAt = performance.now();
  let ended = "finished";
  for (const id of PROTOCOL_STEPS) {
    if (state.walk.interrupted) { ended = "stopped"; break; }
    const i = indexOfStep(id);
    if (walk.includes(id)) { state.protocol.at += 1; state.protocol.within = null; }
    state.activeIdx = i;
    page.focusPanelsFor(i);
    page.renderAll();
    /* The gates are applied when the discovery finishes; here the step
       is only marked as the run's own. */
    if (id === "gate") {
      state.done.add("gate"); state.stale.delete("gate");
      continue;
    }
    /* A focus map already measured on this sample stands: the run keeps
       it and starts at the scan. Measured only when there is none yet,
       which is how a run opened on a protocol begins (Thom, 2026-09-28). */
    if (id === "focus" && state.focus.applied) {
      state.stale.delete("focus");
      continue;
    }
    const why = page.readiness(step(i));
    if (why) {
      state.notes[id] = why;
      ended = "failed";
      break;
    }
    const { outcome } = await page.runStep(i);
    if (outcome !== "finished") { ended = outcome; break; }
  }
  state.walk.running = false;
  state.protocol.summary = {
    ended,
    tiles: state.scanned?.plan.length ?? 0,
    objects: state.cells.size,
    gated: state.gated.size,
    targets: state.acquired.length,
    seconds: (performance.now() - startedAt) / 1000,
    stoppedAt: ended === "finished" ? null : step(state.activeIdx).title,
    endedAt: performance.now(),
  };
  const at = indexOfStep("protocol");
  if (ended === "finished") {
    state.done.add("protocol"); state.ran.add("protocol"); state.stale.delete("protocol");
    try {
      await page.backend.saveProtocol?.(protocolFrom(state));
      state.notes.protocol = "run finished · protocol written";
    } catch (why) {
      state.notes.protocol = `run finished · protocol not written — ${(why as Error).message}`;
    }
  } else {
    state.notes.protocol = ended === "stopped"
      ? "stopped by hand" : `stopped at ${step(state.activeIdx).title} — ${state.notes[step(state.activeIdx).id] ?? "failed"}`;
  }
  state.activeIdx = at;
  page.remountChannel();
  page.focusPanelsFor(at);
  page.renderAll();
}

/** A step's own progress, handed to the protocol's bar while it runs. */
export function protocolWithin(page: TaPage, done: number, of: number): void {
  const state = page.run;
  if (!state.walk.running) return;
  state.protocol.within = { done, of };
  page.renderProtocolProgress();
}

/* What would stop the protocol before it finished, said before it
   starts: the settings a later step needs and does not make for itself.
   The steps' own `ready` rules cannot be asked here for what an earlier
   step of the run produces (gated objects, target tiles), so this asks
   for the settings only. */
export function protocolBlockers(page: TaPage): string[] {
  const state = page.run;
  const blockers: string[] = [];
  const focus = page.step(page.indexOfStep("focus"));
  if (!state.focus.applied && focus.ready?.(state, page)) blockers.push(`Focus strategy: ${focus.ready(state, page)}`);
  if (!hasRecording(state.overviewPreset)) blockers.push("Overview scan area: import the optical configuration first");
  if (!state.plan.length) blockers.push("Overview scan area: nothing to scan yet");
  if (!state.gates.length) blockers.push("Discover Targets: draw a gate first");
  const notCarried = whyGatesNotCarried(state.gates);
  if (notCarried) blockers.push(`Discover Targets: ${notCarried}`);
  if (!hasRecording(state.targetType)) blockers.push("Target scan area: import the target settings first");
  if (state.targetFocusOn && !hasRecording(state.targetFocus)) blockers.push("Acquire Targets: import the focussing settings first");
  return blockers;
}

/** After a run that finished, the burst can be brought back, at the right
    of the press (Thom, 2026-09-28). */
export function afterTheProtocolPress(host: HTMLElement, page: TaPage): void {
  const state = page.run;
  if (state.protocol.summary?.ended === "finished" && page.shown.playBurst) {
    const again = document.createElement("button");
    again.type = "button"; again.className = "run"; again.id = "protocol-again";
    again.textContent = "Rerun confetti";
    /* Set by the box this press stands under, as it is checked above. */
    again.addEventListener("click", () => page.shown.playBurst!());
    host.append(again);
  }
}
