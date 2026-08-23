import React from "react";
import NeuroglancerView from "./NeuroglancerView.jsx";
import LayerPanel from "./LayerPanel.jsx";
import TargetsPanel from "./TargetsPanel.jsx";
import { PlacePointTool, PlaceBoundingBoxTool } from "neuroglancer/unstable/ui/annotations.js";
import {
  lookAtWhatOpened,
  putTheViewBack,
  whatIsOnScreen,
  chooseScaleWhenTheImagesAreMeasured,
  watchTheReplay,
  letGoOfDecodedPieces,
  lettingGo,
  sourceRefreshing,
  sourcesStillWaiting,
  syncLayers,
  syncView,
  stretchTheDisplay,
} from "./engine.js";
import ScaleBar from "./ScaleBar.jsx";
import AxisSlider from "./AxisSlider.jsx";
import { LOOKUP_TABLE_NAMES, engineName, layerKey, layersFor } from "./scene.js";
import { liveStateProblem } from "./live-refresh.js";

// The two ways of looking at a volume, and the only thing the operator has to
// choose between. 2-D is the working view -- one plane, scroll through the
// stack. 3-D is for reading shape: the same data ray-cast, rotatable.
const MODES = { flat: "2D", volume: "3D" };
const LIVE_STATE_CHECK_MS = 10_000;

// Which of the engine's named panel layouts the flat view asks for.
//
// The engine names its panels after *display* axes -- the first, second and third
// of the axes it has been handed, not the axes the image calls x, y and z. So
// this name only means anything alongside the order those axes are handed over
// in, which is settled in engine.js by `pinTheAxesThatMeasureDistance`. It hands
// them over width first, then height, then depth. With that order, "xy" puts width
// across the window running to the right, height down it, and depth into the
// screen -- the plane the operator scrolls through, drawn the same way round as
// the specimen.
//
// **The two must be changed together.** Either one on its own gives a view that
// is edge-on or mirrored, and a mirrored view is the dangerous one because it
// still looks like a good picture. The viewer shipped a mirrored one for months.
// engine.js sets this out at length, and
// `tests/test_the_picture_is_not_mirrored.py` measures it off the screen.
const SLICE_LAYOUT = "xy";
const VOLUME_LAYOUT = "3d";

// How many unanswered questions in a row before the panel says the server has
// gone quiet. At one question every 700 ms this is a little over three seconds,
// which is long enough to ride out a brief hiccup and short enough to be useful.
const UNANSWERED_BEFORE_SAYING_SO = 5;

// -- asking Python to do things -----------------------------------------------
//
// Four short conversations with the server, kept together and kept out of the
// component below. Every one of them answers with something the interface can show
// even when it went wrong, because a button that silently does nothing is the
// hardest kind of fault for an operator to make sense of.

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

async function fetchLiveState(etag = null) {
  try {
    const headers = etag ? { "If-None-Match": etag } : {};
    const response = await fetch("/api/live-state", { headers });
    if (response.status === 304) return { unchanged: true, etag };
    if (!response.ok) return null;
    return {
      unchanged: false,
      etag: response.headers.get("ETag"),
      state: await response.json(),
    };
  } catch {
    return null;
  }
}

// The desktop window can show the operating system's own folder chooser; a
// page in a plain browser cannot, and used to fall back to a bare prompt
// asking for a path typed blind. Now the page draws its own load window
// instead (see LoadWindow below), walking the server's folders by listing
// them through the API.
async function tryNativeChooser() {
  try {
    const response = await fetch("/api/browse", { method: "POST" });
    const answer = await response.json().catch(() => null);
    if (answer?.cancelled) return { cancelled: true };
    if (response.ok && answer?.path) {
      return { path: answer.path, parent: answer.parent };
    }
  } catch {
    // fall through to the in-page window
  }
  return { window: true };
}

async function measureHere(asked) {
  try {
    const response = await fetch("/api/measure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(asked),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    // A measurement that cannot be taken leaves the picture as it is, which
    // is the honest answer to a button that had nothing to read.
    return null;
  }
}

async function openPath(path) {
  const response = await fetch("/api/stores/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) {
    return {
      error: answer?.error || `could not open ${path}`,
      relink: answer?.relink || null,
    };
  }
  return { config: answer };
}

async function startConstruction(path, viewerFolder, bake, name) {
  const response = await fetch("/api/stores/construct", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, viewer_folder: viewerFolder, bake, name }),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) return { error: answer?.error || "the construction could not start" };
  return { started: true };
}

