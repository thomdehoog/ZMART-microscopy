/**
 * The two ways of moving around, and the one place a drag can be lent out.
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
 * **This file belongs to the canvas, and all three options use this one copy.**
 * That is deliberate and it is the property to protect. If each option decided
 * for itself how far a wheel notch should zoom or how a drag should follow the
 * hand, a difference in how the three feel might be the engine or might be
 * somebody's idea of a good number, and there would be no way to tell which.
 * Driven by one file, a difference is a difference in the engine. It is also why
 * a page that embeds the canvas gets the two gestures without writing a line:
 * `openViewer` puts these listeners on, `destroy` takes them off, and the page
 * hears where the view went through `onViewChanged`.
 *
 * The listeners go on the box the viewer was opened inside, rather than on any
 * surface the option laid down in it. Events from whatever is in there bubble up
 * to the box, so this works the same whether the option put down two canvases or
 * one — and the box is measured here rather than being described by each option,
 * so there is one less thing the three could disagree about.
 *
 * **Every refusal is written out on purpose rather than simply left
 * unimplemented**, and each one is counted. An unbound gesture and a gesture
 * nobody tried look exactly alike on screen, so a measurement has to be able to
 * tell them apart, and the only way to do that is for the canvas to say plainly
 * what it turned away.
 *
 * ## Lending a drag out
 *
 * A drag that draws cannot also pan, so an operator who wants to scribble on the
 * picture needs some way to say which of the two they mean. The answer here is
 * the one every drawing program an operator has ever used already takes: **the
 * application chooses the tool, and the canvas obeys.** The canvas keeps the
 * mechanics of the gesture — which button, when the drag began, where the
 * pointer is on the stage — and knows nothing whatever about why the meaning
 * changed. `handDragsTo(handler)` is the whole of the mechanism: hand over a
 * function and the canvas stops panning and gives each drag to it instead; hand
 * over nothing and dragging pans again, which is what it does until somebody
 * says otherwise. Nothing here draws anything; what a lent drag is *for* is the
 * application's business entirely.
 */

/**
 * Listen on `element`, and turn the two allowed gestures into view changes.
 *
 * `getView` and `setView` are how this reaches whatever holds the current view,
 * in micrometres, and they are the only two things it needs. Returns a small
 * record of what was accepted and what was refused, the way to lend a drag out,
 * and the way to stop listening.
 */
