# Review request: review-finding fixes, healed display truth, the browser interface, and the calibration-step removal

Review only the changes on branch `claude/forfable4-document-11mxsx` after
commit `5b8d9a7`. Use `git diff 5b8d9a7..HEAD` as the authoritative scope.
Do not reopen unrelated findings from earlier branch history or review the
repository generally. This is safety-adjacent code used to drive a real
Leica Stellaris 5 — and it now includes a web server whose page can press
the same buttons a notebook can — so review the scoped changes
adversarially and do not implement fixes.

The changes under review are, in dependency order:

- `zmart_controller/layer.py` (a docstring hedge on `Session.closed`)
- `workflows/target_acquisition/workflow/_discovery_widget.py`
- `workflows/target_acquisition/workflow/_run_status.py`
- `workflows/target_acquisition/workflow/react/_support.py`
- `workflows/target_acquisition/workflow/react/_widgets.py`
- `workflows/target_acquisition/workflow/react/PROTOCOL.md`
- `workflows/target_acquisition/workflow/_simulation.py` (new)
- `workflows/target_acquisition/workflow/webapp/` (new package)
- `workflows/target_acquisition/zmart_microscopy_v4.ipynb` and
  `zmart_microscopy_v4_react.ipynb` (section 5b removed)
- `workflows/target_acquisition/README.md` (step list renumbered, web
  interface pointer)
- the changed/new test files (`test_react_widgets.py`,
  `test_discovery_widget.py`, `test_v4_react_notebook.py`,
  `test_notebooks_run_end_to_end.py`, `test_webapp.py`,
  `test_webapp_browser.py`)
- `environment.yml`, `build_env.py`,
  `zmart_drivers/.../navigator_expert/requirements-dev.txt`
- `docs/reviews/v4_streaming_read_only_and_notebook_guards_review_forFable4.md`
  (the review report these fixes answer) and this prompt

## Background

The branch answers the forFable4 review prompt: a findings report
(committed as `..._review_forFable4.md`), then fixes for every confirmed
finding, then a browser front end built on the widget protocol that
PROTOCOL.md always advertised as "the seam to build a future non-notebook
front end against" — plus, at the maintainer's request, the removal of
the calibration-validation step (old section 5b) from both v4 notebooks
and from the web flow. The calibration MODULE
(`workflow/_calibration_check.py`, `wreact.calibration_report`) remains;
only the operator flows dropped the step.

## Intended fixes and features to verify

### 1. Curation integrity across freeze, cancel, and failure

`set_verdict` now refuses on a frozen gallery (`make_read_only`), so the
private `_verdicts`, the synced display trait, and `curation.json` can no
longer diverge. `_verdicts` grows WITH the streamed rows and is emptied
when a run cancels or fails; `set_verdict` bounds against `_verdicts`;
`save_curation`'s strict zip should now be structurally unable to raise.

Attack it: scripted verdicts on frozen galleries; verdicts against rows
left on screen by a cancelled run (both the scripted call and the browser
`verdict` message); a failed run followed by a smaller successful run;
the `after_acquire` hijack path; a forged `verdicts` trait longer,
shorter, and type-invalid; `save_curation` after every one of those.
Check the three lengths (records, row entries, verdicts) cannot disagree
in any reachable state, and that every refusal is a sentence an operator
can act on.

### 2. Healed display truth: `busy`, `read_only`, picks, gate, axes

The run-overlap interlock and cancel now read a private `_busy`;
`read_only` heals in BOTH directions; `picked_indices`,
`acquired_indices` and `gated_mask` heal eagerly from Python truth; an
unknown `x_feature`/`y_feature` restores the previous axis instead of
crashing `_recompute` mid-update; `_histogram` tolerates NaN feature
values; `_matching_target_indices` resolves identity in a first pass so
a copied record cannot steal an original's index in the same call; and
`useStream` skips zero-length image buffers instead of minting object
URLs to empty blobs (broken-image icons on records with no picture).

Attack it: forge every one of those traits (and combinations, in one
`set_state` call) on live and frozen widgets; try to fake a run, hide a
run, blind the buttons, hide an acquired cell, relabel the
"Acquire selected" count, crash the axis observer, and desynchronise the
linked overview map's mark colours. Check the healing observers cannot
re-enter each other (publish flags), that trusted Python-side writes
(`_init_channels` on a frozen empty viewer) survive, and that frozen
widgets still answer display-only `hover`/`mark` messages but nothing
else. PROTOCOL.md's new trust table must match the code exactly —
including its claim that the remaining cosmetic traits are unauthenticated.

### 3. The vendored-React window shim

`_vendored_react_js` now copies DOM constructors
(`HTMLIFrameElement`, `Element`, `Node`, `Event`) and bound
`getSelection`/`matchMedia` onto the private vendor scope. Without the
constructors, react-dom's selection bookkeeping
(`x instanceof window.HTMLIFrameElement`, run before every commit) threw
and EVERY widget rendered an empty cell in a real browser — a blocker
that offline tests cannot see, found by the new Chromium test.

