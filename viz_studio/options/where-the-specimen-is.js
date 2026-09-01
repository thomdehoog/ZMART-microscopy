/**
 * Where the specimen actually is, as against where the run declared room for it.
 *
 * Shared by every option, the way `planes.js` and `brightness.js` are, and for
 * the same reason: it is a fact about the file rather than about a drawing
 * engine.
 *
 * ## Why this exists
 *
 * A run declares the ground it might cover and then images part of it. Opening on
 * the middle of the declared ground is therefore opening on the middle of the
 * *room*, which is only the middle of the specimen when the specimen fills it.
 *
 * Measured on a 75 GB skin biopsy: the tissue's centre of mass sits at plane 467
 * of 833 where the declared middle is 417, and at 56% and 54% of the height and
 * width where the declared middle is 50%. So the view opened about 250 µm away
 * from the specimen in depth and a couple of hundred laterally.
 *
 * On a flat picture that is a slightly off-centre opening view, which an operator
 * corrects with one drag and never thinks about again. **In a volume it is the
 * point the specimen turns about**, and turning something about a point outside
 * it makes it swing rather than rotate — which is how this was noticed, by
 * somebody rotating a biopsy and saying the centre looked wrong.
 *
 * It is the same fault as three others met the same day, and worth naming as one:
 * a *declared* extent standing in for what is actually there. The first plane of
 * a stack, the camera's full range as a display window, the middle of a declared
 * canvas — each read the description where it should have read the picture.
 *
 * ## What it reads, and what it costs
 *
 * The smallest copy in the pyramid, whole. That is the one read where reading all
 * of it is cheap — a few hundred thousand numbers for a store of tens of
 * gigabytes — and where the averaging that makes coarse copies useless for
 * *extremes* is harmless: a centre of mass is a bulk property, and averaging
 * neighbours barely moves it.
 *
 * Everything below a floor is discarded before weighing, because background is
 * most of a light-sheet acquisition by volume and would drag the answer back
 * towards the middle of the room — which is the very thing being corrected.
 */

import { loadOmeZarr } from "@vivjs/loaders";

/** What counts as specimen rather than background, when weighing where it is. */
const THE_FLOOR = 0.8;

/**
 * The most values one plane of "the smallest copy" may hold before this
 * refuses to read it at all.
 *
 * The whole design of this file rests on the smallest copy being cheap, and
 * for an ordinary store it is: a deep pyramid ends in a plane of a few
 * hundred thousand values. A *linked scene* breaks the assumption — it keeps
 * only as many levels as the little position stores it links, so the scene of
 * a whole plate ends in a "smallest" copy of hundreds of megavalues, every
 * one composed on demand out of dozens of stores. Asking for that did not
 * merely open the view in an odd place: it held the viewer's whole open for
 * minutes, the open's own time limit killed it, and the retry asked again —
 * the canvas stayed empty for ever with nothing on screen to say why.
 *
 * Four thousand squared is roomy for every honest smallest copy met so far
 * and refuses the pathological ones. Refusing costs only the centred opening
 * view: the caller keeps the middle of the declared ground.
 */
const A_COPY_WORTH_READING = 4096 * 4096;

/**
 * The centre of mass of whatever is bright, along each axis, in voxels.
 *
 * @param {ArrayLike<number>} values the copy, flat, in the order `sizes` gives.
 * @param {number[]} sizes how long that copy is along each axis, slowest first.
 * @returns {number[]|null} where the specimen sits along each axis, in voxels, or
 *   nothing when there is no specimen to find — a flat picture has no centre of
 *   mass worth the name, and saying so lets the caller keep the geometric middle.
 */
export function theMiddleOfWhatWasImaged(values, sizes) {
  if (!values?.length || !sizes?.length) return null;
  const sorted = Float64Array.from(values).sort();
  const floor = sorted[Math.round(THE_FLOOR * (sorted.length - 1))];
  const top = sorted[sorted.length - 1];
  if (!(top > floor)) return null;

  const weightAlong = sizes.map((along) => new Float64Array(along));
  let total = 0;
  for (let at = 0; at < values.length; at += 1) {
    const weight = values[at] - floor;
    if (weight <= 0) continue;
    total += weight;
    /* Which voxel this is, worked out from the flat index rather than by walking
       the axes, so this stays one pass however many axes the store has. */
    let left = at;
    for (let axis = sizes.length - 1; axis >= 0; axis -= 1) {
      weightAlong[axis][left % sizes[axis]] += weight;
      left = Math.floor(left / sizes[axis]);
    }
  }
  if (!(total > 0)) return null;
  return weightAlong.map((along) => {
    let sum = 0;
    for (let at = 0; at < along.length; at += 1) sum += at * along[at];
    return sum / total;
  });
}

/**
 * Where the specimen sits, from resolutions somebody has already opened.
 *
 * @param {Array<object>} sources the image's resolutions, sharpest first.
 * @returns {Promise<Object<string, number>|null>} a position in voxels of the
 *   *sharpest* copy, per axis name, or nothing when it cannot be read. Given in
 *   the sharpest copy's voxels because that is what every caller counts in.
 */
