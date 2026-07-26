import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";
import LayerPanel from "./LayerPanel.jsx";
import TargetsPanel from "./TargetsPanel.jsx";
import { PlacePointTool, PlaceBoundingBoxTool } from "neuroglancer/unstable/ui/annotations.js";

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

// The engine keeps one flat list of layers and requires their names to be unique,
// while the panel shows them gathered under their acquisition type. Two types can
// easily hold a channel of the same name -- both an overview and a target scan
// have a "marker-a" -- so the name handed to the engine carries the type with it.
// The panel still shows the short name; this is only what the engine is told.
function engineName(spec) {
  return spec.group ? `${spec.group} · ${spec.name}` : spec.name;
}

/**
 * Turn the panel's state into the layer list the engine should draw.
 *
 * Three things are decided here. The **order** follows the panel, because the
 * engine composites in list order and so the order is what decides which
 * acquisition type sits on top of which. **Opacity** multiplies the group's
 * setting by the channel's, so pulling a whole acquisition type back to a third
 * dims everything in it while each channel keeps its relative weight. And
 * **visibility** needs both: hiding a group hides its channels without forgetting
 * which of them were individually switched off.
 */
function layersFor(config, mode, layerState, groupState, groupOrder) {
  const volumetric = mode === "volume";
  const rows = config.layers.map((spec, index) => ({ spec, index }));
  const ordered = groupOrder.flatMap((group) =>
    rows.filter(({ spec }) => (spec.group || "") === group),
  );
  // Anything whose group is somehow not in the order still gets drawn: a layer
  // silently missing is far worse than one in an unexpected place.
  const seen = new Set(ordered.map(({ index }) => index));
  const all = [...ordered, ...rows.filter(({ index }) => !seen.has(index))];

  return all.map(({ spec, index }) => {
    const { visible, color, opacity, window: windowOverride } = layerState[index];
    const group = groupState[spec.group || ""] || { visible: true, opacity: 1 };
    const combinedOpacity = opacity * group.opacity;
    const displayWindow =
      windowOverride || (volumetric ? spec.volumeWindow || spec.window : spec.window);
    const layer = {
      type: "image",
      name: engineName(spec),
      // A row may be drawn from several stores -- several positions of the same
      // acquisition type. The engine takes the list and places each one using the
      // stage position recorded inside it.
      source: (spec.sources || [spec.source]).map(
        (source) => `${window.location.origin}${source}`,
      ),
    };
    // Where a store holds its channels inside one array, this is what picks the
    // channel: the engine exposes it as a per-layer dimension, and each row pins
    // it to its own index. Nothing splits the data; one store feeds every row.
    if (spec.channelIndex != null) layer.localPosition = [spec.channelIndex];
    const shader = shaderFor(displayWindow, color, volumetric, combinedOpacity);
    if (shader) layer.shader = shader;
    layer.visible = visible && group.visible;
    if (volumetric) {
      layer.volumeRendering = "on";
      // This, not the zoom, chooses the pyramid level the volume is drawn from.
      layer.volumeRenderingDepthSamples = config.depthSamples;
    } else {
      layer.opacity = combinedOpacity;
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

const TARGET_LAYER = "Targets";

function annotationLayer(targets, color, visible) {
  return {
    type: "annotation",
    name: TARGET_LAYER,
    source: "local://annotations",
    annotations: targets,
    annotationColor: color,
    visible,
  };
}

// Ask Python to show a folder chooser, then open whatever was picked. The chooser
// has to be opened by Python because a page in a browser cannot be handed a path on
// the machine; in a plain browser tab there is nothing to open, so the operator is
// asked to type the path instead of being left with a button that does nothing.
async function chooseAndOpen() {
  let path = null;
  try {
    const response = await fetch("/api/browse", { method: "POST" });
    const answer = await response.json().catch(() => null);
    if (answer?.cancelled) return { cancelled: true };
    if (response.ok && answer?.path) path = answer.path;
    else if (answer?.reason) path = window.prompt(`${answer.reason}\n\nFolder:`);
  } catch {
    path = window.prompt("Folder holding the images:");
  }
  if (!path) return { cancelled: true };
  const response = await fetch("/api/stores/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) return { error: answer?.error || `could not open ${path}` };
  return { config: answer };
}

async function closeGroup(group) {
  const response = await fetch("/api/stores/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ group }),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) return { error: answer?.error || `could not close ${group}` };
  return { config: answer };
}

async function loadTargets() {
  try {
    const response = await fetch("/api/annotations");
    if (!response.ok) return [];
    return (await response.json()).annotations || [];
  } catch {
    return [];
  }
}

// Read one named axis out of the engine's current coordinate space: where it can
// travel, and where it is now. Returns null when the image has no such axis --
// which is the normal answer for `t` on anything that is not a timelapse, and is
// exactly how the interface decides whether to offer a time slider at all.
function axisInfo(viewer, name) {
  const position = viewer?.navigationState.position;
  const space = position?.coordinateSpace.value;
  if (!space?.valid) return null;
  const index = space.names.indexOf(name);
  if (index < 0) return null;
  // Neuroglancer describes an axis by the real-valued extent the data covers, and
  // separately says whether a whole plane (or frame) sits *on* an integer
  // coordinate or halfway between two. Both conventions occur, and the slider has
  // to land exactly on the planes that exist -- one step too few and the last
  // plane of every stack is unreachable, one too many and the slider runs off the
  // end of the data.
  //
  // When centres are on integers the engine reports the extent shifted by half a
  // voxel (a 48-plane stack comes back as -0.5 to 47.5), so the planes are simply
  // the integers inside that range. When centres fall between integers the extent
  // is unshifted, so the reachable positions are the half-integers inside it.
  const integerCentres = space.bounds.voxelCenterAtIntegerCoordinates[index];
  const lower = space.bounds.lowerBounds[index];
  const upper = space.bounds.upperBounds[index];
  const min = integerCentres ? Math.ceil(lower) : Math.ceil(lower - 0.5) + 0.5;
  const max = integerCentres ? Math.floor(upper) : Math.floor(upper - 0.5) + 0.5;
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) return null;
  return { index, min, max, value: position.value[index] };
}

/**
 * One slider that steps the view along a single axis of the image.
 *
 * Used twice: for `z`, to move through the planes of a stack, and for `t`, to
 * move through the frames of a timelapse. Both are the same job -- change one
 * number in the engine's position -- so they are the same control, and a store
 * that has no such axis simply gets no slider.
 */
function AxisSlider({ viewer, axis: axisName, label, unit = "" }) {
  const [axis, setAxis] = React.useState(null);

  React.useEffect(() => {
    if (!viewer) return undefined;
    const update = () => {
      const next = axisInfo(viewer, axisName);
      setAxis((current) =>
        current?.index === next?.index &&
        current?.min === next?.min &&
        current?.max === next?.max &&
        current?.value === next?.value
          ? current
          : next,
      );
    };
    // NavigationState also fires when coordinate reconciliation replaces the
    // Position object (for example when a writable annotation layer joins the
    // image coordinate space). Listening only to the old Position would leave
    // this slider frozen while Neuroglancer itself continued moving.
    const removeNavigationListener = viewer.navigationState.changed.add(update);
    const removePositionListener = viewer.navigationState.position.changed.add(update);
    const removeSpaceListener =
      viewer.navigationState.position.coordinateSpace.changed.add(update);
    // Neuroglancer may replace the Position while asynchronously reconciling
    // layer coordinate spaces. Signals belong to each Position instance, so a
    // small animation-frame observer ensures this external React control
    // follows the current official navigation object after such a replacement.
    let frame;
    const observeCurrentPosition = () => {
      update();
      frame = requestAnimationFrame(observeCurrentPosition);
    };
    frame = requestAnimationFrame(observeCurrentPosition);
    update();
    return () => {
      removeNavigationListener();
      removePositionListener();
      removeSpaceListener();
      cancelAnimationFrame(frame);
    };
  }, [viewer, axisName]);

  if (!axis) return null;
  // The slider steps in halves rather than whole planes, and that is deliberate.
  // The engine opens a view in the *middle* of an axis, which for an even number
  // of planes lands halfway between two of them: a four-frame timelapse starts at
  // 1.5. A control that could only hold whole numbers would be unable to show
  // that, and the browser would quietly round the thumb to 2 while our code still
  // believed 1.5 -- after which dragging it to 2 would change nothing, because as
  // far as the browser was concerned it was already there. The slider would look
  // correct and do nothing at all. Halves can represent every position the engine
  // actually takes, so what is shown and what is meant never come apart.
  const value = Math.max(axis.min, Math.min(axis.max, axis.value));
  const stepNumber = Math.round(value - axis.min + 1);
  const count = Math.round(axis.max - axis.min + 1);
  const moveTo = (next) => {
    const current = viewer.navigationState.position.value;
    const moved = Float32Array.from(current);
    moved[axis.index] = next;
    viewer.navigationState.position.value = moved;
  };

  return (
    <label style={styles.axisControl}>
      <span style={styles.axisLabel}>{label}</span>
      <input
        type="range"
        min={axis.min}
        max={axis.max}
        step={0.5}
        value={value}
        onChange={(event) => moveTo(Number(event.target.value))}
        aria-label={`${axisName} position`}
        style={styles.axisRange}
      />
      <output aria-label={`${axisName} position value`} style={styles.axisValue}>
        {stepNumber} / {count}
        {unit}
      </output>
    </label>
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
  // One entry per acquisition type, plus the order they are drawn in. Held here
  // rather than in the engine for the same reason as the rows: the panel and the
  // view must never disagree about what is showing.
  const [groupState, setGroupState] = React.useState({});
  const [groupOrder, setGroupOrder] = React.useState([]);
  const [targets, setTargets] = React.useState([]);
  const [targetsLoaded, setTargetsLoaded] = React.useState(false);
  const [targetColor, setTargetColor] = React.useState("#ffd34d");
  const [targetsVisible, setTargetsVisible] = React.useState(true);
  const [activeTool, setActiveTool] = React.useState(null);
  const [annotationGeneration, setAnnotationGeneration] = React.useState(0);
  // What happened the last time the targets were saved, shown in the panel so a
  // failed save cannot pass unnoticed.
  const [saveState, setSaveState] = React.useState({ status: "idle" });
  // Opening or closing images talks to Python, so the button is held while that
  // happens and anything that went wrong is shown rather than swallowed.
  const [storeBusy, setStoreBusy] = React.useState(false);
  const [storeNotice, setStoreNotice] = React.useState(null);
  const annotationSource = React.useRef(null);

  // Take on a new set of images -- at startup, and again whenever something is
  // opened or closed. Anything still open keeps the colour, contrast and opacity
  // the operator gave it: having those quietly reset because a second run was
  // opened alongside would be its own small betrayal.
  const applyConfig = React.useCallback((loaded) => {
    setConfig((previous) => {
      const kept = new Map();
      (previous?.layers || []).forEach((spec, index) => {
        kept.set(`${spec.group}/${spec.name}`, index);
      });
      setLayerState((current) =>
        loaded.layers.map((spec) => {
          const previousIndex = kept.get(`${spec.group}/${spec.name}`);
          if (previousIndex != null && current[previousIndex]) return current[previousIndex];
          return {
            visible: true,
            color: spec.color,
            opacity: 1,
            // Null means "use the mode-specific measured default". Once the
            // operator moves either contrast handle, their chosen window becomes
            // the source of truth in both 2-D and 3-D.
            window: null,
          };
        }),
      );
      return loaded;
    });
    const groups = loaded.groups || [...new Set(loaded.layers.map((l) => l.group || ""))];
    // Keep the order the operator dragged things into, with anything new appended
    // rather than dropped in the middle of what they arranged.
    setGroupOrder((current) => [
      ...current.filter((name) => groups.includes(name)),
      ...groups.filter((name) => !current.includes(name)),
    ]);
    setGroupState((current) =>
      Object.fromEntries(
        groups.map((name) => [name, current[name] || { visible: true, opacity: 1 }]),
      ),
    );
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    Promise.all([fetchConfig(), loadTargets()]).then(([loaded, savedTargets]) => {
      if (cancelled) return;
      applyConfig(loaded);
      setTargets(savedTargets);
      setTargetsLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [applyConfig]);

  // Look again every few seconds for acquisitions that have appeared since. During
  // a run the folder is still being written to, so a new acquisition type can turn
  // up long after the viewer was opened. Only a genuine change is applied:
  // re-applying an unchanged list would interrupt whatever the operator is doing.
  React.useEffect(() => {
    if (!config) return undefined;
    const signature = (c) =>
      JSON.stringify((c.layers || []).map((l) => `${l.group}/${l.name}/${l.channelIndex}`));
    const timer = setInterval(async () => {
      const loaded = await fetchConfig();
      if (signature(loaded) !== signature(config)) applyConfig(loaded);
    }, 4000);
    return () => clearInterval(timer);
  }, [config, applyConfig]);

  React.useEffect(() => {
    if (!viewer || !config || layerState.length !== config.layers.length) return;
    window.zmartViewer = viewer; // handy for inspection and the browser tests
    window.zmartConfig = config;
    window.zmartMode = mode;
    window.zmartLayerState = layerState;
    const oldSpace = viewer.navigationState.position.coordinateSpace.value;
    const oldPosition = viewer.navigationState.position.value;
    const namedPosition = oldSpace?.valid
      ? Object.fromEntries(oldSpace.names.map((name, index) => [name, oldPosition[index]]))
      : null;
    viewer.state.restoreState({
      layers: [
        ...layersFor(config, mode, layerState, groupState, groupOrder),
        annotationLayer(targets, targetColor, targetsVisible),
      ],
      layout: mode === "volume" ? VOLUME_LAYOUT : SLICE_LAYOUT,
      // The engine's own furniture -- the yellow data-bounds box and the axis
      // lines -- is off unless asked for. We are supplying the interface.
      showDefaultAnnotations: config.chrome ?? false,
      showAxisLines: config.chrome ?? false,
      showScaleBar: true,
    });
    const restorePosition = () => {
      if (!namedPosition) return;
      const position = viewer.navigationState.position;
      const space = position.coordinateSpace.value;
      if (!space?.valid) return;
      const moved = Float32Array.from(position.value);
      let changed = false;
      space.names.forEach((name, index) => {
        if (Number.isFinite(namedPosition[name]) && moved[index] !== namedPosition[name]) {
          moved[index] = namedPosition[name];
          changed = true;
        }
      });
      if (changed) position.value = moved;
    };
    restorePosition();
    const restoreTimer = setTimeout(restorePosition, 250);
    const connect = () => {
      const layer = viewer.layerManager.getLayerByName(TARGET_LAYER)?.layer;
      const source = layer?.localAnnotations;
      if (!source || source === annotationSource.current) return false;
      annotationSource.current = source;
      const update = () => setTargets(source.toJSON());
      source.changed.add(update);
      window.zmartAnnotationSource = source;
      setAnnotationGeneration((value) => value + 1);
      return true;
    };
    const connectTimer = connect() ? null : setInterval(() => {
      if (connect()) clearInterval(connectTimer);
    }, 50);
    return () => {
      clearTimeout(restoreTimer);
      if (connectTimer) clearInterval(connectTimer);
    };
  }, [viewer, config, mode, layerState, groupState, groupOrder, targetsLoaded, targetColor, targetsVisible]);

  // Saving happens on its own, shortly after any change, so the operator never
  // has to remember to. That makes it all the more important to *show* whether it
  // worked: a target list that silently failed to save looks exactly like one
  // that saved, right up until the acquisition is reopened and the targets are
  // gone.
  React.useEffect(() => {
    if (!targetsLoaded) return undefined;
    let cancelled = false;
    const timer = setTimeout(async () => {
      setSaveState({ status: "saving" });
      try {
        const response = await fetch("/api/annotations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version: 1, annotations: targets }),
        });
        if (cancelled) return;
        if (response.ok) {
          setSaveState({ status: "saved" });
          return;
        }
        const detail = await response.json().catch(() => null);
        setSaveState({ status: "error", message: detail?.error || `save failed (${response.status})` });
      } catch (error) {
        // Almost always the server having gone away -- worth saying plainly
        // rather than leaving the panel looking as though all is well.
        if (!cancelled) setSaveState({ status: "error", message: "could not reach the server" });
      }
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [targets, targetsLoaded]);

  React.useEffect(() => {
    if (!viewer) return;
    const layer = viewer.layerManager.getLayerByName(TARGET_LAYER)?.layer;
    if (!layer) return;
    layer.tool.value =
      activeTool === "point"
        ? new PlacePointTool(layer, {})
        : activeTool === "box"
          ? new PlaceBoundingBoxTool(layer, {})
          : undefined;
  }, [viewer, activeTool, targetsLoaded]);

  const setGroup = (name, change) =>
    setGroupState((current) => ({ ...current, [name]: { ...current[name], ...change } }));

  // Dragging an acquisition type up or down changes which one is drawn on top,
  // so this is a real control rather than tidying: the engine composites in the
  // order it is given, and this is that order.
  const moveGroup = (from, to) =>
    setGroupOrder((current) => {
      if (from === to || from == null || to == null) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });

  const setLayer = (index, change) =>
    setLayerState((current) =>
      current.map((entry, i) => (i === index ? { ...entry, ...change } : entry)),
    );

  const source = () => annotationSource.current;
  const deleteTarget = (id) => {
    const reference = source()?.getReference(id);
    if (!reference) return;
    source().delete(reference);
    reference.dispose();
  };
  const selectTarget = (id) => {
    const layer = viewer?.layerManager.getLayerByName(TARGET_LAYER)?.layer;
    const state = layer?.annotationStates?.states?.find((entry) => !entry.source.readonly);
    if (state) {
      layer.selectAnnotation(state, id, true);
      window.zmartSelectedTarget = id;
    }
  };
  // Give a target a name. Neuroglancer owns the annotation itself, so the new
  // description is written back through the annotation source rather than kept
  // beside it -- that way the engine, the list, and the saved file cannot drift
  // apart, and the change reaches the sidecar by the same route as everything
  // else the operator draws.
  const describeTarget = (id, description) => {
    const reference = source()?.getReference(id);
    if (!reference?.value) return;
    source().update(reference, { ...reference.value, description });
    reference.dispose();
  };

  return (
    <div style={styles.shell}>
      {config && (
        <LayerPanel
          layers={config.layers}
          state={layerState}
          mode={mode}
          groupOrder={groupOrder}
          groupState={groupState}
          onGroupToggle={(name) => setGroup(name, { visible: !groupState[name]?.visible })}
          onGroupOpacity={(name, opacity) => setGroup(name, { opacity })}
          onGroupMove={moveGroup}
          busy={storeBusy}
          notice={storeNotice}
          onOpenStore={async () => {
            setStoreBusy(true);
            setStoreNotice(null);
            const result = await chooseAndOpen();
            if (result.config) applyConfig(result.config);
            if (result.error) setStoreNotice(result.error);
            setStoreBusy(false);
          }}
          onCloseGroup={async (group) => {
            setStoreBusy(true);
            setStoreNotice(null);
            const result = await closeGroup(group);
            if (result.config) applyConfig(result.config);
            if (result.error) setStoreNotice(result.error);
            setStoreBusy(false);
          }}
          onToggle={(i) => setLayer(i, { visible: !layerState[i].visible })}
          onColor={(i, color) => setLayer(i, { color })}
          onOpacity={(i, opacity) => setLayer(i, { opacity })}
          onWindow={(i, window) => setLayer(i, { window })}
        />
      )}
      <main style={styles.stage}>
        <NeuroglancerView onViewer={setViewer} />
        <ModeToggle mode={mode} onChange={setMode} />
        <div style={styles.axisControls}>
          {/* Z steps through the planes of the stack, so it belongs to the 2-D
              working view; in 3-D the whole depth is already on screen. Time is
              meaningful in both, and appears only for a timelapse store. */}
          {mode === "flat" && (
            <AxisSlider key={`z-${annotationGeneration}`} viewer={viewer} axis="z" label="Z" />
          )}
          <AxisSlider
            key={`t-${annotationGeneration}`}
            viewer={viewer}
            axis="t"
            label="T"
          />
        </div>
      </main>
      <TargetsPanel
        targets={targets}
        activeTool={activeTool}
        color={targetColor}
        visible={targetsVisible}
        saveState={saveState}
        onTool={setActiveTool}
        onColor={setTargetColor}
        onVisible={() => setTargetsVisible((value) => !value)}
        onSelect={selectTarget}
        onDelete={deleteTarget}
        onDescribe={describeTarget}
      />
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
  // The sliders stack in one column at the bottom of the stage, so a timelapse
  // showing both Z and T never has them overlapping.
  axisControls: {
    position: "absolute",
    left: "50%",
    bottom: 16,
    transform: "translateX(-50%)",
    zIndex: 10,
    display: "grid",
    gap: 6,
    justifyItems: "stretch",
  },
  axisControl: {
    display: "grid",
    gridTemplateColumns: "18px minmax(220px, 34vw) 70px",
    alignItems: "center",
    gap: 8,
    padding: "8px 12px",
    border: "1px solid #2c333d",
    borderRadius: 7,
    background: "rgba(18, 22, 28, .94)",
    boxShadow: "0 2px 8px rgba(0,0,0,.55)",
    color: "#c9d1d9",
    font: "600 11px/1 system-ui, sans-serif",
  },
  axisLabel: { color: "#7f8a98" },
  axisRange: { width: "100%", accentColor: "#2f81f7", cursor: "pointer" },
  axisValue: { textAlign: "right", color: "#aab4c0", fontVariantNumeric: "tabular-nums" },
};
