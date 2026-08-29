/**
 * Step 8's channel — the acquired pairs, and the verdict on each.
 *
 * Acquisition happens on the canvas, where the targets ring; this is what
 * stands beside it. One card per acquired target: the two pictures, what and
 * where it is, and the two buttons that mark it kept or discarded. Above
 * them, the recording the targets are imaged with.
 *
 * The widget owns its own markup and rebuilds from the run whenever it is
 * mounted, so nothing stale survives a walk away and back. It never reaches
 * for the page around it: everything it shows and everything it changes
 * arrives in `ctx`.
 */

/** The side of one picture, in pixels. */
const CROP_PX = 132;

/**
 * One small picture: the viewer's copy at `src`, drawn by `draw(paint, img)`
 * once it arrives. A backend that saves nothing gives no address, and the
 * picture is drawn dark, with `draw` given nothing to draw from.
 */
function smallPicture(src, draw) {
  const cv = document.createElement("canvas");
  cv.width = CROP_PX; cv.height = CROP_PX;
  const paint = cv.getContext("2d");
  paint.fillStyle = "#05090e";
  paint.fillRect(0, 0, CROP_PX, CROP_PX);
  if (src) {
    const img = new Image();
    img.onload = () => draw(paint, img);
    img.src = src;
  } else {
    draw(paint, null);
  }
  return cv;
}

const ringed = (paint, r) => {
  paint.strokeStyle = "rgba(22,163,74,0.85)";
  paint.lineWidth = 1.5;
  paint.beginPath(); paint.arc(CROP_PX / 2, CROP_PX / 2, r, 0, Math.PI * 2); paint.stroke();
};

/**
 * The field the target was found in, cropped around it at the overview's
 * magnification: a window a few cell widths wide, the target ringed at its
 * centre. `field` is the plan's position plus `picture`, the field's own
 * small copy, which covers exactly the frame.
 */
function fieldCrop(cell, field) {
  const half = Math.max(40, cell.r * 4);
  return smallPicture(field.picture, (paint, img) => {
    if (img) {
      const perUm = img.naturalWidth / field.frameUm;
      const sx = (cell.x - half - (field.x - field.frameUm / 2)) * perUm;
      const sy = (cell.y - half - (field.y - field.frameUm / 2)) * perUm;
      paint.drawImage(img, sx, sy, 2 * half * perUm, 2 * half * perUm, 0, 0, CROP_PX, CROP_PX);
    }
    ringed(paint, (cell.r / half) * (CROP_PX / 2));
  });
}

/** The target's own frame, as it was imaged. */
function targetFrame(src) {
  return smallPicture(src, (paint, img) => {
    if (img) paint.drawImage(img, 0, 0, CROP_PX, CROP_PX);
  });
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
   *   `fieldOf(cell)`  the field it was found in: the plan's position, and
   *                `picture`, where the field's small copy is (or null)
   *   `pictureOf(id)`  where the target's own frame is (or null)
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
    note.textContent = "overview crop · target frame — mark each ✓ or ✗";

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

    /** One card: the pictures, the caption, and the two marks. */
    const cardFor = (id) => {
      const cell = ctx.cellById(id);
      const card = document.createElement("div");
      card.className = "pair";

      const imgs = document.createElement("div");
      imgs.className = "imgs";
      imgs.append(fieldCrop(cell, ctx.fieldOf(cell)), targetFrame(ctx.pictureOf(id)));

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.append(document.createTextNode(
        `${cell.id} · ${(cell.x / 1000).toFixed(2)}, ${(cell.y / 1000).toFixed(2)} mm`));

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
      ctx.acquired().forEach((id) => pairs.append(cardFor(id)));
      sayTheTally();
    };

    rebuild();
    return { rebuild };
  },
};
