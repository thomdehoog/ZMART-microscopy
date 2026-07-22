"""The one page the operator sees — no notebook, no code, just the run.

The page walks the same numbered steps as ``zmart_microscopy_v4_react
.ipynb``: each step is a collapsible section with one button (or one
embedded panel), a sentence saying what the step does for the experiment,
and a live message from Python saying how it went. Steps fold themselves
away once they are done, so the page always reads top-to-bottom as "what
is next". The interactive panels are the SAME React widgets the notebook
shows — their JavaScript modules are served from this package unchanged —
connected through a small stand-in for the notebook's messaging (defined
at the bottom of the page script).

Everything is inline and offline: no fonts, scripts, or styles are
fetched from anywhere.
"""

from __future__ import annotations

# The steps, in the notebook's order. Each is (id, title, what-it-means,
# button label or None when the section is widget-only, auto-collapse):
# button-only steps fold away when they finish; steps whose panel stays
# useful (the map, the explorer, the gallery) stay open.
_STEPS = [
    (
        "connect",
        "1 · Connect",
        "Start the analysis engine and open the microscope session. "
        "Everything this run saves lands in one new run folder.",
        "Connect",
        True,
    ),
    (
        "set_origin",
        "2 · Set origin",
        "Marks the stage's current position as (0, 0). Every position in "
        "this run counts from here, so do this with the sample framed the "
        "way you want it.",
        "Set origin",
        True,
    ),
    (
        "capture_overview_job",
        "3a · Capture the overview job",
        "In LAS X, select the low-magnification overview job first — then "
        "press capture so the run remembers its settings. (The demo selects "
        "its simulated overview job for you.)",
        "Capture overview job",
        True,
    ),
    (
        "capture_target_job",
        "3b · Capture the target job",
        "Now select the high-magnification target job in LAS X and capture "
        "it too. The run refuses to continue if both captures are the same "
        "job — that would image targets at overview quality.",
        "Capture target job",
        True,
    ),
    (
        "load_positions",
        "4 · Positions and focus",
        "Loads the overview positions from the microscope and opens the "
        "focus map. Click a few spread-out points on the map, then press "
        "Measure in the panel — the fitted focus surface keeps every later "
        "image sharp across the whole sample.",
        "Load positions",
        False,
    ),
    (
        "run_overview",
        "5 · Scan the overview",
        "Drives the stage through every overview position and stitches the "
        "live map below, tile by tile, as the images are saved.",
        "Scan overview",
        False,
    ),
    (
        "discover_targets",
        "6 · Discover cells",
        "The analysis engine segments every overview tile and each found "
        "cell becomes a dot in the explorer below. Gate with the threshold "
        "boxes or draw a lasso; hover any dot to see that cell's picture; "
        "click dots (or map rings) to hand-pick cells.",
        "Discover cells",
        False,
    ),
    (
        "gallery",
        "7 · Acquire and curate",
        "Type how many cells to image (or use your hand-picked ones) and "
        "press Acquire in the panel — each overview/target pair appears the "
        "moment it is captured. Mark each pair good ✓ or bad ✗: that is "
        "your quality record of the run.",
        None,
        False,
    ),
    (
        "save_results",
        "8 · Save the run",
        "Writes the run report, the layout picture, and your good/bad "
        "verdicts into the run folder, next to the images.",
        "Save results",
        True,
    ),
    (
        "disconnect",
        "9 · Disconnect",
        "Shuts the analysis engine down and releases the microscope. Always end a session here.",
        "Disconnect",
        True,
    ),
]

# Which widget mounts inside which step's section.
_WIDGET_SECTIONS = {
    "overview": "run_overview",
    "focus": "load_positions",
    "explorer": "discover_targets",
    "gallery": "gallery",
}


