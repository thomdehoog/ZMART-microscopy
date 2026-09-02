/**
 * Step 8's channel — the acquired targets, and the verdict on each.
 *
 * Acquisition happens on the canvas, where the targets ring; this is what
 * stands beside it. A list of the targets imaged so far, the way the focus
 * step lists its points, and under it one pair -- the field the chosen
 * target was found in and its own frame -- with the two marks that call it
 * kept or discarded. Choosing a row chooses the target on the canvas, and a
 * press on a ringed target on the canvas chooses its row. Above them, the
 * recording the targets are imaged with.
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

/** How the targets are counted, in the words the readout uses. */
export function galleryTally(acquired, verdicts) {
  const marked = acquired.filter((id) => verdicts[id]).length;
  const good = acquired.filter((id) => verdicts[id] === "good").length;
  return acquired.length
    ? `${acquired.length} targets · ${marked} marked · ${good} good`
    : "—";
}

/** The glyph a verdict is listed under. */
const VERDICT_GLYPH = { good: "✓", bad: "✗" };

import { sideGroup } from "../../../../framework/window/panels.js";

export default {
  id: "acquire",
  label: "Acquire Targets",

  /**
   * Build the channel and fill it from the run.
   *
   * `ctx` carries what this step works with and nothing else:
   *   `acquired`   the target ids, in the order they were imaged
   *   `verdicts`   id -> "good" | "bad" | null, changed here
   *   `selected`   the id of the target whose pair is shown, or null
   *   `select(id)` choose that target, on the canvas as well as here
   *   `cellById`   a target's own details, for the crops and the caption
   *   `fieldOf(cell)`  the field it was found in: the plan's position, and
   *                `picture`, where the field's small copy is (or null)
   *   `pictureOf(id)`  where the target's own frame is (or null)
   *   `recordingSlot(host, opts)`  the shared recorder, for the acquisition type
   *   `changed()`  say that something the rest of the page shows has changed
   *
   * Returns a handle whose `rebuild()` fills the list in again — what the
   * step's own run calls as the targets are acquired — and whose `chosen()`
   * answers a choice made on the canvas.
   */
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "gallery-side";

    /* The step's own press at the top of its channel, like the others. */
    const act = document.createElement("div");
    act.className = "acquire-action side-act";

    /* What the targets are imaged with, read off the instrument here -- the
       shared recording slot, which brings its own boxed group the way the
       scan area's does on step 3. */
    const recording = document.createElement("div");
    recording.id = "target-type";

    const listBox = sideGroup("Acquired targets");
    const about = document.createElement("div");
    about.className = "gallery-about";
    const note = document.createElement("div");
    note.className = "side-note";
    note.textContent = "choose a target here or on the canvas — mark it ✓ or ✗";
    const readout = document.createElement("span");
    readout.className = "readout";
    readout.id = "gallery-readout";
    readout.textContent = "—";
    about.append(note, readout);

    /* The list, in the focus step's own clothes: a row a target, the chosen
       one lit, the box capped and scrolling past its few rows. */
    const list = document.createElement("div");
    list.className = "point-list";
    list.id = "target-list";
    listBox.body.append(about, list);

    /* The one pair on show: the chosen target's. */
    const pairBox = sideGroup("Overview crop · target frame");
    const pair = document.createElement("div");
    pair.className = "pairs";
    pair.id = "pairs";
    pairBox.body.append(pair);

    /* Settle what to image first, then press: the run stands under the
       settings it will image with, the way Segment all stands under its. */
    side.append(recording, act, listBox.group, pairBox.group);
    host.append(side);

    ctx.recordingSlot(recording, {
      /* The same opening as the scan area's and the focus step's: the
         configuration is read off the instrument and named after what it
         is, imported with one press. */
      label: "Target acquisition settings", key: "targetType",
      unnamed: true,
      takes: "Import target acquisition settings",
      retakes: "Update",
      changed: () => ctx.changed(),
    });

    const sayTheTally = () => {
      readout.textContent = galleryTally(ctx.acquired(), ctx.verdicts());
    };

    /* Only ids the run still knows: a re-discovery invalidates the old
       ones, and a card for a cell nobody can look up crashed the panel. */
    const known = () => ctx.acquired().filter((id) => ctx.cellById(id));

    /** One row of the list: its place, its name, where it is, its verdict. */
    const rowFor = (id, index) => {
      const cell = ctx.cellById(id);
      const verdict = ctx.verdicts()[id] ?? null;
      const row = document.createElement("div");
      row.className = "point-row";
      row.dataset.target = id;
      row.setAttribute("aria-current", String(id === ctx.selected()));
      const pick = document.createElement("button");
      pick.className = "point-pick"; pick.type = "button";
      pick.setAttribute("aria-label", `choose target ${cell.id}`);
      pick.innerHTML =
        `<span class="idx">${index + 1}</span>` +
        `<span class="name">${cell.id}</span>` +
        `<span>${(cell.x / 1000).toFixed(2)}, ${(cell.y / 1000).toFixed(2)} mm</span>` +
        `<span class="z verdict-${verdict ?? "none"}">${VERDICT_GLYPH[verdict] ?? "—"}</span>`;
      pick.addEventListener("click", () => ctx.select(id));
      row.append(pick);
      return row;
    };

    /** The pair on show: the chosen target's pictures, caption and marks. */
    const pairFor = (id) => {
      const cell = ctx.cellById(id);
      const card = document.createElement("div");
      card.className = "pair";
      card.dataset.target = id;

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
        mark.setAttribute("aria-pressed", String(ctx.verdicts()[id] === kind));
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
          showTheList();
        });
        marks.push(mark);
        verdict.append(mark);
      }
      meta.append(verdict);
      card.append(imgs, meta);
      return card;
    };

    /* The list and the tally follow the run; the pair follows the choice.
       Redrawn apart, so marking a target does not fetch its pictures again. */
    const showTheList = () => {
      list.textContent = "";
      const ids = known();
      if (!ids.length) {
        const none = document.createElement("div");
        none.className = "none";
        none.textContent = "Nothing acquired yet.";
        list.append(none);
      }
      ids.forEach((id, index) => list.append(rowFor(id, index)));
      sayTheTally();
    };
    let pairShown = null;
    const showThePair = () => {
      const id = ctx.selected();
      if (id === pairShown && pair.childElementCount) return;
      pairShown = id;
      pair.textContent = "";
      if (id !== null && ctx.cellById(id)) pair.append(pairFor(id));
    };

    const rebuild = () => {
      /* A choice outlives a rebuild while its target is still acquired; a
         run that has just begun, or lost the chosen one, shows the newest. */
      const ids = known();
      if (!ids.includes(ctx.selected())) ctx.select(ids.at(-1) ?? null, { quietly: true });
      showTheList();
      showThePair();
    };

    rebuild();
    return {
      rebuild,
      /** The choice changed -- here, or on the canvas. */
      chosen() {
        for (const row of list.querySelectorAll(".point-row")) {
          row.setAttribute("aria-current", String(row.dataset.target === ctx.selected()));
        }
        showThePair();
      },
    };
  },
};
