/**
 * Looking at what the page actually put on screen.
 *
 * Most of what a test can ask a viewer is about itself: did the loader resolve,
 * how many layers are open, did anything print an error. Those are useful
 * questions and they all share one blind spot — the engine can answer every one
 * of them correctly and still draw nothing at all. That is not hypothetical; it
 * is the failure this project has met several times, and it is why the viewer
 * keeps a companion to this file at `viz_studio/tests/pixels.py`. This is the
 * same two measurements, for the tests that drive the operator page.
 *
 * So: photograph the canvas, and measure the photograph. It is a deliberately
 * blunt instrument. It cannot tell you the picture is *correct*, only that there
 * is a picture rather than an empty panel — which turns out to be the check that
 * keeps being missing.
 *
 * There is no image library here. A screenshot comes back as a PNG, and Node can
 * already undo the compression inside one, so the few lines it takes to read the
 * pixels out are written below rather than adding something to install.
 */

import zlib from "node:zlib";

/* How much of the picture to look at: the middle half of it, in both
   directions. The middle rather than the whole, because the page draws its own
   controls and readouts over the corners of the canvas, and those would supply
   variety of their own. A measurement that counted them could not tell a drawn
   overview from an empty panel with a label on it, which is the very mistake
   this is here to prevent. */
const MIDDLE = 0.5;

/** How bright a pixel has to be to count as picture rather than background. */
const LIT = 40;

/**
 * Read a PNG into plain pixels.
 *
 * Handles what a browser screenshot actually is — eight bits a channel, colour
 * or colour with transparency, not interlaced — and refuses anything else rather
 * than quietly returning something wrong.
 *
 * @param buffer the PNG file, as bytes.
 * @returns `{ width, height, channels, data }`, where `data` runs row by row and
 *   left to right, with `channels` numbers per pixel.
 */
export function readPng(buffer) {
  if (buffer.readUInt32BE(0) !== 0x89504e47) throw new Error("this is not a PNG");

  let at = 8;                       // past the eight bytes that say "PNG"
  let header = null;
  const parts = [];
  while (at < buffer.length) {
    const length = buffer.readUInt32BE(at);
    const kind = buffer.toString("ascii", at + 4, at + 8);
    const body = buffer.subarray(at + 8, at + 8 + length);
    if (kind === "IHDR") {
      header = {
        width: body.readUInt32BE(0),
        height: body.readUInt32BE(4),
        depth: body[8],
        colour: body[9],
        interlace: body[12],
      };
    } else if (kind === "IDAT") {
      parts.push(body);
    } else if (kind === "IEND") {
      break;
    }
    at += length + 12;              // length, kind, body, and the checksum
  }
  if (!header) throw new Error("this PNG has no header in it");
  if (header.depth !== 8 || header.interlace !== 0 || ![2, 6].includes(header.colour)) {
    throw new Error(
      `this PNG is stored in a way these tests do not read: ${JSON.stringify(header)}`);
  }

  const channels = header.colour === 6 ? 4 : 3;
  const { width, height } = header;
  const raw = zlib.inflateSync(Buffer.concat(parts));
  const stride = width * channels;
  const data = Buffer.alloc(height * stride);

  /* Every row of a PNG is stored as the difference from something already
     known — the pixel to its left, the row above, or a mixture — because
     differences compress far better than the values themselves. Undoing that is
     the whole of what follows: one rule per row, applied left to right. */
  for (let row = 0; row < height; row++) {
    const rule = raw[row * (stride + 1)];
    const from = row * (stride + 1) + 1;
    for (let i = 0; i < stride; i++) {
      const value = raw[from + i];
      const left = i >= channels ? data[row * stride + i - channels] : 0;
      const above = row > 0 ? data[(row - 1) * stride + i] : 0;
      const aboveLeft = row > 0 && i >= channels ? data[(row - 1) * stride + i - channels] : 0;
      let base = 0;
      if (rule === 1) base = left;
      else if (rule === 2) base = above;
      else if (rule === 3) base = (left + above) >> 1;
      else if (rule === 4) {
        // The "Paeth" rule: whichever of the three neighbours the row above
        // suggests is the closest guess.
        const guess = left + above - aboveLeft;
        const dLeft = Math.abs(guess - left);
        const dAbove = Math.abs(guess - above);
        const dAboveLeft = Math.abs(guess - aboveLeft);
        base = dLeft <= dAbove && dLeft <= dAboveLeft ? left : (dAbove <= dAboveLeft ? above : aboveLeft);
      } else if (rule !== 0) {
        throw new Error(`this PNG row uses a rule these tests do not read: ${rule}`);
      }
      data[row * stride + i] = (value + base) & 0xff;
    }
  }
  return { width, height, channels, data };
}