export function onlyPanAndZoom(element, { getView, setView }) {
  let dragging = null;
  // What a drag means at this moment. Nothing here means it pans, which is what
  // it does unless the application has said otherwise.
  let handDragOver = null;

  const refused = { shiftDrag: 0, rightButton: 0, ctrlWheel: 0, keys: 0 };
  const accepted = { drags: 0, wheels: 0, dragsHandedOver: 0, dragsHandedBack: 0 };

  /**
   * How large the box is, in browser pixels.
   *
   * Measured here rather than asked of the option, because every option is
   * opened inside this same box and three answers to one question is three
   * chances for them to differ.
   */
  const sizeOfTheBox = () => ({
    width: element.clientWidth,
    height: element.clientHeight,
  });

  /**
   * Where a pointer event is, both on the stage and in the box.
   *
   * The place on the stage is in micrometres, which is what a drag that draws
   * needs: a mark recorded in screen pixels would slide off the specimen the
   * moment the operator panned or zoomed, while a mark recorded in micrometres
   * stays on the part of the sample it was drawn on.
   */
  const whereThePointerIs = (event) => {
    const view = getView();
    const size = sizeOfTheBox();
    const bounds = element.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    return {
      at: {
        x: view.centre.x + (x - size.width / 2) * view.zoom,
        y: view.centre.y + (y - size.height / 2) * view.zoom,
      },
      screen: { x, y },
    };
  };

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
    // What this drag means is settled here, once, at the moment it begins, and
    // it holds until the operator lets go. An application that changed tool
    // halfway through would otherwise split one movement of the hand between
    // two meanings, which is not something an operator could ever have asked
    // for.
    //
    // Alt is the exception, and it is the canvas's own: it keeps the drag for
    // the picture whatever the application is doing with drags. An application
    // whose tool wants every press on empty canvas would otherwise leave no way
    // to move the picture at all, and an escape hatch that each tool has to
    // remember to implement is not an escape hatch.
    dragging = {
      x: event.clientX,
      y: event.clientY,
      handOver: event.altKey ? null : handDragOver,
    };
    if (dragging.handOver) {
      // Offered, not given. Whoever holds drags may turn this one down — it
      // landed on nothing of theirs — and a drag nobody wants is a drag that
      // pans, which is what dragging means when nothing has claimed it.
      const took = dragging.handOver({ phase: "started", ...whereThePointerIs(event) });
      if (took === false) {
        dragging.handOver = null;
        accepted.dragsHandedBack += 1;
        accepted.drags += 1;
      } else {
        accepted.dragsHandedOver += 1;
      }
    } else {
      accepted.drags += 1;
    }
    element.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  };

  const move = (event) => {
    if (!dragging) return;
    if (dragging.handOver) {
      // Lent out: the view does not move at all, and what the drag means is
      // entirely up to whoever asked for it.
      dragging.handOver({ phase: "moved", ...whereThePointerIs(event) });
      event.preventDefault();
      return;
    }
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
    dragging = { x: event.clientX, y: event.clientY, handOver: null };
    event.preventDefault();
  };

  const up = (event) => {
    // A drag the browser cancelled — the window losing focus, say — arrives here
    // too, and is reported as finished. Whoever borrowed the drag is always told
    // it has ended, however it ended, because a tool left waiting for an end
    // that never comes is a tool that has quietly stopped working.
    if (dragging?.handOver) {
      dragging.handOver({ phase: "finished", ...whereThePointerIs(event) });
    }
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
    // Counted here, before anything is asked of the viewer, for the same reason
    // a drag is counted the moment it begins: the count has to say "this gesture
    // reached us", and a count taken after the work would go missing exactly
    // when the work went wrong.
    accepted.wheels += 1;
    const view = getView();
    const size = sizeOfTheBox();
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

  const swallowTheMenu = (event) => event.preventDefault();

  element.addEventListener("pointerdown", down);
  element.addEventListener("pointermove", move);
  element.addEventListener("pointerup", up);
  element.addEventListener("pointercancel", up);
  element.addEventListener("wheel", wheel, { passive: false });
  element.addEventListener("contextmenu", swallowTheMenu);
  window.addEventListener("keydown", key);

  return {
    refused,
    accepted,

    /**
     * Say what a drag means from now on.
     *
     * Pass a function and the canvas stops panning: each drag is handed to that
     * function instead, one call as it begins, one for every movement of the
     * hand, and one when the operator lets go. Pass nothing — or `null` — and
     * dragging pans again.
     *
     * The function is called with `{ phase, at, screen }`, where `phase` is
     * `"started"`, `"moved"` or `"finished"`, `at` is where the pointer is on
     * the stage in micrometres, and `screen` is where it is in the box in
     * browser pixels, counted from the top-left corner.
     *
     * **It may turn a drag down.** Returning `false` from the `"started"` call
     * says this one is not mine, and the drag pans instead — which is what a
     * drag means when nothing has claimed it. Anything else takes it, and the
     * moves and the release follow. Without that, holding drags at all would
     * mean the picture could never be moved again, so an application would have
     * to hand them back and forth as tools were armed, guessing before the
     * press what the press was going to land on.
     *
     * Alt+drag is never offered. The canvas keeps it for panning.
     */
    handDragsTo(handler) {
      handDragOver = handler || null;
    },

    /**
     * Stop listening, and let go of everything.
     *
     * Every listener that was put on comes off again, including the one on the
     * window. A viewer that is closed and leaves listeners behind looks fine
     * until a second one is opened, at which point one movement of the hand is
     * answered twice.
     */
    stop() {
      element.removeEventListener("pointerdown", down);
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", up);
      element.removeEventListener("pointercancel", up);
      element.removeEventListener("wheel", wheel);
      element.removeEventListener("contextmenu", swallowTheMenu);
      window.removeEventListener("keydown", key);
      dragging = null;
      handDragOver = null;
    },
  };
}
