import React from "react";
// neuroglancer is built from many optional pieces. The bare `makeMinimalViewer`
// wires up the display but registers none of the ways to *read* data. These
// four imports switch on the pieces we need: the layer types (image, etc.), the
// data-format readers (which include OME-Zarr), and the "key-value stores" that
// know how to fetch bytes over plain HTTP. Without them the viewer loads but
// every data source fails with "unsupported scheme". They must come before the
// viewer is created.
import "neuroglancer/unstable/util/polyfills.js";
import "neuroglancer/unstable/layer/enabled_frontend_modules.js";
import "neuroglancer/unstable/datasource/enabled_frontend_modules.js";
import "neuroglancer/unstable/kvstore/enabled_frontend_modules.js";
import { makeMinimalViewer } from "neuroglancer/unstable/ui/minimal_viewer.js";
// Mouse and keyboard navigation (pan, zoom, scroll through z, rotate the 3-D
// view) is NOT part of building a viewer. neuroglancer's panels receive the DOM
// events either way, but without these binding tables no *action* is attached to
// them, so every drag and wheel silently does nothing. Its own entry points
// (default_viewer_setup.js, main_python.js) install them immediately after
// creating the viewer; makeMinimalViewer does not, so we must.
//
// The two tables brought in here are the ones attached to the image panels
// themselves. The engine has a third — its *global* table — which we
// deliberately leave out; see the note beside the call below for why.
import {
  EventActionMap,
  registerActionListener,
} from "neuroglancer/unstable/util/event_action_map.js";
import "neuroglancer/unstable/ui/default_viewer.css";
// Loaded after the engine's own stylesheet so it wins: this hides the handful of
// controls the engine draws inside the image itself. See the file for why.
import "./engine-chrome.css";

/**
 * Mounts the neuroglancer engine and hands the live `viewer` back through
 * `onViewer`. That is all it does.
 *
 * Deliberately, this component owns the engine's *lifetime* (create it when the
 * div appears, dispose it when the component goes away) but NOT what the engine
 * *shows*. Which layers, which layout, the brightness, the z-position — all of
 * that is driven by the parent talking to the `viewer` object. Keeping that
 * split means the control panel can grow without ever touching this file.
 *
 * neuroglancer is not a React component; it draws into a DOM node directly, so
 * we give it an empty div via a ref. The effect is written to survive React
 * StrictMode's deliberate mount → dispose → mount in development, so do not be
 * surprised to see the engine built twice under `vite dev`.
 */
