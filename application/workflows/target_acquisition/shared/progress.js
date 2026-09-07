/**
 * One run's progress, told as the page hears it land.
 *
 * A box under a title: a bar that fills as the things land and sweeps
 * while the run is busy, and one line under it -- what is being done at
 * the left, the arithmetic at the right. Detection and acquisition both
 * tell this story, so it is built here once and each hands it what it
 * hears:
 *
 *     say({ start: true, doing })          the press is taken
 *     say({ doing })                       a sentence about what is happening
 *     say({ done, of, doing, ... })        one more landed; the pace since the
 *                                          start projects the time left
 *     say({ ended: true, note })           the run's own last words; the bar
 *                                          stops where the count stands
 *
 * A whole-population phase after every field landed (detection's UMAP)
 * keeps the bar sweeping: `phase: "umap"` with `running` not false, and
 * `objects` says how many it is over.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import { sideGroup } from "../../../framework/window/panels.js";

/** A duration in the box's own words. */
export const saySpan = (s) => (s >= 90
  ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s`
  : `${s >= 10 ? Math.round(s) : Math.max(0.1, s).toFixed(1)} s`);

/**
 * The box, hidden until the run starts. `now` is the clock the pace is
 * measured on, the page's own unless a test hands in one it can move.
 */
export function progressBox(title, { now = () => performance.now() } = {}) {
  const box = sideGroup(title);
  box.group.style.display = "none";
  const bar = document.createElement("div");
  bar.className = "progress-bar";
  const fill = document.createElement("div");
  fill.className = "progress-fill";
  bar.append(fill);
  const line = document.createElement("div");
  line.className = "progress-line";
  const doing = document.createElement("span");
  doing.className = "progress-doing";
  const count = document.createElement("span");
  count.className = "progress-count";
  line.append(doing, count);
  box.body.append(bar, line);

  /* When the run under way began, for the pace the count line projects.
     Cleared when the run ends; restarted if the box was rebuilt mid-run,
     which loses the early pace but never shows a stale one. */
  let ranSince = null;
  /* Where the count stands, for the line to settle on when the run ends:
     an estimate of time left is no word for a run that has stopped. */
  let stood = null;

  function say(snap) {
    box.group.style.display = "";
    if (snap.start) {
      ranSince = now();
      stood = null;
      bar.classList.add("busy");
      fill.style.width = "0%";
      doing.textContent = snap.doing ?? "";
      count.textContent = "";
      return;
    }
    if (snap.doing != null) doing.textContent = snap.doing;
    if (snap.done != null && snap.of) {
      if (ranSince === null) ranSince = now();
      const gone = (now() - ranSince) / 1000;
      const per = snap.done ? gone / snap.done : null;
      const still = snap.of - snap.done;
      stood = `${snap.done} of ${snap.of}`;
      const mapping = snap.phase === "umap" && snap.running !== false;
      bar.classList.toggle("busy", still > 0 || mapping);
      fill.style.width = `${(100 * snap.done) / snap.of}%`;
      count.textContent = per === null
        ? `0 of ${snap.of}`
        : `${snap.done} of ${snap.of}`
          + (still ? ` · ≈ ${saySpan(per * still)} left` : "")
          + (mapping && snap.objects ? ` · ${snap.objects} objects` : "");
    }
    if (snap.ended) {
      bar.classList.remove("busy");
      doing.textContent = snap.note;
      if (stood !== null) count.textContent = stood;
      ranSince = null;
    }
  }

  return { group: box.group, say, doing, count };
}
