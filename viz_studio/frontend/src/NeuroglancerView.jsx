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

// The address of the image volume, written in neuroglancer's data-source
// syntax: the folder to read from, followed by "|zarr2:" to say "interpret it
// as version-2 Zarr". In development Vite serves the folder from the app's own
// origin; in the shipped app the Python server does. Either way the path is the
// same, so we build it from wherever the page is loaded.
function demoSource() {
  return `${window.location.origin}/data/demo.zarr/|zarr2:`;
}

/**
 * Mounts the neuroglancer engine into a plain <div> and hands the live viewer
 * object back to the parent through `onReady`.
 *
 * neuroglancer is not a React component — it draws into a DOM node directly. So
 * the React-friendly way to use it is to give it an empty div (via a ref),
 * create the viewer once when that div appears, and tear it down when the
 * component goes away. Everything after that (adding layers, changing
 * brightness, switching to 3-D) happens by talking to the viewer object, which
 * is exactly the "your UI, their engine" arrangement: React owns the controls,
 * neuroglancer owns the pixels.
 */
export default function NeuroglancerView({ onReady }) {
  const containerRef = React.useRef(null);
  const viewerRef = React.useRef(null);

  React.useEffect(() => {
    const target = containerRef.current;
    if (!target) return undefined;

    // Create the viewer with all of neuroglancer's own buttons and panels
    // turned off — we are supplying our own controls, so the engine should show
    // nothing but the image itself.
    const viewer = makeMinimalViewer({
      target,
      showUIControls: false,
      showTopBar: false,
      showLayerPanel: false,
      showLocation: false,
      showPanelBorders: false,
      // Do not pop neuroglancer's own "add a layer" dialog, and do not wipe the
      // state when it briefly has no layers — we load our volume ourselves.
      showLayerDialog: false,
      resetStateWhenEmpty: false,
    });
    viewerRef.current = viewer;

    // Load the demo volume. `restoreState` accepts the same description
    // neuroglancer uses everywhere: a list of layers (here one image layer
    // reading our OME-Zarr) and a starting layout. From here on, the React
    // controls will drive this same state object.
    viewer.state.restoreState({
      layers: [
        {
          type: "image",
          name: "volume",
          source: demoSource(),
        },
      ],
      layout: "4panel",
    });

    if (onReady) onReady(viewer);

    return () => {
      viewer.dispose();
      viewerRef.current = null;
    };
  }, [onReady]);

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
