import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";

// The image volume to show, in neuroglancer's data-source syntax: the folder to
// read, then "|zarr2:" meaning "read it as version-2 Zarr". Built from the
// page's own origin so it works both under `vite dev` and when the Python
// server serves the built page.
function demoSource() {
  return `${window.location.origin}/data/demo.zarr/|zarr2:`;
}

/**
 * The application shell, and the single owner of what the viewer shows.
 *
 * <NeuroglancerView> mounts the engine and hands us the `viewer`. Everything
 * about *what* is displayed — which layers, the 2-D/3-D layout, and later the
 * brightness and z-position — lives here and is pushed into the engine through
 * its `viewer.state`. Because this is the only writer of that state, adding
 * controls later is just more of the same call, with no second owner to fight.
 *
 * The layout is a flex row so the control panel (layers, contrast, ...) can grow
 * on the left in the next step, with the viewer filling the rest.
 */
export default function App() {
  const [viewer, setViewer] = React.useState(null);

  // Once the engine exists, load the demo volume into it. This effect is the
  // one and only place viewer state is set; the future control panel will write
  // through the same `viewer` handle.
  React.useEffect(() => {
    if (!viewer) return;
    window.zmartViewer = viewer; // handy for inspection and the browser test
    viewer.state.restoreState({
      layers: [{ type: "image", name: "volume", source: demoSource() }],
      layout: "4panel",
    });
  }, [viewer]);

  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", background: "#0b0d10" }}>
      {/* The control panel will live here, to the left of the viewer. */}
      <main style={{ flex: 1, position: "relative" }}>
        <NeuroglancerView onViewer={setViewer} />
      </main>
    </div>
  );
}