def _sections_html() -> str:
    parts = []
    for step_id, title, meaning, button, auto_collapse in _STEPS:
        widget_holes = "".join(
            f'<div class="widget" id="widget-{widget}"'
            f'{" hidden" if widget == "overview" else ""}></div>'
            for widget, section in _WIDGET_SECTIONS.items()
            if section == step_id
        )
        if step_id == "connect":
            button_html = f"""
          <div class="step-actions">
            <button class="step-btn" data-step="{step_id}" disabled><span class="button-label">{button}</span></button>
            <button id="new-run-btn" disabled>Restart workflow</button>
            <span id="new-run-note">Available after Connect.</span>
          </div>"""
        else:
            button_html = (
                f'<button class="step-btn" data-step="{step_id}" disabled>'
                f'<span class="button-label">{button}</span></button>'
                if button
                else ""
            )
        open_attr = " open" if step_id == "connect" else ""
        parts.append(
            f"""
      <details class="step" id="step-{step_id}" data-collapse="{str(auto_collapse).lower()}"{open_attr}>
        <summary>
          <span class="step-title">{title}</span>
          <span class="step-note" id="note-{step_id}"></span>
        </summary>
        <div class="step-body">
          <p class="meaning">{meaning}</p>
          {button_html}
          {widget_holes}
        </div>
      </details>"""
        )
    return "\n".join(parts)


def page_html() -> str:
    """The complete interface page, ready to serve."""
    return (
        _HEAD
        + """
    <header>
      <h1>ZMART-microscopy: Target acquisition</h1>
      <p id="demo-banner" hidden>
        This is the <strong>demo</strong>: a simulated microscope imaging a
        synthetic sample — the very one the offline tests drive. Nothing
        here touches real hardware, so click around freely.
      </p>
    </header>
"""
        + _sections_html()
        + _SCRIPT
    )


