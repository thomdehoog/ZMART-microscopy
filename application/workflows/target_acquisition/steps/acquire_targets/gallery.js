/**
 * Step 9's channel — the acquired targets and their image pairs.
 *
 * Acquisition happens on the canvas, where the physical target tiles stand;
 * this is what stands beside it. A list of the tiles imaged so far, the way
 * the focus step lists its points, and under it one pair -- the overview crop
 * at the chosen tile and its acquired frame. Choosing a row chooses the tile
 * on the canvas, and pressing an acquired frame chooses its row.
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
  if (src) cv.dataset.picture = src;
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

/**
 * The field the target was found in, cropped to the exact physical window
 * acquired at target magnification. Its pixels are coarser, but its centre
 * and extent are identical, so differences are resolution rather than zoom.
 * `field` is the plan's position plus `picture`, the field's own
 * small copy, which covers exactly the frame.
 */
function fieldCrop(cell, field) {
  const frameUm = Number.isFinite(field.cropFrameUm) && field.cropFrameUm > 0
    ? field.cropFrameUm : Math.max(80, cell.r * 8);
  const half = frameUm / 2;
  const centreX = Number.isFinite(field.cropX) ? field.cropX : cell.x;
  const centreY = Number.isFinite(field.cropY) ? field.cropY : cell.y;
  const cv = smallPicture(field.picture, (paint, img) => {
    if (img) {
      const perUm = img.naturalWidth / field.frameUm;
      const sx = (centreX - half - (field.x - field.frameUm / 2)) * perUm;
      const sy = (centreY - half - (field.y - field.frameUm / 2)) * perUm;
      paint.drawImage(img, sx, sy, 2 * half * perUm, 2 * half * perUm, 0, 0, CROP_PX, CROP_PX);
    }
  });
  cv.dataset.comparison = "overview";
  cv.dataset.frameUm = String(frameUm);
  cv.dataset.centreX = String(centreX);
  cv.dataset.centreY = String(centreY);
  return cv;
}

/** The target's own frame, as it was imaged. */
function targetFrame(src, field) {
  const cv = smallPicture(src, (paint, img) => {
    if (img) paint.drawImage(img, 0, 0, CROP_PX, CROP_PX);
  });
  cv.dataset.comparison = "target";
  cv.dataset.frameUm = String(field.cropFrameUm ?? "");
  cv.dataset.centreX = String(field.cropX ?? "");
  cv.dataset.centreY = String(field.cropY ?? "");
  return cv;
}

import { sideGroup } from "../../../../framework/window/panels.js";

export default {
  id: "acquire",
  label: "Acquire Targets",

  /**
   * Build the channel and fill it from the run.
   *
   * `ctx` carries what this step works with and nothing else:
   *   `acquired`   the unique tile keys, in acquisition order
   *   `tileByKey`  the physical tile for an acquisition key
   *   `selected`   the key of the tile whose pair is shown, or null
   *   `select(key)` choose that tile, on the canvas as well as here
   *   `cellById`   a target's own details, for the crops and the caption
   *   `fieldOf(tile, cell)` the field it was found in: the plan's position, and
   *                `picture`, where the field's small copy is (or null)
   *   `pictureOf(key)` where that target tile's frame is (or null)
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

    /* Acquisition actions stand below the comparison: once there is a
       current pair, the two rerun choices belong directly beneath it. */
    const act = document.createElement("div");
    act.className = "acquire-action side-act";

    const listBox = sideGroup("Acquired target tiles");
    /* The list, in the focus step's own clothes: a row a target, the chosen
       one lit, the box capped and scrolling past its few rows. */
    const list = document.createElement("div");
    list.className = "point-list";
    list.id = "target-list";
    /* The list needs no instruction/tally strip: choosing a row is evident
       from the selected state and the comparison immediately below it. */
    listBox.body.append(list);

    /* The one pair on show: the chosen target's. */
    const pairBox = sideGroup("Overview crop · target frame");
    const pair = document.createElement("div");
    pair.className = "pairs";
    pair.id = "pairs";
    pairBox.body.append(pair);

    /* The settings the targets are imaged with were recorded on the step
       before, beside the selection; here the press stands over what it
       will make. */
    side.append(listBox.group, pairBox.group, act);
    host.append(side);

    const targetIdOf = (tile) => tile?.targetId ?? tile?.covers?.[0] ?? null;
    /* Only acquisition keys whose tile and anchor target the run still knows:
       a re-discovery invalidates the old ones, and an orphan card cannot say
       which overview field supplies its comparison. */
    const known = () => ctx.acquired().filter((key) => {
      const tile = ctx.tileByKey(key);
      return tile && ctx.cellById(targetIdOf(tile));
    });

    /** One row of the list: its place, its name, and where it is. */
    const rowFor = (key, index) => {
      const tile = ctx.tileByKey(key);
      const cell = ctx.cellById(targetIdOf(tile));
      const row = document.createElement("div");
      row.className = "point-row";
      row.dataset.target = key;
      row.setAttribute("aria-current", String(key === ctx.selected()));
      const pick = document.createElement("button");
      pick.className = "point-pick"; pick.type = "button";
      pick.setAttribute("aria-label", `choose target tile ${index + 1} for ${cell.id}`);
      const names = tile.covers?.length ? tile.covers.join(", ") : cell.id;
      pick.innerHTML =
        `<span class="idx">${index + 1}</span>` +
        `<span class="name">${names}</span>` +
        `<span>${(tile.x / 1000).toFixed(2)}, ${(tile.y / 1000).toFixed(2)} mm</span>`;
      pick.addEventListener("click", () => ctx.select(key));
      row.append(pick);
      return row;
    };

    /** The pair on show: the chosen target's pictures and caption. */
    const pairFor = (key, tile, cell, field, picture) => {
      const card = document.createElement("div");
      card.className = "pair";
      card.dataset.target = key;

      const imgs = document.createElement("div");
      imgs.className = "imgs";
      imgs.append(fieldCrop(cell, field), targetFrame(picture, field));

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.append(document.createTextNode(
        `${cell.id} · ${(tile.x / 1000).toFixed(2)}, ${(tile.y / 1000).toFixed(2)} mm`));

      card.append(imgs, meta);
      return card;
    };

    /* The list follows the run; the pair follows the choice. */
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
    };
    let pairShown = null;
    const showThePair = () => {
      const key = ctx.selected();
      const tile = key === null ? null : ctx.tileByKey(key);
      const cell = tile ? ctx.cellById(targetIdOf(tile)) : null;
      const field = cell ? ctx.fieldOf(tile, cell) : null;
      const picture = key === null ? null : ctx.pictureOf(key);
      /* Display controls change the query on these addresses without changing
         the selected target. Key the cache by the actual pictures, so the
         visible pair refreshes immediately instead of waiting for the user to
         select another row and come back. */
      const signature = key === null ? null : `${key}\u0000${field?.picture ?? ""}\u0000${picture ?? ""}`;
      if (signature === pairShown && pair.childElementCount) return;
      pairShown = signature;
      pair.textContent = "";
      if (key !== null && tile && cell) pair.append(pairFor(key, tile, cell, field, picture));
    };

    const rebuild = () => {
      /* A choice outlives a rebuild while its target is still acquired; a
         run that has just begun, or lost the chosen one, shows the newest.
         Until something is acquired there is nothing to list or to show,
         and the boxes wait rather than stand empty. */
      const ids = known();
      listBox.group.hidden = !ids.length;
      pairBox.group.hidden = !ids.length;
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
