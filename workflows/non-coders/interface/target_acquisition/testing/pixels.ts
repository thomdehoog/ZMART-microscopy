/**
 * Looking at what the page actually put on screen.
 *
 * Most of what a test can ask a viewer is about itself: did the loader resolve,
 * how many layers are open, did anything print an error. Those are useful
 * questions and they all share one blind spot — the engine can answer every one
 * of them correctly and still draw nothing at all. That is not hypothetical; it
 * is the failure this project has met several times, and it is why the viewer
 * keeps a companion to this file at `viz_studio/tests/pixels.py` (in ZMART-microscopy). This is the
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
import type { Page } from "@playwright/test";

/** A photograph read into pixels: `data` runs row by row, `channels` numbers a pixel. */
export interface Pixels {
  width: number;
  height: number;
  channels: number;
  data: Buffer;
}

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
export function readPng(buffer: Buffer): Pixels {
  if (buffer.readUInt32BE(0) !== 0x89504e47) throw new Error("this is not a PNG");

  let at = 8;                       // past the eight bytes that say "PNG"
  let header: { width: number; height: number; depth: number; colour: number; interlace: number } | null = null;
  const parts: Buffer[] = [];
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
export async function photograph(page: Page, selector: string, share = MIDDLE): Promise<Pixels> {
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
 * How far one drawing sits from another on the same photograph, in pixels.
 *
 * Two yes-or-no maps of the same size -- where the masks are, where the
 * nuclei are -- and the shift of the first that lays it best over the second,
 * searched over a small square of shifts. `{ dx, dy, score }`, where a
 * positive `dx` means the first map had to move right to fit. The score is
 * the overlap at that shift as a fraction of the first map's area, so a
 * drawing that lands on nothing at any shift scores near zero.
 */
export function bestShift(first: ArrayLike<unknown>, second: ArrayLike<unknown>, width: number, height: number, reach = 12) {
  let best = { dx: 0, dy: 0, score: -1 };
  let area = 0;
  for (let i = 0; i < first.length; i++) area += first[i] ? 1 : 0;
  if (!area) return { dx: 0, dy: 0, score: 0 };
  for (let dy = -reach; dy <= reach; dy++) {
    for (let dx = -reach; dx <= reach; dx++) {
      let hit = 0;
      for (let y = Math.max(0, -dy); y < Math.min(height, height - dy); y++) {
        const from = y * width;
        const to = (y + dy) * width + dx;
        for (let x = Math.max(0, -dx); x < Math.min(width, width - dx); x++) {
          if (first[from + x] && second[to + x]) hit++;
        }
      }
      const score = hit / area;
      if (score > best.score) best = { dx, dy, score };
    }
  }
  return best;
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
export function fractionLit({ data, channels }: Pixels, floor = LIT): number {
  let lit = 0;
  let pixels = 0;
  for (let at = 0; at < data.length; at += channels) {
    const brightest = Math.max(data[at], data[at + 1], data[at + 2]);
    if (brightest > floor) lit += 1;
    pixels += 1;
  }
  return lit / pixels;
}
