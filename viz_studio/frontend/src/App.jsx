import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";
import LayerPanel from "./LayerPanel.jsx";

// The two ways of looking at a volume, and the only thing the operator has to
// choose between. 2-D is the working view -- one plane, scroll through the
// stack. 3-D is for reading shape: the same data ray-cast, rotatable.
const MODES = { flat: "2D", volume: "3D" };

// Neuroglancer names its panels after *display* axes, while an OME-Zarr volume
// arrives ordered z, y, x. Its "yz" panel is therefore the one showing the
// image plane with z perpendicular -- the plane you scroll through. Measured,
// not assumed: in "xy" the wheel steps x.
const SLICE_LAYOUT = "yz";
const VOLUME_LAYOUT = "3d";

const FALLBACK = {
  layers: [
    {
      name: "volume",
      source: "/data/demo.zarr/|zarr2:",
      window: null,
      volumeWindow: null,
      color: null,
    },
  ],
  depthSamples: 256,
  chrome: false,
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

// Real acquisitions occupy a narrow band of the 16-bit range, so without an
// explicit window they render black. In 3-D the intensity drives opacity as
// well, or every background voxel along the ray adds haze and the specimen is
// lost in fog.
function shaderFor(window_, color, volumetric, opacity = 1) {
  if (!window_) return undefined;
  let source = `#uicontrol invlerp normalized(range=[${window_.low}, ${window_.high}])\n`;
  if (volumetric) {
    source += `#uicontrol float opacity slider(min=0, max=1, default=${opacity})\n`;
    const [r, g, b] = color || [1, 1, 1];
    return source + `void main() { emitRGBA(vec4(${r}, ${g}, ${b}, normalized() * opacity)); }`;
  }
  if (!color) return source + "void main() { emitGrayscale(normalized()); }";
  const [r, g, b] = color;
  return source + `void main() { emitRGB(vec3(${r}, ${g}, ${b}) * normalized()); }`;
}

function layersFor(config, mode, layerState) {
  const volumetric = mode === "volume";
  return config.layers.map((spec, index) => {
    const { visible, color, opacity, window: windowOverride } = layerState[index];
    const displayWindow =
      windowOverride || (volumetric ? spec.volumeWindow || spec.window : spec.window);
    const layer = {
      type: "image",
      name: spec.name,
      source: `${window.location.origin}${spec.source}`,
    };
    const shader = shaderFor(displayWindow, color, volumetric, opacity);
    if (shader) layer.shader = shader;
    layer.visible = visible;
    if (volumetric) {
      layer.volumeRendering = "on";
      // This, not the zoom, chooses the pyramid level the volume is drawn from.
      layer.volumeRenderingDepthSamples = config.depthSamples;
    } else {
      layer.opacity = opacity;
    }
    return layer;
  });
}

function ModeToggle({ mode, onChange }) {
  return (
    <div style={styles.toggle}>
      {Object.entries(MODES).map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          style={{ ...styles.button, ...(mode === key ? styles.buttonActive : null) }}
          title={key === "flat" ? "One plane; scroll to move through z" : "Ray-cast volume; drag to rotate"}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * The application shell, and the single owner of what the viewer shows.
 *
 * <NeuroglancerView> mounts the engine and hands back the `viewer`; everything
 * about *what* is displayed is pushed in from here. Switching between the plane
 * and the volume re-applies state to the same viewer rather than rebuilding it,
 * so the data already fetched stays in memory and the toggle is instant.
 */
export default function App() {
  const [viewer, setViewer] = React.useState(null);
  const [config, setConfig] = React.useState(null);
  const [mode, setMode] = React.useState("flat");
  // Per-layer interface state. Held here rather than in the engine because the
  // panel and the viewer must never disagree about what is showing.
  const [layerState, setLayerState] = React.useState([]);

  React.useEffect(() => {
    let cancelled = false;
    fetchConfig().then((loaded) => {
      if (cancelled) return;
      setConfig(loaded);
      setLayerState(
        loaded.layers.map((spec) => ({
          visible: true,
          color: spec.color,
          opacity: 1,
          // Null means "use the mode-specific measured default". Once the
          // operator moves either contrast handle, their chosen window becomes
          // the source of truth in both 2-D and 3-D.
          window: null,
        })),
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    if (!viewer || !config || layerState.length !== config.layers.length) return;
    window.zmartViewer = viewer; // handy for inspection and the browser tests
    window.zmartConfig = config;
    window.zmartMode = mode;
    window.zmartLayerState = layerState;
    viewer.state.restoreState({
      layers: layersFor(config, mode, layerState),
      layout: mode === "volume" ? VOLUME_LAYOUT : SLICE_LAYOUT,
      // The engine's own furniture -- the yellow data-bounds box and the axis
      // lines -- is off unless asked for. We are supplying the interface.
      showDefaultAnnotations: config.chrome ?? false,
      showAxisLines: config.chrome ?? false,
      showScaleBar: true,
    });
  }, [viewer, config, mode, layerState]);

  const setLayer = (index, change) =>
    setLayerState((current) =>
      current.map((entry, i) => (i === index ? { ...entry, ...change } : entry)),
    );

  return (
    <div style={styles.shell}>
      {config && (
        <LayerPanel
          layers={config.layers}
          state={layerState}
          mode={mode}
          onToggle={(i) => setLayer(i, { visible: !layerState[i].visible })}
          onColor={(i, color) => setLayer(i, { color })}
          onOpacity={(i, opacity) => setLayer(i, { opacity })}
          onWindow={(i, window) => setLayer(i, { window })}
        />
      )}
      <main style={styles.stage}>
        <NeuroglancerView onViewer={setViewer} />
        <ModeToggle mode={mode} onChange={setMode} />
      </main>
    </div>
  );
}

const styles = {
  shell: { position: "absolute", inset: 0, display: "flex", background: "#0b0d10" },
  stage: { flex: 1, position: "relative" },
  toggle: {
    position: "absolute",
    top: 12,
    left: 12,
    zIndex: 10,
    display: "flex",
    borderRadius: 6,
    overflow: "hidden",
    border: "1px solid #2c333d",
    boxShadow: "0 1px 4px rgba(0,0,0,.5)",
  },
  button: {
    padding: "6px 14px",
    border: "none",
    background: "#161a20",
    color: "#8b95a3",
    font: "600 12px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
  buttonActive: { background: "#2f6feb", color: "#fff" },
};