async function constructionStatus() {
  const response = await fetch("/api/stores/construct-status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  return response.json().catch(() => ({ state: "error", error: "unreadable answer" }));
}

async function startReplay(path, perSecond) {
  const response = await fetch("/api/stores/replay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // The server counts the pause between positions; the window asks in
    // positions per second, which is how anybody watching describes it. At
    // the top of the range there is no pause at all: the replay goes as fast
    // as the writer can commit, which is the honest meaning of "maximum".
    body: JSON.stringify({
      path,
      every: perSecond >= AS_FAST_AS_IT_CAN ? 0 : 1 / perSecond,
    }),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) return { error: answer?.error || "the replay could not start" };
  return { config: answer };
}

async function replayStatus() {
  const response = await fetch("/api/stores/replay-status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  return response.json().catch(() => ({ state: "error", error: "unreadable answer" }));
}

// Ask the running build or replay to stop at its next step. Cooperative:
// the step in flight finishes whole, so a stopped replay's landed positions
// stay a real run, and a stopped build removes its half-made scene.
async function askToStop(what) {
  await fetch(`/api/stores/${what}-cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => null);
}

async function listFolders(path) {
  const response = await fetch("/api/stores/list", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(path ? { path } : {}),
  });
  const answer = await response.json().catch(() => null);
  if (!response.ok) return { error: answer?.error || "the folders could not be listed" };
  return answer;
}

/**
 * The load window: pick the thing to look at, and the window says what it is.
 *
 * The path box takes a typed or pasted path (Enter goes there); the rows are
 * the folders at that path, each wearing a tag for what it is — a built view,
 * one image, a plate, or raw positions. Choosing a row says in one line what
 * Open will do with it: a view, image or plate opens directly, and raw
 * positions are shown through a view built over them on the spot (with the
 * two build questions — where to save it, and whether to bake the
 * low-resolution mosaic — laid out beforehand, already answered). The
 * experimental tab replays a raw run through the live writer instead, and
 * accepts nothing else. Errors from the walk, the build or the open all show
 * inside the window, where the operator is looking.
 */
// How fast the positions of a replay may land, in positions per second, and
// the mark at which the pace is dropped altogether. Twenty a second is past
// the point where an eye can follow one landing from the next; asking for
// more is asking for "no waiting", so that is what the top of the range
// means.
const AS_FAST_AS_IT_CAN = 20;
const REPLAY_PACES = [0.5, 1, 2, 5, 10, AS_FAST_AS_IT_CAN];

const LOAD_KINDS = [
  { key: "open", label: "default",
    said: "point at what you want to see — a view, an image, a plate, or raw positions. "
      + "Raw data is shown through a view built over it, nothing copied" },
  { key: "other", label: "open positions sequentially",
    said: "replay a finished dataset as though the microscope were running it "
      + "— its positions land one at a time, through the live path, for "
      + "testing and troubleshooting" },
];

// What each kind of row IS — the little tag on the row, and the sentence
// beneath the list once it is chosen. The kinds come from the server's
// listing (see _serve_list_folders); a row with no kind is just a place to
// walk into. A "run" covers both shapes raw data takes: a plain folder of
// position stores, and a bare zarr group wrapping them.
const ROW_KINDS = {
  // A view is at heart a LINK file: a small description pointing at the raw
  // data, copying nothing. Baking only adds one hard-copied piece — the
  // low-resolution mosaic (the ⚡ in the list) — and everything at full
  // resolution stays linked either way. The words below lead with that,
  // because "built" made it sound like the data had been duplicated.
  // Two families only, as the operator settled it (2026-08-23): a row is
  // either ZARR — data, whatever shape it takes — or ZMARTVIEW. The
  // sentence still tells the shapes apart, because Open treats them
  // differently; the tag deliberately does not.
  view: { tag: "zmartview",
          said: "a view — links to the raw data, nothing duplicated; it opens directly" },
  image: { tag: "zarr", said: "one image — it opens directly" },
  plate: { tag: "zarr", said: "a plate of wells — it opens directly" },
  run: { tag: "zarr",
         said: "raw positions from the microscope — Open links them together "
           + "into one picture for this session; nothing is copied and "
           + "nothing is kept unless the mosaic is asked for" },
};

function LoadWindow({ listing, onNavigate, onOpened, onConstructed, onCancel,
                     onArriving,
                      onReplayStarted }) {
  const [busy, setBusy] = React.useState(false);
  const [openError, setOpenError] = React.useState(null);
  // Which tab is chosen. Loading an existing view is the commonest thing
  // to do, so the window starts there, folders already showing.
  const [kind, setKind] = React.useState("open");
  // Raw data being constructed into a viewer: which folder, where the
  // viewer's files go, and whether the pieces are prebaked now or made on
  // the fly later. Null while the operator is still walking folders.
  const [constructing, setConstructing] = React.useState(null);
  // The row the operator clicked last: highlighted in the list, and what
  // the Open button below the list acts on. Cleared when the folder or the
  // tab changes, because the list under it has changed.
  const [selected, setSelected] = React.useState(null);
  // What the running replay reports, while the "other" tab is showing: how
  // far it is and whether it runs at all, so the tab can offer Stop and say
  // why a second Replay must wait. Polled only while that tab is open.
  const [replaying, setReplaying] = React.useState(null);
  // How fast a replay should land its positions. Kept here rather than in the
  // server's answer because it is a wish about the next replay, not a fact
  // about the running one.
  const [pace, setPace] = React.useState(1.4);
  React.useEffect(() => {
    if (kind !== "other") return undefined;
    let watching = true;
    const look = async () => {
      const status = await replayStatus();
      if (watching) setReplaying(status);
    };
    look();
    const ticking = setInterval(look, 700);
    return () => {
      watching = false;
      clearInterval(ticking);
    };
  }, [kind]);
  const polling = React.useRef(null);

  const navigate = (path) => {
    setSelected(null);
    onNavigate(path);
  };

  React.useEffect(() => () => clearInterval(polling.current), []);

  // Opening a store directly -- and a viewer whose raw data has moved
  // answers with a relink ask, which becomes the pane below, prefilled.
  const openStore = async (path) => {
    setBusy(true);
    const result = await openPath(path);
    setBusy(false);
    if (result.config) {
      onOpened(result.config);
    } else if (result.relink) {
      setConstructing({
        relink: true,
        name: result.relink.name,
        data: result.relink.was,
        destination: path.slice(0, path.lastIndexOf("/")),
        bake: result.relink.baked,
      });
    } else {
      setConstructing(null);
      setOpenError(result.error);
    }
  };

  // The kept way to open a run: build the view — with its baked mosaic, at
  // the place the operator chose — and open what was built, as one press.
  // The plain way is not here at all: an untouched Open goes straight to
  // openStore, and the server composes a link file it keeps to itself and
  // forgets when it closes (the operator's rule, 2026-08-23).
  const openRun = async () => {
    const { data, destination, bake } = constructing;
    setConstructing((current) => ({ ...current, running: true, fraction: 0,
                                    error: null }));
    const begun = await startConstruction(data, destination, bake);
    if (begun.error) {
      setConstructing((current) => ({ ...current, running: false, error: begun.error }));
      return;
    }
    polling.current = setInterval(async () => {
      const status = await constructionStatus();
      if (status.state === "running") {
        setConstructing((current) => current && { ...current, fraction: status.fraction || 0 });
        return;
      }
      clearInterval(polling.current);
      if (status.state === "done") {
        await openStore(status.store);
      } else if (status.state === "cancelled") {
        setConstructing((current) => current &&
          { ...current, running: false, fraction: 0 });
      } else {
        setConstructing((current) => current &&
          { ...current, running: false,
            error: status.error || "the view could not be built" });
      }
    }, 350);
  };

  const start = async () => {
    const { data, destination, bake, relink, name } = constructing;
    setConstructing((current) => ({ ...current, running: true, fraction: 0,
                                    error: null, stopped: false }));
    const begun = await startConstruction(data, destination, bake,
                                          relink ? name : undefined);
    if (begun.error) {
      setConstructing((current) => ({ ...current, running: false, error: begun.error }));
      return;
    }
    polling.current = setInterval(async () => {
      const status = await constructionStatus();
      if (status.state === "running") {
        setConstructing((current) => current && { ...current, fraction: status.fraction || 0 });
      } else {
        clearInterval(polling.current);
        if (status.state === "done") {
          setConstructing((current) => current &&
            { ...current, running: false, built: status.store });
        } else if (status.state === "cancelled") {
          setConstructing((current) => current &&
            { ...current, running: false, fraction: 0, stopped: true });
        } else {
          setConstructing((current) => current &&
            { ...current, running: false, error: status.error || "the build failed" });
        }
      }
    }, 350);
  };

  // The pieces the relink pane and the build blocks share, written once.
  const saveField = constructing && (
    <>
      <input
        type="text"
        value={constructing.destination}
        onChange={(event) => setConstructing(
          (current) => ({ ...current, destination: event.target.value }))}
        aria-label="scene folder"
        title="Where the scene's own files are written. The raw data is read and never changed"
        style={{ ...styles.loadPath, marginBottom: 0, flex: 1 }}
      />
      <button
        type="button"
        onClick={async () => {
          const chosen = await tryNativeChooser();
          if (chosen.path) setConstructing(
            (current) => ({ ...current, destination: chosen.path }));
        }}
        aria-label="choose where to save the scene"
        title="Pick the folder with the operating system's own chooser"
        style={styles.loadCancel}
      >
        Choose…
      </button>
    </>
  );
  const buildParts = constructing && (
    <>
      {/* The scene links to the raw data no matter what; that part is
          stated in the info line, not asked. The one question is whether
          the zoomed-out overview -- the low-resolution top of the scene's
          pyramid -- is kept now as a hard copy on disk, or composed from
          the raw data when someone looks. The recommendation is measured,
          not guessed: on the lab workstation
          (MEASURED_the_ladder_of_surveys.md, the on-the-card table) the
          bake costs 5.7 s at 1,024 positions of 384-pixel test tiles where
          the unbaked first look costs 7.7 s -- the crossover, at roughly
          150 megapixels of survey, a few dozen full camera frames. At
          4,096 tiles it is 19 s of build against a 39 s first look, and
          the unbaked scene pays that again on every cold open. "Well under
          one percent" is the pyramid's own arithmetic: the bake keeps the
          levels holding at most 1% of the full-resolution voxels
          (PINNED_SHARE in composer.py) plus the shrinking tail above them,
          about half a percent typically, 1.33% at the geometric worst. */}
      <div style={styles.constructRow}>
        <label style={styles.constructChoice}>
          <input
            type="checkbox"
            checked={constructing.bake}
            onChange={(event) => setConstructing(
              (current) => ({ ...current, bake: event.target.checked }))}
            disabled={constructing.running || !!constructing.built}
            aria-label="include a hard copy of the low-resolution overview"
            title="The zoomed-out picture is computed once now and kept as files, so the whole survey opens instantly. Left unchecked, it is composed from the raw data the first time it is looked at"
          />
          include a hard copy of the low-resolution overview
        </label>
      </div>
      <div style={styles.constructNote}>
        A scene is assembled by linking the raw data into a virtual
        OME-Zarr, so nothing is copied. We found that also building the
        low-resolution overview as a hard copy, well under one percent of
        the data, dramatically improves the experience: the build is a
        one-time cost, and the positions then load instantly. Without it,
        the overview is computed the first time you look.
      </div>
      <div style={styles.loadActions}>
        {!constructing.built ? (
          <button
            type="button"
            onClick={start}
            disabled={constructing.running}
            aria-label="build the scene"
            title={constructing.bake
              ? "Compute the zoomed-out picture now and keep it: takes time once, opens instantly ever after"
              : "Write only the scene's description; everything is composed as it is looked at"}
            style={styles.loadOpen}
          >
            {constructing.running ? "building…" : "Build"}
          </button>
        ) : null}
        {constructing.running && (
          <button
            type="button"
            onClick={() => askToStop("construct")}
            aria-label="stop the build"
            title="Stop the build at its next step. Nothing half-made is kept; building again starts fresh"
            style={{ ...styles.loadCancel, marginLeft: 8 }}
          >
            Stop
          </button>
        )}
        {constructing.built ? (
          <button
            type="button"
            onClick={() => openStore(constructing.built)}
            aria-label="show the scene"
            title="The scene is built; open it in the image data"
            style={styles.loadOpen}
          >
            Show
          </button>
        ) : null}
      </div>
      {constructing.stopped && !constructing.running && (
        <div style={styles.loadEmptyNote} role="status">
          the build was stopped, and nothing half-made was kept
        </div>
      )}
      {/* The bar stays once the build is done, standing full: a finished
          build should look finished, not vanish. */}
      {(constructing.running || constructing.built) && (
        <div
          style={styles.progressTrack}
          role="progressbar"
          aria-label="construction progress"
          aria-valuenow={constructing.built ? 100
            : Math.round((constructing.fraction || 0) * 100)}
        >
          <div style={{ ...styles.progressFill,
                        width: `${constructing.built ? 100
                          : Math.round((constructing.fraction || 0) * 100)}%` }} />
        </div>
      )}
      {constructing.error && (
        <div style={styles.loadError} role="alert">{constructing.error}</div>
      )}
    </>
  );

  return (
    <div style={styles.loadShade}>
      <div role="dialog" aria-label="load data" style={styles.loadWindow}>
        <div style={styles.loadHead}>
          <span style={styles.loadTitle}>load data</span>
        </div>
        <div style={styles.loadKinds}>
          {LOAD_KINDS.map((door) => (
            <button
              key={door.key}
              type="button"
              onClick={() => {
                setKind(door.key);
                setConstructing(null);
                setSelected(null);
                setOpenError(null);
              }}
              aria-label={door.label}
              aria-pressed={kind === door.key}
              title={door.said}
              style={{ ...styles.loadKind,
                       ...(kind === door.key ? styles.loadKindChosen : null) }}
            >
              {door.label}
            </button>
          ))}
        </div>
        {kind && (
        <>
        <div style={{ display: "contents" }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <input
            key={listing.path}
            type="text"
            defaultValue={listing.path}
            onKeyDown={(event) => {
              if (event.key === "Enter") navigate(event.currentTarget.value);
            }}
            aria-label="folder path"
            title="The folder being looked at. Type or paste a path and press Enter"
            style={{ ...styles.loadPath, marginBottom: 0, flex: 1 }}
          />
          <button
            type="button"
            onClick={async () => {
              const chosen = await tryNativeChooser();
              if (chosen.path) {
                // Land on the parent: the picked folder then sits in the
                // list as an ordinary row, wearing its own Open button.
                // The parent is the server's word, never worked out here:
                // slicing at "/" mangled every Windows path.
                navigate(chosen.parent || chosen.path);
              } else if (chosen.window) {
                setOpenError(
                  "no system folder chooser here — type a path above or walk the folders below");
              }
            }}
            aria-label="choose a folder"
            title="Pick the folder with the operating system's own chooser"
            style={styles.loadCancel}
          >
            Choose folder…
          </button>
        </div>
        <div style={styles.loadList}>
          {/* One click selects a row and highlights it, the way the
              operating system's own choosers behave; a double click steps
              into a folder or opens an image at once. What the chosen tab
              is looking for floats to the top; the plain folders to walk
              into follow. */}
          {listing.folders.filter(
            // The sequential door feeds raw positions through the live
            // writer, and a built view is not raw data — so views are not
            // offered there at all, rather than listed and refused (the
            // operator's call, 2026-08-23).
            (folder) => kind !== "other" || folder.kind !== "view",
          ).sort((a, b) => {
            // What the chosen tab can act on floats to the top; the plain
            // folders to walk into follow.
            const wanted = (folder) => (Boolean(folder.kind) ? 0 : 1);
            return wanted(a) - wanted(b) || a.name.localeCompare(b.name);
          }).map((folder) => (
            <button
              key={folder.name}
              type="button"
              onClick={() => {
                setSelected(folder);
                setOpenError(null);
                // Raw positions are always shown through a view, so choosing
                // a run lays out that view's two questions at once — where
                // its files go, and whether the low-resolution mosaic is
                // built now — with plain answers already filled in. Open
                // then does the rest in one press.
                setConstructing(kind === "open" && folder.kind === "run" ? {
                  data: `${listing.path}/${folder.name}`,
                  name: folder.name,
                  destination: `${listing.path}/${folder.name}/scenes`,
                  bake: false,
                } : null);
              }}
              onDoubleClick={() =>
                ["view", "image", "plate"].includes(folder.kind)
                  ? kind !== "other" && openStore(`${listing.path}/${folder.name}`)
                  : navigate(`${listing.path}/${folder.name}`)
              }
              aria-label={folder.name}
              aria-pressed={selected?.name === folder.name}
              style={{ ...styles.loadRow,
                       ...(selected?.name === folder.name
                         ? styles.loadRowChosen : null) }}
              title={ROW_KINDS[folder.kind]
                ? `${ROW_KINDS[folder.kind].said}. Click to select it`
                : "Click to select this folder; double-click to look inside it"}
            >
              <span style={styles.loadRowName}>{folder.name}</span>
              {/* A view wears one tag always, and a second when it keeps
                  its precomputed mosaic — the fast-opening one. Either
                  both, or only zmartview. */}
              {folder.kind === "view" && folder.baked && (
                <span
                  style={styles.loadRowTag}
                  title="keeps its precomputed low-resolution mosaic on disk, so it opens fast"
                >
                  ⚡ precomputed mosaic
                </span>
              )}
              {ROW_KINDS[folder.kind] && (
                <span style={styles.loadRowTag}>{ROW_KINDS[folder.kind].tag}</span>
              )}
            </button>
          ))}
          {!listing.folders.length && (
            <div style={styles.loadEmptyNote}>no folders in here</div>
          )}
        </div>
        </div>
        {/* What the chosen row IS, said under the list in one line — so a
            row that offers nothing is never a silent mystery. */}
        {(selected || kind === "other") && (
          <div style={styles.loadEmptyNote} role="status">
            {kind === "other"
              ? ((selected ? selected.kind : listing.kind) === "run"
                ? (selected
                  ? "raw positions — they replay one at a time, through the "
                    + "same doorway the microscope uses"
                  : "this folder's positions replay one at a time — Open "
                    + "starts them landing")
                : selected?.kind === "image"
                  ? "one position of this folder — Open replays the whole "
                    + "folder, its positions landing one at a time"
                  : selected?.kind === "plate"
                    ? "a plate — its wells replay one at a time, through the "
                      + "same doorway the microscope uses"
                    : selected
                      ? "nothing here can be replayed — raw positions are "
                        + "what feeds the live writer"
                      : "choose a dataset of raw positions, or walk into one")
              : (ROW_KINDS[selected.kind]?.said
                ?? "a plain folder — double-click to look inside")}
          </div>
        )}
        {/* A chosen run needs no questions answered: Open shows it through a
            link file the viewer keeps to itself and throws away when it
            closes — nothing lands on the operator's disk uninvited. The one
            choice on offer is the mosaic; only ticking it asks where the
            kept view should live. */}
        {kind === "open" && constructing && !constructing.relink && (
          <div style={styles.constructPane}>
            <div style={styles.constructRow}>
              <label style={styles.constructChoice}>
                <input
                  type="checkbox"
                  checked={constructing.bake}
                  onChange={(event) => setConstructing(
                    (current) => ({ ...current, bake: event.target.checked }))}
                  disabled={constructing.running}
                  aria-label="build the low-resolution mosaic and keep the view"
                  title="The zoomed-out mosaic is computed once now and kept as files beside the view's link file, so it opens fast ever after — views wearing ⚡ in the list have it. Left unchecked, nothing is written to your data: the viewer links the positions together for this session and forgets it after"
                />
                build the low-resolution mosaic and keep the view (opens fast ever after)
              </label>
            </div>
            {constructing.bake && (
              <label style={styles.constructRow}>
                <span style={styles.constructLabel}
                      title="The view is a small file of links to the raw data plus the baked mosaic — this is where they live">
                  save the view in
                </span>
                {saveField}
              </label>
            )}
            {constructing.running && (
              <div
                style={styles.progressTrack}
                role="progressbar"
                aria-label="construction progress"
                aria-valuenow={Math.round((constructing.fraction || 0) * 100)}
              >
                <div style={{ ...styles.progressFill,
                              width: `${Math.round((constructing.fraction || 0) * 100)}%` }} />
              </div>
            )}
            {constructing.error && (
              <div style={styles.loadError} role="alert">{constructing.error}</div>
            )}
          </div>
        )}
        {!constructing?.relink && (
          <div style={styles.loadActions}>
            {kind === "other" && replaying?.state === "running" && (
              <>
                <span style={{ ...styles.loadEmptyNote, marginRight: 8 }}
                      role="status">
                  {replaying.stop
                    ? "stopping — the position now landing finishes first"
                    : `a replay is running · ${replaying.done ?? 0} of `
                      + `${replaying.total ?? "…"} positions`}
                </span>
                <button
                  type="button"
                  onClick={() => askToStop("replay")}
                  disabled={Boolean(replaying.stop)}
                  aria-label="stop the replay"
                  title="Stop the replay after the position now landing. What has landed stays on screen as a real run"
                  style={{ ...styles.loadCancel, marginRight: 8 }}
                >
                  Stop
                </button>
              </>
            )}
            {kind === "other" && (
              <label style={styles.paceRow}
                     title="How fast the positions land while the replay runs. They land top row first, left to right, the way a stage scans">
                <span style={styles.paceLabel}>per second</span>
                <select
                  value={pace}
                  onChange={(event) => setPace(Number(event.target.value))}
                  aria-label="positions per second"
                  style={styles.paceChoice}
                >
                  {REPLAY_PACES.map((rate) => (
                    <option key={rate} value={rate}>
                      {rate >= AS_FAST_AS_IT_CAN ? "as fast as it can" : rate}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              onClick={async () => {
                // With a row selected, that row is what opens. With nothing
                // selected, the folder being LOOKED AT can itself be the
                // image — the operator typed a store's path, or walked into
                // one — and then the button opens that folder. Without this
                // a store entered directly showed only the scale arrays
                // inside it, none of them openable (2026-08-23).
                const where = selected ? `${listing.path}/${selected.name}` : listing.path;
                if (kind !== "other") {
                  // Raw positions are shown through a link file the server
                  // composes for itself and forgets when it closes — a plain
                  // Open keeps nothing on the operator's disk. Only the
                  // ticked mosaic box builds a view that is KEPT, at the
                  // place the operator chose (the operator's rule,
                  // 2026-08-23). A view, an image or a plate opens directly.
                  if (constructing?.bake) {
                    openRun();
                    return;
                  }
                  openStore(where);
                  return;
                }
                // On this tab, opening shows the dataset arriving: it is
                // opened as one acquisition and its positions appear one at a
                // time, at the pace beside this button. Nothing is copied --
                // every position is already on disk and already placed, so
                // this works for a light-sheet mosaic and a 336-well plate as
                // readily as for a handful of tiles (the operator's call,
                // 2026-08-21).
                //
                // A single image IS one position of the folder around it, so
                // choosing one replays that folder — a raw zarr is raw
                // data, whichever row of its dataset the finger landed on
                // (the operator's point, 2026-08-23).
                const dataset = selected?.kind === "image" ? listing.path : where;
                // The experimental door is a dress rehearsal, and its whole
                // worth is that nothing about the live path is faked: the
                // positions go through the live writer, its sealed profile
                // and its manifest, one commit each, exactly as they would
                // during an acquisition.
                //
                // It briefly did something else (2026-08-21): it opened the
                // dataset like any other and then REVEALED its positions one
                // at a time on screen. That looks the same from a chair and
                // rehearses nothing at all -- the live path is never touched,
                // so a fault in it cannot show up. Seven gates in
                // test_a_dataset_is_relived_as_a_live_run.py said so by going
                // red, which is what they are for.
                setBusy(true);
                const result = await startReplay(dataset, pace);
                setBusy(false);
                if (!result.config) {
                  setOpenError(result.error || "that folder could not be replayed");
                  return;
                }
                onOpened(result.config);
                onReplayStarted?.(result.config);
              }}
              disabled={busy
                        || constructing?.running
                        // The folder being STOOD IN counts as much as a
                        // chosen row — the window lands inside the dataset,
                        // and a dead button at the landing spot read as the
                        // whole door being broken (2026-08-23). A chosen
                        // image counts too: it is one position of the
                        // folder around it, which is what then replays.
                        || (kind === "other"
                          ? (!(selected
                              ? ["run", "plate", "image"].includes(selected.kind)
                              : listing.kind === "run")
                             || replaying?.state === "running")
                          : !(selected
                            ? selected.kind
                            : ["view", "image", "plate"].includes(listing.kind)))}
              aria-label={kind === "other"
                ? "open as a live run"
                : (selected ? `open ${selected.name}`
                   : listing.kind ? "open this folder"
                   : "open the selection")}
              title={kind === "other"
                ? "Relive this dataset as a live run: its positions land on "
                  + "screen one at a time, through the same doorway the "
                  + "microscope uses, at the pace beside this button"
                : "Open this and show it. A view, an image or a plate opens "
                  + "directly; raw positions are shown through a view built "
                  + "over them first"}
              style={styles.loadOpen}
            >
              {busy || constructing?.running ? "…" : "Open"}
            </button>
            {constructing?.running && (
              <button
                type="button"
                onClick={() => askToStop("construct")}
                aria-label="stop the build"
                title="Stop building the view at its next step. Nothing half-made is kept"
                style={{ ...styles.loadCancel, marginLeft: 8 }}
              >
                Stop
              </button>
            )}
            <button
              type="button"
              onClick={onCancel}
              aria-label="cancel loading"
              style={{ ...styles.loadCancel, marginLeft: 8 }}
            >
              Cancel
            </button>
          </div>
        )}
        {constructing?.relink && (
          <div style={styles.constructPane}>
            <div style={{ ...styles.constructTitle, display: "flex",
                          justifyContent: "space-between", alignItems: "center" }}>
              <span>point to the raw data for {constructing.name}</span>
              <button
                type="button"
                onClick={onCancel}
                aria-label="cancel loading"
                style={styles.loadCancel}
              >
                Cancel
              </button>
            </div>
            <label style={styles.constructRow}>
              <span style={styles.constructLabel}>raw data</span>
              <input
                type="text"
                value={constructing.data}
                onChange={(event) => setConstructing(
                  (current) => ({ ...current, data: event.target.value }))}
                aria-label="raw data folder"
                title="Where the raw data lives now. The viewer was built from a folder that is no longer there"
                style={{ ...styles.loadPath, marginBottom: 0, flex: 1 }}
              />
            </label>
            <label style={styles.constructRow}>
              <span style={styles.constructLabel}>save scene in</span>
              {saveField}
            </label>
            {buildParts}
          </div>
        )}
        </>
        )}
        {(listing.error || openError) && (
          <div style={styles.loadError} role="alert">
            {listing.error || openError}
          </div>
        )}
      </div>
    </div>
  );
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

// -- the small pieces the shell draws with -------------------------------------

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
 * The way back to the whole picture, from wherever the operator has wandered.
 *
 * One press centres the picture and zooms so all of it fits the window --
 * panned off the screen, lost deep in detail, turned onto its side, or all
 * three. It sits beside the 2-D/3-D toggle rather than in the panel because
 * it is needed at exactly the moment the panel is no use: the operator
 * cannot see the picture, and the control that would bring it back must be
 * visible without anything being opened first.
 *
 * It puts the whole view back -- straight, centred, sized to the window --
 * and so it means the same thing in both views. There was briefly a second
 * button, Reset, that did the straightening while this one only fitted; one
 * control that behaves the same way everywhere is what an operator can
 * actually rely on, and two that differ only in 3-D is a distinction the
 * button faces cannot carry (2026-08-20).
 *
 * What it does not touch is where the operator is in depth or in time. That
 * is which picture they are looking at, not how they are looking at it.
 */
function BringItBack({ viewer }) {
  if (!viewer) return null;
  return (
    <button
      onClick={() => putTheViewBack(viewer)}
      style={{ ...styles.button, ...styles.bringItBack }}
      title="Put the view back as it opened: straight, centred and sized to the window. The plane and the moment stay where they are"
    >
      Overview
    </button>
  );
}

// Where the chosen theme is remembered between sessions. main.jsx reads the
// same key before anything is drawn, so a page that was left light comes
// back light with no dark flash on the way.
const THEME_KEY = "zmart-theme";

/**
 * The button that swaps the interface between its dark and light dress.
 *
 * It sits in the top bar beside the 2-D/3-D toggle and Overview, and its face
 * names the theme it would switch TO -- press "Light" and the panels go
 * light. Only the chrome changes: the image area stays black in both themes,
 * because fluorescence is read against black, and the colours chosen for
 * channels and targets are the operator's own and are not touched.
 *
 * The switch itself is one attribute on the page. Every colour in the
 * interface is a named variable (see theme.css), and `data-theme` on the
 * <html> element decides which set of values those names take.
 */
function ThemeToggle() {
  const [theme, setTheme] = React.useState(
    () => (localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark"),
  );
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);
  const other = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => setTheme(other)}
      style={{ ...styles.button, ...styles.themeToggle }}
      aria-label={`switch to the ${other} theme`}
      title={other === "light"
        ? "Dress the controls in light colours. The image itself stays on black"
        : "Dress the controls in dark colours again"}
    >
      {other === "light" ? "light-mode" : "dark-mode"}
    </button>
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

/**
 * Did an acquisition that was already on screen, but had nothing in it, just gain
 * its first image?
 *
 * This is the signal behind a fault that cost an operator a whole session. The
 * viewer notices an acquisition the instant its *description* lands, which is the
 * earliest possible moment and is deliberate — waiting would mean a run appearing
 * in the panel some seconds after it started. But at that moment there is no
 * picture behind it yet. The engine looks, finds nothing, and remembers that with
 * no time limit; so when the image arrived a moment later the panel went on
 * showing black, for as long as the page stayed open. The acquisition was listed,
 * its eye was open, and nothing said why it was empty. Reloading the page showed
 * the data perfectly, which is the tell: only the open viewer was stuck.
 *
 * The engine has a way to be told to forget what it has decoded, and the question
 * is when to use it. Doing so on every announcement is far too blunt — it throws
 * away everything fetched, and during a run announcements arrive constantly, so a
 * position arriving would cost a refetch of the whole view. What is wanted is the
 * narrow case: a store the panel already knew about, which had no measurable
 * picture in it, and now has one.
 *
 * That transition is visible in the answer the server gives. A store with nothing
 * written yet has no histogram — there were no pixels to measure — and no count of
 * moments. Once an image lands, both appear. A store arriving for the first time
 * is not this: it was not there before, so the engine has decoded nothing for it
 * and has nothing to forget.
 */
function anyStoreGainedItsFirstImage(previous, loaded) {
  if (!previous) return false;
  const before = new Map((previous.layers || []).map((spec) => [layerKey(spec), spec]));
  return (loaded.layers || []).some((spec) => {
    const was = before.get(layerKey(spec));
    if (!was) return false; // newly arrived, so nothing has been decoded for it
    const hadNothing = was.histogram == null && was.frames == null;
    const hasSomethingNow = spec.histogram != null || spec.frames != null;
    return hadNothing && hasSomethingNow;
  });
}

// -- the shell ----------------------------------------------------------------

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
  // Whether the first fit-to-window has run on this engine; the canvas stays
  // veiled (plain black) until it has. See the effect further down.
  const [framed, setFramed] = React.useState(false);
  // Bumped when an acquisition is closed, which builds the engine again. See
  // the note in NeuroglancerView.
  const [engineGeneration, setEngineGeneration] = React.useState(0);
  // The same engine, reachable without waiting for a re-render. applyConfig below
  // runs while answering the server and needs it there and then; a piece of state
  // would only reach it on the next pass, which is too late to be any use.
  const engine = React.useRef(null);
  const [config, setConfig] = React.useState(null);
  const [mode, setMode] = React.useState("flat");
  // A projection by default rather than accumulation; see `VolumeMode`.
  const [volumeMode, setVolumeMode] = React.useState("max");
  const [volumeGain, setVolumeGain] = React.useState(0);
  const [volumeAttenuation, setVolumeAttenuation] = React.useState(0);
  // Null until the operator moves it, so the launch flag is respected
  // until somebody overrides it deliberately.
  const [chosenDepthSamples, setChosenDepthSamples] = React.useState(null);
  const [displayScales, setDisplayScales] = React.useState({ x: 1, y: 1, z: 1 });
  const depthSamples = chosenDepthSamples ?? config?.depthSamples ?? 256;

  // Applied straight to the engine rather than through the scene, because it
  // is a property of how the picture is viewed and not of any layer in it.
  React.useEffect(() => {
    if (viewer) stretchTheDisplay(viewer, displayScales);
  }, [viewer, displayScales]);
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
  // The in-page load window's folder listing; null while it is closed.
  const [loadListing, setLoadListing] = React.useState(null);
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

  // Set when an announcement arrives while the viewer is already part way through
  // asking what is open. The answer on its way was prepared before that
  // announcement, so one more question is asked when it lands.
  const missedWhileAsking = React.useRef(false);

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
    if (!loaded) return "unchanged";
    const previous = applied.current;
    // Nothing actually different, so leave everything alone. This matters more
    // than it looks: the viewer asks whether anything has changed several times a
    // second, and without this check an identical answer would still count as new
    // and send the whole picture round again.
    //
    // What changed is also reported back, because the caller needs it in order to
    // decide whether the engine has to be told to look at the disk again.
    const unsafe = liveStateProblem(previous?.liveState, loaded.liveState);
    if (unsafe) {
      setStoreNotice(`Live publication state is stale: ${unsafe}. The last safe image is still shown.`);
      return "rejected";
    }
    setStoreNotice(null);
    if (previous && JSON.stringify(previous) === JSON.stringify(loaded)) return "unchanged";
    const outcome = anyStoreGainedItsFirstImage(previous, loaded) ? "gained-image" : "changed";
    applied.current = loaded;

    // Match each channel now open to the same channel before, so the colour,
    // contrast and opacity the operator chose follow it across the change.
    const before = new Map(
      (previous?.layers || []).map((spec, index) => [layerKey(spec), index]),
    );
    setLayerState((current) =>
      loaded.layers.map((spec) => {
        const was = before.get(layerKey(spec));
        if (was != null && current[was]) return current[was];
        return {
          // Showing, unless the run itself says this channel was switched off.
          // What the microscopist had on at the instrument is what the viewer
          // opens with; on a picture of many channels that is the difference
          // between something to read and a glare. The row is still listed and
          // one press brings it back.
          visible: spec.active !== false,
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
        groups.map((name) => [name, current[name] || { visible: true }]),
      ),
    );
    return outcome;
  }, []);

  // Ask the server what is open, and take it on.
  //
  // This is the only place the question is asked, which matters more than it
  // sounds: on a folder of several thousand positions the answer is genuinely
  // expensive, and two of them racing at startup was measurably slower for no
  // benefit at all.
  //
  // It answers with what came of asking, which the caller needs in order to
  // decide whether the engine has to be told to look at the disk again:
  //
  //   "gained-image" an acquisition already on screen, which had nothing in it,
  //                  now has a picture -- see anyStoreGainedItsFirstImage
  //   "changed"      something else about the scene is different, and is applied
  //   "unchanged"    the answer was identical to the one already in hand
  //   "unreachable"  the server did not answer
  const catchUp = React.useCallback(async () => {
    // Not while one is already outstanding. Several announcements can arrive
    // close together at the start of a run, and a browser allows only six
    // connections to one address -- a queue of expensive questions would leave
    // the engine unable to fetch a single piece of image until they finished.
    //
    // The announcement is remembered rather than dropped. Three arriving during
    // one slow answer used to produce one question and no catching up at all:
    // the note asking for another look was written *after* this line, so it was
    // never reached. Mostly the answer in flight was current anyway, because it
    // reads the disk when it is asked rather than when it was requested -- but
    // not always, and "mostly" is not a thing to rely on during somebody's
    // experiment.
    if (asking.current) {
      missedWhileAsking.current = true;
      return "busy";
    }
    asking.current = true;
    let outcome = "unchanged";
    try {
      // Asked again if an announcement arrived while the previous answer was on
      // its way. At most one extra question per burst, because the note is
      // cleared at the top of each turn rather than at the end.
      do {
        missedWhileAsking.current = false;
        rereadWanted.current = true;
        const loaded = await fetchConfig();
        if (!loaded) {
          setStoreNotice("Could not reach the server. Is it still running?");
          return "unreachable";
        }
        // The strongest thing seen across the turns below is what is reported, so
        // that an acquisition gaining its picture is not lost behind a second,
        // duller answer that arrived while this one was being applied.
        const said = applyConfig(loaded);
        if (said === "gained-image") outcome = "gained-image";
        else if (said === "changed" && outcome !== "gained-image") outcome = "changed";
      } while (missedWhileAsking.current);
    } finally {
      asking.current = false;
      // Never left set. A note still lying there when the next unrelated change
      // came along was read as though it belonged to that change.
      missedWhileAsking.current = false;
    }
    return outcome;
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
  const hasManifestState = Boolean(config?.liveState?.runs?.length);

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
    const askAgain = async () => (stop ? "busy" : catchUp());

    const listener = new EventSource("/api/events");
    // Any message at all means "ask again", so both the named event and anything
    // else that arrives are treated the same. Being generous here means a future
    // kind of announcement cannot be silently ignored by an older page.
    // An announcement can carry one piece of detail, and only one: that what was
    // written went into a store the viewer may already have open, rather than into a
    // new store of its own. That is what a run does when it fills in one large
    // OME-Zarr tile by tile, and it is the one change the page cannot see for itself —
    // no description moves, so reading the disk again reveals nothing. The engine has
    // to be told to let go of the image it has already decoded, or it will go on
    // showing the emptiness it settled on earlier and never look again.
    //
    // Anything else, including a message with no detail at all, just means "ask again".
    const heard = async (event) => {
      let said = null;
      try {
        said = event.data ? JSON.parse(event.data) : null;
      } catch {
        said = null; // not readable, so treat it as a plain "something changed"
      }
      if (said?.imageWrittenInPlace && engine.current) {
        // Said outright, so there is no need to wait and find out: drop
        // every decoded piece and let the safe refresh pump refetch each
        // one behind the picture already on screen. This is the ONE
        // invalidation — a surgical "named dirty pieces" ladder was
        // measured against it (in-container and on the T400) and retired:
        // the whole-source path passed the storm identity gates clean
        // while the ladder kept failing its own delivery gates.
        letGoOfDecodedPieces(engine.current);
        askAgain();
        return;
      }
      const outcome = await askAgain();
      // An acquisition that was already on screen, and had nothing in it, now has
      // a picture. The engine has already decided that store is empty and will
      // never ask the disk again, so it has to be told to forget — otherwise the
      // panel goes on showing black for as long as the page stays open, with the
      // acquisition listed and its eye open and nothing saying why.
      //
      // Narrow on purpose. A position arriving, or a timelapse lengthening, is not
      // this, so nothing already fetched is thrown away in the far commoner case.
      // See anyStoreGainedItsFirstImage above for why this particular signal.
      if (outcome === "gained-image" && engine.current) letGoOfDecodedPieces(engine.current);
    };

    listener.addEventListener("changed", heard);
    listener.onmessage = heard;
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

  // SSE is the immediate path; this slow conditional check is the recovery
  // path.  A proxy, sleeping laptop or brief disconnect can lose a hint.  The
  // authoritative revision cannot be lost, so a later 200 catches up while the
  // ordinary idle answer is a header-only 304 and never reaches Neuroglancer.
  React.useEffect(() => {
    if (!shouldListen || !hasManifestState) return undefined;
    let stopped = false;
    let checking = false;
    let etag = null;
    const check = async () => {
      if (stopped || checking) return;
      checking = true;
      try {
        const answer = await fetchLiveState(etag);
        if (stopped || !answer) return;
        etag = answer.etag || etag;
        if (answer.unchanged) return;
        const unsafe = liveStateProblem(config.liveState, answer.state);
        if (unsafe) {
          setStoreNotice(
            `Live publication state is stale: ${unsafe}. The last safe image is still shown.`,
          );
          return;
        }
        setStoreNotice(null);
        if (JSON.stringify(answer.state) !== JSON.stringify(config.liveState)) {
          await catchUp();
        }
      } finally {
        checking = false;
      }
    };
    const asked = Number(globalThis.zmartLiveCheckMs);
    const every = Number.isFinite(asked) && asked > 0 ? asked : LIVE_STATE_CHECK_MS;
    const timer = setInterval(check, every);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [catchUp, config?.liveState, hasManifestState, shouldListen]);

  // Everything the engine should be showing, in the order it should be drawn.
  //
  // This is worked out here, on its own, so that it is recomputed only when
  // something about the picture has genuinely changed. Note what it does *not*
  // depend on: the list of drawn targets. Those live in the engine once their
  // layer exists, and the list beside the image is a reflection of them — so
  // drawing one must not send the whole scene back through here.
  // An acquisition being shown position by position: which group, how many of
  // its stores are on screen, and how fast the rest should follow. Nothing is
  // written for this -- every position is already on disk and already placed;
  // the row is simply drawn from a growing number of them.
  const [revealing, setRevealing] = React.useState(null);
  // The acquisition the view should be pointed at, once its pieces are on
  // screen. Opening used to leave the camera where it was, which on a machine
  // holding one picture at the stage's coordinates and another at zero means
  // opening the second and seeing black (2026-08-21).
  const [lookAt, setLookAt] = React.useState(null);
  const groupsBefore = React.useRef(null);
  React.useEffect(() => {
    if (!config) return;
    const groups = config.groups || [];
    const before = groupsBefore.current;
    groupsBefore.current = groups;
    if (before === null) return;           // the first look is fitted already
    const fresh = groups.filter((one) => !before.includes(one));
    if (fresh.length) setLookAt(fresh[fresh.length - 1]);
  }, [config]);
  React.useEffect(() => {
    if (!viewer || !lookAt || !config) return undefined;
    const named = config.layers
      .filter((spec) => (spec.group || "") === lookAt)
      .map((spec) => engineName(spec));
    if (!named.length) return undefined;
    // Given a moment for the engine to take the new sources on: the bounds
    // this reads are the sources' own, and they are not there until they are.
    // Tried again while the answer is "not yet": the bounds this reads are
    // the sources' own, and a source that has not arrived has none to give.
    const soon = window.setInterval(() => {
      if (lookAtWhatOpened(viewer, named)) setLookAt(null);
    }, 900);
    return () => window.clearInterval(soon);
    // Deliberately not depending on the scene: this effect is declared above
    // it, and naming it here reaches a constant before it exists -- which
    // took the whole page down with "Cannot access 'scene' before
    // initialization" (2026-08-21).
  }, [viewer, lookAt, config]);
  React.useEffect(() => {
    if (!revealing || !config) return undefined;
    // How many pieces this acquisition has to arrive: the stores of its one
    // row, or its rows, whichever way the dataset opened.
    const rows = config.layers.filter(
      (spec) => (spec.group || "") === revealing.group);
    const all = rows.length > 1
      ? rows.length
      : (rows[0]?.sources || []).length;
    if (!all || revealing.count >= all) return undefined;
    const wait = revealing.perSecond > 0 ? 1000 / revealing.perSecond : 0;
    const soon = window.setTimeout(
      () => setRevealing((now) => (now && now.group === revealing.group
        ? { ...now, count: now.count + 1 } : now)),
      wait);
    return () => window.clearTimeout(soon);
  }, [revealing, config]);

  const scene = React.useMemo(() => {
    if (!config || layerState.length !== config.layers.length) return null;
    const layers = layersFor(config, mode, layerState, groupState, groupOrder, volumeMode,
                              { gain: volumeGain, attenuation: volumeAttenuation,
                                depthSamples },
                              revealing);
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
    revealing,
    groupState,
    groupOrder,
    volumeMode,
    volumeGain,
    volumeAttenuation,
    depthSamples,
    targetsLoaded,
    targetColor,
    targetsVisible,
  ]);

  // Let the engine settle on a starting magnification once the images have said
  // how big they are. Declared ahead of the effect that adds the layers so the
  // waiting is in place before there is anything to wait for; see engine.js for
  // what goes wrong without it.
  //
  // Until that first fit has run, the canvas is kept veiled: the engine
  // paints the freshly-attached image at its own default magnification for a
  // frame or two before the fit lands, and that wrongly-sized glimpse read
  // as the picture jumping in size on every first open (2026-08-23). Behind
  // the veil is plain black, so what shows instead is what an empty canvas
  // shows anyway.
  React.useEffect(() => {
    if (!viewer) return undefined;
    setFramed(false);
    return chooseScaleWhenTheImagesAreMeasured(viewer, () => setFramed(true));
  }, [viewer]);

  React.useEffect(() => {
    if (!viewer || !scene) return undefined;
    engine.current = viewer;
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
    const zoom = viewer.navigationState.zoomFactor.value;
    const perspectiveZoom = viewer.perspectiveNavigationState.zoomFactor.value;

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
    // The descriptions the panel just handed the engine, exactly as they were
    // handed over. This exists for one test and is worth the line: `engine.js`
    // carries every field of a description onto the live layer by hand, one line
    // each, so a field added to `scene.js` and forgotten there is dropped in
    // silence -- three controls were found dead that way in a single afternoon.
    // A test can only guard against the *next* one if it can ask what fields are
    // in a description rather than being told a list somebody has to remember to
    // update. See tests/test_no_setting_is_dropped_on_the_way_to_the_engine.py.
    window.zmartScene = scene;
    const reshaped = syncLayers(viewer, scene, { reread });
    const refreshed = sourceRefreshing.sources.length;
    window.zmartLayersReshaped = reshaped; // what the browser tests count
    // How many stores are still queued to be handed to the engine. Asked as a question
    // rather than left as a number, because the answer changes while a large folder is
    // loading and nothing re-runs this to keep a number up to date. Zero means every
    // position the panel knows about has reached the engine.
    window.zmartSourcesWaiting = () => sourcesStillWaiting(viewer);
    // How many times the viewer has asked the engine to let go of decoded image, and
    // how many sources it asked the last time. The browser tests read this to tell an
    // announcement that did nothing from one that did something that did not help.
    window.zmartLetGo = lettingGo;
    window.zmartSourceRefreshing = sourceRefreshing;

    // Only a change in the shape of the scene can move the view: adding or
    // removing an image makes the engine work out the coordinate space afresh,
    // and it lands somewhere sensible rather than where the operator was. Turning
    // a knob cannot, so in that far more common case nothing here runs at all.
    if ((!reshaped && !refreshed) || !looking) return undefined;
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
      if (Number.isFinite(zoom) && viewer.navigationState.zoomFactor.value !== zoom) {
        viewer.navigationState.zoomFactor.value = zoom;
      }
      if (
        Number.isFinite(perspectiveZoom)
        && viewer.perspectiveNavigationState.zoomFactor.value !== perspectiveZoom
      ) {
        viewer.perspectiveNavigationState.zoomFactor.value = perspectiveZoom;
      }
    };
    lookAgain();
    // The coordinate space settles a moment after the images are attached, so
    // it is worth looking once more shortly afterwards -- but ONLY if the
    // axes themselves changed in the meantime. The engine keeps the position
    // steady across everything milder (a timelapse gaining a frame only moves
    // a bound), so on a live run this delayed restore used to fight the
    // operator: every landing armed a quarter-second window in which moving
    // the T or Z slider was silently undone by a stale capture. Caught by
    // the written-moments slider gate the day the time axis went live.
    const namesAtArming = space?.names?.join(",");
    const settled = setTimeout(() => {
      const now = viewer.navigationState.position.coordinateSpace.value;
      if (now?.names?.join(",") !== namesAtArming) lookAgain();
    }, 250);
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

  // Manifest runs may publish timepoints with gaps, so a single high-water
  // number is not an honest description. Read the explicit half-open ranges
  // directly from authoritative live state, not from declared array shape or a
  // convenience field on a layer row. Ordinary folders alongside it retain
  // their existing counted limit.
  const committedTimeRanges = React.useMemo(() => {
    const rows = config?.layers || [];
    const liveRuns = config?.liveState?.runs;
    if (!Array.isArray(liveRuns) || !liveRuns.length) return null;
    const ranges = [
      ...liveRuns.flatMap((run) => (
        run.sources || []
      ).flatMap((source) => source.committed_time_ranges || [])),
      ...rows
        .filter((spec) => spec.liveRunId == null)
        .flatMap((spec) => (
          typeof spec.frames === "number" && spec.frames > 0
            ? [{ start: 0, stop: spec.frames }]
            : []
        )),
    ]
      .map((range) => ({ start: range.start, stop: range.stop }))
      .sort((one, other) => one.start - other.start || one.stop - other.stop);
    const merged = [];
    for (const range of ranges) {
      const last = merged[merged.length - 1];
      if (last && range.start <= last.stop) last.stop = Math.max(last.stop, range.stop);
      else merged.push(range);
    }
    return merged;
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

  const setLayer = (index, change) =>
    setLayerState((current) =>
      current.map((entry, i) => (i === index ? { ...entry, ...change } : entry)),
    );

  /**
   * Set a channel's window only if the operator has not set one themselves.
   *
   * The reading a channel opens with is asked over the network and answers a
   * second or so later. By then an operator may already have moved a handle,
   * and a measurement landing on top of that takes their work away for no
   * reason they can see. Decided here rather than by the panel because this
   * is where the current answer lives: the panel would be deciding from a
   * copy of the state as it was when the question was asked.
   */
  const setWindowIfUnset = (index, window) =>
    setLayerState((current) =>
      current.map((entry, i) =>
        (i === index && !entry.window ? { ...entry, window } : entry)),
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
        <NeuroglancerView onViewer={setViewer} generation={engineGeneration} veiled={!framed} />
        <div style={styles.topBar}>
          <ModeToggle mode={mode} onChange={setMode} />
          <BringItBack viewer={viewer} />
          <ThemeToggle />
        </div>
        <ScaleBar viewer={viewer} />
        {/* The two sliders are placed to match the directions they move in, which
            makes them quicker to reach for without reading the labels. Depth runs
            up and down the right-hand edge, the way a stack is pictured; time runs
            left to right along the bottom, the way a recording is pictured.

            Z steps through the planes of the stack, so it belongs to the 2-D
            working view; in 3-D the whole depth is already on screen. Time is
            meaningful in both. Neither appears unless the image actually has that
            axis with more than one step along it -- a still image gets no time
            slider, and a single plane gets no Z slider. */}
        {/* The depth slider stands OVER the right-hand edge of the drawing
            area rather than beside it, so a picture centred on the whole
            area sits a little behind it. Framing around that strip was
            tried on 2026-08-22 and put back; see the note in
            showTheWholePicture for what it cost. */}
        <div style={styles.depthControl}>
          {mode === "flat" && (
            <AxisSlider viewer={viewer} axis="z" label="Z" orientation="vertical" />
          )}
        </div>
        <div style={styles.timeControl}>
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
            ranges={committedTimeRanges}
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
              busy={storeBusy}
              notice={storeNotice}
              onOpenStore={async () => {
                setStoreBusy(true);
                setStoreNotice(null);
                // The window always appears -- the choice of what kind of
                // thing is being loaded comes first. The native chooser is a
                // button inside it.
                const listing = await listFolders(null);
                if (listing.error) setStoreNotice(listing.error);
                else setLoadListing(listing);
                setStoreBusy(false);
              }}
              onCloseGroup={async (group) => {
                setStoreBusy(true);
                setStoreNotice(null);
                const result = await closeGroup(group);
                if (result.config) applyConfig(result.config);
                if (result.error) setStoreNotice(result.error);
                // The engine is built again, and what was closed goes with
                // it. Removing the layer alone did not: whatever was opened
                // NEXT came up with most of its tiles unpainted, while the
                // server sent the same description, the browser fetched the
                // same pieces, and the engine reported the same sources, the
                // same bounds and the same camera. The only thing that ever
                // put it right was a fresh drawing context (measured
                // 2026-08-21). Closing is a rare, deliberate act and this
                // costs a redraw of what remains, which is the right trade
                // against a picture that is quietly incomplete.
                //
                // Let go of it BEFORE it is thrown away: every effect
                // watching the engine unsubscribes on the way, so nothing is
                // left reading one that has been disposed -- which took the
                // page down with "Cannot read properties of undefined".
                setViewer(null);
                setEngineGeneration((count) => count + 1);
                setStoreBusy(false);
              }}
              onToggle={(i) => setLayer(i, { visible: !layerState[i].visible })}
              onColor={(i, color) => setLayer(i, { color })}
              onOpacity={(i, opacity) => setLayer(i, { opacity })}
              onWindow={(i, window) => setLayer(i, { window })}
              onMeasureHere={async (i, asked = {}) => {
                // Reading the pixels themselves, for the two things in the
                // panel that need them. The panel has the picture drawn but
                // not the numbers behind it -- and what is on the canvas has
                // already been windowed and coloured -- so the reading is
                // asked of the server, which has the store.
                //
                // Auto asks about the part on screen and takes the window
                // from it. The two boxes under the histogram ask about the
                // same pixels over a different stretch of brightness, and
                // take only the bars: widening the axis has to show what is
                // out there, not blank space beside a squeezed picture.
                const spec = config?.layers?.[i];
                if (!spec) return null;
                const box = asked.whole
                  ? [[0, 0], [1, 1]]
                  : viewer && whatIsOnScreen(viewer);
                if (!box) return null;
                const answer = await measureHere({
                  source: (spec.sources || [spec.source])[0],
                  channel: spec.channelIndex ?? null,
                  box,
                  span: asked.span || null,
                });
                if (!answer || answer.empty || !answer.window) return null;
                // The window belongs to the picture, so it goes to the layer;
                // the histogram belongs to the panel that drew it, so it goes
                // back as the answer. An empty view moves nothing: a press
                // that measured no imaged pixels has nothing to say. And a
                // reading taken only to redraw the bars leaves the window
                // exactly where the operator put it.
                if (asked.ifUnset) setWindowIfUnset(i, answer.window);
                else if (!asked.span) setLayer(i, { window: answer.window });
                return answer;
              }}
              onLut={(i, lut) => setLayer(i, { lut })}
              volumeMode={volumeMode}
              onVolumeMode={setVolumeMode}
              volumeGain={volumeGain}
              onVolumeGain={setVolumeGain}
              volumeAttenuation={volumeAttenuation}
              onVolumeAttenuation={setVolumeAttenuation}
              depthSamples={depthSamples}
              onDepthSamples={setChosenDepthSamples}
              displayScales={displayScales}
              onDisplayScales={setDisplayScales}
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
      {loadListing && (
        <LoadWindow
          listing={loadListing}
          onNavigate={async (path) => {
            const listing = await listFolders(path);
            setLoadListing((current) =>
              listing.error ? { ...current, error: listing.error } : listing);
          }}
          onOpened={(config) => {
            applyConfig(config);
            setLoadListing(null);
          }}
          onArriving={(loaded, perSecond) => {
            // The acquisition just opened, shown position by position. Its
            // group is the one the server has just added, and the first
            // position is on screen at once -- an empty screen for the first
            // beat says nothing about anything.
            const group = (loaded.groups || []).at(-1) || "";
            setRevealing({ group, count: 1, perSecond });
          }}
          onReplayStarted={(config) => {
            // Starting a replay is an explicit ask to watch something, so the
            // camera goes to the show once the replay's images have answered
            // -- first plane, first moment, whole picture. The count says how
            // many image rows the fresh config carries, which is what keeps
            // the move from firing before those rows reach the engine.
            if (viewer) {
              watchTheReplay(viewer, (config.layers || []).filter(
                (one) => one.kind !== "segmentation").length);
            }
          }}
          onConstructed={async () => {
            const config = await fetchConfig();
            if (config) applyConfig(config);
            setLoadListing(null);
          }}
          onCancel={() => setLoadListing(null)}
        />
      )}
    </div>
  );
}

// -- how it all looks ---------------------------------------------------------

const styles = {
  // The load window and the shade behind it. The shade keeps the picture
  // visible but plainly not the thing being interacted with.
  loadShade: {
    position: "fixed",
    inset: 0,
    zIndex: 60,
    background: "var(--shade-bg)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  loadWindow: {
    width: 480,
    maxWidth: "88vw",
    maxHeight: "72vh",
    display: "flex",
    flexDirection: "column",
    background: "var(--card-bg)",
    border: "1px solid var(--panel-border)",
    borderRadius: 8,
    boxShadow: "0 12px 40px var(--shadow-color)",
    padding: "12px 14px",
    font: "13px/1.4 system-ui, -apple-system, 'Segoe UI', sans-serif",
    color: "var(--text-primary)",
  },
  loadHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingBottom: 10,
  },
  loadTitle: {
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    color: "var(--text-faint)",
  },
  loadCancel: {
    padding: "4px 10px",
    border: "1px solid var(--control-border)",
    borderRadius: 4,
    background: "var(--control-bg)",
    color: "var(--text-secondary)",
    font: "600 11px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
  loadKinds: { display: "flex", gap: 8, paddingBottom: 10 },
  loadKind: {
    flex: 1,
    padding: "8px 10px",
    border: "1px solid var(--control-border)",
    borderRadius: 5,
    background: "var(--control-bg)",
    color: "var(--text-secondary)",
    font: "600 11px/1.2 system-ui, sans-serif",
    cursor: "pointer",
  },
  loadKindChosen: {
    background: "var(--accent-selection)",
    borderColor: "var(--accent)",
    color: "var(--accent-selection-text)",
  },
  loadPath: {
    boxSizing: "border-box",
    width: "100%",
    background: "var(--input-bg)",
    border: "1px solid var(--subtle-border)",
    borderRadius: 4,
    color: "var(--text-primary)",
    font: "12px/1.4 ui-monospace, monospace",
    padding: "6px 8px",
    marginBottom: 8,
  },
  loadList: {
    flex: 1,
    minHeight: 120,
    overflowY: "auto",
    border: "1px solid var(--subtle-border)",
    borderRadius: 4,
    background: "var(--panel-bg)",
  },
  loadRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    width: "100%",
    textAlign: "left",
    background: "none",
    border: "none",
    borderBottom: "1px solid var(--subtle-border)",
    color: "var(--text-primary)",
    font: "12px/1.4 system-ui, sans-serif",
    padding: "6px 10px",
    cursor: "pointer",
  },
  // The name takes the room; the tag sits at the right edge saying what the
  // row IS (view, image, plate, raw), and a view that keeps its baked
  // low-resolution mosaic wears ⚡ beside its name — the fast-opening one.
  loadRowName: { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" },
  loadRowTag: {
    flexShrink: 0,
    color: "var(--text-faint)",
    font: "600 10px/1 system-ui, sans-serif",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    border: "1px solid var(--subtle-border)",
    borderRadius: 4,
    padding: "2px 6px",
  },
  // The pace, beside the Replay button it belongs to.
  paceRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginRight: 10,
    color: "var(--text-muted)",
    font: "11px system-ui, sans-serif",
  },
  paceLabel: { textTransform: "uppercase", letterSpacing: ".04em", fontSize: 10 },
  paceChoice: {
    // Drawn flat, not with the operating system's glossy button face: the
    // native dress glowed against the rest of the window's plain controls.
    appearance: "none",
    WebkitAppearance: "none",
    background: "var(--input-bg)",
    border: "1px solid var(--control-border)",
    borderRadius: 3,
    color: "var(--text-primary)",
    font: "11px system-ui, sans-serif",
    padding: "2px 14px 2px 6px",
  },
  loadOpen: {
    flexShrink: 0,
    padding: "3px 10px",
    border: "1px solid var(--accent)",
    borderRadius: 4,
    background: "var(--accent-selection)",
    color: "var(--accent-selection-text)",
    font: "600 11px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
  loadEmptyNote: {
    padding: "10px 12px",
    color: "var(--text-muted)",
    font: "12px/1.4 system-ui, sans-serif",
  },
  loadRowChosen: {
    background: "var(--accent-selection)",
    color: "var(--accent-selection-text)",
  },
  loadActions: { display: "flex", justifyContent: "flex-end", marginTop: 8 },
  constructPane: {
    marginTop: 10,
    padding: "10px 12px",
    border: "1px solid var(--panel-border)",
    borderRadius: 6,
    background: "var(--panel-bg)",
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  constructTitle: {
    font: "600 11px/1 system-ui, sans-serif",
    letterSpacing: ".06em",
    textTransform: "uppercase",
    color: "var(--text-muted)",
  },
  constructRow: { display: "flex", alignItems: "center", gap: 10 },
  constructLabel: {
    font: "600 10px/1 system-ui, sans-serif",
    letterSpacing: ".04em",
    textTransform: "uppercase",
    color: "var(--text-muted)",
    flexShrink: 0,
  },
  constructNote: {
    font: "11px/1.5 system-ui, sans-serif",
    color: "var(--text-muted)",
  },
  constructChoice: {
    display: "flex",
    alignItems: "center",
    gap: 5,
    font: "12px/1.2 system-ui, sans-serif",
    color: "var(--text-primary)",
  },
  progressTrack: {
    height: 8,
    borderRadius: 4,
    background: "var(--input-bg)",
    border: "1px solid var(--subtle-border)",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    background: "var(--accent)",
    transition: "width 200ms linear",
  },
  loadError: {
    marginTop: 8,
    padding: "7px 9px",
    border: "1px solid var(--danger-border)",
    borderRadius: 4,
    background: "var(--danger-bg)",
    color: "var(--danger-text)",
    font: "12px/1.5 system-ui, sans-serif",
  },
  shell: { position: "absolute", inset: 0, display: "flex", background: "var(--page-bg)" },
  bar: {
    width: 264,
    flexShrink: 0,
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    border: "1px solid var(--panel-border)",
    borderTop: "none",
    borderBottom: "none",
    background: "var(--card-bg)",
  },
  fold: {
    alignSelf: "stretch",
    width: 14,
    border: "none",
    borderLeft: "1px solid var(--panel-border)",
    background: "var(--card-bg)",
    color: "var(--text-muted)",
    font: "12px/1 system-ui, sans-serif",
    cursor: "pointer",
    padding: 0,
  },
  stage: { flex: 1, position: "relative" },
  // The three top-bar controls sit in one row that lays itself out, so a
  // control appearing or disappearing (Overview only exists once an image
  // is open) never leaves a hole, and the gap between neighbours is said
  // once instead of being baked into each control's distance from the edge.
  topBar: {
    position: "absolute",
    top: 12,
    left: 12,
    zIndex: 10,
    display: "flex",
    gap: 12,
    alignItems: "center",
  },
  toggle: {
    display: "flex",
    borderRadius: 6,
    overflow: "hidden",
    border: "1px solid var(--panel-border)",
    boxShadow: "0 1px 4px var(--shadow-color)",
  },
  button: {
    padding: "6px 14px",
    border: "none",
    background: "var(--control-bg)",
    color: "var(--text-muted)",
    font: "600 12px/1 system-ui, sans-serif",
    cursor: "pointer",
  },
  buttonActive: { background: "var(--accent)", color: "#fff" },
  // Beside the 2-D/3-D toggle rather than inside it: the toggle is a choice
  // between two states and this is an action, so it gets its own edge and never
  // looks like a third mode. Its place in the row comes from topBar above.
  bringItBack: {
    borderRadius: 6,
    border: "1px solid var(--panel-border)",
    boxShadow: "0 1px 4px var(--shadow-color)",
  },
  // Beside Overview, dressed the same way, placed by the same row.
  themeToggle: {
    borderRadius: 6,
    border: "1px solid var(--panel-border)",
    boxShadow: "0 1px 4px var(--shadow-color)",
  },
  // The sliders stack in one column at the bottom of the stage, so a timelapse
  // showing both Z and T never has them overlapping.
  // Down the right-hand edge, between the scale bar in the top corner and the time
  // slider along the bottom. Both gaps are deliberate: the depth slider takes
  // whatever height is left, so it is as long as the window allows without ever
  // running into either of them.
  depthControl: {
    position: "absolute",
    top: 72,
    right: 14,
    bottom: 62,
    zIndex: 10,
    display: "grid",
    justifyItems: "end",
  },
  timeControl: {
    position: "absolute",
    left: 14,
    right: 14,
    bottom: 14,
    zIndex: 10,
    display: "grid",
    justifyItems: "stretch",
  },
};
