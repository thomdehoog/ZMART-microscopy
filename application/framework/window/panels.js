/**
 * The boxes that stand down the channel beside the canvas.
 *
 * Every step's controls live in one or more of these: a heading naming what the
 * box is for, and a card holding the controls themselves. One shape, on every
 * step, because two shapes would read as two kinds of thing and these are not.
 *
 * The heading sits *above* its card rather than inside it, so the card holds
 * controls and nothing else. That is a decision the stylesheet makes as much as
 * this file does — see `.side-group`, `.side-group-title` and `.side-group-body`
 * in `framework/window/style.css`, which is where the spacing and the reasoning behind it
 * are written down.
 *
 * ## A note on where this came from
 *
 * This file was missing from the branch that introduced it: three modules
 * imported `sideGroup` from here and the file itself was never committed, so
 * the page would not load at all. It has been written back from what the rest
 * of the code requires of it — the three call sites fix the interface, and the
 * stylesheet names every class and says how they nest. So it is a
 * reconstruction rather than a recovery, and if the original had anything more
 * in it, that is where the difference will be.
 */

/**
 * Make one box for the channel: a heading, and a card to put controls in.
 *
 * @param title what the box is for, shown above the card.
 * @param extra an optional further class on the box, for the few places that
 *   need to style one differently — the carrier's layout box asks for
 *   `carrier-sizes`, which gives it a little more room inside.
 * @returns `{ group, body }` — `group` is the whole box, to be added to the
 *   channel, and `body` is the card inside it, which is where controls go.
 *   Both are handed back because callers need them for different things: the
 *   box is what gets placed, the card is what gets filled.
 */
export function sideGroup(title, extra) {
  const group = document.createElement("div");
  group.className = extra ? `side-group ${extra}` : "side-group";

  const heading = document.createElement("div");
  heading.className = "side-group-title";
  heading.textContent = title;

  const body = document.createElement("div");
  body.className = "side-group-body";

  group.append(heading, body);
  return { group, body };
}
