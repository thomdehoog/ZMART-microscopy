# forFable6 review: corrective web hardening and full controller-to-website workflow audit

This document answers `docs/reviews/forFable6.md`. It reviews the corrective
diff `9f13398..b993203` on branch `claude/forfable4-document-11mxsx` and then
audits the complete active target-acquisition path — controller contract,
Leica adapter boundary, both v4 notebooks, the React widgets and their
protocol, the simulation, and the plain-browser website. Nothing was fixed as
part of this review; every finding names the smallest safe fix for the
maintainer to apply.

Verdict in one paragraph: the corrective diff genuinely closes the forFable5
findings — the step-order state machine, the bounded queue with coalescing,
the request-thread cancel, the HTTP validation, and the widened curation
rollback all hold up under adversarial reading and under the reproduced test
runs. No blocker was found. Three major findings remain, none of them
regressions from the corrective diff: the web page's stand-in model never
fires local change events (so quick successive edits in the browser can
silently overwrite each other), the position-loading step converts stored
stage coordinates with the objective selected at read time (a silent overview
displacement once an objective-pair calibration is installed), and the web
flow's save step builds matplotlib figures with a GUI backend allowed on the
worker thread. Details, minors, nits, the verified-correct list, and residual
risks follow.

## Validation reproduced

Environment: Python 3.11.15 (the prompt asks for 3.10; the declared support
range is 3.10–3.12), dependencies from `requirements.txt`, Playwright with
the preinstalled Chromium.

- `pytest -q zmart_controller/tests workflows/target_acquisition/tests`:
  **326 passed, 3 skipped** of 329 collected. All three skips are
  `skimage.data` sample-image downloads blocked by this sandbox's network —
  environmental, not code. On a machine with normal network access this is
  the prompt's `329 passed`.
- `tests/test_webapp_browser.py` run three consecutive times: **2 passed**
  each time (the full operator demo and the blocked-stale-snapshot race).
- Leica driver gate (`run_ci.py --mock`): **PASSED** — junit reports 1049
  tests, 1 skipped (the expected CAM-DLL runtime skip), 0 failures, i.e.
  1048 passed. The prompt's `1030 passed` is stale — the suite has grown.
  The `--mock` run in this environment did not emit a coverage figure, so
  the ~83.2% claim was not re-verified. The known `ruff format --check`
  WARN is exactly the three baseline files (`motion/movement.py`,
  `tests/unit/test_limits_adversarial.py`, `tests/unit/test_stage_backlash.py`).
- `ruff check` and `ruff format --check` on all eight changed Python files:
  clean. `git diff --check 9f13398..HEAD`: clean.
- Both v4 notebooks parse as valid nbformat 4.
- All six generated ESM modules pass `node --check`, and none of them (nor
  the page) fetches anything from the internet — the only absolute URLs in
  the bundles are XML-namespace constants and React's error-decoder string
  used as message text.

## Findings

### Blockers

None found.

### Major

#### M1 — the web page's model stand-in never emits a local change event, so successive browser edits can silently overwrite each other

- **Where**: `workflows/target_acquisition/workflow/webapp/_page.py:268`
  (`set(name, value) { this.state[name] = value; this.pending[name] = value; }` —
  compare `applyTrait` at `_page.py:306`, which does emit).
- **Sequence**: the widget JavaScript was written against anywidget
  semantics, where `model.set` fires `change:<name>` synchronously and the
  `useTrait` hook re-renders before the next user action. In the webapp the
  React state only updates when the server echoes the trait back over the
  event stream. Every handler that builds a new trait value from the
  render-time value is therefore a stale read-modify-write: the focus map's
  add/remove point (`react/_widgets.py:903, 915`), the overview channel
  toggles (`_widgets.py:398`), and the explorer's threshold and lasso
  commits (`_widgets.py:1201–1204, 1228`). Click two focus points within
  one round trip and the second `setPoints([...points, new])` is built from
  an array that does not yet contain the first point — the first point
  vanishes, in the browser *and in Python truth*, because the second
  `/trait` post carries the stale base. The echo rides the single worker
  thread, so while a scan or acquisition is running the window is not
  milliseconds but the whole run: any two panel edits made during a long
  step keep only the last one.
