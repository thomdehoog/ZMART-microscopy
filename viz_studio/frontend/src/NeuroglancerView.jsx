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
import "neuroglancer/unstable/ui/default_viewer.css";

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