Verify the shim still leaks nothing to the page's own `window`, that no
other `window.*` read in either vendored bundle can hit the shadow scope
unresolved (grep the minified bundles), and that the six generated ESM
modules still parse and render. The same files also switch the widget
theme to a light palette (white cards; the image viewports deliberately
stay black): sweep every remaining hardcoded colour for contrast against
its actual background — labels drawn INSIDE the black maps and the dark
lightbox must stay light, and rings/strokes on the now-light scatter must
stay dark.

### 4. The web interface (`workflow/webapp/`)

A standard-library HTTP server (no new dependencies, binds 127.0.0.1)
serves one operator page that walks the notebook's steps and embeds the
six React widgets through the PROTOCOL.md seam: server-sent events carry
trait changes and messages out (image bytes fetched as separate binary),
POSTs carry clicks and edits back through `set_state`/`_route_message`.
All state-touching work runs on ONE worker thread; cancel alone is
applied immediately on the request thread — the protocol's
concurrent-host promise.

Attack it as a hostile local page: malformed/oversized/mistyped bodies on
every POST route; path traversal on GET; forged traits over `/trait`
(they must heal exactly as in area 2 — this HTTP surface is the "website
host" the protocol's safety claims must survive on); double-clicked and
out-of-order steps; a stalled SSE client; buffer-store flooding; two tabs
syncing during a streaming run; a dropped-and-reconnected event stream
(the page re-snapshots and re-syncs). Confirm the cancel-bypass is
actually safe (it only sets `_cancel_requested` and writes `status`) and
that nothing else takes that shortcut. Confirm `RunFlow` steps refuse out
of order with operator sentences, never tracebacks, and that failure
paths in `_connect` tear down what they built. Confirm the page shows no
code, fetches nothing from the internet, and its buttons cannot fire
before the event stream is provably open (the fixed boot race).

### 5. The simulated microscope as a module

`workflow/_simulation.py` is the harness's synthetic world, session and
engine moved verbatim (plus a `closed` property mirroring the real
`Session`); the notebook end-to-end tests now import it, and the web
demo drives it. Verify the move changed no behaviour (compare against the
old in-test classes at `5b8d9a7`), that the injected 2 µm target-job
error is small enough not to disturb any remaining assertion, and that
nothing in the operator path imports the simulation unless demo mode
asks for it.

### 6. The calibration-step removal

Section 5b (start/finish_calibration_check + report panel) is gone from
BOTH v4 notebooks, from the web flow, and from the run-status checklist;
the guard test no longer pins those calls; the end-to-end harness no
longer asserts the measured offset. Verify nothing else still references
the removed step (stale "step 5b" strings, dead status rows, dead
imports), that the notebooks still execute end to end offline, and that
the calibration module itself still has its own tests and remains
callable for scripted use.

### 7. Environment honesty

`build_env.py` now import-verifies `ipympl`, `anywidget`, `nbformat`,
`nbclient`; `environment.yml` adds the two notebook-test packages;
the driver's `requirements-dev.txt` adds the traced notebook/test deps.
Verify names exist on conda-forge, the verify list matches reality, and
nothing in the runtime path gained a dependency (the webapp must import
nothing beyond the stdlib and the packages already required).

## Validation to reproduce

With `nbformat`/`nbclient`/`ipykernel` installed (they are now pinned in
the env files precisely because the notebook tests silently skip without
them):

```text
pytest -q zmart_controller/tests workflows/target_acquisition/tests
```

should report **318 passed** (317 plus a skip-or-pass for the optional
real-browser test: it runs only where the `playwright` package and a
Chromium are available, and must skip cleanly elsewhere). The Leica
driver's canonical offline gate is unchanged by this diff:

```text
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py --mock
```

reports RESULT: PASSED (1048 passed + 1 expected CAM-DLL skip, ~86 %
coverage; `ruff format --check` still flags only the three known
baseline files). Independently: syntax-check the six generated ESM
modules with Node, run `ruff check` / `ruff format --check` on the
changed Python files, `git diff --check`, and — if a browser is
available — run `test_webapp_browser.py` several times in a row; it was
made deterministic (buttons gated on the event stream, auto-retrying
image counts) and any flake you can reproduce is a finding.

Known out-of-scope baseline: the three driver ruff-format files, and the
retired pre-controller workflow suite.

## Deliverable

Report findings ordered blocker / major / minor / nit. Every finding
must have an exact `file:line`, a concrete failing sequence, impact, why
the present tests miss it, and the smallest safe fix. Pay special
adversarial attention to the web surface: it is new, it is the first
non-Jupyter host of these widgets, and its threat model (any local page
script, any confused client) is exactly what areas 1–2 claim to survive.
Then give a short verified-correct section and a residual-risk section
containing only what genuinely requires a live LAS X microscope or
testing beyond a local Chromium. If there are no findings, say so
explicitly without inventing style work.
