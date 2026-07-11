"""The one page the operator sees — no notebook, no code, just the run.

The page walks the same numbered steps as ``zmart_microscopy_v4_react
.ipynb``: each section has one button (or one embedded widget), a sentence
saying what the step does for the experiment, and a live message from
Python saying how it went. The interactive panels are the SAME React
widgets the notebook shows — their JavaScript modules are served from this
package unchanged — connected through a small stand-in for the notebook's
messaging (defined at the bottom of the page script).

Everything is inline and offline: no fonts, scripts, or styles are fetched
from anywhere.
"""

from __future__ import annotations

# The steps, in the notebook's order. Each is (id, title, what-it-means,
# button label or None when the section is widget-only).
_STEPS = [
    (
        "connect",
        "1 · Connect",
        "Start the analysis engine and open the microscope session. "
        "Everything this run saves lands in one new run folder.",
        "Connect",
    ),
    (
        "set_origin",
        "2 · Set origin",
        "Marks the stage's current position as (0, 0). Every position in "
        "this run counts from here, so do this with the sample framed the "
        "way you want it.",
        "Set origin",
    ),
    (
        "capture_overview_job",
        "3a · Capture the overview job",
        "In LAS X, select the low-magnification overview job first — then "
        "press capture so the run remembers its settings. (The demo selects "
        "its simulated overview job for you.)",
        "Capture overview job",
    ),
    (
        "capture_target_job",
        "3b · Capture the target job",
        "Now select the high-magnification target job in LAS X and capture "
        "it too. The run refuses to continue if both captures are the same "
        "job — that would image targets at overview quality.",
        "Capture target job",
    ),
    (
        "load_positions",
        "4 · Positions and focus",
        "Loads the overview positions from the microscope and opens the "
        "focus map. Click a few spread-out points on the map, then press "
        "Measure in the panel — the fitted focus surface keeps every later "
        "image sharp across the whole sample.",
        "Load positions",
    ),
    (
        "check_calibration",
        "5 · Validate the calibration",
        "Images the same small ring of sites with both objectives and "
        "measures how far they disagree. If the offset is larger than a "
        "cell, targeted acquisition would miss — better to know now.",
        "Run calibration check",
    ),
    (
        "run_overview",
        "6 · Scan the overview",
        "Drives the stage through every overview position and stitches the "
        "live map below, tile by tile, as the images are saved.",
        "Scan overview",
    ),
    (
        "discover_targets",
        "7 · Discover cells",
        "The analysis engine segments every overview tile and each found "
        "cell becomes a dot in the explorer below. Gate with the threshold "
        "boxes or draw a lasso; hover any dot to see that cell's picture; "
        "click dots (or map rings) to hand-pick cells.",
        "Discover cells",
    ),
    (
        "gallery",
        "8 · Acquire and curate",
        "Type how many cells to image (or use your hand-picked ones) and "
        "press Acquire in the panel — each overview/target pair appears the "
        "moment it is captured. Mark each pair good ✓ or bad ✗: that is "
        "your quality record of the run.",
        None,
    ),
    (
        "save_results",
        "9 · Save the run",
        "Writes the run report, the layout picture, and your good/bad "
        "verdicts into the run folder, next to the images.",
        "Save results",
    ),
    (
        "disconnect",
        "10 · Disconnect",
        "Shuts the analysis engine down and releases the microscope. Always end a session here.",
        "Disconnect",
    ),
]

# Which widget mounts inside which step's section.
_WIDGET_SECTIONS = {
    "status": "status",
    "overview": "run_overview",
    "focus": "load_positions",
    "calibration": "check_calibration",
    "explorer": "discover_targets",
    "gallery": "gallery",
}


