/**
 * The cells the steps of this workflow are made of.
 *
 * A notebook is a column of cells, and each cell is three things: a sentence
 * saying what you are about to do, the control to do it with, and underneath,
 * what came back. These helpers make those three things the same shape on
 * every step, so the column reads as one document rather than five forms.
 *
 * They build elements and nothing else. What a cell says, and what pressing
 * its button does, is the step's.
 */

import { sideGroup } from "../../../framework/window/panels.js";

/** A cell: the same box the target-acquisition channel is made of -- a small
    heading above a white card -- with the notebook's sentence first inside
    the card, and the controls and what came back under it. */
export function cell(title, prose = null) {
  const { group, body } = sideGroup(title);
  group.classList.add("setup-cell");
  if (prose) {
    const p = document.createElement("p");
    p.className = "side-note";
    p.textContent = prose;
    body.append(p);
  }
  return { box: group, body };
}

/** A press. `busy` is the wording while the work is out with the instrument. */
export function press(label, onPress, { busy = "working…", disabled = false } = {}) {
  const b = document.createElement("button");
  b.className = "run";
  b.type = "button";
  b.textContent = label;
  b.disabled = disabled;
  b.addEventListener("click", async () => {
    b.disabled = true;
    const was = b.textContent;
    b.textContent = busy;
    try {
      await onPress();
    } finally {
      b.textContent = was;
      b.disabled = disabled;
    }
  });
  return b;
}

/** What came back, as pairs: a word on the left, its value on the right. */
export function readout(pairs) {
  const dl = document.createElement("dl");
  dl.className = "setup-readout";
  for (const [k, v] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    dl.append(dt, dd);
  }
  return dl;
}

/** A sentence in the quieter voice, for a note, a warning, or a source. */
export function note(text, kind = "") {
  const p = document.createElement("p");
  p.className = kind ? `setup-note ${kind}` : "setup-note";
  p.textContent = text;
  return p;
}

/** A number in a sentence: a few decimals and a unit, never a float's tail. */
export const um = (v, digits = 1) =>
  (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : `${Number(v).toFixed(digits)} µm`);

/** The step's own footer: its Publish press, and the sentence beside it once
    the document is on disk. Every step ends the same way, so it looks the same. */
export function publishRow({ label, onPublish, published, disabled = false }) {
  const row = document.createElement("div");
  row.className = "setup-publish";
  row.append(press(label, onPublish, { busy: "publishing…", disabled }));
  if (published) row.append(note(published, "ok"));
  return row;
}

/** The picture a measurement drew of itself, as the notebook shows it. The
    address carries the moment, so a fresh measurement is a fresh picture and
    never the browser's memory of the last one. */
export function picture(url, alt) {
  const img = document.createElement("img");
  img.className = "setup-picture";
  img.src = `${url}?t=${Date.now()}`;
  img.alt = alt;
  return img;
}
