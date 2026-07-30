import "./style.css";
import { numbered } from "./frame/steps.js";
import {
  MICROSCOPES, DEFAULT_SESSION, DEMO_PRESETS, apisFor, defaultApiFor,
  describeSession, describeConnection, CONNECT_CHECKS,
  SETTING_TYPES, settingType, sampleReading, STAGE_LIMITS_MM,
} from "./lib/microscopes.js";
import { DEFAULT_CARRIER, describeCarrier } from "./lib/carriers.js";
import carrierWidget from "./widgets/carrier.js";
import scanfieldsWidget from "./widgets/scanfields.js";

(() => {
  "use strict";

  /* ============================================================
     the synthetic sample
     ============================================================ */
  /* Deterministic, so the mock looks the same every load and can be argued
     about. Carrier micrometres throughout — the same frame the scan fields and
     the carrier's areas are in.

     Two things, and the split is the point. Tissue belongs to the plate: soft
     patches spread over the carrier, there whether or not anybody looks. Cells
     belong to the plan: the run only knows about what it imaged, so they are
     generated inside the tiles the scan fields ask for. Look somewhere else
     and a different sample comes back, which is the honest behaviour — before
     this the sample was a 7 by 5 block in the corner and the plan could not
     move it. */
  const TARGET_CELLS = 1250;
  const AREA_LO = 60, AREA_HI = 400;

  function makeRng(seed) {
    let s = seed >>> 0;
    return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
  }

  let sample = { tissue: [], cells: [], bounds: null };

  function tissueFor(carrier) {
    const rnd = makeRng(20260728);
    const [w, h] = carrierWidget.extentUm(carrier);
    return Array.from({ length: 7 }, () => ({
      x: (0.08 + 0.84 * rnd()) * w,
      y: (0.08 + 0.84 * rnd()) * h,
      r: (0.10 + 0.16 * rnd()) * Math.min(w, h),
    }));
  }

  function density(x, y) {
    let d = 0;
    for (const b of sample.tissue) {
      const dx = x - b.x, dy = y - b.y;
      d += Math.exp(-(dx * dx + dy * dy) / (2 * b.r * b.r));
    }
    return Math.min(1, d);
  }

  /* Rebuilt whenever the plan or the plate changes, because either changes
     what there is to find. A cell remembers which tile it was imaged in, so
     tuning detection on one tile is a question the sample can answer. */
  function rebuildSample() {
    state.plan = scanfieldsWidget.plan(state.fields, recordedPresets());
    sample = { tissue: tissueFor(state.carrier), cells: [], bounds: null };
    if (!state.plan.length) return;

    const rnd = makeRng(90210);
    const per = TARGET_CELLS / state.plan.length;
    const cells = [];
    let xMin = Infinity, yMin = Infinity, xMax = -Infinity, yMax = -Infinity;

    state.plan.forEach((t, tile) => {
      const half = t.frameUm / 2;
      xMin = Math.min(xMin, t.x - half); xMax = Math.max(xMax, t.x + half);
      yMin = Math.min(yMin, t.y - half); yMax = Math.max(yMax, t.y + half);
      const d = density(t.x, t.y);
      // a rich patch comes back crowded and a bare one nearly empty, rather
      // than every tile returning the same handful
      const n = Math.round(per * (0.15 + 1.85 * d));
      for (let i = 0; i < n; i++) {
        const area = 62 + 330 * Math.pow(rnd(), 1.7);
        cells.push({
          id: cells.length + 1, tile,
          x: t.x + (rnd() - 0.5) * t.frameUm,
          y: t.y + (rnd() - 0.5) * t.frameUm,
          area,
          intensity: Math.max(0.02, Math.min(1, 0.18 + 0.62 * d + 0.22 * (rnd() - 0.5))),
          r: Math.sqrt(area / Math.PI),
        });
      }
    });
    sample.cells = cells;
    sample.bounds = { xMin, yMin, xMax, yMax };
  }

  const cellsInTile = (tile) => sample.cells.filter((c) => c.tile === tile);

  /* ============================================================
     workflow declarations — the whole point of the selector box
     ============================================================ */
  const WORKFLOWS = {
    target_acquisition: {
      name: "Target acquisition",
      blurb: "overview, detect, select, acquire",
      steps: numbered([
        { id: "connect", title: "Microscope configuration", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: ["connect"], ms: 1900 },
        { id: "optics", title: "Optical configuration", why: "Set the microscope up in its own software, name the preset, and record it.", ownButton: true, panels: ["optics"], mode: "optics" },
        { id: "carrier", title: "Carrier configuration", why: "Tell the run what the sample is mounted in — it says where within the stage the sample sits.", panels: [], mode: "carrier" },
        { id: "scanfields", title: "Initial scanfields", why: "Say where on the carrier the overview is taken — a block in every area, or regions drawn by hand.", panels: [], mode: "scanfields" },
        { id: "focus", title: "Focus strategy", why: "Choose how this run keeps every image sharp across the sample.", btn: "Apply strategy", panels: ["focus"], ms: 1400, mode: "focus" },
        { id: "scan", title: "Scan the overview", why: "Drives the stage through every position, stitching tiles as they are saved.", btn: "Scan overview", panels: [], ms: 2600, mode: "scan" },
        { id: "detect", title: "Detect cells", why: "Segments every overview tile. Each cell found becomes one point.", btn: "Detect cells", panels: ["detect"], ms: 1600, mode: "detect" },
        { id: "select", title: "Select cells", why: "Gate the cells worth imaging — drag a box on the plot, or pick them on the canvas.", btn: "Confirm selection", panels: ["analysis"], ms: 600, mode: "select" },
        { id: "acquire", title: "Acquire and curate", why: "Images the selected cells at target magnification and collects your verdicts.", btn: "Acquire selection", panels: ["gallery"], ms: 2200, mode: "targets" },
        { id: "save", title: "Save the run", why: "Writes the report, the layout picture and your verdicts beside the images.", btn: "Save results", panels: [], ms: 800, note: "report + layout written" },
        { id: "disconnect", title: "Disconnect", why: "Releases the microscope and shuts the analysis engine down.", btn: "Disconnect", panels: [], ms: 600, note: "session closed" },
      ]),
    },
    overview_only: {
      name: "Overview only",
      blurb: "no analysis panel",
      steps: numbered([
        { id: "connect", title: "Microscope configuration", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: ["connect"], ms: 1900 },
        { id: "optics", title: "Optical configuration", why: "Set the microscope up in its own software, name the preset, and record it.", ownButton: true, panels: ["optics"], mode: "optics" },
        { id: "carrier", title: "Carrier configuration", why: "Tell the run what the sample is mounted in — it says where within the stage the sample sits.", panels: [], mode: "carrier" },
        { id: "scanfields", title: "Initial scanfields", why: "Say where on the carrier the overview is taken — a block in every area, or regions drawn by hand.", panels: [], mode: "scanfields" },
        { id: "scan", title: "Scan the overview", why: "Drives the stage through every position and stitches the map.", btn: "Scan overview", panels: [], ms: 2600, mode: "scan" },
        { id: "save", title: "Save the run", why: "Writes the stitched map and its report to the run folder.", btn: "Save results", panels: [], ms: 800, note: "map + report written" },
        { id: "disconnect", title: "Disconnect", why: "Releases the microscope.", btn: "Disconnect", panels: [], ms: 600, note: "session closed" },
      ]),
    },
    focus_check: {
      name: "Focus surface check",
      blurb: "calibration run",
      steps: numbered([
        { id: "connect", title: "Microscope configuration", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: ["connect"], ms: 1900 },
        { id: "optics", title: "Optical configuration", why: "Set the microscope up in its own software, name the preset, and record it.", ownButton: true, panels: ["optics"], mode: "optics" },
        { id: "carrier", title: "Carrier configuration", why: "Tell the run what the sample is mounted in — it says where within the stage the sample sits.", panels: [], mode: "carrier" },
        { id: "scanfields", title: "Initial scanfields", why: "Say where on the carrier the overview is taken — a block in every area, or regions drawn by hand.", panels: [], mode: "scanfields" },
        { id: "focus", title: "Focus strategy", why: "Choose how the surface is measured, then run it.", btn: "Apply strategy", panels: ["focus"], ms: 1400, mode: "focus" },
        { id: "save", title: "Write the surface", why: "Fits the plane and records its residual for this objective.", btn: "Write surface", panels: [], ms: 700, note: "residual 1.8 µm · written" },
        { id: "disconnect", title: "Disconnect", why: "Releases the microscope.", btn: "Disconnect", panels: [], ms: 600, note: "session closed" },
      ]),
    },
  };

  /* ============================================================
     run state
     ============================================================ */
  // The focus strategy is its own little document: which approach, that
  // approach's parameters, and whatever it has produced so far.
  function newFocus() {
    return {
      strategy: "plane",
      metric: "brenner",   // which sharpness score the sweep is scored with
      points: [],          // picked positions, plane strategy only
      selected: 0,         // which point's trace is charted
      zFixed: -412,
      reuse: "run_0714_a",
      applied: false,
      surface: null,       // constant | plane | spline, chosen by geometry
      residual: null,
      worst: -1,
    };
  }

  // detection settings live next to the focus strategy: chosen, tried on one
  // tile, then applied to the rest
  function newDetect() {
    return {
      algo: "cellpose",
      diameter: 18,
      cellprob: 0,
      thresh: 0.35,
      minArea: 80,
      tile: 0,
      tested: false,
    };
  }

  const PREVIOUS_SURFACES = {
    run_0714_a: { label: "2026-07-14 · slide A", plane: { a: 96, b: 61, c: -412 }, residual: 1.8, ageDays: 14 },
    run_0709_c: { label: "2026-07-09 · slide C", plane: { a: 71, b: 88, c: -389 }, residual: 3.1, ageDays: 19 },
  };

  /* The bars a run starts with: the demo presets as though the controller had
     already been read for them, and under those the one open bar that is
     always waiting. Built fresh each time, because a bar is edited in place
     and a shared one would carry the last run's typing into the next. */
  function startingBars() {
    const recorded = DEMO_PRESETS.map(({ name, type, nth }) => {
      const reading = sampleReading(type, nth);
      return { type, name, state: reading.summary, detail: reading.detail, frameUm: reading.frameUm };
    });
    return [...recorded, { type: SETTING_TYPES[0].key, name: "" }];
  }

  const state = {
    session: { ...DEFAULT_SESSION },
    recordings: [],
    bars: startingBars(),
    carrier: { ...DEFAULT_CARRIER },
    fields: [],
    plan: [],
    editor: null,
    checks: [],
    wf: "target_acquisition",
    activeIdx: 0,
    done: new Set(),
    running: null,
    notes: {},
    tabs: ["canvas"],     // canvas plus whatever the active step asks for
    tab: null,
    tilesShown: 0,
    focus: newFocus(),
    detect: newDetect(),
    detected: new Set(),
    cellsShown: false,
    gate: null,          // {aLo,aHi,iLo,iHi}
    gated: new Set(),
    acquired: [],
    verdicts: {},
    locked: false,
  };

  const steps = () => WORKFLOWS[state.wf].steps;
  const step = (i) => steps()[i];

  const el = (id) => document.getElementById(id);

  /* ============================================================
     left rail
     ============================================================ */
  const selectEl = el("wf-select");
  for (const [key, wf] of Object.entries(WORKFLOWS)) {
    const opt = document.createElement("option");
    opt.value = key; opt.textContent = wf.name;
    selectEl.append(opt);
  }
  selectEl.value = state.wf;

  selectEl.addEventListener("change", () => {
    if (state.locked) { selectEl.value = state.wf; return; }
    state.wf = selectEl.value;
    resetRun();
  });

  el("restart-btn").addEventListener("click", resetRun);

  /* Closing the session takes the run with it: settings were read off this
     microscope, the origin is in its coordinates, and the tiles came from it.
     Keeping any of that against a session that has been closed would be
     keeping something that might now be a lie. The chosen microscope, API and
     password stay, since editing them is the reason to disconnect. */
  function resetRun() {
    Object.assign(state, {
      activeIdx: 0, done: new Set(), running: null, notes: {},
      recordings: [],
      bars: startingBars(),
      carrier: { ...DEFAULT_CARRIER }, fields: [], plan: [], checks: [],
      tabs: ["canvas"], tab: "canvas", tilesShown: 0, focus: newFocus(),
      detect: newDetect(), detected: new Set(),
      cellsShown: false, gate: null, gated: new Set(), acquired: [], verdicts: {},
      locked: false,
    });
    view.fitted = false; fview.fitted = false;
    // the presets a run starts with complete their step, by the same rule any
    // other recorded preset does
    settingsChanged();
    focusPanelsFor(0);
    el("gate-readout").textContent = "drag a rectangle to gate";
    el("pairs").textContent = "";
    renderFocusToolbar();
    renderAll();
  }

  function renderRail() {
    /* No summary line: the rail below already lists the steps, and a locked
       selector shows for itself that the run has started. */
    selectEl.disabled = state.locked;
    el("restart-btn").disabled = !state.locked;

    const host = el("steps");
    host.textContent = "";

    steps().forEach((s, i) => {
      const done = state.done.has(s.id);
      const active = i === state.activeIdx;
      const running = state.running === s.id;
      const reachable = i <= firstIncomplete();

      const b = document.createElement("button");
      b.className = "step" + (active ? " active" : "") + (done ? " done" : "") + (reachable ? "" : " locked");
      b.type = "button";
      if (!reachable) b.disabled = true;

      const head = document.createElement("div");
      head.className = "step-head";
      head.innerHTML =
        `<span class="step-n">${s.n}</span><span class="step-name"></span>`;
      head.querySelector(".step-name").textContent = s.title;
      if (running) head.insertAdjacentHTML("beforeend", '<span class="spin"></span>');
      b.append(head);

      /* A step says what it produced and nothing else. Standing on one used to
         unfold a sentence explaining it, which grew the step you were on by
         two lines and pushed the rest of the run down the rail every time you
         moved — a rail that shifts underfoot to explain a step the panel
         beside it is already showing. */
      if (state.notes[s.id]) {
        const n = document.createElement("div");
        n.className = "step-body";
        const note = document.createElement("div");
        note.className = "step-note ok";
        note.textContent = state.notes[s.id];
        n.append(note);
        b.append(n);
      }

      b.addEventListener("click", () => {
        if (state.running || !reachable) return;
        state.activeIdx = i;
        if (step(i).id === "carrier") carrierSettled();
        if (step(i).id === "scanfields") scanfieldsSettled();
        focusPanelsFor(i);
        renderAll();
      });

      host.append(b);
    });
  }

  /* What this step needs before it may run, and what to say when it is not
     met. Read by the action bar; the server would enforce the same list. */
  function readiness(s) {
    if (s.mode === "focus" && !STRATEGIES[state.focus.strategy].needs(state.focus)) {
      return STRATEGIES[state.focus.strategy].unmet;
    }
    if (s.mode === "optics" && !recordedBars().length) return "record at least one preset";
    if (s.mode === "detect" && !state.detect.tested) return "try it on one tile first";
    if ((s.mode === "select" || s.mode === "targets") && state.gated.size === 0) return "nothing gated yet";
    return null;
  }

  /* A step's action lives with the panel it operates, at the end of it — the
     way Connect's button has always sat inside its form. There is no bar above
     the panel any more: a button that runs the thing you are looking at should
     not be somewhere else, and a sentence explaining the step belongs with the
     step, which is the rail.

     `ownButton` now means "this panel builds its own", not "hide the bar". */
  function renderStepAction(shown) {
    for (const id of FOOT_IDS) el(id).textContent = "";
    for (const slot of document.querySelectorAll(".carrier-action")) slot.textContent = "";
    if (!shown) return;
    const i = state.activeIdx, s = step(i);
    /* A step with controls of its own puts its action at the end of them; the
       rest fall back to the bar under the panel they are looking at. */
    const host = document.querySelector(`.${s.id}-action`) ?? el(`foot-${shown}`);
    if (!host || s.ownButton || !s.btn) return;

    const done = state.done.has(s.id);
    const running = state.running === s.id;
    const blocked = readiness(s);

    const run = document.createElement("button");
    /* marked as the step's own, because where it sits depends on the step */
    run.className = "run step-run"; run.type = "button";
    run.textContent = running ? "working…" : (done ? "Run again" : s.btn);
    run.disabled = !!state.running || !!blocked;
    run.addEventListener("click", () => runStep(i));
    host.append(run);

    const hint = document.createElement("span");
    if (blocked) { hint.className = "action-hint"; hint.textContent = blocked; }
    else if (running) { hint.className = "action-hint"; hint.textContent = "working…"; }
    else if (s.mode === "select" && !done) { hint.className = "action-hint ok"; hint.textContent = `${state.gated.size} gated`; }
    else if (state.notes[s.id]) { hint.className = "action-hint ok"; hint.textContent = state.notes[s.id]; }
    host.append(hint);
  }

  /* Which panel is showing decides which foot fills, so the action follows the
     operator rather than the step declaring where to put it. */
  const renderActionBar = () => renderStepAction(shownPanel());

  function firstIncomplete() {
    const list = steps();
    for (let i = 0; i < list.length; i++) if (!state.done.has(list[i].id)) return i;
    return list.length - 1;
  }

  /* ============================================================
     running a step — fake work with real state changes
     ============================================================ */
  function runStep(i) {
    const s = step(i);
    if (state.running) return;
    state.running = s.id;
    state.locked = true;
    renderAll();

    const started = performance.now();
    let raf = null;

    /* Connecting is a handful of questions, not one action. Each answer lands
       as it arrives, so a session that fails does so at a named check rather
       than as a spinner that stops. */
    if (s.id === "connect") {
      /* Every question is on screen from the moment it is asked; only the
         answers arrive. A list that grew a row at a time made the last check
         look like an afterthought and moved everything under it as it came. */
      state.checks = CONNECT_CHECKS.map((check) => ({ ...check, result: null }));
      renderSetup();
      CONNECT_CHECKS.forEach((check, k) => {
        setTimeout(() => {
          if (state.running !== "connect") return;
          state.checks[k].result = check.result(state.session);
          answerCheck(k);
        }, 260 * (k + 1));
      });
    }

    if (s.mode === "scan") {
      state.tilesShown = 0;
      const total = state.plan.length;
      const tick = () => {
        const t = Math.min(1, (performance.now() - started) / s.ms);
        state.tilesShown = Math.round(t * total);
        state.notes[s.id] = `${state.tilesShown} / ${total} tiles`;
        drawStage(); renderAll();
        if (t < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }

    setTimeout(() => {
      if (raf) cancelAnimationFrame(raf);
      state.running = null;
      state.done.add(s.id);
      if (s.note) state.notes[s.id] = s.note;
      if (s.id === "connect") state.notes[s.id] = describeSession(state.session);
      if (s.id === "optics") {
        const n = recordedBars().length;
        state.notes[s.id] = `${n} setting${n === 1 ? "" : "s"} recorded`;
      }

      if (s.mode === "focus") {
        const f = state.focus;
        if (f.strategy === "plane") { remeasure(); f.selected = 0; }
        f.applied = true;
        state.notes[s.id] =
          f.strategy === "plane" ? `${f.surface.model} from ${f.points.length} points · rms ${f.residual.toFixed(1)} µm`
          : f.strategy === "fixed" ? `fixed z ${f.zFixed} µm`
          : f.strategy === "auto" ? `autofocus per position · ${METRICS[f.metric].label}`
          : `reusing ${PREVIOUS_SURFACES[f.reuse].label}`;
        renderFocusToolbar(); drawTrace();
      }
      if (s.mode === "scan") { state.tilesShown = state.plan.length; }
      if (s.mode === "detect") {
        // the settings proven on one tile, now applied to every tile
        state.detected = new Set(sample.cells.filter(detects).map((c) => c.id));
        state.cellsShown = true;
        state.notes[s.id] = `${state.detected.size} cells · ${ALGOS[state.detect.algo].label}`;
      }
      if (s.mode === "select") { state.notes[s.id] = `${state.gated.size} cells selected`; }
      if (s.mode === "targets") {
        const picked = [...state.gated].slice(0, 12);
        state.acquired = picked;
        state.notes[s.id] = `${picked.length} pairs acquired`;
        buildGallery();
      }
      if (s.id === "disconnect") { state.locked = false; }

      /* Finishing a run never moves the operator. The gallery is still being
         curated, the trace still being read, and a step that quietly hands
         the page to the next one takes that away. Advancing is a click. */
      focusPanelsFor(state.activeIdx);
      renderAll();
    }, s.ms);
  }

  /* ============================================================
     tabs — they accumulate as steps declare panels
     ============================================================ */
  /* Each setup step brings its own panel rather than sharing one called Setup.
     They are three different things — a session, a list of presets, a carrier —
     and a tab beside the canvas should say which of them it opens. They draw
     into the same element because only one is ever shown. */
  const FOOT_IDS = ["foot-setup", "foot-canvas", "foot-detect", "foot-focus", "foot-analysis", "foot-gallery"];

  const PANEL_META = {
    connect: { label: "Microscope configuration", panel: "panel-setup" },
    optics: { label: "Optical configuration", panel: "panel-setup" },
    canvas: { label: "Canvas", panel: "panel-canvas" },
    detect: { label: "Detection", panel: "panel-detect" },
    focus: { label: "Focus strategy", panel: "panel-focus" },
    analysis: { label: "Analysis", panel: "panel-analysis" },
    gallery: { label: "Gallery", panel: "panel-gallery" },
  };

  /* The canvas is the microscope's own limits drawn to scale, so it is there
     from the step that sets it up onward. Nothing about the frame depends on
     the carrier chosen inside it; the carrier only says where within those
     limits the sample sits.

     Setting it up fixes the run's zero as well, which is why no step asks for
     an origin any more. That happens behind the scenes and is deliberately not
     drawn: it is a consequence of having a frame, not a thing to confirm.

     From there the canvas is the window into the run, filling with data rather
     than appearing once data exists. The tab set is rebuilt on every render
     rather than growing forever. */
  /* It belongs to the steps that happen inside it, and to no others — the same
     rule every other panel follows. The session and the instrument are not on
     the stage, so walking back to those steps leaves the canvas behind rather
     than parking a tab there for something the step has nothing to do with.
     Which makes this a question about the step being looked at, not about how
     far the run has got. */
  const canvasAt = (i) => {
    const c = indexOfStep("carrier");
    return c >= 0 && i >= c;
  };

  function panelsFor(i) {
    const own = (step(i).panels || []).filter((p) => p !== "canvas");
    return canvasAt(i) ? ["canvas", ...own] : own;
  }

  function focusPanelsFor(i) {
    state.tabs = panelsFor(i);
    // a step that brings a panel of its own opens on it; otherwise the base
    state.tab = state.tabs.length > 1 ? state.tabs[1] : state.tabs[0];
  }

  /* ============================================================
     the setup panel — the run's configuration, before it has data
     ============================================================ */
  /* Rows come from the steps themselves: anything a setup step recorded shows
     its result, anything not yet run shows what it is waiting for. A workflow
     that skips a step simply has no row for it. */
  const SETUP_ROWS = [
    { step: "focus", name: "Focus surface", waiting: "not measured" },
  ];

  /* Connecting is a card that reads downward — the form, the checks, what they
     came to, and the button that acts on all of it. Its button is its own
     rather than the frame's, because it is disabled until there is a password
     and it changes what it does once a session is open. */
  function renderSessionCard(host) {
    const connected = state.done.has("connect");
    let connectBtn = null;
    let connectHint = null;
    const connecting = state.running === "connect";
    const card = document.createElement("div");
    card.className = "session-card" + (connected ? " done" : "");

    /* The heading is the heading and nothing else. What the session was opened
       with is already in the fields below it and in the rail beside it, so a
       third copy in the corner was the panel talking about itself. */
    const head = document.createElement("div");
    head.className = "session-head";
    head.innerHTML = '<span class="session-title">Connect to the microscope</span>';
    card.append(head);

    {
      const locked = connected || connecting;
      const form = document.createElement("div");
      form.className = "session-form";

      const scope = document.createElement("label");
      scope.className = "field";
      scope.innerHTML = "<span>Microscope</span><select></select>";
      const scopeSel = scope.querySelector("select");
      for (const [key, m] of Object.entries(MICROSCOPES)) {
        const o = document.createElement("option");
        o.value = key;
        o.textContent = m.detail ? `${m.label} · ${m.detail}` : m.label;
        scopeSel.append(o);
      }
      scopeSel.value = state.session.microscope;
      scopeSel.disabled = locked;
      scopeSel.addEventListener("change", () => {
        state.session.microscope = scopeSel.value;
        state.session.api = defaultApiFor(scopeSel.value);
        renderSetup(); renderActionBar();
      });

      const api = document.createElement("label");
      api.className = "field";
      api.innerHTML = "<span>API</span><select></select>";
      const apiSel = api.querySelector("select");
      for (const [key, a] of apisFor(state.session.microscope)) {
        const o = document.createElement("option");
        o.value = key;
        o.textContent = `${a.label} · ${a.detail}`;
        apiSel.append(o);
      }
      apiSel.value = state.session.api;
      apiSel.disabled = locked;
      apiSel.addEventListener("change", () => {
        state.session.api = apiSel.value;
        renderSetup(); renderActionBar();
      });

      const pw = document.createElement("label");
      pw.className = "field";
      pw.innerHTML = '<span>Password</span><input type="password" autocomplete="current-password">';
      const pwInput = pw.querySelector("input");
      pwInput.value = state.session.password;
      pwInput.disabled = locked;
      /* Typing must not rebuild the card: re-rendering destroys the very
         input being typed into, which drops focus after every keystroke.
         Only what depends on the password is touched. */
      pwInput.addEventListener("input", () => {
        state.session.password = pwInput.value;
        const ready = !!pwInput.value;
        if (connectBtn) connectBtn.disabled = connecting || !ready;
        if (connectHint) connectHint.hidden = ready;
      });

      form.append(scope, api, pw);
      card.append(form);
    }

    /* Every check is listed the moment the session is opened, and each one
       ticks as its answer comes back. The row is the question; the mark is the
       answer. An open session is not editable, so the fields stay on show as
       the record of what it was opened with. */
    if (state.checks.length) {
      const list = document.createElement("div");
      list.className = "check-list";
      for (const c of state.checks) {
        const answered = c.result !== null;
        const row = document.createElement("div");
        row.className = "check-row" + (answered ? "" : " pending");
        row.innerHTML = '<span class="check-mark">✓</span><span class="check-name"></span>'
          + '<span class="check-value"></span>';
        row.querySelector(".check-name").textContent = c.label;
        row.querySelector(".check-value").textContent = answered ? c.result : "";
        list.append(row);
      }
      card.append(list);
    }

    /* What the checks came to, said once, where they end. The microscope and
       the API stand out of the sentence, being the two things in it that were
       chosen rather than written. */
    if (connected) {
      const done = document.createElement("div");
      done.className = "session-done";
      for (const part of describeConnection(state.session)) {
        const span = document.createElement(part.name ? "b" : "span");
        span.textContent = part.text;
        done.append(span);
      }
      card.append(done);
    }

    /* The button sits at the end of the card, after everything it acts on —
       the rule every other step already follows. It never leaves: while the
       session is closed it opens one, and while one is open it is the way out
       of it. */
    {
      const foot = document.createElement("div");
      foot.className = "session-foot";

      const btn = document.createElement("button");
      btn.type = "button";
      if (connected) {
        btn.className = "danger";
        btn.textContent = "Disconnect";
        btn.disabled = !!state.running;
        btn.addEventListener("click", closeSession);
      } else {
        btn.className = "run";
        btn.textContent = connecting ? "connecting…" : "Connect";
        btn.disabled = connecting || !state.session.password;
        btn.addEventListener("click", () => runStep(indexOfStep("connect")));
        connectBtn = btn;

        connectHint = document.createElement("div");
        connectHint.className = "session-hint";
        connectHint.textContent = "a password is needed to open the session";
        connectHint.hidden = !!state.session.password || connecting;
      }
      foot.append(btn);
      if (connectHint) foot.append(connectHint);
      card.append(foot);
    }

    host.append(card);
  }

  /* Only the answer lands. The row is already on screen, so filling one in
     touches that row rather than rebuilding the card under the operator —
     which would restart every other row's arrival along with it. */
  function answerCheck(k) {
    const row = document.querySelectorAll(".check-row")[k];
    if (!row) return;
    row.classList.remove("pending");
    row.querySelector(".check-value").textContent = state.checks[k].result;
  }

  /* Closing the session takes the run with it, for the reason resetRun already
     gives: everything after this was read off this session. Reopening against
     a different microscope is the reason to close one, so the choice of
     microscope, API and password is what survives. */
  function closeSession() {
    if (state.running) return;
    resetRun();
  }

  const indexOfStep = (id) => steps().findIndex((s) => s.id === id);
  /* One bar per setting, and a bar is the setting.
   *
   * It starts as a kind, a name and a Record button. Recording reads the state
   * off the instrument and the bar becomes that record — the fields give way
   * to what was captured, in place. Nothing jumps to a list somewhere else,
   * and nothing is typed in twice, so nothing can disagree with the
   * instrument.
   *
   * Choosing a kind in the last open bar opens a fresh one beneath, and there
   * is always exactly one open bar waiting at the bottom.
   */
  const recordedBars = () => state.bars.filter((b) => b.state);

  /* Recording is the work, so there is nothing left to confirm: the step is
     done once a setting exists, and undone again if the last one is forgotten.
     The rail stays honest about what may follow without asking for a press
     that would only repeat what the operator already did. */
  function settingsChanged() {
    const n = recordedBars().length;
    if (n) {
      state.done.add("optics");
      state.notes.optics = `${n} preset${n === 1 ? "" : "s"} recorded`;
    } else {
      state.done.delete("optics");
      delete state.notes.optics;
    }
  }

  const ensureOpenBar = () => {
    if (!state.bars.some((b) => !b.state)) {
      state.bars.push({ type: SETTING_TYPES[0].key, name: "" });
    }
  };

  /* Each recorded setting is its own box, because each is an object the run
     holds. The bar that takes the next one is not: it is the act of taking,
     drawn as the field it is being taken into, opening on the same edge the
     boxes stand on. */
  function renderOpticsCard(host) {
    /* No title and no count. The rail says which step this is, the boxes are
       the settings, and counting things the operator can see is the panel
       talking about itself instead of showing the run. */

    /* The open bar sits above what has been recorded: it is the thing you are
       doing, and it should not walk further down the panel each time a setting
       is taken. */
    /* The open bar is a group of one, so its label sits the same distance off
       its box as every other label does. */
    const open = state.bars.find((b) => !b.state);
    if (open) {
      const group = document.createElement("div");
      group.className = "setting-group";

      const label = document.createElement("div");
      label.className = "group-label";
      label.textContent = "Record optical configuration";
      group.append(label);

      const box = document.createElement("div");
      box.className = "setting-box open";
      box.append(renderOpenBar(open));
      group.append(box);
      host.append(group);
    }

    /* Recorded settings are grouped by kind, in the order the kinds are
       declared: every acquisition together, every autofocus together. A run
       is read as "what can it image with" and "how does it focus", not as the
       order somebody happened to press record in. */
    for (const type of SETTING_TYPES) {
      const mine = state.bars.filter((b) => b.state && b.type === type.key);
      if (!mine.length) continue;

      const group = document.createElement("div");
      group.className = "setting-group";

      /* The kind names the group, once, instead of being repeated on every row
         inside it. The column it used to occupy stays empty so a recorded
         setting still lines up with the open bar's selector. */
      const label = document.createElement("div");
      label.className = "group-label";
      // the selector says the kind; the heading says what kind of thing it is
      label.textContent = `Recorded ${type.label} presets`;
      group.append(label);

      for (const bar of mine) {
        const box = document.createElement("div");
        box.className = "setting-box done";
        box.append(renderRecordedBar(bar));
        group.append(box);
      }
      host.append(group);
    }
  }

  /* The summary is the headline; the detail is what the controller actually
     read. Folded away by default, because a list of presets should stay a
     list — but one click from view, because "trust me" is not a good answer
     when the run depends on it. */
  function renderRecordedBar(bar) {
    const wrap = document.createDocumentFragment();

    const row = document.createElement("div");
    row.className = "rec-row";
    // no kind cell: the group above names it, so the name starts at the left
    row.innerHTML = '<button type="button" class="rec-fold"></button>'
      + '<span class="rec-name"></span><span class="rec-state"></span>'
      + '<button type="button" class="rec-drop">✕</button>';
    row.querySelector(".rec-name").textContent = bar.name;
    row.querySelector(".rec-state").textContent = bar.state;

    const fold = row.querySelector(".rec-fold");
    fold.textContent = "▸";
    fold.title = bar.expanded ? "fold away" : "show everything recorded";
    fold.setAttribute("aria-expanded", String(!!bar.expanded));
    fold.classList.toggle("open", !!bar.expanded);
    fold.addEventListener("click", () => {
      bar.expanded = !bar.expanded;
      renderSetup();
    });

    const drop = row.querySelector(".rec-drop");
    drop.title = "forget this preset";
    drop.disabled = !!state.running;
    drop.addEventListener("click", () => {
      state.bars = state.bars.filter((b) => b !== bar);
      ensureOpenBar();
      settingsChanged();
      scanfieldsSettled();
      renderSetup();
      renderAll();
    });

    wrap.append(row);

    if (bar.expanded && bar.detail) {
      const detail = document.createElement("dl");
      detail.className = "rec-detail";
      for (const [label, value] of bar.detail) {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        detail.append(dt, dd);
      }
      wrap.append(detail);
    }
    return wrap;
  }

  function renderOpenBar(bar) {
    const row = document.createElement("div");
    row.className = "rec-new";

    const kind = document.createElement("select");
    for (const t of SETTING_TYPES) {
      const o = document.createElement("option");
      o.value = t.key;
      /* The kind names a kind; what is being taken is a preset of it. Composed
         here rather than stored that way, because the group heading below says
         "Recorded acquisition presets" off the same label. */
      o.textContent = `${t.label} preset`;
      kind.append(o);
    }
    kind.value = bar.type;
    kind.addEventListener("change", () => {
      bar.type = kind.value;
      ensureOpenBar();
      renderSetup();
    });

    const name = document.createElement("input");
    name.type = "text";
    name.placeholder = "Name of this preset";
    name.value = bar.name;
    name.setAttribute("aria-label", "name for this preset");

    const go = document.createElement("button");
    go.className = "run";
    go.type = "button";
    go.textContent = "Record";

    const why = document.createElement("div");
    why.className = "session-hint";

    const capitalised = (v) => (v ? v[0].toUpperCase() + v.slice(1) : v);
    const taken = (value) =>
      state.bars.some((b) => b !== bar
        && b.name.trim().toLowerCase() === value.toLowerCase());

    // typing must not rebuild the row, or the field loses focus every keystroke
    const check = () => {
      bar.name = name.value;
      const value = name.value.trim();
      const clash = value && taken(value);
      go.disabled = !value || clash || !!state.running;
      why.textContent = clash ? "that name is already used" : "";
      why.classList.toggle("bad", !!clash);
    };
    name.addEventListener("input", check);
    check();

    go.addEventListener("click", () => {
      const nth = recordedBars().filter((b) => b.type === bar.type).length;
      go.disabled = true;
      go.textContent = "reading…";
      // a controller round-trip, not an instant assignment
      setTimeout(() => {
        const reading = sampleReading(bar.type, nth);
        bar.name = capitalised(name.value.trim());
        bar.state = reading.summary;
        bar.detail = reading.detail;
        bar.frameUm = reading.frameUm;
        ensureOpenBar();
        settingsChanged();
        scanfieldsSettled();
        renderSetup();
        renderAll();
      }, 480);
    });

    /* The name leads, the way it leads a recorded row. It is the thing being
       filled in; the kind is a choice standing beside it. */
    row.append(name, kind, go, why);
    return row;
  }

  /* The carrier is what the canvas is drawing, so its controls sit beside the
     drawing and stay there. Not a menu that appears for one step: the frame is
     a property of the run, readable whenever the canvas is, and only editable
     until it has been applied.

     Mounted once per lock state rather than on every render, because the widget
     keeps its own and rebuilding it would throw away the number being typed. */
  /* The carrier is settled by being configured, so there is nothing to press:
     it always holds a valid one, and the operator either accepts what is there
     or edits it. Standing on the step is the whole of it. Completing is not
     advancing — the rail still waits for a click to move on.

     It stays editable until something has been done inside the frame, at which
     point changing it would invalidate what was done. */
  function carrierSettled() {
    if (indexOfStep("carrier") < 0) return;
    state.done.add("carrier");
    state.notes.carrier = describeCarrier(state.carrier);
  }

  const carrierLocked = () => {
    const i = indexOfStep("carrier");
    return !!state.running || steps().slice(i + 1).some((s) => state.done.has(s.id));
  };

  /* The channel belongs to the step standing in it.

     Both steps that own one are about the canvas rather than beside it — the
     carrier is what the canvas is drawing, the scan fields are what is being
     drawn on it — so each docks its controls in the same column and the
     heading says which. One column, because two would take the picture's width
     to show controls for a step nobody is on. */
  const SIDE_WIDGETS = { carrier: carrierWidget, scanfields: scanfieldsWidget };

  const sideWidget = () => SIDE_WIDGETS[step(state.activeIdx).id] ?? null;

  const scanfieldsLocked = () => {
    const i = indexOfStep("scanfields");
    return !!state.running || (i >= 0 && steps().slice(i + 1).some((s) => state.done.has(s.id)));
  };

  function renderSide(show) {
    const host = el("canvas-side");
    const widget = show === "canvas" ? sideWidget() : null;
    host.hidden = !widget;
    const locked = widget?.id === "carrier" ? carrierLocked() : scanfieldsLocked();
    const key = widget && `${widget.id}:${locked}`;
    if (state.sideMounted === key) return;
    state.sideMounted = key;
    state.editor?.destroy?.();
    state.editor = null;
    host.textContent = "";
    if (!widget) return;

    if (widget.id === "carrier") {
      widget.render(host, {
        config: state.carrier,
        locked,
        onChange: (next) => {
          state.carrier = next;
          state.notes.carrier = describeCarrier(next);
          // the tissue is spread over the plate, so a different plate is a
          // different sample even before the plan moves
          rebuildSample();
          view.fitted = false;
          drawStage();
          renderRail();
        },
      });
      return;
    }

    state.editor = widget.render(host, {
      fields: state.fields,
      carrier: state.carrier,
      presets: recordedPresets(),
      locked,
      onChange: (next) => {
        state.fields = next;
        scanfieldsSettled();
        drawStage();
        renderRail();
      },
    });
  }

  /* What a scan field can be taken with: the presets this run recorded, in the
     order they were taken. A field names one rather than carrying a frame of
     its own, so changing what a preset is changes what the plan covers. */
  const recordedPresets = () => recordedBars().map((b, i) => ({
    id: `preset${i}`,
    kind: b.type,
    name: b.name,
    summary: b.state,
    frameUm: b.frameUm,
  }));

  /* Drawing fields is the work, the way recording and configuring are: the
     step is done once there is something to scan, and undone again if the last
     field is removed. */
  function scanfieldsSettled() {
    rebuildSample();
    if (indexOfStep("scanfields") < 0) return;
    const positions = state.plan.length;
    if (positions) {
      state.done.add("scanfields");
      state.notes.scanfields = `${positions} position${positions === 1 ? "" : "s"}`;
    } else {
      state.done.delete("scanfields");
      delete state.notes.scanfields;
    }
  }

  /* A card belongs to its step and shows while you are standing on it —
     the same rule the rows follow. Click back on Connect and the session and
     its checks are there again; step away and the panel is about the step you
     moved to. */
  const SETUP_CARDS = {
    connect: renderSessionCard,
    optics: renderOpticsCard,
  };

  function renderSetup(which = step(state.activeIdx).id) {
    const host = el("setup-list");
    host.textContent = "";
    const present = new Set(steps().map((s) => s.id));

    const activeId = step(state.activeIdx).id;
    if (SETUP_CARDS[which]) SETUP_CARDS[which](host);

    /* Only what the run has established, plus whatever is being done now. The
       rail already lists what is still ahead; repeating it here as a column of
       "not set" would make the panel a second, worse copy of it. */
    for (const row of SETUP_ROWS) {
      if (!present.has(row.step)) continue;
      if (!state.done.has(row.step) && row.step !== activeId) continue;
      const done = state.done.has(row.step);
      const value = state.notes[row.step];

      const el_ = document.createElement("div");
      el_.className = "setup-row" + (done ? "" : " pending");
      el_.innerHTML =
        `<span class="setup-mark">${done ? "✓" : "·"}</span>` +
        '<span class="setup-name"></span><span class="setup-value"></span>';
      el_.querySelector(".setup-name").textContent = row.name;
      el_.querySelector(".setup-value").textContent = done && value ? value : row.waiting;
      host.append(el_);
    }

  }

  /* Always drawn, even for one. A tab used to say "Setup" for every step and
     was worth hiding; it says what it holds now — Optical configuration, the
     presets that were loaded — and naming what you are looking at is worth a
     line whether or not there is a second one to switch to. */
  function renderTabs() {
    const host = el("tabs");
    host.textContent = "";

    for (const key of state.tabs) {
      const meta = PANEL_META[key];
      const b = document.createElement("button");
      b.className = "tab"; b.type = "button"; b.role = "tab";
      b.setAttribute("aria-selected", String(state.tab === key));
      b.append(document.createTextNode(meta.label));

      if (key === "analysis" && state.gated.size) {
        const c = document.createElement("span");
        c.className = "count"; c.textContent = String(state.gated.size);
        b.append(c);
      }
      if (key === "gallery" && state.acquired.length) {
        const c = document.createElement("span");
        c.className = "count"; c.textContent = String(state.acquired.length);
        b.append(c);
      }
      b.addEventListener("click", () => { state.tab = key; renderPanels(); renderTabs(); });
      host.append(b);
    }

    /* The channel beside the canvas is named where it sits, at the right end
       of the same row and over the column it heads. Not a tab: it is not an
       alternative to the canvas, it is the controls for what the canvas is
       showing — so it says whose controls those are rather than offering a
       switch. */
    const owner = shownPanel() === "canvas" ? sideWidget() : null;
    if (owner) {
      const side = document.createElement("span");
      side.className = "side-tab";
      /* The name is its own element: it carries the rule under it, so that
         rule is as wide as the word the way a tab's is, rather than as wide
         as the channel this stands over. */
      const label = document.createElement("span");
      label.textContent = owner.label;
      side.append(label);
      host.append(side);
    }
  }

  const shownPanel = () => (state.tabs.includes(state.tab) ? state.tab : state.tabs[0]);

  function renderPanels() {
    const show = shownPanel();
    if (!show) return;
    /* By element, not by key: the setup steps share one, so asking each key in
       turn would switch it on for its own and straight back off for the next. */
    const shown = PANEL_META[show].panel;
    for (const id of new Set(Object.values(PANEL_META).map((m) => m.panel))) {
      el(id).classList.toggle("on", id === shown);
    }
    renderSide(show);
    renderStepAction(show);
    if (SETUP_CARDS[show]) renderSetup(show);
    if (show === "canvas") { sizeCanvas(stageCv); drawStage(); }
    if (show === "detect") { renderDetectToolbar(); drawTilePreview(); }
    if (show === "focus") { renderFocusToolbar(); drawFocus(); drawTrace(); }
    if (show === "analysis") { sizeCanvas(scatterCv); drawScatter(); }
  }

  function renderAll() {
    /* The step being looked at decides the tab set on its own, so this is the
       one place that has to agree with it — recomputed rather than trusted,
       and the selection kept only while it still names a tab that is there. */
    state.tabs = panelsFor(state.activeIdx);
    if (!state.tabs.includes(state.tab)) state.tab = state.tabs[0];

    renderRail();
    renderActionBar();
    renderTabs();
    renderPanels();
  }

  /* ============================================================
     shared canvas plumbing
     ============================================================ */
  function sizeCanvas(cv) {
    const host = cv.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return false;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cv.cssW = w; cv.cssH = h;
    return true;
  }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /* ============================================================
     the stage viewer — one projection, layers on top
     ============================================================ */
  const stageCv = el("stage-canvas");
  const stageTip = el("stage-tip");
  const view = { scale: 0.03, tx: 0, ty: 0, fitted: false };

  /* The canvas is the stage, so it is what the view frames — not the carrier
     inside it and not the scan inside that. Everything else is drawn in the
     same coordinates and lands where it belongs. */
  const STAGE_UM = [STAGE_LIMITS_MM.width * 1000, STAGE_LIMITS_MM.height * 1000];

  /* Where the carrier's own zero sits on the stage.
   *
   * Centred in the travel, because that is where a holder puts a plate and it
   * is the only placement that can be worked out rather than measured. It is a
   * default and not a fact: the real offset comes from calibrating against a
   * plate actually on the stage, and this is the one line that answer replaces.
   *
   * Everything the run produces is placed from this point too, so the carrier
   * and what was imaged inside it move together instead of drifting apart the
   * moment either of them moves. */
  function carrierOriginUm() {
    const [w, h] = carrierWidget.extentUm(state.carrier);
    return [(STAGE_UM[0] - w) / 2, (STAGE_UM[1] - h) / 2];
  }

  function fitView() {
    const w = stageCv.cssW || 800, h = stageCv.cssH || 600;
    const pad = 26;
    const [fw, fh] = STAGE_UM;
    const s = Math.min((w - 2 * pad) / fw, (h - 2 * pad) / fh);
    view.scale = s;
    view.tx = (w - fw * s) / 2;
    view.ty = (h - fh * s) / 2;
    view.fitted = true;
  }

  /* Where the stage ends. Drawn first and faintly: it is the edge of what any
     of this can reach, which is context for everything else rather than a
     thing in its own right. */
  function drawStageLimits(ctx) {
    const [x, y] = toScreen(0, 0);
    ctx.save();
    ctx.strokeStyle = css("--line-strong");
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, STAGE_UM[0] * view.scale, STAGE_UM[1] * view.scale);
    ctx.restore();
  }

  const toScreen = (x, y) => [x * view.scale + view.tx, y * view.scale + view.ty];
  const toWorld = (px, py) => [(px - view.tx) / view.scale, (py - view.ty) / view.scale];

  function tileTexture(ctx, tile, place) {
    const [sx, sy] = place(tile.x - tile.frameUm / 2, tile.y - tile.frameUm / 2);
    const sz = tile.frameUm * view.scale;

    // tile ground with a gentle per-tile vignette — the flat-field seam
    // an operator actually sees in a stitched overview
    const g = ctx.createRadialGradient(sx + sz / 2, sy + sz / 2, sz * 0.1, sx + sz / 2, sy + sz / 2, sz * 0.75);
    g.addColorStop(0, "#0d1a24");
    g.addColorStop(1, "#05090e");
    ctx.fillStyle = g;
    ctx.fillRect(sx, sy, sz + 0.6, sz + 0.6);
  }

  function drawStage() {
    if (!sizeCanvas(stageCv)) return;
    if (!view.fitted) fitView();
    const ctx = stageCv.getContext("2d");
    const w = stageCv.cssW, h = stageCv.cssH;

    /* The stage is the page's own surface — empty travel, nothing in it. What
       the carrier declares sits a shade off that, so the areas a sample can be
       in read as the only part of the stage that is anything. */
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, 0, w, h);

    drawStageLimits(ctx);

    /* One projection for everything that sits in the carrier: the carrier
       itself and every tile, cell and target the run put inside it. Handed
       down rather than reached for, so where the carrier stands is decided in
       one place and nothing can be drawn against a different answer. */
    const [ox, oy] = carrierOriginUm();
    const place = (x, y) => toScreen(x + ox, y + oy);

    /* Grey, not the accent: the carrier is the room the run happens in, not a
       thing the run produced. Dark enough to read against the stage behind it,
       which is grey too. */
    carrierWidget.drawOn(ctx, {
      config: state.carrier, toScreen: place, scale: view.scale,
      colour: css("--ink-3"), fill: css("--surface-3"),
    });

    const showTiles = el("lay-tiles").checked;
    const showCells = el("lay-cells").checked;
    const showTargets = el("lay-targets").checked;
    const ch0 = el("ch-0").checked, ch1 = el("ch-1").checked;

    // ---- tiles, in the order the scan writes them
    const shown = Math.max(state.tilesShown, 0);
    if (showTiles && shown > 0) {
      ctx.save();
      const done = state.plan.slice(0, shown);
      for (const t of done) tileTexture(ctx, t, place);
      /* Tissue is drawn inside the tiles that have been taken, because an
         image is the only way the run knows it is there. */
      ctx.globalCompositeOperation = "lighter";
      for (const t of done) {
        const d = density(t.x, t.y);
        if (d < 0.02) continue;
        const [bx, by] = place(t.x, t.y);
        const br = (t.frameUm * 0.75) * view.scale;
        const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        if (ch0) g.addColorStop(0, `rgba(34,211,238,${0.34 * d})`);
        g.addColorStop(0.55, ch1 ? `rgba(245,158,11,${0.16 * d})` : `rgba(34,211,238,${0.12 * d})`);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }

    // ---- scan frontier: the tile the stage is standing on
    if (state.running === "scan" && showTiles && state.plan[shown]) {
      const t = state.plan[shown];
      const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      ctx.strokeStyle = css("--accent");
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(fx, fy, t.frameUm * view.scale, t.frameUm * view.scale);
      ctx.setLineDash([]);
    }

    /* ---- sample bounds: the edge of what has been imaged, so it exists once
       something has been. Drawn from the first tile it was a second square
       sitting in the plate's corner before any of this had happened, which
       says the run has a sample somewhere it does not yet have one. */
    if (shown > 0 && sample.bounds) {
      const b = sample.bounds;
      const [bx, by] = place(b.xMin, b.yMin);
      ctx.strokeStyle = css("--line-strong");
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, (b.xMax - b.xMin) * view.scale, (b.yMax - b.yMin) * view.scale);
    }

    // ---- cells
    if (showCells && state.cellsShown) {
      const ctxRad = Math.max(1.1, 1.4 * Math.sqrt(view.scale / 0.03));
      ctx.fillStyle = css("--mark-context");
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      for (const c of sample.cells) {
        if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
        const [x, y] = place(c.x, c.y);
        if (x < -8 || y < -8 || x > w + 8 || y > h + 8) continue;
        ctx.moveTo(x + ctxRad, y);
        ctx.arc(x, y, ctxRad, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.globalAlpha = 1;

      // gated cells — ringed, so identity is not carried by colour alone
      const gr = Math.max(3, 4.2 * Math.sqrt(view.scale / 0.03));
      for (const c of sample.cells) {
        if (!state.gated.has(c.id)) continue;
        const [x, y] = place(c.x, c.y);
        if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
        ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
      }
    }

    // ---- acquired targets
    if (showTargets && state.acquired.length) {
      for (const id of state.acquired) {
        const c = sample.cells[id - 1];
        const [x, y] = place(c.x, c.y);
        const rr = Math.max(7, 9 * Math.sqrt(view.scale / 0.03));
        ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
        ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2.2; ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = "#16a34a"; ctx.fill();
      }
    }

    /* The plan, under whatever the run has since produced: it is what the run
       was told to do, so it stays readable once the tiles start landing on top
       of it. Dimmed once the scan has begun, because by then the images are
       the answer and this is only the question. */
    scanfieldsWidget.drawOn(ctx, {
      fields: state.fields, presets: recordedPresets(),
      toScreen: place, scale: view.scale, dim: shown > 0,
    });

    // and the editing itself only while somebody is standing in it
    if (sideWidget()?.id === "scanfields") {
      state.editor?.drawChrome(ctx, { toScreen: place, scale: view.scale });
    }

    drawScaleBar(ctx, w, h);
  }

  /* Carrier coordinates for the editor: it places fields inside the carrier,
     so it is handed where the pointer is in that frame rather than where it is
     on the stage. */
  function toCarrier(px, py) {
    const [wx, wy] = toWorld(px, py);
    const [ox, oy] = carrierOriginUm();
    return { x: wx - ox, y: wy - oy };
  }

  /* The editor sees the pointer first and says whether it took it. Only what
     it turns down pans or picks, so drawing a region does not drag the stage
     out from under the shape being drawn. */
  function editorTook(kind, e) {
    if (sideWidget()?.id !== "scanfields" || !state.editor) return false;
    const { x, y } = toCarrier(e.offsetX, e.offsetY);
    const took = state.editor.pointer(kind, { x, y, shift: e.shiftKey, scale: view.scale });
    if (took) drawStage();
    /* Only a true means the editor claimed the event. Anything else it answers
       is "the picture changed" — the pointer moved over a field — and the
       canvas still gets to say where the stage is under the cursor. */
    return took === true;
  }

  function drawScaleBar(ctx, w, h, scale = view.scale) {
    const targetPx = 130;
    const raw = targetPx / scale;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const nice = [1, 2, 5, 10].map((m) => m * pow).reduce((a, b) =>
      Math.abs(b - raw) < Math.abs(a - raw) ? b : a);
    const px = nice * scale;
    const x = w - px - 20, y = h - 24;

    ctx.strokeStyle = css("--ink-2");
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, y - 5); ctx.lineTo(x, y); ctx.lineTo(x + px, y); ctx.lineTo(x + px, y - 5);
    ctx.stroke();
    ctx.fillStyle = css("--ink-2");
    ctx.font = '11.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "center";
    ctx.fillText(nice >= 1000 ? `${nice / 1000} mm` : `${nice} µm`, x + px / 2, y - 9);
    ctx.textAlign = "left";
  }

  // ---- stage interaction: pan, zoom, pick focus points, hover a cell
  let dragging = false, dragMoved = false, lastX = 0, lastY = 0;

  stageCv.addEventListener("pointerdown", (e) => {
    if (editorTook("down", e)) { stageCv.setPointerCapture(e.pointerId); return; }
    dragging = true; dragMoved = false;
    lastX = e.offsetX; lastY = e.offsetY;
    stageCv.setPointerCapture(e.pointerId);
    stageCv.classList.add("dragging");
  });

  stageCv.addEventListener("pointermove", (e) => {
    if (!dragging && editorTook("move", e)) return;
    if (dragging) {
      const dx = e.offsetX - lastX, dy = e.offsetY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
      view.tx += dx; view.ty += dy;
      lastX = e.offsetX; lastY = e.offsetY;
      drawStage();
      return;
    }
    /* The readout is where the stage is, because the canvas is the stage. The
       hit test is not: a cell knows where it is in the carrier, so the pointer
       is put into the carrier's coordinates to meet it. */
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    el("stage-readout").textContent =
      `x ${wx.toFixed(0)} µm · y ${wy.toFixed(0)} µm · ${(view.scale * 1000).toFixed(1)} px/mm`;

    // hover the nearest visible cell
    let hit = null;
    if (state.cellsShown && el("lay-cells").checked) {
      const [ox, oy] = carrierOriginUm();
      let best = 12 / view.scale;
      for (const c of sample.cells) {
        if (!state.detected.has(c.id)) continue;
        const d = Math.hypot(c.x + ox - wx, c.y + oy - wy);
        if (d < best) { best = d; hit = c; }
      }
    }
    if (hit) {
      stageTip.classList.add("on");
      stageTip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br><b>int</b> ${hit.intensity.toFixed(2)}`;
      const left = Math.min(e.offsetX + 14, stageCv.cssW - 130);
      stageTip.style.left = `${left}px`;
      stageTip.style.top = `${Math.max(6, e.offsetY - 52)}px`;
    } else {
      stageTip.classList.remove("on");
    }
  });

  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    stageCv.classList.remove("dragging");
    if (e && stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
  };
  stageCv.addEventListener("pointerup", (e) => {
    if (editorTook("up", e)) {
      if (stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
      renderRail();
      return;
    }
    endDrag(e);
  });
  stageCv.addEventListener("pointerleave", (e) => {
    editorTook("leave", e);
    endDrag(e);
    stageTip.classList.remove("on");
  });

  stageCv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    const f = Math.exp(-e.deltaY * 0.0016);
    view.scale = Math.max(0.004, Math.min(3, view.scale * f));
    view.tx = e.offsetX - wx * view.scale;
    view.ty = e.offsetY - wy * view.scale;
    drawStage();
  }, { passive: false });

  el("fit-btn").addEventListener("click", () => { fitView(); drawStage(); });
  for (const id of ["lay-tiles", "lay-cells", "lay-targets", "ch-0", "ch-1"]) {
    el(id).addEventListener("change", drawStage);
  }

  /* ============================================================
     the focus strategy panel — positions come from the microscope
     software; the operator drops focus points onto them
     ============================================================ */
  const focusCv = el("focus-canvas");
  const focusTip = el("focus-tip");

  // ground truth the "microscope" would measure, so picked points behave
  /* The sample is not flat and not level: a gentle tilt across the plate. Over
     the carrier's own extent, so it is the same surface wherever the plan
     decides to look at it. */
  const carrierSpan = () => carrierWidget.extentUm(state.carrier);
  const trueZ = (x, y) => {
    const [w, h] = carrierSpan();
    return -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);
  };

  const STRATEGIES = {
    plane: {
      label: "Fit from points",
      blurb: "Measure a few positions and fit a surface. Four or more non-collinear points buy a "
        + "thin-plate spline; fewer buy a plane; a flat sample buys a constant.",
      needs: (f) => f.points.length >= 3,
      unmet: "place at least 3 points",
    },
    fixed: {
      label: "Fixed Z",
      blurb: "One focus height for the whole sample. Fastest, flattest assumption.",
      needs: () => true,
    },
    auto: {
      label: "Per-tile autofocus",
      blurb: "Autofocus at every position. Most robust, and the slowest by far.",
      needs: () => true,
    },
    reuse: {
      label: "Reuse surface",
      blurb: "Take the surface a previous run measured on this holder.",
      needs: (f) => !!f.reuse,
    },
  };

  function focusSurface() {
    const f = state.focus;
    if (f.strategy === "fixed") return { kind: "affine", a: 0, b: 0, c: f.zFixed };
    if (f.strategy === "reuse") return { kind: "affine", ...PREVIOUS_SURFACES[f.reuse].plane };
    return f.surface;
  }

  /* Model by geometry, the way workflow/_focus_surface.py does it: a spline
     needs four non-collinear points before it means anything, so fewer points
     buy a plane, and a flat sample buys a constant. */
  const FLAT_TOLERANCE_UM = 0.1;
  const SPLINE_SMOOTHING = 0.1;

  function surfaceZ(m, x, y) {
    if (!m) return 0;
    if (m.kind === "affine") {
      const [w, h] = carrierSpan();
      return m.a * (x / w - 0.5) + m.b * (y / h - 0.5) + m.c;
    }
    if (m.kind === "constant") return m.c;
    if (m.kind === "plane") return m.c0 * (x - m.x0) + m.c1 * (y - m.y0) + m.c2;
    const u = (x - m.x0) / m.scale, v = (y - m.y0) / m.scale;
    let z = m.a0 + m.a1 * u + m.a2 * v;
    for (let i = 0; i < m.pts.length; i++) {
      const du = u - m.pts[i].u, dv = v - m.pts[i].v;
      z += m.w[i] * kernelU(Math.sqrt(du * du + dv * dv));
    }
    return z;
  }

  // the thin-plate basis: r² ln r, which is what minimises bending energy
  const kernelU = (r) => (r < 1e-9 ? 0 : r * r * Math.log(r));

  // dense gaussian elimination with partial pivoting — n stays tiny here
  function solve(A, b) {
    const n = b.length;
    const M = A.map((row, i) => [...row, b[i]]);
    for (let i = 0; i < n; i++) {
      let piv = i;
      for (let k = i + 1; k < n; k++) if (Math.abs(M[k][i]) > Math.abs(M[piv][i])) piv = k;
      if (Math.abs(M[piv][i]) < 1e-12) return null;
      [M[i], M[piv]] = [M[piv], M[i]];
      for (let k = i + 1; k < n; k++) {
        const f = M[k][i] / M[i][i];
        for (let j = i; j <= n; j++) M[k][j] -= f * M[i][j];
      }
    }
    const out = new Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) {
      let acc = M[i][n];
      for (let j = i + 1; j < n; j++) acc -= M[i][j] * out[j];
      out[i] = acc / M[i][i];
    }
    return out;
  }

  const ptp = (a) => Math.max(...a) - Math.min(...a);

  // are the points spread in two dimensions, or strung out along one line?
  function nonCollinear(xc, yc) {
    let sxx = 0, sxy = 0, syy = 0;
    for (let i = 0; i < xc.length; i++) { sxx += xc[i] * xc[i]; sxy += xc[i] * yc[i]; syy += yc[i] * yc[i]; }
    const tr = sxx + syy, det = sxx * syy - sxy * sxy;
    if (tr <= 0) return false;
    const disc = Math.max(0, tr * tr / 4 - det);
    const small = tr / 2 - Math.sqrt(disc);
    return small > 1e-9 * tr;
  }

  function fitSurface(points) {
    const n = points.length;
    if (!n) return null;
    const xs = points.map((p) => p.x), ys = points.map((p) => p.y), zs = points.map((p) => p.z);
    const x0 = xs.reduce((a, b) => a + b, 0) / n;
    const y0 = ys.reduce((a, b) => a + b, 0) / n;
    const xc = xs.map((x) => x - x0), yc = ys.map((y) => y - y0);

    if (ptp(zs) < FLAT_TOLERANCE_UM || n === 1) {
      return { kind: "constant", model: "constant", c: zs.reduce((a, b) => a + b, 0) / n };
    }

    if (n >= 4 && nonCollinear(xc, yc)) {
      const scale = Math.max(ptp(xc), ptp(yc)) || 1;
      const u = xc.map((x) => x / scale), v = yc.map((y) => y / scale);
      const N = n + 3;
      const A = Array.from({ length: N }, () => new Array(N).fill(0));
      const b = new Array(N).fill(0);
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
          const du = u[i] - u[j], dv = v[i] - v[j];
          // smoothing on the diagonal: the spline passes NEAR the points, not
          // exactly through them, which is what leaves a residual to read
          A[i][j] = i === j ? SPLINE_SMOOTHING : kernelU(Math.sqrt(du * du + dv * dv));
        }
        A[i][n] = 1; A[i][n + 1] = u[i]; A[i][n + 2] = v[i];
        A[n][i] = 1; A[n + 1][i] = u[i]; A[n + 2][i] = v[i];
        b[i] = zs[i];
      }
      const sol = solve(A, b);
      if (sol) {
        return {
          kind: "spline", model: "spline", x0, y0, scale,
          pts: u.map((uu, i) => ({ u: uu, v: v[i] })),
          w: sol.slice(0, n), a0: sol[n], a1: sol[n + 1], a2: sol[n + 2],
        };
      }
    }

    // least-squares plane through centred coordinates
    const design = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    const rhs = [0, 0, 0];
    for (let i = 0; i < n; i++) {
      const row = [xc[i], yc[i], 1];
      for (let a = 0; a < 3; a++) {
        for (let b2 = 0; b2 < 3; b2++) design[a][b2] += row[a] * row[b2];
        rhs[a] += row[a] * zs[i];
      }
    }
    // Points strung out along one line leave the normal equations singular in
    // the across-line direction. lstsq answers that with a minimum-norm fit —
    // a plane that tilts along the line and stays flat across it — so a ridge
    // stands in for the same thing rather than collapsing to a constant.
    let c = solve(design, rhs);
    if (!c) {
      const ridge = 1e-9 * (design[0][0] + design[1][1] + design[2][2]) || 1e-12;
      const damped = design.map((row, i) => row.map((v, j) => (i === j ? v + ridge : v)));
      c = solve(damped, rhs);
    }
    if (!c) return { kind: "constant", model: "constant", c: zs.reduce((a, b) => a + b, 0) / n };
    return { kind: "plane", model: "plane", x0, y0, c0: c[0], c1: c[1], c2: c[2] };
  }

  /* How far each measured point sits from the fitted surface. One large
     residual is the tell that a single autofocus landed on dust and is
     quietly bending everything else — the same reading as residuals_um(). */
  function residualsUm(surface, points) {
    return points.map((p) => p.z - surfaceZ(surface, p.x, p.y));
  }

  // viridis — multi-hue but monotone in lightness, which is the property that
  // matters: it stays readable in greyscale and for every kind of colour vision
  const VIRIDIS = [
    [68, 1, 84], [72, 36, 117], [65, 68, 135], [53, 95, 141], [42, 120, 142],
    [33, 145, 140], [34, 168, 132], [68, 190, 112], [122, 209, 81], [189, 223, 38], [253, 231, 37],
  ];

  function viridis(t) {
    const u = Math.max(0, Math.min(0.99999, t)) * (VIRIDIS.length - 1);
    const i = Math.floor(u), f = u - i;
    const a = VIRIDIS[i], b = VIRIDIS[i + 1];
    return [
      Math.round(a[0] + (b[0] - a[0]) * f),
      Math.round(a[1] + (b[1] - a[1]) * f),
      Math.round(a[2] + (b[2] - a[2]) * f),
    ];
  }

  const zColor = (t) => { const c = viridis(t); return `rgb(${c[0]},${c[1]},${c[2]})`; };

  /* The surface is continuous, so it is painted as a continuous field: one
     small offscreen buffer sampled across the sample bounds, then scaled up
     with smoothing. Nothing about z is per-tile — only the positions are. */
  /* Its own camera. Sharing one with the canvas was tempting, but the two
     panels are different sizes, so a fit computed against one of them puts
     the sample off the edge of the other and clicks land nowhere. */
  const fview = { scale: 0.03, tx: 0, ty: 0, fitted: false };

  function fitFocusView() {
    const w = focusCv.cssW || 800, h = focusCv.cssH || 600;
    const pad = 26;
    const b = planBox();
    const bw = b.xMax - b.xMin, bh = b.yMax - b.yMin;
    const s = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
    fview.scale = s;
    fview.tx = (w - bw * s) / 2 - b.xMin * s;
    fview.ty = (h - bh * s) / 2 - b.yMin * s;
    fview.fitted = true;
  }

  const fToScreen = (x, y) => [x * fview.scale + fview.tx, y * fview.scale + fview.ty];
  const fToWorld = (px, py) => [(px - fview.tx) / fview.scale, (py - fview.ty) / fview.scale];

  /* What the focus panel frames: the positions the run is going to visit, or
     the whole carrier while there are none. */
  function planBox() {
    if (sample.bounds) return sample.bounds;
    const [w, h] = carrierSpan();
    return { xMin: 0, yMin: 0, xMax: w, yMax: h };
  }

  /* The position under the pointer, if it is over one. A list of positions has
     no rows and columns to index into, so it is asked by distance. */
  function nearestPosition(x, y) {
    let best = null;
    state.plan.forEach((t, i) => {
      const half = t.frameUm / 2;
      if (x < t.x - half || x > t.x + half || y < t.y - half || y > t.y + half) return;
      const d = Math.hypot(t.x - x, t.y - y);
      if (!best || d < best.d) best = { t, i, d };
    });
    return best;
  }

  const FIELD_W = 148, FIELD_H = 108;
  const fieldCv = document.createElement("canvas");
  fieldCv.width = FIELD_W; fieldCv.height = FIELD_H;

  function paintSurface(surf, zLo, zHi, box) {
    const fctx = fieldCv.getContext("2d");
    const img = fctx.createImageData(FIELD_W, FIELD_H);
    const span = zHi - zLo || 1;
    let k = 0;
    for (let j = 0; j < FIELD_H; j++) {
      const y = box.yMin + ((j + 0.5) / FIELD_H) * (box.yMax - box.yMin);
      for (let i = 0; i < FIELD_W; i++) {
        const x = box.xMin + ((i + 0.5) / FIELD_W) * (box.xMax - box.xMin);
        const c = viridis((surfaceZ(surf, x, y) - zLo) / span);
        img.data[k++] = c[0]; img.data[k++] = c[1]; img.data[k++] = c[2]; img.data[k++] = 255;
      }
    }
    fctx.putImageData(img, 0, 0);
  }

  function drawFocus() {
    if (!sizeCanvas(focusCv)) return;
    if (!fview.fitted) fitFocusView();
    const ctx = focusCv.getContext("2d");
    const w = focusCv.cssW, h = focusCv.cssH;
    const f = state.focus;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, 0, w, h);

    const surf = focusSurface();
    const showSurface = surf && (f.strategy !== "plane" || f.applied);

    // predicted z range across the sample, for the ramp and its legend
    const box = planBox();
    let zLo = 0, zHi = 1;
    if (showSurface) {
      // a spline can bulge between its points, so sample the field rather than
      // trusting the corners the way a plane would let you
      zLo = Infinity; zHi = -Infinity;
      for (let j = 0; j <= 12; j++) {
        for (let i = 0; i <= 16; i++) {
          const z = surfaceZ(surf,
            box.xMin + (i / 16) * (box.xMax - box.xMin),
            box.yMin + (j / 12) * (box.yMax - box.yMin));
          if (z < zLo) zLo = z;
          if (z > zHi) zHi = z;
        }
      }
      if (zHi - zLo < 1) { zLo -= 0.5; zHi += 0.5; }
    }

    // ---- the surface, as one continuous field rather than tile blocks
    if (showSurface) {
      const [sx0, sy0] = fToScreen(box.xMin, box.yMin);
      const sw = (box.xMax - box.xMin) * fview.scale, sh = (box.yMax - box.yMin) * fview.scale;
      paintSurface(surf, zLo, zHi, planBox());
      ctx.save();
      ctx.globalAlpha = 0.82;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(fieldCv, sx0, sy0, sw, sh);
      ctx.restore();
    }

    // ---- the positions, exactly as the software reports them
    /* The positions themselves, as the scan fields laid them out. This panel
       works on the list the run is going to drive, not on a grid of its own. */
    for (const t of state.plan) {
      const [tx, ty] = fToScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const sz = t.frameUm * fview.scale;
      ctx.strokeStyle = showSurface ? "rgba(255,255,255,0.30)" : css("--line-strong");
      ctx.lineWidth = 1;
      if (sz < 2) { ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(tx, ty, 2, 2); continue; }
      ctx.strokeRect(tx + 0.5, ty + 0.5, sz - 1, sz - 1);
    }

    if (f.strategy === "auto") {
      ctx.fillStyle = css("--ink-3");
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.textAlign = "center";
      for (const t of state.plan) {
        const [tx, ty] = fToScreen(t.x, t.y);
        if (t.frameUm * fview.scale > 34) ctx.fillText("AF", tx, ty + 4);
      }
      ctx.textAlign = "left";
    }

    // ---- focus points
    if (f.strategy === "plane") {
      for (const p of f.points) {
        const [x, y] = fToScreen(p.x, p.y);
        ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2);
        if (p.z === null) {
          ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2; ctx.stroke();
        } else {
          ctx.fillStyle = "#0284c7"; ctx.fill();
          ctx.lineWidth = 2; ctx.strokeStyle = css("--screen"); ctx.stroke();
          // the label sits on viridis, which runs dark to bright — so it
          // carries its own contrast instead of trusting the background
          ctx.font = '11px ui-monospace, Consolas, monospace';
          ctx.lineJoin = "round";
          ctx.lineWidth = 3;
          ctx.strokeStyle = "rgba(10, 14, 20, 0.72)";
          ctx.strokeText(`${p.z.toFixed(1)} µm`, x + 10, y + 4);
          ctx.fillStyle = "#ffffff";
          ctx.fillText(`${p.z.toFixed(1)} µm`, x + 10, y + 4);
        }
      }
    }

    // ---- ramp legend
    if (showSurface) {
      // the legend sits ON the field, so it carries its own plate
      const bw = 132, bh = 9, bx = 20, by = h - 26;
      const padL = 8, top = by - 36;
      ctx.fillStyle = css("--screen");
      ctx.globalAlpha = 0.88;
      ctx.fillRect(bx - padL, top, bw + padL * 2, (by + bh + 7) - top);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = css("--line");
      ctx.lineWidth = 1;
      ctx.strokeRect(bx - padL + 0.5, top + 0.5, bw + padL * 2 - 1, (by + bh + 7) - top - 1);

      for (let i = 0; i < bw; i++) {
        ctx.fillStyle = zColor(i / bw);
        ctx.fillRect(bx + i, by, 1.4, bh);
      }
      ctx.strokeStyle = css("--line-strong");
      ctx.strokeRect(bx - 0.5, by - 0.5, bw + 1, bh + 1);

      ctx.fillStyle = css("--ink-3");
      ctx.font = '11.5px system-ui, sans-serif';
      ctx.fillText("predicted focus height", bx, top + 14);
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.fillStyle = css("--ink-2");
      ctx.fillText(`${zLo.toFixed(0)}`, bx, by - 5);
      ctx.textAlign = "right";
      ctx.fillText(`${zHi.toFixed(0)} µm`, bx + bw, by - 5);
      ctx.textAlign = "left";
    }

    drawScaleBar(ctx, w, h, fview.scale);
  }

  // pan / zoom shared with the stage, so the two never disagree about where things are
  let fDrag = false, fMoved = false, fLastX = 0, fLastY = 0;
  focusCv.addEventListener("pointerdown", (e) => {
    fDrag = true; fMoved = false; fLastX = e.offsetX; fLastY = e.offsetY;
    focusCv.setPointerCapture(e.pointerId);
  });
  focusCv.addEventListener("pointermove", (e) => {
    if (fDrag) {
      const dx = e.offsetX - fLastX, dy = e.offsetY - fLastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) fMoved = true;
      fview.tx += dx; fview.ty += dy;
      fLastX = e.offsetX; fLastY = e.offsetY;
      drawFocus();
      return;
    }
    const [wx, wy] = fToWorld(e.offsetX, e.offsetY);
    const near = nearestPosition(wx, wy);
    if (near) {
      const { t, i } = near;
      focusTip.classList.add("on");
      const surf = focusSurface();
      const showSurface = surf && (state.focus.strategy !== "plane" || state.focus.applied);
      focusTip.innerHTML =
        `<b>position</b> ${i + 1} of ${state.plan.length}<br>` +
        `<b>centre</b> ${(t.x / 1000).toFixed(2)}, ${(t.y / 1000).toFixed(2)} mm` +
        (showSurface ? `<br><b>z</b> ${surfaceZ(surf, t.x, t.y).toFixed(1)} µm` : "");
      focusTip.style.left = `${Math.min(e.offsetX + 14, focusCv.cssW - 190)}px`;
      focusTip.style.top = `${Math.max(6, e.offsetY - 62)}px`;
    } else {
      focusTip.classList.remove("on");
    }
  });
  focusCv.addEventListener("pointerup", (e) => {
    if (!fDrag) return;
    fDrag = false;
    focusCv.releasePointerCapture?.(e.pointerId);
    if (fMoved) return;
    const f = state.focus;
    if (f.strategy !== "plane" || f.applied) return;
    const [wx, wy] = fToWorld(e.offsetX, e.offsetY);
    const b = planBox();
    if (wx < b.xMin || wy < b.yMin || wx > b.xMax || wy > b.yMax) return;
    const near = f.points.findIndex((p) => Math.hypot(p.x - wx, p.y - wy) < 9 / fview.scale);
    if (near >= 0) f.points.splice(near, 1);
    else f.points.push({ x: wx, y: wy, z: null });
    drawFocus(); renderFocusToolbar(); renderActionBar();
  });
  focusCv.addEventListener("pointerleave", () => { fDrag = false; focusTip.classList.remove("on"); });
  focusCv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [wx, wy] = fToWorld(e.offsetX, e.offsetY);
    fview.scale = Math.max(0.004, Math.min(3, fview.scale * Math.exp(-e.deltaY * 0.0016)));
    fview.tx = e.offsetX - wx * fview.scale;
    fview.ty = e.offsetY - wy * fview.scale;
    drawFocus();
  }, { passive: false });

  /* ---- the sweep behind one focus point -----------------------------------
     Both metrics score the same stack, differently: Brenner's gradient is
     broad and a little skewed, DCT energy is sharper and more symmetric. They
     are drawn together so the two can be compared. The peak is refined by
     fitting a parabola to the best sample and its two neighbours — which the
     chart draws, so the choice is visible rather than asserted. */
  const METRICS = {
    brenner: { label: "Brenner gradient", short: "Brenner", token: "--m-brenner", width: 9.0, bias: 0.0, skew: 0.16, noise: 0.045 },
    dct: { label: "DCT energy", short: "DCT", token: "--m-dct", width: 6.2, bias: -0.7, skew: 0.03, noise: 0.028 },
  };
  const METRIC_KEYS = Object.keys(METRICS);

  const SWEEP_N = 61, SWEEP_HALF = 34;   // µm either side of the guess
  const MIN_TISSUE_WIDTH = 4.5;          // µm — anything narrower is not cells

  // Some positions have a speck of debris in the field. Debris is a hard edge
  // in ONE plane, so it scores higher than the tissue and over a far narrower
  // range — the classic way an autofocus ends up focused on dust.
  function debrisAt(idx) {
    const r = makeRng(770 + idx * 613);
    if (r() > 0.45) return null;
    return { offset: (r() < 0.5 ? -1 : 1) * (9 + 13 * r()), amp: 1.12 + 0.34 * r(), width: 0.55 + 0.45 * r() };
  }

  function sweep(point, metricKey, idx) {
    const m = METRICS[metricKey];
    const centre = trueZ(point.x, point.y) + m.bias;
    const guess = trueZ(point.x, point.y) - 6 + 12 * (((idx * 37) % 11) / 10);
    const r = makeRng(1000 + idx * 91 + metricKey.length * 17);
    const speck = debrisAt(idx);
    // a coarse metric smears the speck out; a fine one resolves it fully
    const speckGain = { brenner: 1.0, dct: 0.72 }[metricKey];

    const samples = [];
    for (let i = 0; i < SWEEP_N; i++) {
      const z = guess - SWEEP_HALF + (2 * SWEEP_HALF * i) / (SWEEP_N - 1);
      const d = z - centre;
      const core = Math.exp(-(d * d) / (2 * m.width * m.width));
      const tail = m.skew * Math.exp(-(d * d) / (2 * (m.width * 3) * (m.width * 3))) * (d > 0 ? 1 : 0.35);
      let s = core + tail;
      if (speck) {
        const ds = z - (centre + speck.offset);
        const sw = speck.width + m.width * 0.05;
        s += speck.amp * speckGain * Math.exp(-(ds * ds) / (2 * sw * sw));
      }
      samples.push({ z, s: Math.max(0.02, s + m.noise * (r() - 0.5)) });
    }
    return { samples, candidates: findCandidates(samples), hasDebris: !!speck };
  }

  // every local maximum, refined by a parabola through its three samples,
  // with the half-height width that tells tissue from a speck
  function findCandidates(samples) {
    const stepUm = samples[1].z - samples[0].z;
    const floor = Math.min(...samples.map((q) => q.s));
    const out = [];
    for (let i = 1; i < samples.length - 1; i++) {
      if (!(samples[i].s >= samples[i - 1].s && samples[i].s > samples[i + 1].s)) continue;
      const [p0, p1, p2] = [samples[i - 1], samples[i], samples[i + 1]];
      const denom = p0.s - 2 * p1.s + p2.s;
      const shift = Math.abs(denom) < 1e-6 ? 0 : (0.5 * (p0.s - p2.s)) / denom;
      const z = p1.z + shift * stepUm;
      const s = p1.s - 0.25 * (p0.s - p2.s) * shift;
      const half = floor + (s - floor) / 2;
      let lo = p1.z, hi = p1.z;
      for (let k = i; k >= 0 && samples[k].s > half; k--) lo = samples[k].z;
      for (let k = i; k < samples.length && samples[k].s > half; k++) hi = samples[k].z;
      const width = Math.max(stepUm, hi - lo);
      if (s - floor < 0.12) continue;          // noise, not a peak
      out.push({ z, s, width, used: [p0, p1, p2], narrow: width < MIN_TISSUE_WIDTH });
    }
    if (!out.length) {
      let bi = 0;
      samples.forEach((p, i) => { if (p.s > samples[bi].s) bi = i; });
      const p1 = samples[Math.max(1, Math.min(samples.length - 2, bi))];
      out.push({ z: p1.z, s: p1.s, width: stepUm, used: [p1, p1, p1], narrow: false });
    }
    return out;
  }

  /* One rule, not a menu of them: debris is sharp in a single plane, tissue
     stays sharp over microns, so a peak narrower than MIN_TISSUE_WIDTH is not
     a candidate. The rejected ones stay drawn on the trace, and dragging the
     line is how an operator overrules the whole thing. */
  function pickPeak(candidates) {
    const wide = candidates.filter((c) => !c.narrow);
    return (wide.length ? wide : candidates).reduce((a, b) => (b.s > a.s ? b : a));
  }

  function renderPointList() {
    const f = state.focus;
    const host = el("point-list");
    host.textContent = "";

    if (f.strategy !== "plane") {
      const d = document.createElement("div");
      d.className = "none";
      d.textContent = f.strategy === "auto"
        ? "Per-tile autofocus measures every position — no points to place."
        : f.strategy === "fixed"
          ? "A fixed height needs no measured points."
          : "The stored surface already carries its points.";
      host.append(d);
      return;
    }
    if (!f.points.length) {
      const d = document.createElement("div");
      d.className = "none";
      d.textContent = "Click the position map to place focus points. Three or more spread-out points make a plane.";
      host.append(d);
      return;
    }

    f.points.forEach((p, i) => {
      const b = document.createElement("button");
      b.className = "point-row"; b.type = "button";
      b.setAttribute("aria-current", String(i === f.selected));
      const suspect = p.onNarrow || (f.worst === i && Math.abs(p.residual || 0) > 3);
      b.innerHTML =
        `<span class="idx">${i + 1}</span>` +
        `<span>${(p.x / 1000).toFixed(2)}, ${(p.y / 1000).toFixed(2)} mm</span>` +
        (p.residual === undefined || p.residual === null ? ""
          : `<span class="res"${suspect ? ' style="color:var(--bad)"' : ""}>` +
            `${p.residual >= 0 ? "+" : ""}${p.residual.toFixed(1)}</span>`) +
        `<span class="z${p.z === null ? " pending" : ""}"` +
        `${suspect && !p.manual ? ' style="color:var(--bad)"' : ""}>` +
        `${p.z === null ? "—" : (p.manual ? "✎ " : suspect ? "⚠ " : "") + p.z.toFixed(1) + " µm"}</span>`;
      b.addEventListener("click", () => {
        f.selected = i;
        renderPointList(); drawTrace(); drawFocus();
      });
      host.append(b);
    });
  }

  const traceCv = el("trace-canvas");

  function drawTrace() {
    const f = state.focus;
    const has = f.strategy === "plane" && f.applied && f.points.length > f.selected;
    el("trace-empty").classList.toggle("hidden", has);
    el("trace-which").textContent = has ? `point ${f.selected + 1}` : "";
    if (!has || !sizeCanvas(traceCv)) return;

    const ctx = traceCv.getContext("2d");
    const w = traceCv.cssW, h = traceCv.cssH;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--surface-2");
    ctx.fillRect(0, 0, w, h);

    /* Both metrics on one plot. They score the same stack on different
       scales, so each is normalised to its own maximum — the shapes are the
       comparison, not the absolute numbers. */
    const curves = METRIC_KEYS.map((key) => {
      const sw = sweep(f.points[f.selected], key, f.selected);
      const peak = Math.max(...sw.samples.map((q) => q.s)) || 1;
      return { key, sw, norm: sw.samples.map((q) => ({ z: q.z, s: q.s / peak })) };
    });
    const deciding = curves.find((c) => c.key === f.metric) || curves[0];
    const t = deciding.sw;

    const P = { l: 40, r: 14, t: 16, b: 30 };
    const zs = t.samples.map((p) => p.z);
    const zLo = Math.min(...zs), zHi = Math.max(...zs);
    const sHi = 1.16;
    const X = (z) => P.l + ((z - zLo) / (zHi - zLo)) * (w - P.l - P.r);
    const Y = (s) => (h - P.b) - (s / sHi) * (h - P.t - P.b);
    const decidingPeak = Math.max(...t.samples.map((q) => q.s)) || 1;

    // recessive frame
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(P.l, P.t); ctx.lineTo(P.l, h - P.b); ctx.lineTo(w - P.r, h - P.b);
    ctx.stroke();

    ctx.fillStyle = css("--ink-3");
    ctx.font = '10.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "center";
    ctx.fillText(`${zLo.toFixed(0)}`, X(zLo) + 10, h - P.b + 15);
    ctx.fillText(`${zHi.toFixed(0)} µm`, X(zHi) - 16, h - P.b + 15);
    ctx.save();
    ctx.translate(13, (P.t + h - P.b) / 2); ctx.rotate(-Math.PI / 2);
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillText("sharpness", 0, 0);
    ctx.restore();
    ctx.textAlign = "left";

    // the comparison curve first, so the deciding one reads on top
    legendHits = [];
    let lx = P.l + 8;
    for (const c of curves) {
      const isDeciding = c === deciding;
      ctx.save();
      ctx.strokeStyle = css(METRICS[c.key].token);
      ctx.lineWidth = isDeciding ? 2 : 1.5;
      ctx.globalAlpha = isDeciding ? 1 : 0.55;
      if (!isDeciding) ctx.setLineDash([4, 3]);
      ctx.beginPath();
      c.norm.forEach((q, i) => { const x = X(q.z), y = Y(q.s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      ctx.restore();

      // legend doubles as the control: click a metric to let it decide
      ctx.save();
      ctx.strokeStyle = css(METRICS[c.key].token);
      ctx.lineWidth = isDeciding ? 2.5 : 1.5;
      if (!isDeciding) ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(lx, P.t + 3); ctx.lineTo(lx + 16, P.t + 3); ctx.stroke();
      ctx.restore();
      ctx.font = `${isDeciding ? "600 " : ""}11px system-ui, sans-serif`;
      ctx.fillStyle = isDeciding ? css("--ink") : css("--ink-3");
      const label = METRICS[c.key].short + (isDeciding ? " · deciding" : "");
      ctx.fillText(label, lx + 22, P.t + 7);
      const wLab = 22 + ctx.measureText(label).width;
      legendHits.push({ key: c.key, x0: lx - 4, x1: lx + wLab + 4, y0: P.t - 6, y1: P.t + 13 });
      lx += wLab + 18;
    }

    // everything below is drawn against the deciding curve, so its raw scores
    // are normalised the same way the curve was
    const N = (s) => s / decidingPeak;
    const p = f.points[f.selected];
    // sweep() is deterministic, so the recomputed candidate at the recorded
    // height is the same peak the rule picked when the strategy ran
    const chosen = t.candidates.find((c) => Math.abs(c.z - p.zAuto) < 1e-6) || t.candidates[0];

    // every measured z
    for (const q of t.samples) {
      ctx.beginPath();
      ctx.arc(X(q.z), Y(N(q.s)), 2.2, 0, Math.PI * 2);
      ctx.fillStyle = css("--mark-context");
      ctx.fill();
    }

    // candidate peaks the rule turned down — a narrow one is almost always a
    // speck of debris, and this is where it becomes visible instead of silent
    for (const c of t.candidates) {
      if (c === chosen || Math.abs(c.z - chosen.z) < 1e-6) continue;
      ctx.beginPath();
      ctx.arc(X(c.z), Y(N(c.s)), 4, 0, Math.PI * 2);
      ctx.strokeStyle = c.narrow ? css("--bad") : css("--ink-3");
      ctx.lineWidth = 1.6;
      ctx.stroke();
      if (c.narrow) {
        ctx.fillStyle = css("--bad");
        ctx.font = '10px ui-monospace, Consolas, monospace';
        const lbl = `${c.width.toFixed(1)} µm wide`;
        const lw = ctx.measureText(lbl).width;
        ctx.fillText(lbl, Math.max(P.l, Math.min(X(c.z) - lw / 2, w - P.r - lw)), Y(N(c.s)) - 8);
      }
    }

    // the parabola through the chosen peak's three samples
    if (chosen.used && chosen.used.length === 3 && chosen.used[0] !== chosen.used[1]) {
      ctx.save();
      ctx.strokeStyle = "#16a34a";
      ctx.lineWidth = 1.6;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      const [q0, q1, q2] = chosen.used;
      for (let i = 0; i <= 40; i++) {
        const z = q0.z + ((q2.z - q0.z) * i) / 40;
        const l0 = ((z - q1.z) * (z - q2.z)) / ((q0.z - q1.z) * (q0.z - q2.z));
        const l1 = ((z - q0.z) * (z - q2.z)) / ((q1.z - q0.z) * (q1.z - q2.z));
        const l2 = ((z - q0.z) * (z - q1.z)) / ((q2.z - q0.z) * (q2.z - q1.z));
        const s = q0.s * l0 + q1.s * l1 + q2.s * l2;
        const x = X(z), y = Y(N(s));
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
      for (const q of chosen.used) {
        ctx.beginPath(); ctx.arc(X(q.z), Y(N(q.s)), 3.6, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--surface-2"); ctx.stroke();
      }
    }

    // where the metric put the peak — kept visible as a reference once the
    // operator has dragged the chosen height somewhere else
    if (p.manual) {
      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 1.5;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(X(p.zAuto), P.t); ctx.lineTo(X(p.zAuto), h - P.b);
      ctx.stroke();
      ctx.restore();
    }

    // the draggable height
    const zSel = p.z;
    const sSel = N(scoreAt(t.samples, zSel));
    const xSel = X(zSel);
    // a peak too narrow to be tissue never gets to look like a confident answer
    const pickColour = p.manual ? css("--accent") : (p.onNarrow ? css("--bad") : "#16a34a");
    ctx.strokeStyle = pickColour;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xSel, P.t); ctx.lineTo(xSel, h - P.b);
    ctx.stroke();

    // a grab handle, so it reads as draggable
    ctx.fillStyle = pickColour;
    ctx.beginPath();
    ctx.moveTo(xSel - 5, P.t); ctx.lineTo(xSel + 5, P.t); ctx.lineTo(xSel, P.t + 7);
    ctx.closePath(); ctx.fill();

    ctx.beginPath(); ctx.arc(xSel, Y(sSel), 4.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 1.8; ctx.strokeStyle = css("--surface-2"); ctx.stroke();

    const lab = p.onNarrow && !p.manual
      ? `${zSel.toFixed(1)} µm · ${chosen.width.toFixed(1)} µm wide`
      : `${zSel.toFixed(1)} µm`;
    ctx.font = '11px ui-monospace, Consolas, monospace';
    const tw = ctx.measureText(lab).width;
    ctx.fillStyle = p.manual ? css("--accent-deep") : pickColour;
    ctx.fillText(lab, Math.min(xSel + 7, w - P.r - tw), Y(sSel) - 7);

    traceGeom = { zLo, zHi, P, w, h, samples: t.samples };
    drawZPreview(p, f.selected);
  }

  // linear read of the sweep between its samples
  function scoreAt(samples, z) {
    if (z <= samples[0].z) return samples[0].s;
    const last = samples[samples.length - 1];
    if (z >= last.z) return last.s;
    for (let i = 1; i < samples.length; i++) {
      if (z <= samples[i].z) {
        const a = samples[i - 1], b = samples[i];
        return a.s + ((b.s - a.s) * (z - a.z)) / (b.z - a.z);
      }
    }
    return last.s;
  }

  let traceGeom = null;
  let legendHits = [];

  /* ---- the image at whatever height the line is sitting on ---------------
     Defocus is the whole point of the preview, so it is drawn once sharp and
     blurred by how far the chosen height sits from this point's true focus. */
  function drawZPreview(point, idx) {
    const cv = el("zpreview-canvas");
    const ctx = cv.getContext("2d");
    const S = cv.width;
    const trueFocus = trueZ(point.x, point.y);
    const defocus = Math.abs(point.z - trueFocus);
    const blur = Math.min(11, defocus * 0.42);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, S, S);
    ctx.fillStyle = "#05090e";
    ctx.fillRect(0, 0, S, S);

    const r = makeRng(4400 + idx * 131);
    const nuclei = Array.from({ length: 14 }, () => ({
      x: S * (0.08 + 0.84 * r()), y: S * (0.08 + 0.84 * r()),
      rad: S * (0.045 + 0.055 * r()), amp: 0.5 + 0.5 * r(),
    }));

    if ("filter" in ctx) ctx.filter = blur > 0.25 ? `blur(${blur.toFixed(2)}px)` : "none";
    // out-of-focus light spreads out instead of vanishing
    const spread = 1 + blur * 0.16;
    for (const n of nuclei) {
      const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.rad * spread);
      g.addColorStop(0, `rgba(34,211,238,${(0.85 * n.amp) / spread})`);
      g.addColorStop(0.6, `rgba(34,211,238,${(0.3 * n.amp) / spread})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.rad * spread, 0, Math.PI * 2); ctx.fill();
    }
    // the speck of debris, if this position has one — it comes into focus in a
    // plane of its own, which is exactly what fools the metric
    const speck = debrisAt(idx);
    if (speck) {
      const speckZ = trueFocus + METRICS[state.focus.metric].bias + speck.offset;
      const speckBlur = Math.min(11, Math.abs(point.z - speckZ) * 0.55);
      ctx.filter = speckBlur > 0.25 ? `blur(${speckBlur.toFixed(2)}px)` : "none";
      const sr = makeRng(9100 + idx * 17);
      const cx = S * (0.3 + 0.4 * sr()), cy = S * (0.3 + 0.4 * sr());
      const sSpread = 1 + speckBlur * 0.5;
      ctx.fillStyle = `rgba(226,232,240,${Math.min(0.95, 0.95 / sSpread)})`;
      ctx.beginPath();
      ctx.ellipse(cx, cy, S * 0.035 * sSpread, S * 0.022 * sSpread, sr() * 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.filter = "none";
    }

    el("zpreview-z").textContent = `${point.z.toFixed(1)} µm`;
    const st = el("zpreview-state");
    st.classList.toggle("manual", !!point.manual);
    if (point.manual) {
      const d = point.z - point.zAuto;
      st.textContent = `moved by hand · ${d >= 0 ? "+" : ""}${d.toFixed(1)} µm off the pick`;
    } else if (point.onNarrow) {
      st.textContent = "locked onto a narrow peak";
      st.classList.add("manual");
    } else {
      st.textContent = defocus < 2 ? "cells in focus" : "off the tissue plane";
    }
  }

  /* ---- drag the height, and watch the image follow -----------------------
     The whole reason the preview is here: a peak the metric loved can be a
     speck, and the operator decides by looking rather than by trusting. */
  let scrubbing = false;

  function scrubTo(clientOffsetX) {
    const f = state.focus;
    if (!traceGeom || f.strategy !== "plane" || !f.applied) return;
    const p = f.points[f.selected];
    const { zLo, zHi, P, w } = traceGeom;
    const t = Math.max(0, Math.min(1, (clientOffsetX - P.l) / (w - P.l - P.r)));
    p.z = zLo + t * (zHi - zLo);
    p.manual = Math.abs(p.z - p.zAuto) > 0.05;
    refitSurface();
    drawTrace(); renderPointList(); drawFocus(); renderFocusToolbar();
  }

  traceCv.addEventListener("pointerdown", (e) => {
    const f = state.focus;
    if (f.strategy !== "plane" || !f.applied) return;
    // the legend is the metric control — no separate row of buttons for it
    const hit = legendHits.find((g) =>
      e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
    if (hit) {
      if (hit.key !== f.metric) {
        f.metric = hit.key;
        remeasure();
        drawTrace(); renderPointList(); drawFocus(); renderFocusToolbar(); renderActionBar();
      }
      return;
    }
    scrubbing = true;
    traceCv.setPointerCapture(e.pointerId);
    scrubTo(e.offsetX);
  });

  traceCv.addEventListener("pointermove", (e) => {
    if (scrubbing) return;
    const over = legendHits.some((g) =>
      e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
    traceCv.style.cursor = over ? "pointer" : "ew-resize";
  });
  traceCv.addEventListener("pointermove", (e) => { if (scrubbing) scrubTo(e.offsetX); });
  traceCv.addEventListener("pointerup", (e) => {
    scrubbing = false;
    traceCv.releasePointerCapture?.(e.pointerId);
  });
  traceCv.addEventListener("pointercancel", () => { scrubbing = false; });

  // keyboard equivalent, because a drag-only control is not operable by everyone
  traceCv.tabIndex = 0;
  traceCv.setAttribute("role", "slider");
  traceCv.setAttribute("aria-label", "focus height for the selected point");
  traceCv.addEventListener("keydown", (e) => {
    const f = state.focus;
    if (f.strategy !== "plane" || !f.applied) return;
    const nudge = { ArrowLeft: -0.5, ArrowRight: 0.5, PageDown: -3, PageUp: 3 }[e.key];
    if (nudge === undefined) return;
    e.preventDefault();
    const p = f.points[f.selected];
    p.z += nudge * (e.shiftKey ? 4 : 1);
    p.manual = Math.abs(p.z - p.zAuto) > 0.05;
    refitSurface();
    drawTrace(); renderPointList(); drawFocus(); renderFocusToolbar();
  });

  // ---- strategy control and its parameters
  el("focus-strategy").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-strat]");
    if (!b || state.focus.applied || state.running) return;
    state.focus.strategy = b.dataset.strat;
    renderFocusToolbar(); drawFocus(); renderActionBar();
  });

  // measure every placed point with the current metric, then fit the plane
  function remeasure() {
    const f = state.focus;
    f.points.forEach((p, i) => {
      const chosen = pickPeak(sweep(p, f.metric, i).candidates);
      p.zAuto = chosen.z;
      p.onNarrow = chosen.narrow;
      // a height the operator dragged by hand survives a change of metric
      if (!p.manual) p.z = p.zAuto;
    });
    refitSurface();
  }

  function refitSurface() {
    const f = state.focus;
    f.surface = fitSurface(f.points);
    const errs = residualsUm(f.surface, f.points);
    f.points.forEach((p, i) => { p.residual = errs[i]; });
    f.residual = Math.sqrt(errs.reduce((a, e) => a + e * e, 0) / Math.max(1, errs.length));
    let worst = -1;
    errs.forEach((e, i) => { if (worst < 0 || Math.abs(e) > Math.abs(errs[worst])) worst = i; });
    f.worst = errs.length ? worst : -1;
  }

  function renderFocusToolbar() {
    const f = state.focus;
    for (const b of el("focus-strategy").querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.strat === f.strategy));
      b.disabled = f.applied;
    }
    renderPointList();

    const host = el("focus-params");
    host.textContent = "";
    const add = (html) => {
      const d = document.createElement("div");
      d.className = "param";
      d.innerHTML = html;
      host.append(d);
      return d;
    };

    if (f.strategy === "plane") {
      // the instruction is only worth its width until the first point exists
      const d = add(f.points.length
        ? `<span class="hint">${f.points.length} point${f.points.length === 1 ? "" : "s"}</span>`
        : '<span class="hint">click the map to place focus points</span>');
      if (f.points.length && !f.applied) {
        const b = document.createElement("button");
        b.className = "ghost"; b.type = "button"; b.textContent = "Clear points";
        b.addEventListener("click", () => { f.points = []; renderFocusToolbar(); drawFocus(); renderActionBar(); });
        d.append(b);
      }
    } else if (f.strategy === "fixed") {
      const d = add('<label for="zfix">Z</label><input type="number" id="zfix" step="1"><span class="hint">µm</span>');
      const inp = d.querySelector("input");
      inp.value = f.zFixed;
      inp.disabled = f.applied;
      inp.addEventListener("input", () => {
        f.zFixed = Number(inp.value) || 0;
        drawFocus();
      });
    } else if (f.strategy === "auto") {
      const n = state.plan.length;
      add(`<span class="hint">${n} position${n === 1 ? "" : "s"} × ~4 s ≈ ${Math.max(1, Math.round((n * 4) / 60))} min added to the scan</span>`);
    } else if (f.strategy === "reuse") {
      const opts = Object.entries(PREVIOUS_SURFACES)
        .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
      const d = add(`<label for="reuse-sel">Surface</label><select id="reuse-sel">${opts}</select>`);
      const sel = d.querySelector("select");
      sel.value = f.reuse;
      sel.disabled = f.applied;
      sel.addEventListener("change", () => { f.reuse = sel.value; renderFocusToolbar(); drawFocus(); });
      const s = PREVIOUS_SURFACES[f.reuse];
      add(`<span class="hint">residual ${s.residual} µm · measured ${s.ageDays} days ago</span>`);
    }

    const out = el("focus-readout");
    if (f.applied && f.strategy === "plane") {
      const narrow = f.points.filter((p) => p.onNarrow).length;
      const hand = f.points.filter((p) => p.manual).length;
      const model = f.surface ? f.surface.model : "—";
      const worstErr = f.worst >= 0 ? f.points[f.worst].residual : null;
      out.textContent =
        `${model} · ${f.points.length} points · rms ${f.residual.toFixed(1)} µm` +
        (worstErr !== null && Math.abs(worstErr) > 0.05
          ? ` · worst ${worstErr >= 0 ? "+" : ""}${worstErr.toFixed(1)} µm at point ${f.worst + 1}`
          : "") +
        (narrow ? ` · ${narrow} on a narrow peak` : "") +
        (hand ? ` · ${hand} by hand` : "");
      out.style.color = narrow ? "var(--bad)" : "";
    } else if (f.applied) {
      out.style.color = "";
      out.textContent = `${STRATEGIES[f.strategy].label} applied`;
    } else {
      out.style.color = "";
      out.textContent = STRATEGIES[f.strategy].blurb;
    }
  }

  /* ============================================================
     detection — tuned on one tile, then run across all of them
     ============================================================ */
  const tileCv = el("tile-canvas");

  const ALGOS = {
    cellpose: {
      label: "Cellpose",
      blurb: "Diameter is the size it looks for; cell probability is how sure it has to be.",
    },
    threshold: {
      label: "Threshold",
      blurb: "Everything brighter than the level, larger than the minimum area.",
    },
  };

  // the same rule the tile test and the full run both use
  function detects(c) {
    const d = state.detect;
    const dia = 2 * c.r;
    if (d.algo === "cellpose") {
      // a diameter well off the truth costs you objects at both ends, which is
      // the whole reason to try it on a tile before running the sample
      return dia > d.diameter * 0.70 && dia < d.diameter * 1.55
        && c.intensity > 0.36 + d.cellprob * 0.05;
    }
    return c.intensity >= d.thresh && c.area >= d.minArea;
  }

  // golden-angle hues, so neighbouring labels never share a colour
  const labelColour = (id, a = 1) => `hsla(${(id * 137.508) % 360}, 68%, 58%, ${a})`;

  function drawTilePreview() {
    if (!sizeCanvas(tileCv)) return;
    const ctx = tileCv.getContext("2d");
    const w = tileCv.cssW, h = tileCv.cssH;
    const d = state.detect;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--surface-3");
    ctx.fillRect(0, 0, w, h);

    const tile = state.plan[d.tile];
    if (!tile) return;
    const frame = tile.frameUm;
    const pad = 18;
    const s = Math.min((w - 2 * pad) / frame, (h - 2 * pad) / frame);
    const ox = (w - frame * s) / 2, oy = (h - frame * s) / 2;
    const X = (x) => ox + (x - (tile.x - frame / 2)) * s;
    const Y = (y) => oy + (y - (tile.y - frame / 2)) * s;

    ctx.save();
    ctx.beginPath();
    ctx.rect(ox, oy, frame * s, frame * s);
    ctx.clip();

    ctx.fillStyle = "#05090e";
    ctx.fillRect(ox, oy, frame * s, frame * s);
    {
      // the tissue this tile happens to sit on, at the brightness it was found
      const dens = density(tile.x, tile.y);
      const cx = X(tile.x), cy = Y(tile.y), rr = frame * 0.8 * s;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rr);
      g.addColorStop(0, `rgba(34,211,238,${0.30 * dens})`);
      g.addColorStop(0.6, `rgba(34,211,238,${0.10 * dens})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.fill();
    }

    // objects are drawn larger than life: at 5x a cell is a couple of pixels,
    // and the point of this view is to judge the labels
    const inTile = cellsInTile(d.tile);
    for (const c of inTile) {
      const rr = Math.max(5, c.r * s * 2.4);
      const found = d.tested && detects(c);
      ctx.beginPath(); ctx.arc(X(c.x), Y(c.y), rr, 0, Math.PI * 2);
      if (found) {
        ctx.fillStyle = labelColour(c.id, 0.55);
        ctx.fill();
        ctx.lineWidth = 1.6; ctx.strokeStyle = labelColour(c.id, 1); ctx.stroke();
      } else {
        // rejected objects stay visible — what a setting threw away matters
        ctx.fillStyle = `rgba(226,232,240,${d.tested ? 0.26 : 0.62})`;
        ctx.fill();
      }
    }
    ctx.restore();

    ctx.strokeStyle = css("--line-strong");
    ctx.lineWidth = 1;
    ctx.strokeRect(ox + 0.5, oy + 0.5, frame * s - 1, frame * s - 1);
    drawScaleBar(ctx, w, h, s);
  }

  function renderDetectToolbar() {
    const d = state.detect;
    for (const b of el("detect-algo").querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.algo === d.algo));
    }
    el("tile-label").textContent = `${d.tile + 1} / ${state.plan.length}`;

    const host = el("detect-params");
    host.textContent = "";
    const num = (label, key, min, max, step, unit) => {
      const wrap = document.createElement("div");
      wrap.className = "param";
      wrap.innerHTML = `<label>${label}</label><input type="number" min="${min}" max="${max}" step="${step}">` +
        (unit ? `<span class="hint">${unit}</span>` : "");
      const inp = wrap.querySelector("input");
      inp.value = d[key];
      inp.addEventListener("input", () => {
        d[key] = Number(inp.value);
        d.tested = false;
        drawTilePreview(); renderDetectToolbar(); renderActionBar();
      });
      host.append(wrap);
    };

    if (d.algo === "cellpose") {
      num("Diameter", "diameter", 4, 60, 1, "µm");
      num("Cell prob.", "cellprob", -6, 6, 0.5, "");
    } else {
      num("Level", "thresh", 0, 1, 0.05, "");
      num("Min area", "minArea", 20, 400, 10, "µm²");
    }

    const test = document.createElement("button");
    test.className = "ghost"; test.type = "button";
    test.textContent = "Test on this tile";
    test.addEventListener("click", () => {
      d.tested = true;
      drawTilePreview(); renderDetectToolbar(); renderActionBar();
    });
    host.append(test);

    const out = el("detect-readout");
    if (d.tested) {
      const inTile = cellsInTile(d.tile);
      const found = inTile.filter(detects).length;
      out.textContent = `${found} of ${inTile.length} objects at position ${d.tile + 1}`;
    } else {
      out.textContent = ALGOS[d.algo].blurb;
    }
  }

  el("detect-algo").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-algo]");
    if (!b || state.running) return;
    state.detect.algo = b.dataset.algo;
    state.detect.tested = false;
    renderDetectToolbar(); drawTilePreview(); renderActionBar();
  });

  for (const [id, step] of [["tile-prev", -1], ["tile-next", 1]]) {
    el(id).addEventListener("click", () => {
      const d = state.detect;
      const total = state.plan.length || 1;
      d.tile = (d.tile + step + total) % total;
      d.tested = false;
      renderDetectToolbar(); drawTilePreview(); renderActionBar();
    });
  }

  /* ============================================================
     the analysis panel — a scatter you gate on
     ============================================================ */
  const scatterCv = el("scatter-canvas");
  const scatterTip = el("scatter-tip");
  const PAD = { l: 62, r: 18, t: 18, b: 46 };

  const sx = (area, w) => PAD.l + ((area - AREA_LO) / (AREA_HI - AREA_LO)) * (w - PAD.l - PAD.r);
  const sy = (inten, h) => (h - PAD.b) - inten * (h - PAD.t - PAD.b);
  const invX = (px, w) => AREA_LO + ((px - PAD.l) / (w - PAD.l - PAD.r)) * (AREA_HI - AREA_LO);
  const invY = (py, h) => ((h - PAD.b) - py) / (h - PAD.t - PAD.b);

  function drawScatter() {
    if (!sizeCanvas(scatterCv)) return;
    const ctx = scatterCv.getContext("2d");
    const w = scatterCv.cssW, h = scatterCv.cssH;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, 0, w, h);

    // recessive grid
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    ctx.fillStyle = css("--ink-3");
    ctx.font = '11.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "right";
    for (let v = 0; v <= 1.0001; v += 0.25) {
      const y = sy(v, h);
      ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(w - PAD.r, y); ctx.stroke();
      ctx.fillText(v.toFixed(2), PAD.l - 9, y + 4);
    }
    ctx.textAlign = "center";
    for (let a = 100; a <= AREA_HI; a += 100) {
      const x = sx(a, w);
      ctx.beginPath(); ctx.moveTo(x, PAD.t); ctx.lineTo(x, h - PAD.b); ctx.stroke();
      ctx.fillText(String(a), x, h - PAD.b + 18);
    }

    // axis titles
    ctx.fillStyle = css("--ink-2");
    ctx.font = '12.5px system-ui, sans-serif';
    ctx.fillText("cell area (µm²)", (PAD.l + w - PAD.r) / 2, h - 12);
    ctx.save();
    ctx.translate(16, (PAD.t + h - PAD.b) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("mean intensity · ch2", 0, 0);
    ctx.restore();

    // context points
    ctx.fillStyle = css("--mark-context");
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    for (const c of sample.cells) {
      if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
      const x = sx(c.area, w), y = sy(c.intensity, h);
      ctx.moveTo(x + 2, y); ctx.arc(x, y, 2, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.globalAlpha = 1;

    // gated points — larger and ringed as well as coloured
    const acquired = new Set(state.acquired);
    for (const c of sample.cells) {
      if (!state.gated.has(c.id)) continue;
      const x = sx(c.area, w), y = sy(c.intensity, h);
      const isAcq = acquired.has(c.id);
      ctx.beginPath(); ctx.arc(x, y, isAcq ? 4.6 : 3.4, 0, Math.PI * 2);
      ctx.fillStyle = isAcq ? "#16a34a" : "#0284c7";
      ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = css("--screen"); ctx.stroke();
    }

    // the gate itself
    if (state.gate) {
      const g = state.gate;
      const x0 = sx(g.aLo, w), x1 = sx(g.aHi, w);
      const y0 = sy(g.iHi, h), y1 = sy(g.iLo, h);
      ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.setLineDash([]);
    }
    if (drag.active) {
      ctx.strokeStyle = css("--accent"); ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1),
        Math.abs(drag.x1 - drag.x0), Math.abs(drag.y1 - drag.y0));
      ctx.setLineDash([]);
    }
  }

  const drag = { active: false, x0: 0, y0: 0, x1: 0, y1: 0 };

  scatterCv.addEventListener("pointerdown", (e) => {
    if (!state.cellsShown) return;
    drag.active = true;
    drag.x0 = drag.x1 = e.offsetX; drag.y0 = drag.y1 = e.offsetY;
    scatterCv.setPointerCapture(e.pointerId);
  });

  scatterCv.addEventListener("pointermove", (e) => {
    const w = scatterCv.cssW, h = scatterCv.cssH;
    if (drag.active) {
      drag.x1 = e.offsetX; drag.y1 = e.offsetY;
      drawScatter();
      return;
    }
    if (!state.cellsShown) return;
    let hit = null, best = 9;
    for (const c of sample.cells) {
      if (!state.detected.has(c.id)) continue;
      const d = Math.hypot(sx(c.area, w) - e.offsetX, sy(c.intensity, h) - e.offsetY);
      if (d < best) { best = d; hit = c; }
    }
    if (hit) {
      scatterTip.classList.add("on");
      scatterTip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br>` +
        `<b>int</b> ${hit.intensity.toFixed(2)}<br><b>at</b> ${(hit.x / 1000).toFixed(2)}, ${(hit.y / 1000).toFixed(2)} mm`;
      scatterTip.style.left = `${Math.min(e.offsetX + 14, w - 160)}px`;
      scatterTip.style.top = `${Math.max(6, e.offsetY - 68)}px`;
    } else {
      scatterTip.classList.remove("on");
    }
  });

  scatterCv.addEventListener("pointerup", (e) => {
    if (!drag.active) return;
    drag.active = false;
    scatterCv.releasePointerCapture?.(e.pointerId);
    const w = scatterCv.cssW, h = scatterCv.cssH;
    if (Math.abs(drag.x1 - drag.x0) < 6 || Math.abs(drag.y1 - drag.y0) < 6) { drawScatter(); return; }
    const g = {
      aLo: invX(Math.min(drag.x0, drag.x1), w), aHi: invX(Math.max(drag.x0, drag.x1), w),
      iLo: invY(Math.max(drag.y0, drag.y1), h), iHi: invY(Math.min(drag.y0, drag.y1), h),
    };
    applyGate(g);
  });

  scatterCv.addEventListener("pointerleave", () => scatterTip.classList.remove("on"));

  function applyGate(g) {
    state.gate = g;
    state.gated = new Set(sample.cells
      .filter((c) => state.detected.has(c.id)
        && c.area >= g.aLo && c.area <= g.aHi && c.intensity >= g.iLo && c.intensity <= g.iHi)
      .map((c) => c.id));
    el("gate-readout").textContent =
      `${state.gated.size} of ${state.detected.size} detected gated · area ${g.aLo.toFixed(0)}–${g.aHi.toFixed(0)} µm² · int ${g.iLo.toFixed(2)}–${g.iHi.toFixed(2)}`;
    drawScatter();
    drawStage();
    renderTabs();
    renderActionBar();
  }

  el("clear-gate").addEventListener("click", () => {
    state.gate = null; state.gated = new Set();
    el("gate-readout").textContent = "drag a rectangle to gate";
    drawScatter(); drawStage(); renderTabs(); renderActionBar();
  });

  /* ============================================================
     the gallery — acquired overview / target pairs
     ============================================================ */
  function cropCanvas(cell, zoom, seed) {
    const cv = document.createElement("canvas");
    const S = 132;
    cv.width = S; cv.height = S;
    const ctx = cv.getContext("2d");
    const r = makeRng(seed);
    ctx.fillStyle = "#05090e";
    ctx.fillRect(0, 0, S, S);
    const blobN = zoom > 1 ? 5 : 14;
    for (let i = 0; i < blobN; i++) {
      const bx = S * r(), by = S * r();
      const br = (zoom > 1 ? 26 : 9) * (0.5 + r());
      const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
      g.addColorStop(0, `rgba(34,211,238,${0.30 + 0.35 * r()})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
    }
    // the cell itself, centred
    const cr = zoom > 1 ? 34 : 7;
    const g2 = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, cr);
    g2.addColorStop(0, `rgba(245,158,11,${0.55 + 0.4 * cell.intensity})`);
    g2.addColorStop(0.7, "rgba(245,158,11,0.22)");
    g2.addColorStop(1, "rgba(245,158,11,0)");
    ctx.fillStyle = g2;
    ctx.beginPath(); ctx.arc(S / 2, S / 2, cr, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(22,163,74,0.85)";
    ctx.lineWidth = zoom > 1 ? 2 : 1.5;
    ctx.beginPath(); ctx.arc(S / 2, S / 2, cr * 0.75, 0, Math.PI * 2); ctx.stroke();
    return cv;
  }

  function buildGallery() {
    const host = el("pairs");
    host.textContent = "";
    state.acquired.forEach((id, i) => {
      const cell = sample.cells[id - 1];
      const card = document.createElement("div");
      card.className = "pair";

      const imgs = document.createElement("div");
      imgs.className = "imgs";
      imgs.append(cropCanvas(cell, 1, 7000 + i), cropCanvas(cell, 3, 9100 + i));
      card.append(imgs);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.append(document.createTextNode(
        `#${cell.id} · ${(cell.x / 1000).toFixed(2)}, ${(cell.y / 1000).toFixed(2)} mm`));

      const verdict = document.createElement("div");
      verdict.className = "verdict";
      for (const [kind, glyph] of [["good", "✓"], ["bad", "✗"]]) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = `pick-${kind}`;
        b.textContent = glyph;
        b.setAttribute("aria-pressed", "false");
        b.setAttribute("aria-label", `mark cell ${cell.id} ${kind}`);
        b.addEventListener("click", () => {
          state.verdicts[cell.id] = state.verdicts[cell.id] === kind ? null : kind;
          for (const sib of verdict.querySelectorAll("button")) {
            sib.setAttribute("aria-pressed",
              String(sib.classList.contains(`pick-${state.verdicts[cell.id]}`)));
          }
          updateGalleryReadout();
        });
        verdict.append(b);
      }
      meta.append(verdict);
      card.append(meta);
      host.append(card);
    });
    updateGalleryReadout();
  }

  function updateGalleryReadout() {
    const total = state.acquired.length;
    const marked = state.acquired.filter((id) => state.verdicts[id]).length;
    const good = state.acquired.filter((id) => state.verdicts[id] === "good").length;
    el("gallery-readout").textContent =
      total ? `${total} pairs · ${marked} marked · ${good} good` : "—";
  }

  /* ============================================================
     boot
     ============================================================ */
  const ro = new ResizeObserver(() => {
    if (el("panel-canvas").classList.contains("on")) { sizeCanvas(stageCv); drawStage(); }
    if (el("panel-detect").classList.contains("on")) drawTilePreview();
    if (el("panel-focus").classList.contains("on")) { drawFocus(); drawTrace(); }
    if (el("panel-analysis").classList.contains("on")) { sizeCanvas(scatterCv); drawScatter(); }
  });
  ro.observe(el("panel-canvas"));
  ro.observe(el("panel-detect"));
  ro.observe(el("panel-focus"));
  ro.observe(el("panel-analysis"));

  const mo = new MutationObserver(() => { drawStage(); drawTilePreview(); drawFocus(); drawTrace(); drawScatter(); });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  renderFocusToolbar();
  renderDetectToolbar();
  settingsChanged();
  rebuildSample();
  focusPanelsFor(0);
  renderAll();
})();