- **Impact**: silently lost operator input (focus points, gate thresholds,
  channel settings). It cannot move the stage anywhere wrong — gates are
  recomputed and picks revalidated in Python at acquire time, and the
  display converges to Python truth on the echo — but the truth itself has
  quietly lost an edit the operator made.
- **Why tests miss it**: `test_react_widgets.py` drives Python directly and
  never executes the JS; the browser tests perform single awaited
  interactions and never two edits inside one round trip, never an edit
  while the worker is busy.
- **Smallest safe fix**: add `this.emit(\`change:${name}\`);` at the end of
  `ZmartModel.set` in `_page.py`. Python truth still wins afterwards — the
  echo and the `recover()` path re-apply authoritative values.

#### M2 — stored template positions are converted with the objective selected at read time, displacing the overview by the objective-pair offset

- **Where**: adapter `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/zmart_adapter.py:1004–1017`
  (`_scan_field` computes `frame = stored_stage − origin − ΔT(currently
  selected objective)`); flow order
  `workflows/target_acquisition/workflow/webapp/_flow.py:101–112` and
  `:231–259` (both v4 notebooks share the same order).
- **Sequence** (real path, dual-objective use with an objective-pair
  calibration installed — the adapter's own canonical scenario): the
  operator sets the origin and captures the overview job under the
  low-magnification objective; step 3b requires switching LAS X to the
  high-magnification target job and capturing it; step 4 (`load_positions`)
  then calls `get_positions` **while the target job is still selected**.
  The stored navigator/template positions are absolute stage coordinates
  the operator created earlier (naturally under the overview objective),
  but `_scan_field` subtracts ΔT of the *currently selected* (target)
  objective. `run_overview` then re-applies the overview job and moves with
  ΔT = 0, so every overview tile lands at `stored_stage − ΔT(target
  objective)` — displaced by the full paracentric offset between the two
  objectives (typically tens of micrometres), silently.
- **Impact**: bounded but real. I traced the downstream legs: target
  acquisition and the focus surface are *self-consistent* with the
  displaced tiles (the contamination cancels — targets land exactly on the
  cells discovered in the tiles, and the parfocal z leg re-applies
  correctly), so no cell is misidentified and no curation record lies. The
  harm is that the survey itself images a region shifted from where the
  operator marked it, by an offset that appears only when a calibration is
  installed — the better-calibrated machine behaves worse than the
  uncalibrated one, which is exactly the wrong direction for trust.
  Without a calibration the read degrades to ΔT = 0 with a warning and
  everything is consistent, so today's uncalibrated deployments are
  unaffected.
- **Why tests miss it**: the simulation models neither per-job objectives
  nor translation calibrations, so ΔT is always zero offline; the driver's
  own frame tests exercise `get_xyz`/`set_xyz` round-trips (live reads,
  where the current-objective transform is correct by design), not stored
  template coordinates read under a different selection.
- **Smallest safe fix**: this needs a maintainer decision on the
  convention (which objective anchors a stored template coordinate) rather
  than a blind patch. The least invasive workflow-level fix is to read the
  positions under the objective that will acquire them: in
  `_flow._load_positions` (and the corresponding notebook cell), apply
  `overview_state` via `session.set_state` before `get_positions`.
  Alternatively the adapter could record and honour a per-position source
  objective. Either way, one live LAS X pass should confirm whether LAS X
  itself already paracentrically compensates stored navigator positions
  (see residual risks).

#### M3 — the web flow's save step builds matplotlib figures with a GUI backend allowed, on the worker thread, and never closes them

- **Where**: `workflows/target_acquisition/workflow/webapp/_flow.py:328–334`
  calls `write_run_report(...)` without `show=False`;
  `workflows/target_acquisition/workflow/viz.py:183–189` only forces the
  Agg (no-window) backend when `show` is falsy, and `plot_frame_layout`
  never closes the figure it creates (`viz.py:189`, no `plt.close`).
- **Sequence**: on the microscope PC — Windows, standard Python with
  tkinter — matplotlib's default backend is TkAgg. `save_results` runs on
  the hub's worker thread; `plt.subplots` under TkAgg creates Tk objects on
  a non-main thread, which Tk does not support (intermittent
  `RuntimeError: main thread is not in main loop`, hangs, or crashes at
  teardown are the documented failure modes). Independently of the backend,
  `save_results` is deliberately repeatable (verdict edits are saved
  again), and each repetition leaks one open figure on the server —
  matplotlib starts warning at twenty and memory grows without bound.
- **Impact**: the operator-facing save step can wedge or crash the single
  worker on a real deployment, after the run's images are already acquired
  — the most expensive possible moment to fail. In the notebook this same
  default is correct (the figure is meant to display inline); only the
  webapp inherits it wrongly.
- **Why tests miss it**: `tests/test_webapp.py:27` pins `matplotlib.use("Agg")`
  for the whole suite, and headless Linux CI falls back to Agg anyway, so
  no test can ever meet a GUI backend.
- **Smallest safe fix**: pass `show=False` from `_flow._save_results`, and
  close the figure in `plot_frame_layout` when `show` is falsy (or have
  `write_run_report` close it for non-notebook callers).

### Minor

#### m1 — a tab's own `sync` is dropped while another tab's replay is executing, leaving it permanently missing the head of the replay

- **Where**: `workflows/target_acquisition/workflow/webapp/_host.py:198–220` —
  the coalesce key `(widget, "sync")` is held for the whole execution of
  `push_snapshot` (discarded in `apply()`'s `finally`), not just while the
  duplicate is queued.
- **Sequence**: tab A's sync replay is executing (an overview
  `push_snapshot` re-encodes every tile — seconds of work). Tab B boots
  mid-replay: its SSE client registers after tiles 0..k were broadcast, its
  `/state` snapshot carries tile metadata with empty image fields, its
  freshly mounted widget sends `{type: "sync"}` — and the host coalesces
  that sync away (returning ok), because A's is still running. Tab B shows
  blank tiles 0..k until some unrelated event triggers another replay.
- **Impact**: display-only holes in a second tab; recoverable by reloading.
- **Why tests miss it**: the coalescing test only asserts queue size while
  the worker is blocked; no test connects a client mid-replay; the browser
  tests use one tab.
- **Smallest safe fix**: discard the pending key at the *start* of
  `apply()` (before `_route_message`) instead of in `finally`. Queued-flood
  coalescing is preserved; a sync arriving during an executing replay
  schedules exactly one more. For `acquire`/`measure`, execution-time
  duplicates remain refused by the busy interlock and debounce.

#### m2 — an evicted or missing image buffer degrades to a silent, permanent blank — and a replay's leading reset revokes the good copies first

- **Where**: eviction `_host.py:160–169`; 404 `_server.py:114–119`; the
  page maps a 404 to an empty buffer (`_page.py:311–313`); `useStream`
  leaves the image field empty (`react/_support.py:270–276`) and its
  `reset` handling revokes all previously good object URLs
  (`_support.py:257–266`) before the replay that may then 404.
- **Sequence**: a lagging tab falls more than 64 MiB of broadcast buffers
  behind (a 25-tile live scan plus snapshot rebroadcasts can reach that),
  the oldest unfetched ids are evicted, and the tab's serial catch-up
  fetches 404 — producing broken/blank tiles or gallery panes with no
  message, indistinguishable from the deliberate "no image in this record"
  case. Because the replay's reset already revoked the tab's good URLs, a
  failed catch-up can *remove* images that were displaying correctly.
- **Impact**: display-only, self-heals on the next successful replay, but
  silent and confusing at exactly the moment (heavy streaming) it occurs.
- **Why tests miss it**: only the Python-side cap is tested; no test
  fetches a buffer after eviction from a page, and the demo run is far
  under the cap.
- **Smallest safe fix**: keep the previous object URL when a replay
  delivers an empty buffer for an owner key, and surface a one-line status
  note on final fetch failure (optionally retry once in `applyMsg`).

#### m3 — the Host header is never validated, so a DNS-rebinding page gets read access to the run

- **Where**: `workflows/target_acquisition/workflow/webapp/_server.py:97–124`
  (GET routes have no origin/host check) and `:74–93` (the Origin allowlist
  guards POSTs only).
- **Sequence**: a malicious website the operator visits rebinds its DNS
  name to 127.0.0.1 and then reads `/state`, `/events`, `/buffer/<id>`, and
  `/esm/*.mjs` as same-origin GETs. Writes stay blocked — per the fetch
  standard every browser POST carries an Origin header, and the rebound
  origin's hostname fails the loopback allowlist — so hardware cannot be
  driven this way. (The `test_cross_origin_and_simple_content_type_posts_are_refused`
  test covers the write side.)
- **Impact**: read-only exfiltration of run state, streamed images, and
  widget code from an operator's browser session. Low likelihood, but the
  fix is one header check.
- **Why tests miss it**: tests exercise Origin handling on POSTs; nothing
  sends a hostile Host header on GETs.
- **Smallest safe fix**: in the handler, reject requests whose `Host` is
  not `127.0.0.1:<port>`, `localhost:<port>`, or `[::1]:<port>` (when bound
  to loopback) with 403 before routing.

#### m4 — a slow SSE client is dropped silently: its tab keeps a live connection that will never carry another event

- **Where**: `_host.py:140–145` (`broadcast` removes a client whose queue
  is full) and `_server.py:138–148` (the serving loop cannot learn it was
  removed; it keeps sending keep-alive comments on a healthy socket).
- **Sequence**: a tab stalls just long enough for its 4096-event queue to
  fill while its socket stays writable. `broadcast` drops the client;
  `_serve_events` then loops on `queue.get` timeouts and keep-alives
  forever. The browser's EventSource sees a healthy stream and never
  reconnects, so the tab is permanently stale with no error anywhere.
- **Impact**: rare (needs a multi-thousand-event backlog), but the failure
  mode is the worst kind — silent staleness on a page whose whole promise
  is live truth. The stalled-socket variant self-heals via the 15 s write
  timeout; only the queue-full-with-writable-socket path is silent.
- **Why tests miss it**: no test fills a client queue while keeping its
  socket readable.
- **Smallest safe fix**: on drop, enqueue a sentinel (e.g. `None`) before
  removing the client, and have `_serve_events` close the response when it
  reads the sentinel — the EventSource then reconnects and the boot
  snapshot heals the tab.

#### m5 — explorer lasso: no pointer capture, no cancel/leave handling, no minimum-drag threshold

- **Where**: `react/_widgets.py:1213–1230` (svg pointer handlers), dot
  handlers at `:1254–1263`.
- **Sequence**: (a) a slightly sloppy click produces a pointermove, and the
  commit gate is only `moved && length >= 3`, so a ~2-pixel sliver polygon
  commits as the lasso and empties the gate; if the click landed on a dot,
  the dot is *also* picked (its `stopPropagation` stops the click event,
  not the pointer events), so one click both picks a cell and empties the
  gate, and the next "Acquire selected" refuses. (b) press inside the plot,
  drag out, release outside: no `setPointerCapture`, `onPointerLeave`, or
  `onPointerCancel` cleans up, so the trail keeps growing when the cursor
  re-enters. (The overview map handles the equivalent case with
  `onPointerLeave` at `_widgets.py:405`.)
- **Impact**: recoverable operator confusion — the gate refusals are loud
  and honest, and clearing the lasso restores the gate — but it is the kind
  of input-handling roughness that erodes trust in a curation tool.
- **Why tests miss it**: the lasso is only tested by writing the gate trait
  from Python; no test draws on the scatter.
- **Smallest safe fix**: `setPointerCapture` on pointerdown with
  `onPointerCancel`/lostpointercapture cleanup mirroring pointerup, and a
  minimum pixel-extent (say 5 px) before a lasso commits.

#### m6 — a failed boot/reconnect snapshot wedges the page in buffering mode

- **Where**: `_page.py:436–453` — `events.onopen` sets
  `applyingSnapshot = true` and awaits `applySnapshot()` with no
  try/finally; a rejected `/state` fetch (or JSON parse failure) leaves
  `applyingSnapshot` true.
- **Sequence**: the SSE stream connects but the immediately following
  `/state` fetch fails once (transient hiccup, server restart window).
  Every subsequent event is buffered forever: the page is silently frozen
  (and `bufferedEvents` grows without bound) until the stream itself drops
  and a reconnect retries.
- **Impact**: unlikely on localhost, but the failure is silent and the
  memory growth unbounded.
- **Why tests miss it**: no test fails a `/state` fetch under an open
  stream.
- **Smallest safe fix**: wrap the body of `onopen` in try/finally (reset
  `applyingSnapshot`, re-enable buttons) and retry the snapshot after a
  short delay on failure.

#### m7 — a retried disconnect can shut the analysis engine down twice

- **Where**: `_flow.py:342–349` — `_disconnect` runs `engine.shutdown()`
  then `session.disconnect()` in a `finally`. If `shutdown` raises, the
  step fails (so `disconnect` is not marked complete) but the session was
  already disconnected; the retry then calls `engine.shutdown()` again.
- **Impact**: depends entirely on whether the smart-analysis engine's
  `shutdown` tolerates a second call; the microscope side is safe
  (`Session.disconnect` is idempotent — it marks itself closed before
  calling the driver, `zmart_controller/layer.py:191–197`).
- **Why tests miss it**: no test makes `engine.shutdown` raise once and
  then retries the step.
- **Smallest safe fix**: set `self.engine = None` right after a successful
  `shutdown()` and guard the call, mirroring how the session is treated.

#### m8 — a single hardware message queued behind a long step fires much later, with no feedback that it was queued

- **Where**: `_host.py:185–220` (dispatch queues behind the worker) plus
  `react/_widgets.py:262–270` (`_debounced` only covers the two seconds
  after the *same widget's* previous run).
- **Sequence**: the focus panel's Measure button is enabled while the
  overview *step* runs (busy is per-widget). A Measure click during a
  ten-minute scan is queued — no coalescing applies (nothing of that kind
  is pending) and no status changes — and then drives the stage the moment
  the scan finishes, long after the operator forgot the click. This is
  deliberate notebook-parity ("one thing at a time, in order"), and it can
  never interleave with a run or cross an origin change; but in a notebook
  the operator can see the queued cell, and on the web page nothing shows
  the pending intent.
- **Impact**: surprising stage motion between steps; scientifically
  harmless (state is reapplied per run), operationally spooky.
- **Why tests miss it**: coalescing and debounce tests cover duplicates,
  not a single stale non-duplicate.
- **Smallest safe fix**: broadcast a small "queued behind the current
  work" status when a hardware-kind message is enqueued while the worker
  is busy — or drop hardware kinds older than a short expiry when they
  reach the front of the queue.

### Nit

#### n1 — `_hardware_run` arms busy before clearing the cancel flag

`react/_widgets.py:301–302` sets `_set_busy(True)` and then
`_cancel_requested = False`. A cancel processed on the request thread in
that microsecond window is acknowledged ("cancel requested — stopping…")
and then silently erased by the reset. Swap the two lines.

#### n2 — `recover()` and `ensureWidget` snapshots are not ordered against live events

The boot path buffers events while `/state` is applied (`_page.py:428–447`),
but the per-widget recovery snapshot (`_page.py:277–292`) and the
widget-created path (`_page.py:342–346`) apply fetched values directly: an
SSE event delivered between the server building the snapshot and the fetch
resolving can be overwritten by the older snapshot value, and a `msg` event
arriving for a widget whose module import is still in flight is dropped
(`_page.py:422–424`, optional chaining). Both windows are milliseconds on
localhost, self-heal on the next change or reconnect, and cannot forge
Python truth — worth closing only if the page grows more such paths (e.g.
route all snapshot application through one buffered helper).

#### n3 — stale documentation details

- `workflows/target_acquisition/README.md` (Layout section) says
  `_bootstrap.py` adds a `microscopes/` directory to `sys.path`; no such
  directory exists, and the actual third entry is the `target_acquisition`
  directory itself (`_bootstrap.py:15–26`).
- `_page.py:234–235` still says "the panels are self-contained dark cards";
  the shared theme has been light for a while
  (`react/_support.py:333–354`). Fix the comment before someone restyles
  against it.
- The structural notebook guards forbid `def`/`class` but not lambdas
  (`tests/test_v4_notebook.py`, `tests/test_v4_react_notebook.py`); the
  single lambda present is trivial forwarding, so this is a latent test gap
  only.

## Verified correct

Each item below was checked adversarially against the code and, where noted,
the reproduced tests.

- **Step-order state machine** (`_flow.py:101–163`). All prerequisite
  checks run at execution time on the single worker, so queue order cannot
  bypass chain order; every completed hardware step is one-shot
  (`already complete`), `save_results` alone repeats, disconnect is
  available from `connect` onward and blocks everything afterwards except
  `save_results`. Re-setting the origin after positions or focus exist is
  impossible (one-shot), so no reachable sequence applies coordinates
  across an origin change — confirmed by
  `test_origin_must_precede_every_coordinate_dependent_step`. Retry after
  failure is permitted and each step's partial-failure cleanup was traced
  (`_connect` tears down engine and session on every failure leg and only
  assigns `self.session` after full success).
- **Duplicate actions and queue pressure** (`_host.py:46–47, 74, 177–220`;
  `_flow.py:120–134`). The work queue is bounded at 256; step duplicates
  coalesce in `RunFlow._pending`; widget `acquire`/`acquire_selected`/
  `measure`/`sync` coalesce per widget; queue-full returns an actionable
  503 plus a broadcast `failed` sentence; 50 duplicate overview requests
  produced exactly one hardware run in the reproduced tests; a full queue
  recovers. No second overview/focus/target run can emerge as a
  *duplicate*; the residual single-stale-message case is m8.
- **Cancel** (`_server.py` → `_host.dispatch_message:195–197` →
  `_widgets.request_cancel:240–260`). Cancel is the only request-thread
  mutation; it reads the private busy flag and sets only the private
  cancel flag plus the status sentence; `capture_positions` checks it
  before every stage move and a cancelled run commits nothing
  (`_capture_run.py`, `RunCancelled`). It works when the worker queue is
  full because it never touches the queue. The one-microsecond arming
  window is n1.
- **Snapshot/SSE ordering, boot path** (`_server._serve_events:126–137`,
  `_page.py:398–453`). The client queue is registered before the headers
  that let EventSource report `open`; the page buffers live events during
  `/state` and replays them in order; trait events carry full new values so
  replay is idempotent; the deliberately blocked stale snapshot racing a
  newer `busy` event passes in a real browser three runs in a row. The
  widget registry is locked while snapshotting (`_host.py:108–115`).
- **HTTP validation** (`_server.py:59–93, 156–214`). Content-Length is
  parsed defensively and capped at 4 MiB; JSON parsing rejects NaN/Infinity
  and catches recursion; non-dict bodies, unknown routes/widgets/steps,
  non-string steps, and non-dict messages/changes return 400/404; trait
  writes are validated twice (request thread and worker) against synced
  names and traitlets types with no cross-validation hooks to run side
  effects; `/esm/` and `/buffer/` are dictionary lookups (no path
  traversal); slow bodies are bounded by the 15 s socket timeout; the
  worker survives any exception (`_host.py:245–255`). Cross-origin and
  wrong-content-type posts are refused (415/403, tested), and because every
  browser POST carries Origin, even DNS rebinding cannot reach a
  state-changing route (the read-only gap is m3).
- **Curation transaction** (`react/_widgets.py:2004–2071`). The corrective
  change is correct: `after_acquire` and the post-hook image re-read are
  now inside the try, so a hook failure, a hook that mutates the records
  list (the strict zip at `:2049` refuses), an image re-read failure, or a
  cancel all leave `picked`/`records`/`_verdicts`/`verdicts`/`curation.json`
  agreeing (empty), while streamed rows stay visible but uncuratable
  (`handle_message` explains instead of judging, `:1932–1935`). The strict
  zip in `save_curation` (`:1913`) is unreachable as an error because
  `capture_positions` calls `on_record` exactly once per returned record
  and returns records only on full success — verified in
  `_capture_run.py:27–79`. A smaller retry resets everything first
  (`:2009–2019`). Forged verdict traits are healed and reported
  (`_heal_verdict_trait:1868–1873`), read-only locks refuse both message
  and scripted paths, and the browser demo test drives a real verdict
  through the page.
- **Controller-adapter contract parity**. Every operation the workflow
  calls exists on `zmart_controller.Session` and in the Leica ops table:
  `run_procedure{get_root, get_positions, get_focus_points, autofocus}`,
  `set_origin`, `get_state`, `set_state`, `get_xyz`, `set_xyz`, `acquire`,
  `get_procedures`, `disconnect` (call sites in `_flow.py`,
  `_capture_run.py`, `_focus_run.py`, `react/_widgets.py`; implementations
  in `zmart_adapter.py:1091–1110` and the dispatch at `:893–919`). Return
  shapes match every consumer. The demo-only `select_job`/`OVERVIEW_JOB`/
  `TARGET_JOB` exist only on the simulated session and are guarded by
  `if self.demo`.
- **Stage-limit provenance** (`_flow.py:218–225`; gate at
  `navigator_expert` `gate.py:192–201, 305, 373`). The guard requires
  limits present, `is_fallback` false, *and* `source == "machine"`. The
  third clause is load-bearing: a ProgramData envelope seeded from the
  bundled defaults loads with `is_fallback=False` but `source="defaults"`
  and is correctly refused; only the measured-envelope notebook writes
  `source="machine"`. The guard fails closed on odd source strings.
- **Coordinate frames and teardown**. `set_origin` captures stage XY, both
  z drives, and the objective; the frame is session-scoped and never
  restored at connect; `set_xyz` pre-flights both legs of every move
  against the gated envelope before anything travels and refuses
  cross-objective moves without translations; `Session.disconnect` is
  idempotent and a closed handle refuses all hardware ops
  (`_require_open`). The one cross-objective read asymmetry is M2.
- **Simulation isolation**. `_simulation` is imported at exactly one code
  site, inside `if self.demo:` (`_flow.py:184–185`); everything else is a
  docstring or a test.
- **Notebooks**. Both v4 notebooks contain no function/class definitions,
  no driver imports, no direct Leica calls (guard tests plus direct read);
  lifecycle is explicit with failure-path disconnects; the removed
  calibration-validation step is absent from the notebooks, the run-status
  checklist (`workflow/_run_status.py`), and the web flow, while the
  standalone calibration module, its React panel, and its nine tests remain
  importable and green. The end-to-end tests execute every cell of both
  notebooks against the simulation (with `display` stubbed and button
  presses scripted from Python — the honest limits of headless testing).
- **Browser UI**. Object-URL lifecycle has zero growth per re-sync
  (per-key revocation on replace, reset, and unmount in `useStream`);
  each module ships its own vendored React 18.3.1 in a private scope with
  nothing written to `window`, so six widgets on one page cannot collide;
  the light theme sets both background and ink everywhere it draws, and
  panels are self-contained on white and black host surfaces; hover, pan,
  pick, gate, verdict, lightbox, and Escape handling were traced without
  stale-closure or listener-leak defects (the lasso roughness is m5); the
  page and modules fetch nothing external.

## Residual risks (real deployment / beyond local Chromium)

These are not code defects found in this review; they are the things that
genuinely need a real LAS X, the real smart-analysis engine, or a
non-Chromium browser to settle.

1. **The stored-position objective convention (ties to M2).** Whether LAS X
   itself paracentrically compensates stored navigator positions when jobs
   switch objectives determines the right fix direction. One bench pass:
   mark a position under the overview objective, switch to the target job,
   run `get_positions`, and compare against a live `get_xyz` at the marked
   spot under both selections.
2. **Z-drive additivity.** The adapter's own docstring still wants one
   hardware pass confirming the two z drives combine additively with the
   same sign before large z moves are trusted (`zmart_adapter.py:50–56`).
3. **The localhost/no-auth threat model.** Any local process can drive the
   microscope through the HTTP surface; that is the stated model (same
   trust as the operator's own shell), and `--host` broadening is explicit
   with a warning in `--help` — but note that a broadened bind protects
   browser POSTs (Origin allowlist) while raw non-browser clients on the
   network would have full control. A printed warning when binding
   non-loopback would make the choice unmissable. `ThreadingHTTPServer`
   also spawns one thread per connection with no cap, so a hostile local
   process can bloat memory — consistent with the threat model, worth a
   note, not a fix.
4. **Engine shutdown semantics.** m7's impact depends on the real
   smart-analysis `Engine.shutdown()` tolerating a second call; the mock
   tolerates anything.
5. **Ctrl-C on a live server.** `serve()` prints "remember to disconnect
   the session if it was live" rather than attempting an orderly
   `disconnect` (`webapp/__init__.py:39–44`). On the real instrument that
   leaves the CAM connection claimed until LAS X cleans up; an attempted
   best-effort disconnect on KeyboardInterrupt would be kinder.
6. **Non-Chromium browsers.** The SSE reconnect/replay behaviour, pointer
   events, and EventSource keep-alive handling were validated on Chromium
   only; Firefox and Safari on the microscope PC deserve one manual pass.
7. **CAM-DLL leg.** The single expected skip means the DLL-load path is
   still only proven on a machine with LAS X installed, as before.
