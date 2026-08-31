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
  getDefaultPerspectivePanelBindings,
  getDefaultSliceViewPanelBindings,
} from "neuroglancer/unstable/ui/default_input_event_bindings.js";
import { registerActionListener } from "neuroglancer/unstable/util/event_action_map.js";
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
export default function NeuroglancerView({ onViewer }) {
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

    // Navigation inside the image panels: drag to pan, wheel to move through z,
    // drag to rotate the volume, the arrow keys, and so on. This is everything an
    // operator needs in order to move around an acquisition, and all of it is
    // wanted.
    //
    // What is **not** installed is the engine's global keyboard table, and that
    // omission is the whole point of doing this by hand rather than calling
    // `setDefaultInputEventBindings`. That table binds single unmodified letters
    // and digits across the whole page, to actions belonging to an interface this
    // viewer deliberately hides — and one of them left an operator with no way
    // out. Pressing the space bar split the image into four panels, and because
    // clicking "2D" while the viewer already believed it was in 2-D changes
    // nothing and so re-runs nothing, there was no way back short of switching to
    // 3-D and returning. It needed no click to reach: the engine's element holds
    // the keyboard focus from the moment the page loads, so a stray space bar was
    // enough.
    //
    // Its siblings were quieter but no better. The digits 1 to 9 hid a channel
    // while the panel's eye still showed it as open, so the operator's next click
    // on that eye appeared to do nothing; `b`, `a` and `v` put back the engine's
    // own scale bars, axis lines and bounding box, which are switched off because
    // this viewer draws its own; `s` turned the slices off inside the volume view;
    // and `o` added an orthographic projection.
    //
    // Nothing in that table is reachable through our own interface, so leaving it
    // out removes a set of traps and costs an operator nothing. The engine's own
    // help panel (`h`) goes with it, which is right — it describes controls that
    // are not on screen.
    const bindings = viewer.inputEventBindings;
    bindings.sliceView.addParent(
      getDefaultSliceViewPanelBindings(),
      Number.NEGATIVE_INFINITY,
    );
    bindings.perspectiveView.addParent(
      getDefaultPerspectivePanelBindings(),
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
  }, [onViewer]);

  // Size the mount with width/height rather than absolute insets: neuroglancer
  // sets `position: relative` on this element itself, which would cancel any
  // inset-based sizing and collapse it to zero height. Filling the (already
  // sized) parent sidesteps that entirely.
  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", background: "#000" }}
    />
  );
}