/**
 * Photograph the middle of a canvas on the page.
 *
 * This is what the operator would see, taken off the screen with everything
 * drawn onto it — rather than a number the drawing engine reports about itself.
 * That distinction is the whole point.
 *
 * @param page the Playwright page.
 * @param selector which canvas to photograph.
 * @returns the pixels, ready for the two measurements below.
 */
export async function photograph(page, selector, share = MIDDLE) {
  const box = await page.locator(selector).boundingBox();
  if (!box) throw new Error(`there is no ${selector} on the page to photograph`);
  const margin = (1 - share) / 2;
  const shot = await page.screenshot({
    clip: {
      x: box.x + box.width * margin,
      y: box.y + box.height * margin,
      width: box.width * share,
      height: box.height * share,
    },
  });
  return readPng(shot);
}

/**
 * Whether one pixel is showing picture rather than background.
 *
 * `only` narrows the question to one of red, green or blue. That is worth having
 * when more than one thing is on screen and they are different colours: asking
 * about green alone finds the specimen, whatever has been drawn around it.
 */
const isLit = ({ data, channels }, x, y, width, floor, only = null) => {
  const at = (y * width + x) * channels;
  if (only !== null) return data[at + only] > floor;
  return Math.max(data[at], data[at + 1], data[at + 2]) > floor;
};

/**
 * The rectangle of the photograph that has any picture in it at all.
 *
 * This is what makes it possible to ask *where* something was drawn without
 * knowing how the page happened to frame it. The overview is drawn with a margin
 * around it, and how wide that margin is depends on the shape of the panel — but
 * the lit part is the overview, so finding its edges gives the picture's own
 * coordinates to measure in.
 *
 * @returns `{ left, top, right, bottom }`, the last two not included, or `null`
 *   if nothing at all was drawn.
 */
export function litBounds(pixels, { floor = LIT, only = null } = {}) {
  const { width, height } = pixels;
  let left = width;
  let top = height;
  let right = 0;
  let bottom = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!isLit(pixels, x, y, width, floor, only)) continue;
      if (x < left) left = x;
      if (x >= right) right = x + 1;
      if (y < top) top = y;
      if (y >= bottom) bottom = y + 1;
    }
  }
  return right > left && bottom > top ? { left, top, right, bottom } : null;
}

/**
 * How lit each square of a grid laid over the picture is.
 *
 * Laid over the lit part of the photograph rather than the whole of it, so the
 * squares line up with the run's own tiles however the page framed it. With a
 * five by five grid over a run of five by five positions, this answers "which
 * positions have been imaged, and are they in the right places" — the question
 * that matters when most of a canvas is room that was declared and never
 * written.
 *
 * Pass `over` to measure against a rectangle worked out from another
 * photograph. That is what to do when comparing several pictures of the same
 * run — one plane of a stack may light less of each tile than another, which
 * would move the edges and quietly measure a different grid each time.
 *
 * @returns rows of numbers between 0 and 1, top row first, or `null` when
 *   nothing was drawn at all.
 */
export function litGrid(pixels, cells, { floor = LIT, over = null, inset = 0.3 } = {}) {
  const bounds = over ?? litBounds(pixels, { floor });
  if (!bounds) return null;
  const { width } = pixels;
  const across = (bounds.right - bounds.left) / cells;
  const down = (bounds.bottom - bounds.top) / cells;
  const grid = [];
  for (let row = 0; row < cells; row++) {
    const line = [];
    for (let col = 0; col < cells; col++) {
      /* The middle of each square rather than the whole of it, because the edges
         of neighbouring squares meet exactly where one tile stops and the next
         begins, and a pixel either side of that line is ambiguous. How much of
         the middle is `inset`: a small one takes in nearly the whole square,
         which is what to use when the picture only fills part of it. */
      const x0 = Math.round(bounds.left + (col + inset) * across);
      const x1 = Math.round(bounds.left + (col + 1 - inset) * across);
      const y0 = Math.round(bounds.top + (row + inset) * down);
      const y1 = Math.round(bounds.top + (row + 1 - inset) * down);
      let lit = 0;
      let seen = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          if (isLit(pixels, x, y, width, floor)) lit += 1;
          seen += 1;
        }
      }
      line.push(seen ? lit / seen : 0);
    }
    grid.push(line);
  }
  return grid;
}