export default function NeuroglancerView({ onViewer, generation = 0, veiled = false }) {
  const containerRef = React.useRef(null);

  React.useEffect(() => {
    const target = containerRef.current;
    if (!target) return undefined;

    // Create the viewer with all of neuroglancer's own buttons and panels
    // turned off — we supply our own controls, so the engine shows nothing but
    // the image. `showLayerDialog`/`resetStateWhenEmpty` are off so the engine
    // does not pop its own "add a layer" dialog or wipe state before the parent
    // loads a volume.
    const viewer = makeMinimalViewer({
      target,
      showUIControls: false,
      showTopBar: false,
      showLayerPanel: false,
      showLocation: false,
      showPanelBorders: false,
      showLayerDialog: false,
      resetStateWhenEmpty: false,
    });

    // The panels are given explicit tables holding exactly the gestures our
    // interface documents, instead of inheriting the engine's defaults. What
    // an operator can do to the picture is written out here, once, in full —
    // CONTROLS.md records each decision.
    //
    // The engine's *global* keyboard table is not installed either, and never
    // was. It binds single unmodified letters and digits across the whole
    // page, to actions belonging to an interface this viewer hides — the
    // space bar split the image into four panels with no way back, the digits
    // hid channels while the panel's eye still showed them open, and several
    // letters restored scale bars and axis lines this viewer draws for
    // itself. The engine's element holds the keyboard focus from the moment
    // the page loads, so a stray keystroke was enough.
    //
    // The engine's *panel* tables used to be installed whole, and they were
    // the second hole (closed 2026-08-18): they bound their own keyboard —
    // arrows panned, comma and full stop stepped z, the brackets stepped time
    // straight past the T slider's clamp to the written moments, `r`, `e` and
    // Shift with the arrows rotated the flat view so the picture silently
    // stopped lining up with the stage coordinates drawn over it, and a right
    // click jumped the view to the point clicked. None of it is shown
    // anywhere on screen. Moving through the stack and through time belongs
    // to the sliders, where it is visible, labelled and clamped; moving
    // around belongs to the two gestures. So: no keyboard at all, and the
    // flat view cannot rotate. The test file
    // `test_the_keyboard_cannot_trap_the_operator.py` holds each of these
    // removals in place.
    //
    // What stays, besides movement, is the drawing family our Point and Box
    // buttons rely on: Ctrl+click places (the engine's "annotate" action
    // triggers whichever placement tool those buttons installed), Enter
    // finishes a shape and Backspace undoes a step of one. Without an active
    // tool all three do nothing.
    const bindings = viewer.inputEventBindings;
    bindings.sliceView.addParent(
      EventActionMap.fromObject({
        "at:mousedown0": { action: "translate-via-mouse-drag", stopPropagation: true },
        "at:touchtranslate2": "translate-in-plane-via-touchtranslate",
        "at:touchpinch": "zoom-via-touchpinch",
        "at:control+mousedown0": "annotate",
        enter: "finish-annotation",
        backspace: "undo-annotation-step",
      }),
      Number.NEGATIVE_INFINITY,
    );
    // The volume view keeps rotation — turning the specimen over is the point
    // of a three-dimensional view, and nothing is drawn over it in stage
    // coordinates — and it keeps the slab-thickness wheel, which has no
    // control of its own yet.
    bindings.perspectiveView.addParent(
      EventActionMap.fromObject({
        "at:mousedown0": { action: "rotate-via-mouse-drag", stopPropagation: true },
        "at:shift+mousedown0": { action: "translate-via-mouse-drag", stopPropagation: true },
        "at:touchtranslate1": "rotate-out-of-plane-via-touchtranslate",
        "at:touchtranslate2": "translate-in-plane-via-touchtranslate",
        "at:touchrotate": "rotate-in-plane-via-touchrotate",
        "at:touchpinch": "zoom-via-touchpinch",
        "at:alt+wheel": { action: "adjust-depth-range-via-wheel", preventDefault: true },
        "at:control+mousedown0": "annotate",
        enter: "finish-annotation",
        backspace: "undo-annotation-step",
      }),
      Number.NEGATIVE_INFINITY,
    );

    // The plain wheel zooms, and stepping through z moves to shift+wheel.
    //
    // This is ours, not the engine's. Neuroglancer gives the plain wheel to z and
    // puts zoom behind Control, which is right for reading through a volume and
    // wrong for an operator looking at a plate. The wheel is the gesture made
    // most often and without thinking, and a browser has taught everybody what it
    // does; zoom has nowhere else to live, since this interface has no zoom
    // button, slider or key, while the stack keeps the slider down the right-hand
    // side -- better than a gesture anyway, because it shows where in the stack
    // you are. `CONTROLS.md` section 1 records the decision.
    //
    // It is set here rather than left to the defaults because these entries win
    // over the parent table added above, which is why that is added at the lowest
    // possible precedence.
    //
    // The reason this was worth doing: on a run one plane deep -- an overview
    // scan, which is most of them -- the engine's binding leaves the first
    // gesture an operator makes doing nothing whatsoever, with nothing on screen
    // to say why. The operator page beside this one has zoomed on the plain wheel
    // all along, so until now the two disagreed.
    // `preventDefault` is passed explicitly. Handing `set` a bare action name --
    // which is how `CONTROLS.md` writes it -- leaves it unset, because
    // `normalizeEventAction` returns only `{action, originalEventIdentifier}` for
    // a string. The engine's own table sets it on every wheel entry, and without
    // it the browser keeps its native wheel behaviour and acts on the same notch
    // we are acting on.
    // Both panels, and the second one is not an afterthought. Rebinding the flat
    // view alone left the volume view on the engine's defaults, where the plain
    // wheel steps z and zoom hides behind Control -- so an operator taught that
    // the wheel zooms found it doing nothing in three dimensions, and on a run
    // one plane deep it could do nothing at all. That looked exactly like a
    // volume view unable to draw at any resolution but the coarsest, and cost an
    // afternoon and two reviews before the measurement was made with the volume
    // view's own zoom. It refines perfectly well: 20.8 um down to 0.33 um across
    // the projection zooms, the whole pyramid.
    // A gentler notch than the engine's, and the reason is worth stating because
    // the engine's is not wrong -- it is simply pitched for travelling.
    //
    // `getWheelZoomAmount` returns `exp(deltaY / 200)`, and a wheel notch on
    // Windows reports a deltaY of 100, so one notch magnifies by about 1.65. A
    // pyramid level is 2, so a single notch crosses roughly seven-tenths of a
    // level. Pulled back that is pleasant -- you cross the specimen in a few
    // turns. Zoomed in on something it is unusable: there is no stop between too
    // far out and too far in, and because the engine zooms about the *cursor*
    // rather than the centre, every notch slides the view sideways as well. The
    // two compound, and it reads as flying rather than zooming.
    //
    // A third of the exponent gives about 1.18 a notch, so four notches to a
    // level. Zooming about the cursor is kept exactly as it was: this hands the
    // work back to the very method the engine's own action calls, so pointing at
    // something and turning the wheel still travels towards it.
    const GENTLER = 3;
    const howFarToZoom = (event) => {
      const perPixel = { 0: 1 / 200, 1: 1 / 10, 2: 2 }[event.deltaMode] ?? 1 / 200;
      return Math.exp((event.deltaY * perPixel) / GENTLER);
    };
    registerActionListener(target, "zmart-zoom-via-wheel", (fired) => {
      const wheel = fired.detail;
      for (const panel of viewer.display.panels) {
        if (!panel.element?.contains(wheel.target) || !panel.zoomByMouse) continue;
        panel.onMousemove?.(wheel, false);
        panel.zoomByMouse(howFarToZoom(wheel));
        return;
      }
    });

    for (const panel of [bindings.sliceView, bindings.perspectiveView]) {
      panel.set("at:wheel", { action: "zmart-zoom-via-wheel", preventDefault: true });
      panel.set("at:shift+wheel", {
        action: "z+1-via-wheel",
        preventDefault: true,
      });
    }

    onViewer?.(viewer);
    return () => viewer.dispose();
    // ``generation`` is how the interface asks for a *new* engine rather than
    // a changed one. Closing an acquisition is the only thing that asks. The
    // engine holds more than the layer it was told to delete: with the layer
    // gone, its sources rebuilt and every piece fetched again, the next
    // acquisition still came up with most of its tiles unpainted, and the
    // only thing that ever put it right was a fresh drawing context
    // (measured 2026-08-21 -- same bounds, same camera, same requests, a
    // different picture). So a close builds one.
  }, [onViewer, generation]);

  // Size the mount with width/height rather than absolute insets: neuroglancer
  // sets `position: relative` on this element itself, which would cancel any
  // inset-based sizing and collapse it to zero height. Filling the (already
  // sized) parent sidesteps that entirely.
  //
  // The black stays black in the light theme too, on purpose. Fluorescence
  // is read against black -- at the microscope and in every viewer -- and a
  // light ground here would change what a dim signal looks like. Only the
  // chrome around the image follows the theme.
  // While ``veiled`` the drawing is held at opacity zero over that black
  // ground: the engine's first frames come out at its own default
  // magnification before the fit-to-window lands, and showing them read as
  // the picture jumping in size on every first open. Black underneath means
  // the veil looks like an empty canvas, and the short fade makes the
  // arrival read as the picture appearing rather than snapping.
  return (
    <div style={{ width: "100%", height: "100%", background: "#000" }}>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          background: "#000",
          opacity: veiled ? 0 : 1,
          transition: "opacity 120ms linear",
        }}
      />
    </div>
  );
}
