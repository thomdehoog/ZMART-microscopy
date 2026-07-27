import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";
import LayerPanel from "./LayerPanel.jsx";
import TargetsPanel from "./TargetsPanel.jsx";
import { PlacePointTool, PlaceBoundingBoxTool } from "neuroglancer/unstable/ui/annotations.js";
import { chooseScaleWhenTheImagesAreMeasured, syncLayers, syncView } from "./engine.js";
import ScaleBar from "./ScaleBar.jsx";
import AxisSlider from "./AxisSlider.jsx";
import { LOOKUP_TABLE_NAMES, layerKey, layersFor } from "./scene.js";

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

// How many unanswered questions in a row before the panel says the server has
// gone quiet. At one question every 700 ms this is a little over three seconds,
// which is long enough to ride out a brief hiccup and short enough to be useful.
const UNANSWERED_BEFORE_SAYING_SO = 5;

// How long each frame is held when an axis is played through. Fast enough to read
// as movement, slow enough that the engine can usually fetch the next plane before
// it is wanted.
const PLAY_STEP_MS = 140;


/**
 * Ask the server what is open, or return null if it cannot be reached.
 *
 * Returning null rather than an invented set of images is the point. An earlier
 * version answered a failure with a made-up volume that did not exist, so a
 * server that had stopped answering looked exactly like data that had failed to
 * load: a black screen and nothing to read. Saying plainly that the server could
 * not be reached is far more use to someone at two in the morning wondering
 * whether their experiment is still running.
 */
