import "./style.css";
import { numbered } from "./frame/steps.js";
import {
  MICROSCOPES, DEFAULT_SESSION, apisFor, defaultApiFor, describeSession, CONNECT_CHECKS,
  OPTICAL_CONFIGS, DEFAULT_OPTICS, opticalConfig, CARRIERS, DEFAULT_CARRIER, carrier,
} from "./lib/microscopes.js";

(() => {
  "use strict";

  /* ============================================================
     synthetic sample — deterministic, so the mock looks the same
     every load. Geometry is in stage micrometres throughout.
     ============================================================ */
  const TILE_UM = 2662;          // 2048 px at 1.3 µm/px, a 5x overview tile
  const COLS = 7, ROWS = 5;
  const W_UM = COLS * TILE_UM, H_UM = ROWS * TILE_UM;

  function makeRng(seed) {
    let s = seed >>> 0;
    return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
  }

  const rnd = makeRng(20260728);

  const blobs = Array.from({ length: 6 }, () => ({
    x: (0.12 + 0.76 * rnd()) * W_UM,
    y: (0.12 + 0.76 * rnd()) * H_UM,
    r: (0.10 + 0.13 * rnd()) * W_UM,
  }));

  function density(x, y) {
    let d = 0;
    for (const b of blobs) {
      const dx = x - b.x, dy = y - b.y;
      d += Math.exp(-(dx * dx + dy * dy) / (2 * b.r * b.r));
    }
    return Math.min(1, d);
  }

  // cells live where there is tissue
  const cells = [];
  for (let i = 0; cells.length < 1250 && i < 24000; i++) {
    const x = rnd() * W_UM, y = rnd() * H_UM;
    const d = density(x, y);
    if (rnd() > d * 0.92) continue;
    const area = 62 + 330 * Math.pow(rnd(), 1.7);
    const intensity = Math.max(0.02, Math.min(1, 0.18 + 0.62 * d + 0.22 * (rnd() - 0.5)));
    cells.push({ id: cells.length + 1, x, y, area, intensity, r: Math.sqrt(area / Math.PI) });
  }

  const AREA_LO = 60, AREA_HI = 400;

  /* ============================================================
     workflow declarations — the whole point of the selector box
     ============================================================ */
  const WORKFLOWS = {
    target_acquisition: {
      name: "Target acquisition",
      blurb: "overview, detect, select, acquire",
      steps: numbered([
        { id: "connect", title: "Connect", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: [], ms: 1900 },
        { id: "optics", title: "Optical configurations", why: "Pick the configuration that surveys the sample and the one that images the targets.", btn: "Apply configurations", panels: [], ms: 800, mode: "optics" },
        { id: "carrier", title: "Carrier setup", why: "Tell the run what the sample is mounted in — it decides where the stage may go.", btn: "Apply carrier", panels: [], ms: 700, mode: "carrier" },
        { id: "origin", title: "Set origin", why: "Marks the stage where it stands as (0, 0) for this run.", btn: "Set origin", panels: [], ms: 600, note: "origin at 0.0, 0.0 µm" },
        { id: "focus", title: "Focus strategy", why: "Choose how this run keeps every image sharp across the sample.", btn: "Apply strategy", panels: ["focus"], ms: 1400, mode: "focus" },
        { id: "scan", title: "Scan the overview", why: "Drives the stage through every position, stitching tiles as they are saved.", btn: "Scan overview", panels: [], ms: 2600, note: "35 / 35 tiles", mode: "scan" },
        { id: "detect", title: "Detect cells", why: "Segments every overview tile. Each cell found becomes one point.", btn: "Detect cells", panels: ["detect"], ms: 1600, note: "1250 cells found", mode: "detect" },
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
        { id: "connect", title: "Connect", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: [], ms: 1900 },
        { id: "optics", title: "Optical configurations", why: "Pick the configuration that surveys the sample and the one that images the targets.", btn: "Apply configurations", panels: [], ms: 800, mode: "optics" },
        { id: "carrier", title: "Carrier setup", why: "Tell the run what the sample is mounted in — it decides where the stage may go.", btn: "Apply carrier", panels: [], ms: 700, mode: "carrier" },
        { id: "origin", title: "Set origin", why: "Marks the stage where it stands as (0, 0).", btn: "Set origin", panels: [], ms: 600, note: "origin at 0.0, 0.0 µm" },
        { id: "scan", title: "Scan the overview", why: "Drives the stage through every position and stitches the map.", btn: "Scan overview", panels: [], ms: 2600, note: "35 / 35 tiles", mode: "scan" },
        { id: "save", title: "Save the run", why: "Writes the stitched map and its report to the run folder.", btn: "Save results", panels: [], ms: 800, note: "map + report written" },
        { id: "disconnect", title: "Disconnect", why: "Releases the microscope.", btn: "Disconnect", panels: [], ms: 600, note: "session closed" },
      ]),
    },
    focus_check: {
      name: "Focus surface check",
      blurb: "calibration run",
      steps: numbered([
        { id: "connect", title: "Connect", why: "Choose the microscope, its API and the password, then open the session.", btn: "Connect", ownButton: true, panels: [], ms: 1900 },
        { id: "optics", title: "Optical configurations", why: "Pick the configuration that surveys the sample and the one that images the targets.", btn: "Apply configurations", panels: [], ms: 800, mode: "optics" },
        { id: "carrier", title: "Carrier setup", why: "Tell the run what the sample is mounted in — it decides where the stage may go.", btn: "Apply carrier", panels: [], ms: 700, mode: "carrier" },
        { id: "origin", title: "Set origin", why: "Marks the stage where it stands as (0, 0).", btn: "Set origin", panels: [], ms: 600, note: "origin at 0.0, 0.0 µm" },
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
      tile: { col: 3, row: 2 },
      tested: false,
    };
  }

  const PREVIOUS_SURFACES = {
    run_0714_a: { label: "2026-07-14 · slide A", plane: { a: 96, b: 61, c: -412 }, residual: 1.8, ageDays: 14 },
    run_0709_c: { label: "2026-07-09 · slide C", plane: { a: 71, b: 88, c: -389 }, residual: 3.1, ageDays: 19 },
  };

  const state = {
    session: { ...DEFAULT_SESSION },
    optics: { ...DEFAULT_OPTICS },
    carrier: DEFAULT_CARRIER,
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

  function resetRun() {
    Object.assign(state, {
      activeIdx: 0, done: new Set(), running: null, notes: {},
      session: { ...DEFAULT_SESSION }, optics: { ...DEFAULT_OPTICS },
      carrier: DEFAULT_CARRIER, checks: [],
      tabs: ["canvas"], tab: "canvas", tilesShown: 0, focus: newFocus(),
      detect: newDetect(), detected: new Set(),
      cellsShown: false, gate: null, gated: new Set(), acquired: [], verdicts: {},
      locked: false,
    });
    view.fitted = false; fview.fitted = false;
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
      else if (done) head.insertAdjacentHTML("beforeend", '<span class="tick">✓</span>');
      b.append(head);

      if (state.notes[s.id]) {
        const n = document.createElement("div");
        n.className = "step-body";
        n.innerHTML = '<div class="step-note ok"></div>';
        n.querySelector(".step-note").textContent = state.notes[s.id];
        b.append(n);
      }

      b.addEventListener("click", () => {
        if (state.running || !reachable) return;
        state.activeIdx = i;
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
    if (s.mode === "optics" && opticsClash()) return "survey and target must differ";
    if (s.mode === "detect" && !state.detect.tested) return "try it on one tile first";
    if ((s.mode === "select" || s.mode === "targets") && state.gated.size === 0) return "nothing gated yet";
    return null;
  }

  function renderActionBar() {
    const host = el("action-bar");
    host.textContent = "";
    host.hidden = !!step(state.activeIdx).ownButton;
    if (host.hidden) return;
    const i = state.activeIdx, s = step(i);
    const done = state.done.has(s.id);
    const running = state.running === s.id;
    const blocked = readiness(s);

    if (s.btn && !s.ownButton) {
      const run = document.createElement("button");
      run.className = "run"; run.type = "button";
      run.textContent = running ? "working…" : (done ? "Run again" : s.btn);
      run.disabled = !!state.running || !!blocked;
      run.addEventListener("click", () => runStep(i));
      host.append(run);
    }

    const why = document.createElement("span");
    why.className = "action-why";
    why.textContent = s.why;
    host.append(why);

    const hint = document.createElement("span");
    if (blocked) { hint.className = "action-hint"; hint.textContent = blocked; }
    else if (running) { hint.className = "action-hint"; hint.textContent = "working…"; }
    else if (s.mode === "select" && !done) { hint.className = "action-hint ok"; hint.textContent = `${state.gated.size} gated`; }
    else if (state.notes[s.id]) { hint.className = "action-hint ok"; hint.textContent = state.notes[s.id]; }
    host.append(hint);
  }

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
      state.checks = [];
      CONNECT_CHECKS.forEach((check, k) => {
        setTimeout(() => {
          if (state.running !== "connect") return;
          state.checks.push({ ...check, result: check.result(state.session) });
          renderSetup();
        }, 260 * (k + 1));
      });
    }

    if (s.mode === "scan") {
      state.tilesShown = 0;
      const total = COLS * ROWS;
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
      if (s.id === "carrier") state.notes[s.id] = carrier(state.carrier).label;
      if (s.id === "optics") {
        state.notes[s.id] = `${opticalConfig(state.optics.overview).label} → ${opticalConfig(state.optics.target).label}`;
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
      if (s.mode === "scan") { state.tilesShown = COLS * ROWS; }
      if (s.mode === "detect") {
        // the settings proven on one tile, now applied to every tile
        state.detected = new Set(cells.filter(detects).map((c) => c.id));
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
  const PANEL_META = {
    setup: { label: "Setup", panel: "panel-setup" },
    canvas: { label: "Canvas", panel: "panel-canvas" },
    detect: { label: "Detection", panel: "panel-detect" },
    focus: { label: "Focus strategy", panel: "panel-focus" },
    analysis: { label: "Analysis", panel: "panel-analysis" },
    gallery: { label: "Gallery", panel: "panel-gallery" },
  };

  /* The canvas holds acquired data, so it appears when there is some — before
     the first tile lands it would be an empty stage, and the setup steps have
     real state worth showing instead. Everything else belongs to the step you
     are standing on, so the tab bar is rebuilt each time the active step
     changes rather than growing forever. */
  const hasAcquiredData = () => state.tilesShown > 0;

  function panelsFor(i) {
    const own = (step(i).panels || []).filter((p) => p !== "canvas");
    const base = hasAcquiredData() ? ["canvas"] : ["setup"];
    return own.length ? [...base, ...own] : base;
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
    { step: "origin", name: "Stage origin", waiting: "not set" },
    { step: "focus", name: "Focus surface", waiting: "not measured" },
  ];

  /* Connecting is a form, so its button belongs in the form rather than in the
     bar above it — you fill a session in and open it, you do not configure it
     here and press something over there. */
  function renderSessionCard(host) {
    const connected = state.done.has("connect");
    let connectBtn = null;
    let connectHint = null;
    const connecting = state.running === "connect";
    const card = document.createElement("div");
    card.className = "session-card" + (connected ? " done" : "");

    const head = document.createElement("div");
    head.className = "session-head";
    head.innerHTML = '<span class="session-title">Session</span><span class="session-state"></span>';
    head.querySelector(".session-state").textContent = connected
      ? describeSession(state.session)
      : "not connected";
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

      // once the session is open the button has nothing left to do; the fields
      // stay on show as the record of what it was opened with
      if (!connected) {
        connectBtn = document.createElement("button");
        connectBtn.className = "run";
        connectBtn.type = "button";
        connectBtn.textContent = connecting ? "connecting…" : "Connect";
        connectBtn.disabled = connecting || !state.session.password;
        connectBtn.addEventListener("click", () => runStep(indexOfStep("connect")));
        form.append(connectBtn);

        connectHint = document.createElement("div");
        connectHint.className = "session-hint";
        connectHint.textContent = "a password is needed to open the session";
        connectHint.hidden = !!state.session.password || connecting;
        form.append(connectHint);
      }
      card.append(form);
    }

    if (state.checks.length) {
      const list = document.createElement("div");
      list.className = "check-list";
      for (const c of state.checks) {
        const row = document.createElement("div");
        row.className = "check-row";
        row.innerHTML = '<span class="check-mark">✓</span><span class="check-name"></span>'
          + '<span class="check-value"></span>';
        row.querySelector(".check-name").textContent = c.label;
        row.querySelector(".check-value").textContent = c.result;
        list.append(row);
      }
      card.append(list);
    }

    host.append(card);
  }

  const indexOfStep = (id) => steps().findIndex((s) => s.id === id);

  /* Two configurations, and they may not be the same one: imaging targets at
     overview quality is the mistake this pairing exists to prevent, so it is
     refused rather than warned about. */
  const opticsClash = () => state.optics.overview === state.optics.target;

  function renderOpticsCard(host) {
    const done = state.done.has("optics");
    const card = document.createElement("div");
    card.className = "session-card" + (done ? " done" : "");

    const head = document.createElement("div");
    head.className = "session-head";
    head.innerHTML = '<span class="session-title">Optical configurations</span>'
      + '<span class="session-state"></span>';
    head.querySelector(".session-state").textContent = done
      ? `${opticalConfig(state.optics.overview).label} → ${opticalConfig(state.optics.target).label}`
      : "not applied";
    card.append(head);

    const form = document.createElement("div");
    form.className = "session-form";

    for (const [role, label] of [["overview", "Survey with"], ["target", "Image with"]]) {
      const field = document.createElement("label");
      field.className = "field";
      field.innerHTML = `<span>${label}</span><select></select>`;
      const sel = field.querySelector("select");
      for (const oc of OPTICAL_CONFIGS) {
        const o = document.createElement("option");
        o.value = oc.key;
        o.textContent = `${oc.label} · ${oc.detail}`;
        sel.append(o);
      }
      sel.value = state.optics[role];
      sel.disabled = done || !!state.running;
      sel.addEventListener("change", () => {
        state.optics[role] = sel.value;
        renderSetup(); renderActionBar();
      });
      form.append(field);
    }

    if (!done && opticsClash()) {
      const hint = document.createElement("div");
      hint.className = "session-hint bad";
      hint.textContent = "the two must differ — this would image targets at survey quality";
      form.append(hint);
    }

    card.append(form);
    host.append(card);
  }

  function renderCarrierCard(host) {
    const done = state.done.has("carrier");
    const card = document.createElement("div");
    card.className = "session-card" + (done ? " done" : "");

    const head = document.createElement("div");
    head.className = "session-head";
    head.innerHTML = '<span class="session-title">Carrier</span><span class="session-state"></span>';
    head.querySelector(".session-state").textContent = done
      ? carrier(state.carrier).label
      : "not applied";
    card.append(head);

    const form = document.createElement("div");
    form.className = "session-form";
    const field = document.createElement("label");
    field.className = "field";
    field.innerHTML = "<span>Mounted in</span><select></select>";
    const sel = field.querySelector("select");
    for (const c of CARRIERS) {
      const o = document.createElement("option");
      o.value = c.key;
      o.textContent = `${c.label} · ${c.detail}`;
      sel.append(o);
    }
    sel.value = state.carrier;
    sel.disabled = done || !!state.running;
    sel.addEventListener("change", () => {
      state.carrier = sel.value;
      renderSetup(); renderActionBar();
    });
    form.append(field);
    card.append(form);
    host.append(card);
  }

  /* Each setup step gets a card, and keeps it until the next one has been
     settled — a session you have already moved past twice is history, and the
     panel should be showing the thing being decided now. */
  const SETUP_CARDS = [
    { step: "connect", render: renderSessionCard },
    { step: "optics", render: renderOpticsCard },
    { step: "carrier", render: renderCarrierCard },
  ];

  function renderSetup() {
    const host = el("setup-list");
    host.textContent = "";
    const present = new Set(steps().map((s) => s.id));

    const shown = SETUP_CARDS.filter((c) => present.has(c.step));
    shown.forEach((card, i) => {
      const successor = shown[i + 1];
      const retired = successor && state.done.has(successor.step);
      if (!retired) card.render(host);
    });

    /* Only what the run has established, plus whatever is being done now. The
       rail already lists what is still ahead; repeating it here as a column of
       "not set" would make the panel a second, worse copy of it. */
    const activeId = step(state.activeIdx).id;
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
  }

  function renderPanels() {
    const show = state.tabs.includes(state.tab) ? state.tab : state.tabs[0];
    for (const [key, meta] of Object.entries(PANEL_META)) {
      el(meta.panel).classList.toggle("on", show === key);
    }
    if (show === "setup") renderSetup();
    if (show === "canvas") { sizeCanvas(stageCv); drawStage(); }
    if (show === "detect") { renderDetectToolbar(); drawTilePreview(); }
    if (show === "focus") { renderFocusToolbar(); drawFocus(); drawTrace(); }
    if (show === "analysis") { sizeCanvas(scatterCv); drawScatter(); }
  }

  function renderAll() {
    /* Recomputed every render, not only on a step change: the first tile of a
       scan lands while the operator is standing still, and that is the moment
       the canvas earns its place and setup stops being the useful view. */
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

  function fitView() {
    const w = stageCv.cssW || 800, h = stageCv.cssH || 600;
    const pad = 26;
    const s = Math.min((w - 2 * pad) / W_UM, (h - 2 * pad) / H_UM);
    view.scale = s;
    view.tx = (w - W_UM * s) / 2;
    view.ty = (h - H_UM * s) / 2;
    view.fitted = true;
  }

  const toScreen = (x, y) => [x * view.scale + view.tx, y * view.scale + view.ty];
  const toWorld = (px, py) => [(px - view.tx) / view.scale, (py - view.ty) / view.scale];

  function tileTexture(ctx, col, row) {
    const x0 = col * TILE_UM, y0 = row * TILE_UM;
    const [sx, sy] = toScreen(x0, y0);
    const sz = TILE_UM * view.scale;

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

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--surface-3");
    ctx.fillRect(0, 0, w, h);

    const showTiles = el("lay-tiles").checked;
    const showCells = el("lay-cells").checked;
    const showTargets = el("lay-targets").checked;
    const ch0 = el("ch-0").checked, ch1 = el("ch-1").checked;

    // ---- tiles, in the order the scan writes them
    const shown = Math.max(state.tilesShown, 0);
    if (showTiles && shown > 0) {
      ctx.save();
      for (let i = 0; i < shown; i++) {
        const row = Math.floor(i / COLS);
        const col = row % 2 === 0 ? i % COLS : COLS - 1 - (i % COLS); // serpentine, like the stage
        tileTexture(ctx, col, row);
      }
      // tissue, clipped to what has been scanned
      ctx.globalCompositeOperation = "lighter";
      for (const b of blobs) {
        const [bx, by] = toScreen(b.x, b.y);
        const br = b.r * view.scale;
        const rowsDone = Math.ceil(shown / COLS);
        if (b.y > rowsDone * TILE_UM + b.r * 0.4) continue;
        const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        if (ch0) { g.addColorStop(0, "rgba(34,211,238,0.30)"); }
        g.addColorStop(0.55, ch1 ? "rgba(245,158,11,0.13)" : "rgba(34,211,238,0.10)");
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }

    // ---- scan frontier
    if (state.running === "scan" && showTiles) {
      const row = Math.floor(shown / COLS);
      const col = row % 2 === 0 ? shown % COLS : COLS - 1 - (shown % COLS);
      const [fx, fy] = toScreen(col * TILE_UM, row * TILE_UM);
      ctx.strokeStyle = css("--accent");
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(fx, fy, TILE_UM * view.scale, TILE_UM * view.scale);
      ctx.setLineDash([]);
    }

    // ---- sample bounds
    {
      const [bx, by] = toScreen(0, 0);
      ctx.strokeStyle = css("--line-strong");
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, W_UM * view.scale, H_UM * view.scale);
    }

    // ---- cells
    if (showCells && state.cellsShown) {
      const ctxRad = Math.max(1.1, 1.4 * Math.sqrt(view.scale / 0.03));
      ctx.fillStyle = css("--mark-context");
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      for (const c of cells) {
        if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
        const [x, y] = toScreen(c.x, c.y);
        if (x < -8 || y < -8 || x > w + 8 || y > h + 8) continue;
        ctx.moveTo(x + ctxRad, y);
        ctx.arc(x, y, ctxRad, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.globalAlpha = 1;

      // gated cells — ringed, so identity is not carried by colour alone
      const gr = Math.max(3, 4.2 * Math.sqrt(view.scale / 0.03));
      for (const c of cells) {
        if (!state.gated.has(c.id)) continue;
        const [x, y] = toScreen(c.x, c.y);
        if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
        ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
      }
    }

    // ---- acquired targets
    if (showTargets && state.acquired.length) {
      for (const id of state.acquired) {
        const c = cells[id - 1];
        const [x, y] = toScreen(c.x, c.y);
        const rr = Math.max(7, 9 * Math.sqrt(view.scale / 0.03));
        ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
        ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2.2; ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = "#16a34a"; ctx.fill();
      }
    }

    // ---- the origin, which is the one thing step 2 establishes
    if (state.done.has("origin")) {
      const [ox, oy] = toScreen(0, 0);
      ctx.strokeStyle = css("--accent");
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(ox - 9, oy); ctx.lineTo(ox + 9, oy);
      ctx.moveTo(ox, oy - 9); ctx.lineTo(ox, oy + 9);
      ctx.stroke();
      ctx.fillStyle = css("--ink-3");
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.fillText("0, 0", ox + 11, oy - 4);
    }

    drawScaleBar(ctx, w, h);
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
    dragging = true; dragMoved = false;
    lastX = e.offsetX; lastY = e.offsetY;
    stageCv.setPointerCapture(e.pointerId);
    stageCv.classList.add("dragging");
  });

  stageCv.addEventListener("pointermove", (e) => {
    if (dragging) {
      const dx = e.offsetX - lastX, dy = e.offsetY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
      view.tx += dx; view.ty += dy;
      lastX = e.offsetX; lastY = e.offsetY;
      drawStage();
      return;
    }
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    el("stage-readout").textContent =
      `x ${wx.toFixed(0)} µm · y ${wy.toFixed(0)} µm · ${(view.scale * 1000).toFixed(1)} px/mm`;

    // hover the nearest visible cell
    let hit = null;
    if (state.cellsShown && el("lay-cells").checked) {
      let best = 12 / view.scale;
      for (const c of cells) {
        if (!state.detected.has(c.id)) continue;
        const d = Math.hypot(c.x - wx, c.y - wy);
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
  stageCv.addEventListener("pointerup", (e) => endDrag(e));
  stageCv.addEventListener("pointerleave", (e) => { endDrag(e); stageTip.classList.remove("on"); });

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
  const trueZ = (x, y) => -412 + 96 * (x / W_UM - 0.5) + 61 * (y / H_UM - 0.5);

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
    if (m.kind === "affine") return m.a * (x / W_UM - 0.5) + m.b * (y / H_UM - 0.5) + m.c;
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
    const s = Math.min((w - 2 * pad) / W_UM, (h - 2 * pad) / H_UM);
    fview.scale = s;
    fview.tx = (w - W_UM * s) / 2;
    fview.ty = (h - H_UM * s) / 2;
    fview.fitted = true;
  }

  const fToScreen = (x, y) => [x * fview.scale + fview.tx, y * fview.scale + fview.ty];
  const fToWorld = (px, py) => [(px - fview.tx) / fview.scale, (py - fview.ty) / fview.scale];

  const FIELD_W = 148, FIELD_H = 108;
  const fieldCv = document.createElement("canvas");
  fieldCv.width = FIELD_W; fieldCv.height = FIELD_H;

  function paintSurface(surf, zLo, zHi) {
    const fctx = fieldCv.getContext("2d");
    const img = fctx.createImageData(FIELD_W, FIELD_H);
    const span = zHi - zLo || 1;
    let k = 0;
    for (let j = 0; j < FIELD_H; j++) {
      const y = ((j + 0.5) / FIELD_H) * H_UM;
      for (let i = 0; i < FIELD_W; i++) {
        const x = ((i + 0.5) / FIELD_W) * W_UM;
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
    let zLo = 0, zHi = 1;
    if (showSurface) {
      // a spline can bulge between its points, so sample the field rather than
      // trusting the corners the way a plane would let you
      zLo = Infinity; zHi = -Infinity;
      for (let j = 0; j <= 12; j++) {
        for (let i = 0; i <= 16; i++) {
          const z = surfaceZ(surf, (i / 16) * W_UM, (j / 12) * H_UM);
          if (z < zLo) zLo = z;
          if (z > zHi) zHi = z;
        }
      }
      if (zHi - zLo < 1) { zLo -= 0.5; zHi += 0.5; }
    }

    // ---- the surface, as one continuous field rather than tile blocks
    if (showSurface) {
      const [sx0, sy0] = fToScreen(0, 0);
      const sw = W_UM * fview.scale, sh = H_UM * fview.scale;
      paintSurface(surf, zLo, zHi);
      ctx.save();
      ctx.globalAlpha = 0.82;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(fieldCv, sx0, sy0, sw, sh);
      ctx.restore();
    }

    // ---- the positions, exactly as the software reports them
    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const [tx, ty] = fToScreen(col * TILE_UM, row * TILE_UM);
        const sz = TILE_UM * fview.scale;
        ctx.strokeStyle = showSurface ? "rgba(255,255,255,0.30)" : css("--line-strong");
        ctx.lineWidth = 1;
        ctx.strokeRect(tx + 0.5, ty + 0.5, sz - 1, sz - 1);
      }
    }

    if (f.strategy === "auto") {
      ctx.fillStyle = css("--ink-3");
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.textAlign = "center";
      for (let row = 0; row < ROWS; row++) {
        for (let col = 0; col < COLS; col++) {
          const [tx, ty] = fToScreen((col + 0.5) * TILE_UM, (row + 0.5) * TILE_UM);
          if (TILE_UM * fview.scale > 34) ctx.fillText("AF", tx, ty + 4);
        }
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
    const col = Math.floor(wx / TILE_UM), row = Math.floor(wy / TILE_UM);
    if (col >= 0 && col < COLS && row >= 0 && row < ROWS) {
      focusTip.classList.add("on");
      const surf = focusSurface();
      const showSurface = surf && (state.focus.strategy !== "plane" || state.focus.applied);
      focusTip.innerHTML =
        `<b>position</b> r${row + 1}c${col + 1}<br>` +
        `<b>centre</b> ${(((col + 0.5) * TILE_UM) / 1000).toFixed(2)}, ${(((row + 0.5) * TILE_UM) / 1000).toFixed(2)} mm` +
        (showSurface ? `<br><b>z</b> ${surfaceZ(surf, (col + 0.5) * TILE_UM, (row + 0.5) * TILE_UM).toFixed(1)} µm` : "");
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
    if (wx < 0 || wy < 0 || wx > W_UM || wy > H_UM) return;
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
      add(`<span class="hint">${COLS * ROWS} positions × ~4 s ≈ ${Math.round(COLS * ROWS * 4 / 60)} min added to the scan</span>`);
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

  const cellsInTile = (col, row) => cells.filter((c) =>
    c.x >= col * TILE_UM && c.x < (col + 1) * TILE_UM
    && c.y >= row * TILE_UM && c.y < (row + 1) * TILE_UM);

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

    const pad = 18;
    const s = Math.min((w - 2 * pad) / TILE_UM, (h - 2 * pad) / TILE_UM);
    const ox = (w - TILE_UM * s) / 2, oy = (h - TILE_UM * s) / 2;
    const X = (x) => ox + (x - d.tile.col * TILE_UM) * s;
    const Y = (y) => oy + (y - d.tile.row * TILE_UM) * s;

    ctx.save();
    ctx.beginPath();
    ctx.rect(ox, oy, TILE_UM * s, TILE_UM * s);
    ctx.clip();

    ctx.fillStyle = "#05090e";
    ctx.fillRect(ox, oy, TILE_UM * s, TILE_UM * s);
    for (const b of blobs) {
      const g = ctx.createRadialGradient(X(b.x), Y(b.y), 0, X(b.x), Y(b.y), b.r * s);
      g.addColorStop(0, "rgba(34,211,238,0.26)");
      g.addColorStop(0.6, "rgba(34,211,238,0.09)");
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(X(b.x), Y(b.y), b.r * s, 0, Math.PI * 2); ctx.fill();
    }

    // objects are drawn larger than life: at 5x a cell is a couple of pixels,
    // and the point of this view is to judge the labels
    const inTile = cellsInTile(d.tile.col, d.tile.row);
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
    ctx.strokeRect(ox + 0.5, oy + 0.5, TILE_UM * s - 1, TILE_UM * s - 1);
    drawScaleBar(ctx, w, h, s);
  }

  function renderDetectToolbar() {
    const d = state.detect;
    for (const b of el("detect-algo").querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.algo === d.algo));
    }
    el("tile-label").textContent = `r${d.tile.row + 1}c${d.tile.col + 1}`;

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
      const inTile = cellsInTile(d.tile.col, d.tile.row);
      const found = inTile.filter(detects).length;
      out.textContent = `${found} of ${inTile.length} objects on r${d.tile.row + 1}c${d.tile.col + 1}`;
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
      let n = d.tile.row * COLS + d.tile.col + step;
      n = (n + COLS * ROWS) % (COLS * ROWS);
      d.tile = { col: n % COLS, row: Math.floor(n / COLS) };
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
    for (const c of cells) {
      if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
      const x = sx(c.area, w), y = sy(c.intensity, h);
      ctx.moveTo(x + 2, y); ctx.arc(x, y, 2, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.globalAlpha = 1;

    // gated points — larger and ringed as well as coloured
    const acquired = new Set(state.acquired);
    for (const c of cells) {
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
    for (const c of cells) {
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
    state.gated = new Set(cells
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
      const cell = cells[id - 1];
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
  focusPanelsFor(0);
  renderAll();
})();