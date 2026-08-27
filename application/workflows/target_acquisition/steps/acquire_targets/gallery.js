/**
 * Step 8's channel — the acquired pairs, and the verdict on each.
 *
 * Acquisition happens on the canvas, where the targets ring; this is what
 * stands beside it. One card per acquired target: the two crops, what and
 * where it is, and the two buttons that mark it kept or discarded. Above
 * them, the recording the targets are imaged with.
 *
 * The widget owns its own markup and rebuilds from the run whenever it is
 * mounted, so nothing stale survives a walk away and back. It never reaches
 * for the page around it: everything it shows and everything it changes
 * arrives in `ctx`.
 */

import { makeRng } from "../../../../parts/microscope/pretend-sample/rng.js";

/** The side of one crop, in pixels. */
const CROP_PX = 132;

/**
 * A crop of the sample around one target, drawn rather than photographed.
 *
 * The pretend instrument has no camera, so this stands in for the pair of
 * pictures a real acquisition saves: the same cell at the overview's
 * magnification and at the target's, which is what the operator compares.
 * When the backend returns real images this is the one thing that goes.
 */
function cropCanvas(cell, zoom, seed) {
  const cv = document.createElement("canvas");
  cv.width = CROP_PX; cv.height = CROP_PX;
  const ctx = cv.getContext("2d");
  const r = makeRng(seed);
  ctx.fillStyle = "#05090e";
  ctx.fillRect(0, 0, CROP_PX, CROP_PX);

  // the sample around it: fewer and larger blobs the further in the zoom is
  const blobs = zoom > 1 ? 5 : 14;
  for (let i = 0; i < blobs; i++) {
    const bx = CROP_PX * r(), by = CROP_PX * r();
    const br = (zoom > 1 ? 26 : 9) * (0.5 + r());
    const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
    g.addColorStop(0, `rgba(34,211,238,${0.30 + 0.35 * r()})`);
    g.addColorStop(1, "rgba(34,211,238,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
  }

  // the cell itself, centred and ringed the way it is on the canvas
  const cr = zoom > 1 ? 34 : 7;
  const mid = CROP_PX / 2;
  const g = ctx.createRadialGradient(mid, mid, 0, mid, mid, cr);
  g.addColorStop(0, `rgba(245,158,11,${0.55 + 0.4 * cell.intensity})`);
  g.addColorStop(0.7, "rgba(245,158,11,0.22)");
  g.addColorStop(1, "rgba(245,158,11,0)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(mid, mid, cr, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "rgba(22,163,74,0.85)";
  ctx.lineWidth = zoom > 1 ? 2 : 1.5;
  ctx.beginPath(); ctx.arc(mid, mid, cr * 0.75, 0, Math.PI * 2); ctx.stroke();
  return cv;
}

/** How the pairs are counted, in the words the readout uses. */
export function galleryTally(acquired, verdicts) {
  const marked = acquired.filter((id) => verdicts[id]).length;
  const good = acquired.filter((id) => verdicts[id] === "good").length;
  return acquired.length
    ? `${acquired.length} pairs · ${marked} marked · ${good} good`
    : "—";
}

export default {
  id: "acquire",
  label: "Acquire Targets",

  /**
   * Build the channel and fill it from the run.
   *
   * `ctx` carries what this step works with and nothing else:
   *   `acquired`   the target ids, in the order they were imaged
   *   `verdicts`   id -> "good" | "bad" | null, changed here
   *   `cellById`   a target's own details, for the crops and the caption
   *   `recordingSlot(host, opts)`  the shared recorder, for the acquisition type
   *   `changed()`  say that something the rest of the page shows has changed
   *
   * Returns a handle whose `rebuild()` fills the cards in again — what the
   * step's own run calls once the targets have been acquired.
   */
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "gallery-side";

    // what the targets are imaged with, read off the instrument here
    const recording = document.createElement("div");
    recording.className = "side-pad";
    recording.id = "target-type";

    const head = document.createElement("div");
    head.className = "side-head";
    head.append("Acquired pairs");
    const readout = document.createElement("span");
    readout.className = "readout";
    readout.id = "gallery-readout";
    readout.textContent = "—";
    head.append(readout);

    const note = document.createElement("div");
    note.className = "side-note";
    note.textContent = "overview crop · target crop — mark each ✓ or ✗";

    const wrap = document.createElement("div");
    wrap.className = "gallery-wrap";
    const pairs = document.createElement("div");
    pairs.className = "pairs";
    pairs.id = "pairs";
    wrap.append(pairs);

    side.append(recording, head, note, wrap);
    host.append(side);

    ctx.recordingSlot(recording, {
      /* Just the thing, not the gesture: the heading already says "Record",
         so a label that says it too reads "Record record …" on screen. */
      label: "Acquisition type", key: "targetType",
      changed: () => ctx.changed(),
    });

    const sayTheTally = () => {
      readout.textContent = galleryTally(ctx.acquired(), ctx.verdicts());
    };

    /** One card: the crops, the caption, and the two marks. */
    const cardFor = (id, i) => {
      const cell = ctx.cellById(id);
      const card = document.createElement("div");
      card.className = "pair";

      const imgs = document.createElement("div");
      imgs.className = "imgs";
      imgs.append(cropCanvas(cell, 1, 7000 + i), cropCanvas(cell, 3, 9100 + i));

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.append(document.createTextNode(
        `#${cell.id} · ${(cell.x / 1000).toFixed(2)}, ${(cell.y / 1000).toFixed(2)} mm`));

      const verdict = document.createElement("div");
      verdict.className = "verdict";
      const marks = [];
      for (const [kind, glyph] of [["good", "✓"], ["bad", "✗"]]) {
        const mark = document.createElement("button");
        mark.type = "button";
        mark.className = `pick-${kind}`;
        mark.textContent = glyph;
        mark.setAttribute("aria-pressed", "false");
        mark.setAttribute("aria-label", `mark cell ${cell.id} ${kind}`);
        /* Pressing the mark it already carries takes it back off: a verdict
           given by mistake is undone the same way it was given. */
        mark.addEventListener("click", () => {
          const verdicts = ctx.verdicts();
          verdicts[cell.id] = verdicts[cell.id] === kind ? null : kind;
          for (const one of marks) {
            one.setAttribute("aria-pressed",
              String(one.classList.contains(`pick-${verdicts[cell.id]}`)));
          }
          sayTheTally();
        });
        marks.push(mark);
        verdict.append(mark);
      }
      meta.append(verdict);
      card.append(imgs, meta);
      return card;
    };

    const rebuild = () => {
      pairs.textContent = "";
      ctx.acquired().forEach((id, i) => pairs.append(cardFor(id, i)));
      sayTheTally();
    };

    rebuild();
    return { rebuild };
  },
};
