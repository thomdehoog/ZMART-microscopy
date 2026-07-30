/**
 * The two ways of moving around, and nothing else.
 *
 * `viz_studio/CONTROLS.md` settles this for the flat view: **dragging pans, and
 * the plain scroll wheel zooms.** Everything else that could change where the
 * operator is or which way they are facing has been taken away — rotating with
 * shift and drag, rotating with `r` and `e`, tilting with shift and the arrow
 * keys, stepping through the stack on the wheel, zooming with ctrl and the
 * wheel, and recentring with the right button.
 *
 * Note that this is *not* what the drawing engine does by default. Left to
 * itself the engine steps through the stack on the plain wheel and wants ctrl
 * held down to zoom, which is a perfectly sensible choice for someone reading
 * through a volume and the wrong one for a microscopist looking at a plate. The
 * engine also binds rotation four different ways, and a rotated flat view stops
 * lining up with the carrier outline and the tile rectangles drawn over it while
 * nothing at all reports that it has.
 *
 * In this arrangement the operator's own sheet lies over the engine and catches
 * every gesture, so the engine never receives one and its own table is never
 * consulted. That removes the engine's defaults as a hazard and puts the whole
 * of the responsibility here instead — which is why the removals below are
 * written out one by one rather than simply left unimplemented. An unbound
 * gesture and a gesture nobody tried look exactly alike, so each one is refused
 * on purpose and there is a measurement that tries them all.
 */

/**
 * Listen on one element and turn the two allowed gestures into view changes.
 *
 * ``getView`` and ``setView`` are how this reaches whatever is holding the
 * current view; ``sizeOf`` gives the element's size in browser pixels. Returns a
 * function that stops listening.
 */
export function onlyPanAndZoom(element, { getView, setView, sizeOf }) {
  let dragging = null;

  const refused = { shiftDrag: 0, rightButton: 0, ctrlWheel: 0, keys: 0 };
  // What was accepted, kept for the same reason as what was refused: a
  // measurement has to be able to tell "the gesture reached the page and moved
  // the view" from "the gesture never arrived at all", and on screen those look
  // identical when the answer is supposed to be "nothing happened".
  const accepted = { drags: 0, wheels: 0 };

  const down = (event) => {
    // The right button used to recentre the view, and shift with the left button
    // used to rotate it. Both are gone. Counted rather than silently dropped so
    // a measurement can tell "the gesture was made and refused" from "the
    // gesture was never made".
    if (event.button !== 0) {
      refused.rightButton += 1;
      event.preventDefault();
      return;
    }
    if (event.shiftKey) {
      refused.shiftDrag += 1;
      event.preventDefault();
      return;
    }
    dragging = { x: event.clientX, y: event.clientY };
    accepted.drags += 1;
    element.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  };

  const move = (event) => {
    if (!dragging) return;
    const view = getView();
    // Panning is the one gesture where what the operator expects is exactly
    // literal: the point they took hold of should stay under their finger, so a
    // movement of so many screen pixels is that many pixels' worth of specimen.
    const nextView = {
      ...view,
      cx: view.cx - (event.clientX - dragging.x) * view.scale,
      cy: view.cy - (event.clientY - dragging.y) * view.scale,
    };
    dragging = { x: event.clientX, y: event.clientY };
    setView(nextView);
    event.preventDefault();
  };

  const up = (event) => {
    dragging = null;
    element.releasePointerCapture?.(event.pointerId);
  };

  const wheel = (event) => {
    // Always prevented, whatever we then do with it, so the browser never zooms
    // the page itself. A page zoom would change how many real pixels there are
    // to a browser pixel underneath us, which is precisely the thing two stacked
    // surfaces have to agree about.
    event.preventDefault();
    if (event.ctrlKey) {
      // Ctrl and the wheel is the engine's own way of zooming. Here the plain
      // wheel does that, and this combination does nothing at all.
      refused.ctrlWheel += 1;
      return;
    }
    const view = getView();
    const size = sizeOf();
    const bounds = element.getBoundingClientRect();
    const pointerX = event.clientX - bounds.left;
    const pointerY = event.clientY - bounds.top;
    // The point under the pointer stays under the pointer. Everyone expects
    // this, and its absence is felt immediately even by people who cannot say
    // what is wrong.
    const worldX = view.cx + (pointerX - size.width / 2) * view.scale;
    const worldY = view.cy + (pointerY - size.height / 2) * view.scale;
    accepted.wheels += 1;
    const step = Math.exp(event.deltaY * 0.0015);
    const scale = view.scale * step;
    setView({
      scale,
      cx: worldX - (pointerX - size.width / 2) * scale,
      cy: worldY - (pointerY - size.height / 2) * scale,
    });
  };

  const key = (event) => {
    // Not one key moves the flat view. `r` and `e` rotated it, shift with the
    // arrow keys tilted it out of the plane, the arrow keys stepped it sideways,
    // and the comma, full stop and bracket keys moved through the stack and
    // through time — which now belongs to the sliders, where it is labelled.
    refused.keys += 1;
  };

  element.addEventListener("pointerdown", down);
  element.addEventListener("pointermove", move);
  element.addEventListener("pointerup", up);
  element.addEventListener("pointercancel", up);
  element.addEventListener("wheel", wheel, { passive: false });
  element.addEventListener("contextmenu", (event) => event.preventDefault());
  window.addEventListener("keydown", key);

  return {
    refused,
    accepted,
    stop: () => window.removeEventListener("keydown", key),
  };
}