/**
 * How much of the picture is showing specimen rather than nothing.
 *
 * This asks a different question from {@link colourSpread}, and the difference
 * matters more than it sounds. Counting colours is the right question when the
 * worry is a viewer that drew nothing at all, but it cannot tell a blank panel
 * from one completely covered by an even tile: both are one flat colour and both
 * score the same. A canvas being filled in tile by tile passes through exactly
 * that state, so a test watching for variety would report the picture vanishing
 * at the moment it became complete.
 *
 * Counting how much of the view is brighter than the background separates the
 * two, and it rises steadily as tiles land — which is what a test following a
 * scan needs. The floor sits well above the near-black of a region nothing has
 * been written to and well below any real signal, so it is not sensitive to
 * where exactly it is set.
 *
 * @returns a share between 0 and 1.
 */
export function fractionLit({ data, channels }, floor = LIT) {
  let lit = 0;
  let pixels = 0;
  for (let at = 0; at < data.length; at += channels) {
    const brightest = Math.max(data[at], data[at + 1], data[at + 2]);
    if (brightest > floor) lit += 1;
    pixels += 1;
  }
  return lit / pixels;
}

/**
 * The average colour of each square of a grid laid over the picture.
 *
 * Where {@link litGrid} asks "is there anything here", this asks "what colour is
 * it" — which is the question when something has been drawn *underneath* the
 * image and what matters is whether it shows through.
 *
 * @returns rows of `[red, green, blue]`, top row first.
 */
export function meanGrid(pixels, cells, { over = null } = {}) {
  const bounds = over ?? { left: 0, top: 0, right: pixels.width, bottom: pixels.height };
  const { width, data, channels } = pixels;
  const across = (bounds.right - bounds.left) / cells;
  const down = (bounds.bottom - bounds.top) / cells;
  const grid = [];
  for (let row = 0; row < cells; row++) {
    const line = [];
    for (let col = 0; col < cells; col++) {
      const x0 = Math.round(bounds.left + (col + 0.3) * across);
      const x1 = Math.round(bounds.left + (col + 0.7) * across);
      const y0 = Math.round(bounds.top + (row + 0.3) * down);
      const y1 = Math.round(bounds.top + (row + 0.7) * down);
      const total = [0, 0, 0];
      let seen = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const at = (y * width + x) * channels;
          for (let c = 0; c < 3; c++) total[c] += data[at + c];
          seen += 1;
        }
      }
      line.push(seen ? total.map((sum) => Math.round(sum / seen)) : [0, 0, 0]);
    }
    grid.push(line);
  }
  return grid;
}

/**
 * How much of the picture is one particular colour.
 *
 * This is the measurement for a layer the page drew itself. Asking whether
 * anything was drawn is not enough when the question is *which* of several
 * drawings reached the screen — a picture is full of colours already, and a
 * layer switched on adds one more. Counting the pixels that are close to the
 * colour the page used answers that, and answers it from a photograph rather
 * than from the page's opinion of itself.
 *
 * Close rather than exact, because a colour does not always survive the journey
 * unchanged. A drawing composited into another surface, or drawn with smoothed
 * edges, comes back a shade or two out. The allowance is wide enough to survive
 * that and far narrower than the distance between any two colours these tests
 * ask about.
 *
 * @param pixels a photograph, from {@link photograph}.
 * @param colour the colour to look for, as red, green and blue from 0 to 255.
 * @param allowance how far each of the three may be out and still count.
 * @returns a share between 0 and 1.
 */
export function fractionNear({ data, channels }, [red, green, blue], allowance = 24) {
  let near = 0;
  let pixels = 0;
  for (let at = 0; at < data.length; at += channels) {
    if (Math.abs(data[at] - red) <= allowance
      && Math.abs(data[at + 1] - green) <= allowance
      && Math.abs(data[at + 2] - blue) <= allowance) near += 1;
    pixels += 1;
  }
  return near / pixels;
}

/**
 * How much variety there is in the picture.
 *
 * Three numbers that say the same thing from different angles, because any one
 * of them alone is easy to fool: how many different colours appear (a panel
 * showing nothing has one), what share of it is taken up by its commonest colour
 * (one means every pixel is identical), and how far a typical pixel sits from
 * the average (zero means perfectly flat).
 */
export function colourSpread({ data, channels }) {
  const seen = new Map();
  let total = 0;
  let sum = 0;
  let sumOfSquares = 0;
  for (let at = 0; at < data.length; at += channels) {
    const colour = (data[at] << 16) | (data[at + 1] << 8) | data[at + 2];
    seen.set(colour, (seen.get(colour) ?? 0) + 1);
    for (let c = 0; c < 3; c++) {
      sum += data[at + c];
      sumOfSquares += data[at + c] ** 2;
    }
    total += 1;
  }
  const values = total * 3;
  const mean = sum / values;
  return {
    distinct: seen.size,
    dominantFraction: Math.max(...seen.values()) / total,
    spread: Math.sqrt(Math.max(0, sumOfSquares / values - mean * mean)),
  };
}
