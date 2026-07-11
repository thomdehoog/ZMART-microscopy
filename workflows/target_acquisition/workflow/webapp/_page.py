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
    "status": "status",
    "overview": "run_overview",
    "focus": "load_positions",
    "explorer": "discover_targets",
    "gallery": "gallery",
}


def _sections_html() -> str:
    parts = []
    for step_id, title, meaning, button, auto_collapse in _STEPS:
        widget_holes = "".join(
            f'<div class="widget" id="widget-{widget}"></div>'
            for widget, section in _WIDGET_SECTIONS.items()
            if section == step_id
        )
        button_html = (
            f'<button class="step-btn" data-step="{step_id}" disabled>{button}</button>'
            if button
            else ""
        )
        parts.append(
            f"""
      <details class="step" id="step-{step_id}" data-collapse="{str(auto_collapse).lower()}" open>
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
      <h1>ZMART target acquisition</h1>
      <p>
        The same run as the operator notebook, one step at a time. A green
        ✓ marks a finished step (finished steps fold away — click any title
        to open it again), and every panel updates live while the
        microscope works.
      </p>
      <p id="demo-banner" hidden>
        This is the <strong>demo</strong>: a simulated microscope imaging a
        synthetic sample — the very one the offline tests drive. Nothing
        here touches real hardware, so click around freely.
      </p>
    </header>
    <details class="step" id="step-status" open>
      <summary><span class="step-title">Where the run stands</span></summary>
      <div class="step-body">
        <div class="widget" id="widget-status"></div>
      </div>
    </details>
"""
        + _sections_html()
        + _SCRIPT
    )


_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZMART target acquisition</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%230284c7'/%3E%3C/svg%3E">
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px 16px 60px; background: #ffffff; color: #0f172a;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 15px; line-height: 1.5;
  }
  header, .step { max-width: 980px; margin: 0 auto 12px; }
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
  }
  .step summary::-webkit-details-marker { display: none; }
  .step summary::before {
    content: "▸"; color: #94a3b8; font-size: 12px; align-self: center;
    transition: transform 0.15s;
  }
  .step[open] summary::before { transform: rotate(90deg); }
  .step-title { font-weight: 600; font-size: 15px; }
  .step.done .step-title::after { content: " ✓"; color: #16a34a; }
  .step-note { color: #64748b; font-size: 13.5px; }
  .step-note.ok { color: #15803d; }
  .step-note.bad { color: #b91c1c; }
  .step-body { padding: 0 16px 12px; }
  .meaning { color: #475569; margin: 2px 0 10px; max-width: 78ch; }
  .step-btn {
    background: #0284c7; color: #ffffff; border: none; border-radius: 8px;
    padding: 8px 18px; font-weight: 600; cursor: pointer; font-size: 14px;
  }
  .step-btn:hover:enabled { background: #0369a1; }
  .step-btn:disabled { background: #e2e8f0; color: #94a3b8; cursor: default; }
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

function markDone(step) {
  const section = document.getElementById(`step-${step}`);
  if (!section) return;
  section.classList.add("done");
  // Finished button-only steps fold away so the page reads as "what's
  // next"; panels the operator keeps using stay open. A click reopens any.
  if (section.dataset.collapse === "true") section.open = false;
}

function flowUpdate(ev) {
  const note = noteFor(ev.step);
  if (!note) return;
  if (ev.state === "running") {
    note.textContent = "working…";
    note.className = "step-note";
  } else if (ev.state === "done") {
    note.textContent = ev.message;
    note.className = "step-note ok";
    markDone(ev.step);
  } else {
    note.textContent = ev.message;
    note.className = "step-note bad";
    const section = document.getElementById(`step-${ev.step}`);
    if (section) section.open = true;
  }
  const button = document.querySelector(`button[data-step="${ev.step}"]`);
  if (button) button.disabled = ev.state === "running";
}

document.querySelectorAll(".step-btn").forEach((button) => {
  button.addEventListener("click", (e) => {
    e.preventDefault();
    // Close the double-click window locally; Python independently coalesces
    // duplicate pending steps, so this is UX rather than the safety gate.
    button.disabled = true;
    post("/action", { step: button.dataset.step }).catch((error) => {
      button.disabled = false;
      const note = noteFor(button.dataset.step);
      if (note) {
        note.textContent = `request failed: ${error.message}`;
        note.className = "step-note bad";
      }
    });
  });
});

// ---- boot: connect the live stream FIRST, then the state snapshot ----------
// Buttons stay disabled until the stream is provably open, so a click can
// never fire while its progress events would have nowhere to arrive.

async function applySnapshot() {
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
  (snapshot.flow.completed || []).forEach(markDone);
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
  if ((ev.kind === "trait" || ev.kind === "msg") && !models[ev.widget]) {
    if (!pendingWidgetEvents.has(ev.widget)) pendingWidgetEvents.set(ev.widget, []);
    pendingWidgetEvents.get(ev.widget).push(ev);
    ensureWidget(ev.widget);
    return;
  }
  if (ev.kind === "trait") models[ev.widget].applyTrait(ev.name, ev.value);
  else if (ev.kind === "msg") models[ev.widget].applyMsg(ev.content, ev.buffers);
  else if (ev.kind === "widget") ensureWidget(ev.widget);
  else if (ev.kind === "flow") flowUpdate(ev);
}

function synchronizedSnapshot() {
  snapshotChain = snapshotChain.then(async () => {
    applyingSnapshot = true;
    try {
      await applySnapshot();
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
  const restored = await synchronizedSnapshot();
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
