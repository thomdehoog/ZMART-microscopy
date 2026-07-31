/**
 * The two ways of moving around, and nothing else.
 *
 * `viz_studio/CONTROLS.md` settles this for the flat view: **dragging pans, and
 * the plain scroll wheel zooms.** Everything else that could change where the
 * operator is or which way they are facing has been taken away — rotating with
 * shift and drag, rotating with the `r` and `e` keys, tilting with shift and the
 * arrow keys, stepping through the stack on the wheel, zooming with ctrl and the
 * wheel, and recentring with the right button. Moving through the stack and
 * through time is not lost; it moves to sliders, where it is visible and
 * labelled rather than living on a gesture an operator has to be told about.
 *
 * This lives in the harness rather than inside any one option, and that is the
 * point. If each option interpreted gestures for itself, a difference in how the
 * three feel might be the engine or might be somebody's idea of how far a wheel
 * notch should zoom, and there would be no way to tell which. Here every option
 * is driven by this one file, so a difference is a difference in the engine.
 *
 * The listeners go on the box the viewer was opened inside. Events from whatever
 * surface the option put in there bubble up to it, so this works the same
 * whether the option laid down two canvases or one.
 *
 * **Every refusal is written out on purpose rather than simply left
 * unimplemented**, and each one is counted. An unbound gesture and a gesture
 * nobody tried look exactly alike on screen, so a measurement has to be able to
 * tell them apart, and the only way to do that is for the page to say plainly
 * what it turned away.
 */

/**
 * Listen on `element`, and turn the two allowed gestures into view changes.
 *
 * `getView` and `setView` are how this reaches whatever holds the current view;
 * `sizeOf` gives the element's size in browser pixels. Returns a small record of
 * what was accepted and what was refused, and a way to stop listening.
 */
export function onlyPanAndZoom(element, { getView, setView, sizeOf }) {
  let dragging = null;

  const refused = { shiftDrag: 0, rightButton: 0, ctrlWheel: 0, keys: 0 };
  const accepted = { drags: 0, wheels: 0 };

  const down = (event) => {
    // The right button used to recentre the view and shift with the left button
    // used to rotate it. Both are gone.
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
    setView({
      zoom: view.zoom,
      centre: {
        x: view.centre.x - (event.clientX - dragging.x) * view.zoom,
        y: view.centre.y - (event.clientY - dragging.y) * view.zoom,
      },
    });
    dragging = { x: event.clientX, y: event.clientY };
    event.preventDefault();
  };

  const up = (event) => {
    dragging = null;
    element.releasePointerCapture?.(event.pointerId);
  };

  const wheel = (event) => {
    // Always prevented, whatever is then done with it, so the browser never
    // zooms the page itself. A page zoom changes how many real pixels there are
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
    // what is wrong. It matters more than usual here: if the page's idea of a
    // zoom notch and the engine's ever disagreed, the picture would creep out
    // from under the outlines drawn on it, a little on every notch.
    const heldX = view.centre.x + (pointerX - size.width / 2) * view.zoom;
    const heldY = view.centre.y + (pointerY - size.height / 2) * view.zoom;
    accepted.wheels += 1;
    const zoom = view.zoom * Math.exp(event.deltaY * 0.0015);
    setView({
      zoom,
      centre: {
        x: heldX - (pointerX - size.width / 2) * zoom,
        y: heldY - (pointerY - size.height / 2) * zoom,
      },
    });
  };

  const key = () => {
    // Not one key moves the flat view. `r` and `e` rotated it, shift with the
    // arrow keys tilted it out of the plane, the arrow keys stepped it sideways,
    // and the comma, full stop and bracket keys moved through the stack and
    // through time — which now belongs to the sliders.
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