_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZMART-microscopy: Target acquisition</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%230284c7'/%3E%3C/svg%3E">
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px 16px 60px 50px; background: #ffffff; color: #0f172a;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 15px; line-height: 1.5;
  }
  header, .step { max-width: 1600px; margin: 0 0 12px; }
  header { margin-bottom: 22px; }
  header h1 { font-size: 24px; margin: 0 0 8px; letter-spacing: -0.01em; }
  header p { color: #475569; margin: 4px 0; max-width: 72ch; }
  #demo-banner { color: #92400e; background: #fffbeb; border: 1px solid #fde68a;
                 border-radius: 8px; padding: 8px 12px; }
  .step {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .step[open] { padding-bottom: 4px; }
  .step summary {
    display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
    padding: 12px 16px; cursor: pointer; list-style: none; user-select: none;
    background: #f8fafc; border-radius: 10px;
  }
  .step[open] > summary {
    background: #eff6ff; border-bottom: 1px solid #dbeafe;
    border-radius: 10px 10px 0 0;
  }
  .step:not([open]) > summary:hover { background: #f1f5f9; }
  .step summary::-webkit-details-marker { display: none; }
  .step summary::before {
    content: "▸"; color: #0284c7; font-size: 18px; line-height: 1;
    width: 18px; align-self: center;
    transition: transform 0.15s;
  }
  .step[open] summary::before { transform: rotate(90deg); }
  .step summary::after {
    content: "Collapsed"; margin-left: auto; color: #64748b;
    font-size: 12px; font-weight: 600;
  }
  .step[open] summary::after { content: "Open"; color: #0369a1; }
  .step-title { font-weight: 650; font-size: 15px; }
  .step[open] .step-title { color: #075985; }
  .step.done .step-title::after { content: " ✓"; color: #16a34a; }
  .step-note { color: #64748b; font-size: 13.5px; }
  .step-note.ok { color: #15803d; }
  .step-note.bad { color: #b91c1c; }
  .step-body { padding: 0 16px 12px; }
  .meaning { color: #475569; margin: 2px 0 10px; max-width: 78ch; }
  .step-btn {
    background: #0284c7; color: #ffffff; border: none; border-radius: 8px;
    padding: 8px 18px; font-weight: 600; cursor: pointer; font-size: 14px;
    display: inline-flex; align-items: center; justify-content: center;
    position: relative;
  }
  .step-btn::before {
    content: ""; width: 12px; height: 12px; position: absolute; left: 10px;
    border: 2px solid transparent; border-radius: 50%;
  }
  .step-btn.running { padding: 8px 2px 8px 34px; }
  .step-btn.running::before {
    border-color: rgba(100, 116, 139, 0.35); border-top-color: #475569;
    animation: button-spin 0.7s linear infinite;
  }
  @keyframes button-spin { to { transform: rotate(360deg); } }
  .step-btn:hover:enabled { background: #0369a1; }
  .step-btn:disabled { background: #e2e8f0; color: #94a3b8; cursor: default; }
  .step.done .step-btn { background: #16a34a; color: #ffffff; }
  .step.done .step-btn:hover:enabled { background: #15803d; }
  .step.done .step-btn.running { background: #e2e8f0; color: #94a3b8; }
  .step-btn[data-step="connect"] { min-width: 112px; }
  .step-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  #new-run-btn {
    background: #0f172a; color: #ffffff; border: none; border-radius: 8px;
    padding: 8px 18px; font-weight: 600; cursor: pointer; font-size: 14px;
  }
  #new-run-btn:hover:enabled { background: #334155; }
  #new-run-btn:disabled { background: #cbd5e1; cursor: default; }
  #new-run-note { color: #64748b; font-size: 13.5px; }
  /* The panels are self-contained light cards; give them room and let wide
     ones scroll sideways inside their step instead of the whole page. */
  .widget { margin-top: 12px; max-width: 100%; overflow-x: auto; }
  .widget:empty { display: none; }
  @media (max-width: 640px) {
    body { padding: 16px 8px 40px; font-size: 14px; }
    .step summary { padding: 10px 12px; }
    .step-body { padding: 0 12px 10px; }
  }
</style>
</head>
<body>
"""


_SCRIPT = """
<script type="module">
// ---- the notebook's messaging, replayed over plain HTTP ------------------
// Each widget's React app talks to a "model": get/set traits, send/receive
// messages. In Jupyter, anywidget provides it; here this small class does,
// backed by one server-sent-events stream (Python -> page) and small POSTs
// (page -> Python). Image bytes are fetched separately, never inlined.

globalThis.ZMART_WIDGET_SCALE = 2;
globalThis.ZMART_WIDGET_SCALES = { explorer: 2.5 };
globalThis.ZMART_WIDGET_FILL = { gallery: true };

const models = {};
const mounting = new Map();
const ensuringWidgets = new Map();
const pendingWidgetEvents = new Map();

class ZmartModel {
  constructor(name, traits) {
    this.name = name;
    this.state = { ...traits };
    this.handlers = new Map();
    this.deferred = new Map();
    this.pending = {};
    this.chain = Promise.resolve();
  }
  get(name) { return this.state[name]; }
  set(name, value) {
    this.state[name] = value;
    this.pending[name] = value;
    this.emit(`change:${name}`);
  }
  save_changes() {
    const changes = this.pending;
    this.pending = {};
    post("/trait", { widget: this.name, changes }).catch((error) => this.recover(error));
  }
  send(content) {
    post("/msg", { widget: this.name, content }).catch((error) => this.recover(error));
  }
  async recover(error) {
    // A bounded/full worker queue can reject a request. Restore every trait
    // from Python truth so optimistic browser input cannot remain displayed.
    try {
      await synchronizedSnapshot();
    } catch (_) {
      // The status below is still better than an unhandled rejection; a later
      // SSE trait or reconnect snapshot will restore the model.
    } finally {
      if (this.state.status !== undefined) {
        this.state.status = `request failed: ${error.message}`;
        this.emit("change:status");
      }
    }
  }
  on(event, cb) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event).push(cb);
    const waiting = this.deferred.get(event) || [];
    this.deferred.delete(event);
    waiting.forEach((args) => queueMicrotask(() => cb(...args)));
  }
  off(event, cb) {
    const list = this.handlers.get(event) || [];
    const i = list.indexOf(cb);
    if (i >= 0) list.splice(i, 1);
  }
  emit(event, ...args) {
    const handlers = (this.handlers.get(event) || []).slice();
    if (handlers.length) {
      handlers.forEach((cb) => cb(...args));
    } else if (event.startsWith("change:")) {
      // A trait's newest value supersedes older unseen values.
      this.deferred.set(event, [args]);
    } else {
      // Stream messages are ordered and none may disappear while React's
      // effect subscribes after a dynamic module has mounted.
      const waiting = this.deferred.get(event) || [];
      waiting.push(args);
      this.deferred.set(event, waiting);
    }
  }
  applyTrait(name, value) { this.state[name] = value; this.emit(`change:${name}`); }
  applyMsg(content, bufferIds) {
    // Chained so messages reach the widget in exactly the order Python
    // sent them, even though their image fetches finish at random times.
    this.chain = this.chain.then(async () => {
      let missing = false;
      const buffers = await Promise.all((bufferIds || []).map(async (id) => {
        for (let attempt = 0; attempt < 2; attempt += 1) {
          try {
            const response = await fetch(`/buffer/${id}`);
            if (response.ok) return response.arrayBuffer();
          } catch (_) {}
        }
        missing = true;
        return new ArrayBuffer(0);
      }));
      if (missing && this.state.status !== undefined) {
        this.state.status = "an image could not be refreshed — the previous copy was kept";
        this.emit("change:status");
      }
      this.emit("msg:custom", content, buffers);
    }).catch((error) => {
      if (this.state.status !== undefined) {
        this.state.status = `image update failed: ${error.message}`;
        this.emit("change:status");
      }
    });
  }
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).error || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response;
}

async function mountWidget(name, traits) {
  if (models[name]) return;
  if (mounting.has(name)) return mounting.get(name);
  const el = document.getElementById(`widget-${name}`);
  if (!el) return;
  const promise = (async () => {
    const model = new ZmartModel(name, traits);
    const mod = await import(`/esm/${name}.mjs`);
    mod.default.render({ model, el });
    models[name] = model;
    for (const ev of pendingWidgetEvents.get(name) || []) applyEvent(ev);
    pendingWidgetEvents.delete(name);
  })();
  mounting.set(name, promise);
  try {
    await promise;
  } finally {
    mounting.delete(name);
  }
}

async function ensureWidget(name) {
  if (models[name]) return;
  if (ensuringWidgets.has(name)) return ensuringWidgets.get(name);
  const promise = synchronizedSnapshot();
  ensuringWidgets.set(name, promise);
  let restored = false;
  try {
    restored = await promise;
  } finally {
    ensuringWidgets.delete(name);
  }
  if (!restored && !models[name]) setTimeout(() => ensureWidget(name), 250);
}

// ---- the step buttons and their fold-away sections -------------------------

function noteFor(step) { return document.getElementById(`note-${step}`); }

const newRunButton = document.getElementById("new-run-btn");
const newRunNote = document.getElementById("new-run-note");

// The first time the operator enters a new section, fold whatever section
// was open before it. Reopening an already-visited section is unrestricted,
// so completed maps and controls can still be compared side by side.
document.querySelectorAll("details.step").forEach((section) => {
  section.dataset.opened = section.open ? "true" : "false";
  section.addEventListener("toggle", () => {
    if (!section.open || section.dataset.opened === "true") return;
    document.querySelectorAll("details.step[open]").forEach((other) => {
      if (other !== section) other.open = false;
    });
    section.dataset.opened = "true";
  });
});

function setNewRunAvailable(available) {
  newRunButton.disabled = !available;
  newRunNote.textContent = available
    ? "Disconnects this session, clears the website state, and returns to step 1."
    : "Available after Connect.";
}

function showOverview() {
  document.getElementById("widget-overview").hidden = false;
}

function openNextStep(step) {
  const section = document.getElementById(`step-${step}`);
  let next = section?.nextElementSibling;
  while (next && !next.classList.contains("step")) next = next.nextElementSibling;
  if (next) next.open = true;
}

// openBehavior: "live" folds button-only steps away and keeps panel steps
// (map, explorer, gallery) open — what should happen when a step finishes
// while the operator watches. "boot" folds everything (the boot layout then
// opens the current section). "silent" never touches the fold state: used by
// mid-session state re-fetches, which must not rearrange what the operator
// is looking at.
function markDone(step, openBehavior = "live") {
  const section = document.getElementById(`step-${step}`);
  if (!section) return;
  section.classList.add("done");
  const completedLabels = {
    connect: "Reconnect",
    set_origin: "Change Origin",
    capture_overview_job: "Recapture Overview Job",
  };
  if (completedLabels[step]) {
    const label = section.querySelector(".button-label");
    if (label) label.textContent = completedLabels[step];
  }
  if (openBehavior === "live") section.open = section.dataset.collapse !== "true";
  else if (openBehavior === "boot") section.open = false;
}

function flowUpdate(ev) {
  const note = noteFor(ev.step);
  if (!note) return;
  if (ev.state === "running") {
    note.textContent = "working…";
    note.className = "step-note";
    if (ev.step === "run_overview") showOverview();
  } else if (ev.state === "done") {
    note.textContent = ev.message;
    note.className = "step-note ok";
    markDone(ev.step);
    const section = document.getElementById(`step-${ev.step}`);
    if (section?.dataset.collapse === "true") openNextStep(ev.step);
    if (ev.step === "connect") setNewRunAvailable(true);
  } else {
    note.textContent = ev.message;
    note.className = "step-note bad";
    const section = document.getElementById(`step-${ev.step}`);
    if (section) section.open = true;
  }
  const button = document.querySelector(`button[data-step="${ev.step}"]`);
  if (button) {
    button.disabled = ev.state === "running";
    button.classList.toggle("running", ev.state === "running");
  }
}

document.querySelectorAll(".step-btn").forEach((button) => {
  button.addEventListener("click", (e) => {
    e.preventDefault();
    // Close the double-click window locally; Python independently coalesces
    // duplicate pending steps, so this is UX rather than the safety gate.
    button.disabled = true;
    button.classList.add("running");
    post("/action", { step: button.dataset.step }).catch((error) => {
      button.disabled = false;
      button.classList.remove("running");
      const note = noteFor(button.dataset.step);
      if (note) {
        note.textContent = `request failed: ${error.message}`;
        note.className = "step-note bad";
      }
    });
  });
});

newRunButton.addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Restart the workflow for a new run? The current microscope session will be " +
    "disconnected, and current steps, images, segmentation, and selections will be " +
    "cleared. Files already saved stay on disk."
  );
  if (!confirmed) return;
  newRunButton.disabled = true;
  newRunNote.textContent = "restarting…";
  try {
    await post("/reset", {});
    window.location.reload();
  } catch (error) {
    newRunButton.disabled = false;
    newRunNote.textContent = `restart failed: ${error.message}`;
  }
});

// ---- boot: connect the live stream FIRST, then the state snapshot ----------
// Buttons stay disabled until the stream is provably open, so a click can
// never fire while its progress events would have nowhere to arrive.

// ``layout`` folds completed sections and opens the current one — wanted
// exactly once, when a fresh page catches up on an existing run. Mid-session
// re-fetches (a widget mounting late, a rejected request restoring truth)
// pass layout=false so they never rearrange the sections under the operator.
async function applySnapshot(layout) {
  const response = await fetch("/state");
  if (!response.ok) throw new Error(`state snapshot failed: ${response.status}`);
  const snapshot = await response.json();
  for (const [name, traits] of Object.entries(snapshot.widgets)) {
    if (models[name]) {
      for (const [trait, value] of Object.entries(traits)) {
        models[name].applyTrait(trait, value);
      }
    } else {
      await mountWidget(name, traits);
    }
  }
  const completed = snapshot.flow.completed || [];
  completed.forEach((step) => markDone(step, layout ? "boot" : "silent"));
  if (layout) {
    const completedSet = new Set(completed);
    let firstIncomplete = [...document.querySelectorAll("details.step")]
      .find((section) => !completedSet.has(section.id.replace("step-", "")));
    const focusMeasured = Boolean(snapshot.widgets.focus?.measured?.length);
    if (completedSet.has("load_positions") && !focusMeasured
        && !completedSet.has("run_overview")) {
      firstIncomplete = document.getElementById("step-load_positions");
    }
    if (firstIncomplete) firstIncomplete.open = true;
  }
  const overviewStarted = completed.includes("run_overview")
    || Boolean(snapshot.widgets.overview?.status);
  document.getElementById("widget-overview").hidden = !overviewStarted;
  setNewRunAvailable(completed.includes("connect"));
  if (snapshot.flow.demo) document.getElementById("demo-banner").hidden = false;
  return snapshot;
}

let everConnected = false;
let applyingSnapshot = true;
let bufferedEvents = [];
let snapshotChain = Promise.resolve(true);
let retryTimer = null;
const events = new EventSource("/events");
function applyEvent(ev) {
  if (ev.widget === "overview" && (
      (ev.kind === "msg" && ev.content?.type === "tile")
      || (ev.kind === "trait" && ev.name === "status" && ev.value))) {
    showOverview();
  }
  if ((ev.kind === "trait" || ev.kind === "msg") && !models[ev.widget]) {
    // Some workflow widgets are intentionally backend-only. Do not retain
    // browser events forever when the page has no mount point for one.
    if (!document.getElementById(`widget-${ev.widget}`)) return;
    if (!pendingWidgetEvents.has(ev.widget)) pendingWidgetEvents.set(ev.widget, []);
    pendingWidgetEvents.get(ev.widget).push(ev);
    ensureWidget(ev.widget);
    return;
  }
  if (ev.kind === "trait") models[ev.widget].applyTrait(ev.name, ev.value);
  else if (ev.kind === "msg") models[ev.widget].applyMsg(ev.content, ev.buffers);
  else if (ev.kind === "widget") ensureWidget(ev.widget);
  else if (ev.kind === "flow") flowUpdate(ev);
  else if (ev.kind === "reset") window.location.reload();
}

function synchronizedSnapshot(layout = false) {
  snapshotChain = snapshotChain.then(async () => {
    applyingSnapshot = true;
    try {
      await applySnapshot(layout);
      return true;
    } catch (_) {
      return false;
    } finally {
      const caughtUp = bufferedEvents;
      bufferedEvents = [];
      applyingSnapshot = false;
      caughtUp.forEach(applyEvent);
    }
  });
  return snapshotChain;
}

function enableSteps() {
  document.querySelectorAll(".step-btn").forEach((b) => { b.disabled = false; });
}

async function restoreConnection(reconnecting) {
  // A fresh page lays the sections out to match the run; a mere stream
  // reconnect only refreshes state and leaves the operator's view alone.
  const restored = await synchronizedSnapshot(!reconnecting);
  if (!restored) {
    retryTimer = setTimeout(() => restoreConnection(reconnecting), 250);
    return;
  }
  retryTimer = null;
  enableSteps();
  if (reconnecting) {
    for (const name of ["overview", "gallery"]) models[name]?.send({ type: "sync" });
  }
}

events.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  // Events can arrive while /state is in flight. Applying them immediately
  // would let the older snapshot overwrite newer busy/read-only/status truth;
  // hold them and replay in order after the snapshot instead.
  if (applyingSnapshot) bufferedEvents.push(ev);
  else applyEvent(ev);
};
events.onopen = () => {
  const reconnecting = everConnected;
  everConnected = true;
  if (retryTimer !== null) clearTimeout(retryTimer);
  // On first open: everything the server already knows. On a re-open after
  // a dropped stream: the same snapshot covers missed traits and finished
  // steps, and each streaming widget asks for its own image catch-up.
  restoreConnection(reconnecting);
};
</script>
</body>
</html>
"""