async function fetchConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
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
  // What happened the last time the targets were saved, shown in the panel so a
  // failed save cannot pass unnoticed.
  const [saveState, setSaveState] = React.useState({ status: "idle" });
  // Opening or closing images talks to Python, so the button is held while that
  // happens and anything that went wrong is shown rather than swallowed.
  const [storeBusy, setStoreBusy] = React.useState(false);
  const [storeNotice, setStoreNotice] = React.useState(null);
  // Which channel the block of controls is acting on. Held by name rather than by
  // position in the list, because the list is rebuilt whenever something is opened
  // or closed: a position would still be a valid number afterwards and would
  // quietly refer to a different channel, so the sliders would go on working while
  // adjusting something the operator was not looking at.
  const [selectedKey, setSelectedKey] = React.useState(null);
  const [barOpen, setBarOpen] = React.useState(true);
  // Which edge the bar of controls sits on, decided when the viewer is started.
  const onLeft = config?.panelSide === "left";
  const annotationSource = React.useRef(null);
  // How to stop listening to the annotation source we are currently following.
  const stopListening = React.useRef(null);
  // The targets read back from the previous session. These are handed to the
  // engine once, when the layer that holds them is built. Kept aside from the
  // living list of targets on purpose: that list changes with every scribble, and
  // if the description of the scene depended on it, drawing would rebuild the very
  // layer being drawn into.
  const targetsFromDisk = React.useRef([]);
  // The set of images last taken on, used to spot an answer that says nothing new.
  const applied = React.useRef(null);
  // Whether the (expensive) question of what is open is already outstanding.
  const asking = React.useRef(false);
  // Set when an announcement arrives, so the next pass through the engine reads each
  // open store's description again rather than assuming it still says what it did.
  // A timelapse gaining a frame changes nothing the panel can see -- same stores,
  // same channels -- so without this the engine would go on believing the old length
  // and the time slider would never reach the new frame.
  const rereadWanted = React.useRef(false);

  // Take on a new set of images -- at startup, and again whenever something is
  // opened or closed. Anything still open keeps the colour, contrast and opacity
  // the operator gave it: having those quietly reset because a second run was
  // opened alongside would be its own small betrayal.
  const applyConfig = React.useCallback((loaded) => {
    // What was taken on last time. Kept here rather than read back out of the
    // displayed state because it is needed *while* deciding the new state, and a
    // piece of state cannot be read and written in the same breath.
    // Nothing came back: the server could not be reached. Whatever is on screen
    // stays there — an experiment half-watched is better than a blank panel — and
    // the poll below is what says so out loud.
    if (!loaded) return;
    const previous = applied.current;
    // Nothing actually different, so leave everything alone. This matters more
    // than it looks: the viewer asks whether anything has changed several times a
    // second, and without this check an identical answer would still count as new
    // and send the whole picture round again.
    if (previous && JSON.stringify(previous) === JSON.stringify(loaded)) return;
    applied.current = loaded;

    // Match each channel now open to the same channel before, so the colour,
    // contrast and opacity the operator chose follow it across the change.
    const before = new Map(
      (previous?.layers || []).map((spec, index) => [`${spec.group}/${spec.name}`, index]),
    );
    setLayerState((current) =>
      loaded.layers.map((spec) => {
        const was = before.get(`${spec.group}/${spec.name}`);
        if (was != null && current[was]) return current[was];
        return {
          visible: true,
          color: spec.color,
          // No colour map to begin with: a channel opens in the flat colour the
          // store asked for, and a lookup table is something you choose.
          lut: null,
          opacity: 1,
          // Null means "use the mode-specific measured default". Once the
          // operator moves either contrast handle, their chosen window becomes
          // the source of truth in both 2-D and 3-D.
          window: null,
        };
      }),
    );
    setConfig(loaded);

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

  // Ask the server what is open, and take it on.
  //
  // This is the only place the question is asked, which matters more than it
  // sounds: on a folder of several thousand positions the answer is genuinely
  // expensive, and two of them racing at startup was measurably slower for no
  // benefit at all.
  const catchUp = React.useCallback(async () => {
    // Not while one is already outstanding. Several announcements can arrive
    // close together at the start of a run, and a browser allows only six
    // connections to one address -- a queue of expensive questions would leave
    // the engine unable to fetch a single piece of image until they finished.
    if (asking.current) return;
    asking.current = true;
    rereadWanted.current = true;
    const loaded = await fetchConfig().finally(() => {
      asking.current = false;
    });
    if (loaded) applyConfig(loaded);
    else setStoreNotice("Could not reach the server. Is it still running?");
  }, [applyConfig]);

  // The targets drawn in a previous session, read once. The images are not read
  // here: they arrive when the connection below opens, which is the moment we
  // know the server is actually answering.
  React.useEffect(() => {
    let cancelled = false;
    loadTargets().then((savedTargets) => {
      if (cancelled) return;
      targetsFromDisk.current = savedTargets;
      setTargets(savedTargets);
      setTargetsLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Whether there is anything to listen for. Finished data cannot change, so a
  // viewer on it holds no connection open. Until the first answer arrives we do
  // not know which we have, and "listen" is the right assumption: a live run that
  // heard nothing would sit there missing its own data.
  const shouldListen = config === null || config.live !== false;

  // Listen for the server saying that something has changed.
  //
  // The viewer used to find this out by asking, every seven hundred milliseconds
  // for the life of the window, whether anything had moved -- and being told
  // "nothing" almost every time. Now the server says so when it happens: the page
  // holds one connection open and hears a line on it when there is something to
  // hear. Between events nothing is sent and nothing is asked.
  //
  // A message carries no detail, and does not need to. Hearing one means "ask
  // again", and the answer is read from disk, so there is only ever one
  // description of the world and it is the true one.
  React.useEffect(() => {
    // On finished data there is nothing to hear, so no connection is held. This
    // is the whole of static mode on this side.
    //
    // Written so the *first* answer is still fetched whichever mode we are in:
    // until something has been loaded there is a viewer with nothing in it, and
    // we do not yet know which mode we are in.
    if (!shouldListen) return undefined;
    let stop = false;
    const askAgain = () => {
      if (!stop) catchUp();
    };

    const listener = new EventSource("/api/events");
    // Any message at all means "ask again", so both the named event and anything
    // else that arrives are treated the same. Being generous here means a future
    // kind of announcement cannot be silently ignored by an older page.
    listener.addEventListener("changed", askAgain);
    listener.onmessage = askAgain;
    // Opening the connection is also what fetches the images for the first time,
    // and this is deliberate rather than convenient. It means "we are connected"
    // and "we are up to date" are established together, so there is no separate
    // path to get wrong -- and a viewer that opened while the server was still
    // starting simply catches up when the browser reconnects, which it does on
    // its own. During a run there is no button to try again with, so recovering
    // without one matters.
    listener.onopen = () => {
      if (stop) return;
      setStoreNotice(null);
      catchUp();
    };
    // The browser reconnects on its own when a connection drops, so this is not a
    // place to retry from -- it is a place to say something. A viewer that has
    // quietly lost its server looks exactly like an experiment that has stopped
    // producing data, and at two in the morning those call for very different
    // reactions.
    let silence = 0;
    listener.onerror = () => {
      if (stop) return;
      silence += 1;
      if (silence === UNANSWERED_BEFORE_SAYING_SO) {
        setStoreNotice("Not hearing from the server — what is shown may be out of date.");
      }
    };

    return () => {
      stop = true;
      listener.close();
    };
    // Depending on one true-or-false rather than on the whole of what is open, and
    // the difference matters more than it looks.
    //
    // The set of open images changes every time an acquisition appears. If that
    // tore this down, it would close and reopen the very connection the news
    // arrived on -- so a run producing data steadily would spend it reconnecting,
    // with a gap each time in which the next announcement would be missed.
    //
    // It is a plain true-or-false rather than the mode itself for a smaller
    // reason: before the first answer we do not yet know the mode, and going from
    // "not known yet" to "live" would count as a change and reconnect once for
    // nothing. Both of those states mean "listen", so as one boolean they are the
    // same value and nothing happens.
  }, [catchUp, shouldListen]);

  // Everything the engine should be showing, in the order it should be drawn.
  //
  // This is worked out here, on its own, so that it is recomputed only when
  // something about the picture has genuinely changed. Note what it does *not*
  // depend on: the list of drawn targets. Those live in the engine once their
  // layer exists, and the list beside the image is a reflection of them — so
  // drawing one must not send the whole scene back through here.
  const scene = React.useMemo(() => {
    if (!config || layerState.length !== config.layers.length) return null;
    const layers = layersFor(config, mode, layerState, groupState, groupOrder);
    // The layer holding drawn targets is added once the saved ones have been read
    // back, so whatever was saved is present from the moment the layer exists.
    if (targetsLoaded) {
      layers.push(annotationLayer(targetsFromDisk.current, targetColor, targetsVisible));
    }
    return layers;
  }, [
    config,
    mode,
    layerState,
    groupState,
    groupOrder,
    targetsLoaded,
    targetColor,
    targetsVisible,
  ]);

  // Let the engine settle on a starting magnification once the images have said
  // how big they are. Declared ahead of the effect that adds the layers so the
  // waiting is in place before there is anything to wait for; see engine.js for
  // what goes wrong without it.
  React.useEffect(() => {
    if (!viewer) return undefined;
    return chooseScaleWhenTheImagesAreMeasured(viewer);
  }, [viewer]);

  React.useEffect(() => {
    if (!viewer || !scene) return undefined;
    window.zmartViewer = viewer; // handy for inspection and the browser tests
    window.zmartConfig = config;
    window.zmartMode = mode;
    window.zmartLayerState = layerState;
    // Where the operator is looking, remembered by axis name rather than by
    // position in the list. Adding an acquisition can introduce an axis the view
    // did not have before, which shifts every axis after it along one place; going
    // by name means the view still comes back to the same plane rather than to
    // whatever now happens to sit in that slot.
    const space = viewer.navigationState.position.coordinateSpace.value;
    const looking = space?.valid
      ? Object.fromEntries(
          space.names.map((name, index) => [
            name,
            viewer.navigationState.position.value[index],
          ]),
        )
      : null;

    syncView(viewer, {
      layout: mode === "volume" ? VOLUME_LAYOUT : SLICE_LAYOUT,
      // The engine's own furniture -- the yellow data-bounds box and the axis
      // lines -- is off unless asked for. We are supplying the interface.
      chrome: config.chrome ?? false,
    });
    // An announcement means something on disk has changed, and it may be something
    // no description of the scene would show -- a frame added to a store already
    // open. So the descriptions are read again on the pass that follows one.
    const reread = rereadWanted.current;
    rereadWanted.current = false;
    const reshaped = syncLayers(viewer, scene, { reread });
    window.zmartLayersReshaped = reshaped; // what the browser tests count

    // Only a change in the shape of the scene can move the view: adding or
    // removing an image makes the engine work out the coordinate space afresh,
    // and it lands somewhere sensible rather than where the operator was. Turning
    // a knob cannot, so in that far more common case nothing here runs at all.
    if (!reshaped || !looking) return undefined;
    const lookAgain = () => {
      const position = viewer.navigationState.position;
      const now = position.coordinateSpace.value;
      if (!now?.valid) return;
      const moved = Float32Array.from(position.value);
      let changed = false;
      now.names.forEach((name, index) => {
        if (Number.isFinite(looking[name]) && moved[index] !== looking[name]) {
          moved[index] = looking[name];
          changed = true;
        }
      });
      if (changed) position.value = moved;
    };
    lookAgain();
    // The coordinate space settles a moment after the images are attached, so it
    // is worth looking once more shortly afterwards.
    const settled = setTimeout(lookAgain, 250);
    return () => clearTimeout(settled);
  }, [viewer, scene, config, mode, layerState]);

  // Start listening to the layer that holds drawn targets, so the list beside the
  // image follows what is actually in the engine. The layer's store of annotations
  // is created a moment after the layer itself, which is why this waits for it
  // rather than assuming it is there.
  React.useEffect(() => {
    if (!viewer || !targetsLoaded) return undefined;
    const connect = () => {
      const layer = viewer.layerManager.getLayerByName(TARGET_LAYER)?.layer;
      const source = layer?.localAnnotations;
      if (!source) return false; // not built yet; look again shortly
      if (source === annotationSource.current) return true; // already listening
      // Let go of the previous one first. This only happens if the layer really
      // was rebuilt, which is rare now, but leaving the old listener attached
      // would mean two of them writing to the same list.
      if (stopListening.current) stopListening.current();
      annotationSource.current = source;
      stopListening.current = source.changed.add(() => setTargets(source.toJSON()));
      window.zmartAnnotationSource = source;
      setTargets(source.toJSON());
      return true;
    };
    if (connect()) return undefined;
    const waiting = setInterval(() => {
      if (connect()) clearInterval(waiting);
    }, 50);
    return () => clearInterval(waiting);
  }, [viewer, targetsLoaded, scene]);

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

  // The furthest any open acquisition has got in time. Several may be running at
  // once and one can be a frame ahead of another, so the slider follows the
  // longest -- a frame that exists somewhere is worth being able to reach.
  const framesAvailable = React.useMemo(() => {
    const counts = (config?.layers || [])
      .map((spec) => spec.frames)
      .filter((n) => typeof n === "number" && n > 0);
    return counts.length ? Math.max(...counts) : null;
  }, [config]);

  // Where the chosen channel now sits in the list. Falling back to the first row
  // means closing the channel that was being adjusted leaves the controls on
  // something real rather than on nothing.
  const selected = React.useMemo(() => {
    const rows = config?.layers || [];
    const at = rows.findIndex((spec) => layerKey(spec) === selectedKey);
    return at >= 0 ? at : 0;
  }, [config, selectedKey]);

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
  /**
   * Show a target: pick it out, and move the view to where it is.
   *
   * Both halves are needed. Picking it out on its own leaves the view exactly
   * where it was, and a target is usually on some other plane of the stack — so
   * clicking it in the list looked, from the operator's side, like the button
   * simply did nothing. Moving the view is what makes it a way of getting back to
   * a place you marked earlier, which is the whole point of marking it.
   */
  const selectTarget = (id) => {
    const layer = viewer?.layerManager.getLayerByName(TARGET_LAYER)?.layer;
    const state = layer?.annotationStates?.states?.find((entry) => !entry.source.readonly);
    if (!state) return;
    layer.selectAnnotation(state, id, true);
    window.zmartSelectedTarget = id;

    const target = targets.find((entry) => entry.id === id);
    // A point sits at one place; a box is a corner and its opposite, so the
    // middle of the two is the place to go.
    const where =
      target?.point ||
      (target?.pointA && target?.pointB
        ? target.pointA.map((value, axis) => (value + target.pointB[axis]) / 2)
        : null);
    if (!where) return;
    const position = viewer.navigationState.position;
    const moved = Float32Array.from(position.value);
    // A target is recorded against the same axes the view uses, in the same
    // order, so this is a straight copy of as much of it as there is room for.
    where.slice(0, moved.length).forEach((value, axis) => {
      if (Number.isFinite(value)) moved[axis] = value;
    });
    position.value = moved;
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
    <div
      style={{
        ...styles.shell,
        // Putting the bar on the left is done by reversing the row rather than by
        // moving anything: the image and the bar keep the same order in the page,
        // so the fold strip stays between them and still folds towards the edge the
        // bar is on, whichever edge that is.
        flexDirection: onLeft ? "row-reverse" : "row",
      }}
    >
      <main style={styles.stage}>
        <NeuroglancerView onViewer={setViewer} />
        <ModeToggle mode={mode} onChange={setMode} />
        <ScaleBar viewer={viewer} />
        <div style={styles.axisControls}>
          {/* Z steps through the planes of the stack, so it belongs to the 2-D
              working view; in 3-D the whole depth is already on screen. Time is
              meaningful in both. Neither appears unless the image actually has
              that axis with more than one step along it -- a still image gets no
              time slider, and a single plane gets no Z slider. */}
          {mode === "flat" && <AxisSlider viewer={viewer} axis="z" label="Z" />}
          <AxisSlider
            viewer={viewer}
            axis="t"
            label="T"
            // A timelapse is given its full length in time when it is created,
            // long before the run has produced that many frames. The slider stops
            // at what has actually been written, because the engine remembers
            // "nothing here" for a frame looked at too early and will not look
            // again -- so that frame would stay blank for the rest of the session.
            limit={framesAvailable}
          />
        </div>
      </main>
      {/* One bar holding everything: the images and the targets.
          It folds away to the edge because at the microscope the screen is often
          a laptop's, and a third of it permanently given to controls is a third
          of the specimen not being looked at. */}
      <button
        type="button"
        onClick={() => setBarOpen((open) => !open)}
        style={styles.fold}
        aria-label={barOpen ? "hide the controls" : "show the controls"}
        aria-expanded={barOpen}
        title={barOpen ? "Fold the controls away" : "Show the controls"}
      >
        {barOpen === onLeft ? "›" : "‹"}
      </button>
      {barOpen && (
        <aside style={styles.bar} aria-label="controls">
          {config && (
            <LayerPanel
              layers={config.layers}
              state={layerState}
              mode={mode}
              groupOrder={groupOrder}
              groupState={groupState}
              selected={selected}
              onSelect={(index) => setSelectedKey(layerKey(config.layers[index]))}
              canOpen={config.canOpen !== false}
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
              onLut={(i, lut) => setLayer(i, { lut })}
              lookupTables={LOOKUP_TABLE_NAMES}
            />
          )}
          {config?.canSelect && (
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
          )}
        </aside>
      )}
    </div>
  );
}

const styles = {
  shell: { position: "absolute", inset: 0, display: "flex", background: "#0b0d10" },
  bar: {
    width: 264,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    border: "1px solid #232a33",
    borderTop: "none",
    borderBottom: "none",
    background: "#12161c",
  },
  fold: {
    alignSelf: "stretch",
    width: 14,
    border: "none",
    borderLeft: "1px solid #232a33",
    background: "#12161c",
    color: "#8b95a3",
    font: "12px/1 system-ui, sans-serif",
    cursor: "pointer",
    padding: 0,
  },
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
    left: 14,
    right: 14,
    bottom: 14,
    zIndex: 10,
    display: "grid",
    gap: 6,
    justifyItems: "stretch",
  },
};
