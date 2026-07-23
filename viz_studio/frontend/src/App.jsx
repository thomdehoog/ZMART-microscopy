import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";

// What to open, and how to display it, comes from the Python side: pointing the
// viewer at a real acquisition is then a server-side argument rather than a
// rebuild of this page. The demo store is the fallback so `vite dev` still shows
// something when no server config is reachable.
const FALLBACK = {
  layers: [{ name: "volume", source: "/data/demo.zarr/|zarr2:", window: null, color: null }],
};

async function fetchConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return FALLBACK;
    return await response.json();
  } catch {
    return FALLBACK;
  }
}

// Stretch the given intensity window across the display ramp. Real acquisitions
// occupy a narrow band of the 16-bit range, so without this they render black.
// A colour is emitted when several channels are shown together, so they overlay
// legibly instead of washing into one grey.
// In 3-D the intensity has to drive opacity as well, or every background voxel
// along the ray adds a little haze and the specimen is lost in fog.
function shaderFor(window_, color, volumetric) {
  if (!window_) return undefined;
  let control = `#uicontrol invlerp normalized(range=[${window_.low}, ${window_.high}])\n`;
  if (volumetric) {
    control += "#uicontrol float opacity slider(min=0, max=1, default=1)\n";
    const [r, g, b] = color || [1, 1, 1];
    return control + `void main() { emitRGBA(vec4(${r}, ${g}, ${b}, normalized() * opacity)); }`;
  }
  if (!color) return control + "void main() { emitGrayscale(normalized()); }";
  const [r, g, b] = color;
  return control + `void main() { emitRGB(vec3(${r}, ${g}, ${b}) * normalized()); }`;
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
    if (!viewer) return undefined;
    window.zmartViewer = viewer; // handy for inspection and the browser test
    let cancelled = false;
    fetchConfig().then((config) => {
      if (cancelled) return;
      const layers = config.layers.map((spec) => {
        const layer = {
          type: "image",
          name: spec.name,
          source: `${window.location.origin}${spec.source}`,
        };
        const shader = shaderFor(spec.window, spec.color, spec.volumetric);
        if (shader) layer.shader = shader;
        if (spec.volumetric) {
          layer.volumeRendering = "on";
          // Not cosmetic: this is what picks the pyramid level in 3-D. Zooming
          // does not sharpen a volume — neuroglancer chooses the level a ray
          // crosses in about this many samples, so 64 (its default) stays
          // coarse however far you zoom in.
          layer.volumeRenderingDepthSamples = spec.depthSamples;
        }
        return layer;
      });
      viewer.state.restoreState({ layers, layout: "4panel" });
      window.zmartConfig = config; // what the page was told to open
    });
    return () => {
      cancelled = true;
    };
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