def _sections_html() -> str:
    parts = []
    for step_id, title, meaning, button in _STEPS:
        widget_holes = "".join(
            f'<div class="widget" id="widget-{widget}"></div>'
            for widget, section in _WIDGET_SECTIONS.items()
            if section == step_id
        )
        button_html = (
            f'<button class="step-btn" data-step="{step_id}">{button}</button>' if button else ""
        )
        parts.append(
            f"""
      <section id="step-{step_id}">
        <div class="step-head">
          <h2>{title}</h2>
          {button_html}
          <span class="step-note" id="note-{step_id}"></span>
        </div>
        <p class="meaning">{meaning}</p>
        {widget_holes}
      </section>"""
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
        The same run as the operator notebook, step by step: connect, set
        the origin, capture the two jobs, measure focus, validate the
        calibration, scan the overview, discover cells, acquire and curate,
        save, disconnect. Green ✓ marks a finished step; every panel below
        updates live while the microscope works.
      </p>
      <p id="demo-banner" hidden>
        This is the <strong>demo</strong>: a simulated microscope imaging a
        synthetic sample — the very one the offline tests drive. Nothing
        here touches real hardware, so click around freely.
      </p>
    </header>
    <section id="step-status">
      <div class="step-head"><h2>Where the run stands</h2></div>
      <div class="widget" id="widget-status"></div>
    </section>
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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%2338bdf8'/%3E%3C/svg%3E">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: #0f172a; color: #e2e8f0;
    font-family: system-ui, -apple-system, sans-serif; font-size: 14px;
  }
  header, section { max-width: 1060px; margin: 0 auto 14px; }
  header h1 { font-size: 22px; margin: 0 0 6px; }
  header p { color: #94a3b8; margin: 4px 0; max-width: 72ch; }
  #demo-banner { color: #fbbf24; }
  section {
    background: #1e293b; border: 1px solid #334155; border-radius: 12px;
    padding: 14px 16px;
  }
  .step-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .step-head h2 { font-size: 15px; margin: 0; }
  .meaning { color: #94a3b8; margin: 6px 0 0; max-width: 78ch; }
  .step-btn {
    background: #38bdf8; color: #082f49; border: none; border-radius: 8px;
    padding: 7px 16px; font-weight: 600; cursor: pointer; font-size: 13px;
  }
  .step-btn:disabled { background: #334155; color: #94a3b8; cursor: default; }
  .step-note { color: #94a3b8; font-size: 13px; }
  .step-note.ok { color: #4ade80; }
  .step-note.bad { color: #f87171; }
  section.done { border-color: #14532d; }
  section.done h2::after { content: " ✓"; color: #4ade80; }
  .widget { margin-top: 12px; }
  .widget:empty { display: none; }
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

class ZmartModel {
  constructor(name, traits) {
    this.name = name;
    this.state = { ...traits };
    this.handlers = new Map();
    this.pending = {};
    this.chain = Promise.resolve();
  }
  get(name) { return this.state[name]; }
  set(name, value) { this.state[name] = value; this.pending[name] = value; }
  save_changes() {
    const changes = this.pending;
    this.pending = {};
    post("/trait", { widget: this.name, changes });
  }
  send(content) { post("/msg", { widget: this.name, content }); }
  on(event, cb) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event).push(cb);
  }
  off(event, cb) {
    const list = this.handlers.get(event) || [];
    const i = list.indexOf(cb);
    if (i >= 0) list.splice(i, 1);
  }
  emit(event, ...args) {
    (this.handlers.get(event) || []).slice().forEach((cb) => cb(...args));
  }
  applyTrait(name, value) { this.state[name] = value; this.emit(`change:${name}`); }
  applyMsg(content, bufferIds) {
    // Chained so messages reach the widget in exactly the order Python
    // sent them, even though their image fetches finish at random times.
    this.chain = this.chain.then(async () => {
      const buffers = await Promise.all((bufferIds || []).map((id) =>
        fetch(`/buffer/${id}`).then((r) => r.ok ? r.arrayBuffer() : new ArrayBuffer(0))));
      this.emit("msg:custom", content, buffers);
    });
  }
}

function post(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function mountWidget(name, traits) {
  if (models[name]) return;
  const el = document.getElementById(`widget-${name}`);
  if (!el) return;
  const model = new ZmartModel(name, traits);
  models[name] = model;
  const mod = await import(`/esm/${name}.mjs`);
  mod.default.render({ model, el });
}

async function ensureWidget(name) {
  if (models[name]) return;
  const snapshot = await fetch("/state").then((r) => r.json());
  if (snapshot.widgets[name]) await mountWidget(name, snapshot.widgets[name]);
}

// ---- the step buttons -----------------------------------------------------

function noteFor(step) { return document.getElementById(`note-${step}`); }

function markDone(step) {
  const section = document.getElementById(`step-${step}`);
  if (section) section.classList.add("done");
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
  }
  const button = document.querySelector(`button[data-step="${ev.step}"]`);
  if (button) button.disabled = ev.state === "running";
}

document.querySelectorAll(".step-btn").forEach((button) => {
  button.addEventListener("click", () => {
    post("/action", { step: button.dataset.step });
  });
});

// ---- boot: state snapshot first, then the live stream ---------------------

let everConnected = false;

async function applySnapshot() {
  const snapshot = await fetch("/state").then((r) => r.json());
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

await applySnapshot();
const events = new EventSource("/events");
events.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  if (ev.kind === "trait") models[ev.widget]?.applyTrait(ev.name, ev.value);
  else if (ev.kind === "msg") models[ev.widget]?.applyMsg(ev.content, ev.buffers);
  else if (ev.kind === "widget") ensureWidget(ev.widget);
  else if (ev.kind === "flow") flowUpdate(ev);
};
events.onopen = async () => {
  if (!everConnected) { everConnected = true; return; }
  // The stream dropped and came back: re-sync everything we may have
  // missed — traits from the snapshot, streamed images via each widget's
  // own catch-up request.
  await applySnapshot();
  for (const name of ["overview", "gallery"]) models[name]?.send({ type: "sync" });
};
</script>
</body>
</html>
"""