export async function whereTheSpecimenIs(sources) {
  const smallest = sources?.[sources.length - 1];
  const sharpest = sources?.[0];
  if (!smallest || !sharpest) return null;
  try {
    const labels = smallest.labels || [];
    const deep = labels.indexOf("z") >= 0
      ? smallest.shape[labels.indexOf("z")] : 1;

    /* Is the smallest copy actually small? See A_COPY_WORTH_READING. */
    const planeHolds = ["y", "x"]
      .map((name) => (labels.indexOf(name) >= 0 ? smallest.shape[labels.indexOf(name)] : 1))
      .reduce((held, along) => held * along, 1);
    if (planeHolds > A_COPY_WORTH_READING) {
      console.warn(
        `the smallest copy of this image holds ${planeHolds.toLocaleString()} ` +
          "values per plane, which is too large to read just to centre the " +
          "opening view — the view opens on the middle of the declared ground instead.",
      );
      return null;
    }

    /* A plane at a time, and not every plane.
     *
     * A reader hands back one plane per ask — there is no call for a block — so
     * the whole of even the smallest copy would be one round trip per plane, and
     * a hundred round trips to answer a question about where the middle is would
     * be worse than not asking. Twelve spread through the stack put the answer
     * within a plane or two of the true centre on the biopsy this was written
     * for, which is far inside the error it is correcting.
     *
     * The first version of this read one raster and treated it as though it held
     * the whole stack. It cost nothing to run and gave a confident wrong answer:
     * a centre 1400 µm from the specimen, in the wrong direction. A wrong answer
     * that looks like a right one is the failure this project keeps meeting.
     */
    const asksAllowed = Math.min(deep, 12);
    const alongZ = [];
    let flat = null;
    let across = 0;
    for (let which = 0; which < asksAllowed; which += 1) {
      const plane = deep <= 1
        ? 0
        : Math.round((which + 0.5) * (deep / asksAllowed));
      const selection = {};
      labels.forEach((name) => {
        if (name === "x" || name === "y") return;
        selection[name] = name === "z" ? Math.min(plane, deep - 1) : 0;
      });
      const raster = await smallest.getRaster({ selection });
      const values = raster?.data;
      if (!values?.length) continue;
      across = raster.width ?? across;
      if (!flat) flat = new Float64Array(values.length);
      /* How much *specimen* this plane holds, not how much light. Summing the
         raw values was tried and follows the background, which is most of a
         light-sheet acquisition by volume: on the biopsy it put the answer at
         plane 380 where the tissue's centre is 467 — off in the opposite
         direction from the fault being corrected. Each plane is therefore weighed
         against its own floor, and only what stands above it counts. */
      const sorted = Float64Array.from(values).sort();
      const floor = sorted[Math.round(THE_FLOOR * (sorted.length - 1))];
      let mass = 0;
      for (let at = 0; at < values.length; at += 1) {
        const above = values[at] - floor;
        if (above <= 0) continue;
        flat[at] += above;
        mass += above;
      }
      alongZ.push({ plane: Math.min(plane, deep - 1), mass });
    }
    if (!flat || !alongZ.length) return null;

    const height = across > 0 ? Math.round(flat.length / across) : 0;
    const middle = theMiddleOfWhatWasImaged(flat, [height, across]);
    if (!middle) return null;

    /* Depth is weighed across the planes that were asked for, with the same floor
       taken over their masses: a stack is mostly background by volume, and
       weighing every plane equally would put the answer back in the middle. */
    const masses = alongZ.map((step) => step.mass).sort((a, b) => a - b);
    const floor = masses[Math.round(THE_FLOOR * (masses.length - 1))];
    let weighted = 0;
    let total = 0;
    for (const step of alongZ) {
      const above = step.mass - floor;
      if (above <= 0) continue;
      weighted += step.plane * above;
      total += above;
    }

    const coarse = { y: height, x: across, z: deep };
    const at = {};
    for (const [name, value] of [["y", middle[0]], ["x", middle[1]],
                                 ["z", total > 0 ? weighted / total : null]]) {
      if (value === null) continue;
      const which = sharpest.labels.indexOf(name);
      if (which < 0) continue;
      at[name] = value * (sharpest.shape[which] / Math.max(coarse[name], 1));
    }
    return Object.keys(at).length ? at : null;
  } catch (whyNot) {
    /* Not being able to find the specimen is not a reason to refuse to draw it:
       the caller keeps the middle of the declared ground, which is where every
       view opened until now. Said out loud because a view that opens in a
       slightly odd place is exactly the kind of thing nobody reports. */
    console.warn("could not work out where the specimen is", whyNot);
    return null;
  }
}

/**
 * The same, for an option that has only the address.
 *
 * Neuroglancer reads a store in order to build its layers and then keeps it to
 * itself, so its adapter has to ask for the image separately — exactly as it does
 * for the display window. One small read of the smallest copy.
 *
 * @param {string} url the store's address; anything after a `|` is a reader's own
 *   suffix and is taken off.
 */
export async function whereTheSpecimenIsInThisStore(url) {
  const bar = url.indexOf("|");
  const address = (bar < 0 ? url : url.slice(0, bar)).replace(/\/+$/, "");
  try {
    const opened = await loadOmeZarr(address, { type: "multiscales" });
    return whereTheSpecimenIs(opened?.data);
  } catch (whyNot) {
    console.warn(`could not work out where the specimen is in ${address}`, whyNot);
    return null;
  }
}
