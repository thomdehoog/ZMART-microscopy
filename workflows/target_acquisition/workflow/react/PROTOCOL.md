# The React widgets' wire protocol

This file documents how the browser half and the Python half of each React
widget talk to each other. It exists so the widgets can one day be embedded
outside Jupyter (for example in a website) with as little friction as
possible: everything a front end needs is listed here, and nothing else is
part of the contract.

## The model in one paragraph

Each widget is an [anywidget](https://anywidget.dev) — a Python object whose
state lives in **traits** (named values kept in sync between Python and the
browser) plus **messages** (small one-off packets either side sends). The
browser only ever *asks* for things; Python alone drives the microscope,
and every stage move still passes the controller session's safety gating.
Nothing the browser sends — a message or a trait write — is trusted:
Python validates counts and indices, recomputes gating decisions from the
raw inputs at the moment they matter, and treats malformed values as
absent rather than raising mid-update.

## The React runtime is vendored

The official MIT-licensed production builds of react and react-dom 18.3.1
ship inside the Python package (`vendor/`) and are evaluated into a private
scope in the browser (never onto the page's own `window`, which runs a
different React). No CDN, no internet requirement, no third-party code
fetched into a page whose buttons drive a real microscope. A website build
can keep this or swap `REACT_PRELUDE` in `_support.py` for its own bundle —
that is the only place the runtime is wired.

## Streaming: messages for new items, buffers for pixels

A trait update always retransmits the whole value. Appending tile 25 to a
trait list would resend tiles 1–24 as well — megabytes per update, growing
with the square of the count, on the same channel the operator watches.
So streamed lists follow one rule everywhere:

- each **new** item is sent once, as a custom message
  `{"type": <kind>, "index": <position>, "entry": <item>, "buffer_keys": [...]}`
  whose image pixels ride as **binary buffers** (raw PNG bytes, in
  `buffer_keys` order — about a quarter smaller than base64 and no
  encode/decode work); the browser turns each buffer into an object URL
  and revokes it when a snapshot replaces it;
- the matching trait holds the **full snapshot** (data URLs there, since
  traits are JSON), refreshed when a browser view sends `{"type": "sync"}`
  (every view does, on mount) and at natural commit points (end of a run,
  a reload);
- every image is kept under a fixed pixel budget (about 1.5 million
  pixels), so no single update can stall the channel.

A front end renders `trait ∪ streamed messages`, replacing its local list
wholesale whenever the trait changes. That is exactly what the shared
`useStream` hook in `_support.py` does.

## Common to every widget

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `status` | trait (str) | Python → browser | One plain-language line for the operator. Errors land here too (`"failed: ..."`). |
| `busy` | trait (bool) | Python → browser | True while a hardware run is in progress; buttons disable on it. |
| `read_only` | trait (bool) | Python → browser | Display mirror of observer mode (buttons hide). The LOCK is Python-private state set by `make_read_only()` — rewriting this trait from the page does not re-enable hardware. |
| `{"type": "sync"}` | message | browser → Python | "I just mounted — publish the full snapshot traits." |
| `{"type": "cancel"}` | message | browser → Python | Ask a running loop to stop before its next site. Cooperative and clean: the current site finishes, nothing is committed, no further move fires (`RunCancelled`). Honesty note: under classic Jupyter the kernel may only process the click when it next comes up for air; a website host that handles messages concurrently gets immediate cancellation through this same path. When no run is active, the status line says so. |

Button-triggered runs are debounced: a request arriving within 2 seconds of
the previous run's end is ignored (clicks queue in the browser while Python
is busy, and would otherwise start a second hardware run the moment the
first finishes). Scripted runs (`gallery.acquire(...)`, `picker.measure()`)
share the same busy flag, read-only lock, and debounce bookkeeping. A
*refused* run (empty gate, no points) never arms the debounce.

## OverviewViewerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `tiles` | trait (list) | Python → browser | Snapshot of tile entries: `{src, x0, y0, w, h, label}`, positions and sizes in frame micrometres. |
| `{"type": "tile", index, entry}` + buffer | message | Python → browser | One freshly acquired tile (PNG in the buffer). |
| `channels` | trait (list) | both ways | Per-channel display state: `{color, palette, visible, lo, hi}`. The browser edits it; Python recomposites every tile PNG in response (malformed entries fall back to defaults). |
| `marks` | trait (list) | Python → browser | Discovered cells overlaid on the map: `{x, y, gated}`. Kept live against the linked explorer's gate (`show_targets(targets, explorer)`). |
| `{"type": "mark", index}` | message | browser → Python | Ask for a marked cell's crop; answered via the `mark_hover` trait (cached). |

Python-side extras (not wire protocol, but part of the operator surface):
`save_display(path)` / `load_display(path)` persist the channel settings
across kernel restarts.

## FocusPickerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `points` | trait (list) | both ways | The picked focus points `{x, y}` (frame µm). Editing them invalidates a fitted surface. |
| `squares` | trait (list) | Python → browser | Overview tile markers `{x, y, fill}`; `fill` carries the fitted-z tint. |
| `measured` | trait (list) | Python → browser | Autofocus results so far, `{x_um, y_um, z_um, residual_um}` — the residual is how far the point sits from the fitted surface (one large residual = one bad autofocus bending the fit; the status line names the worst). |
| `heatmap` | trait (dict) | Python → browser | The fitted surface as `{src, x0, y0, w, h}`. |
| `{"type": "measure"}` | message | browser → Python | Autofocus every point (cached results reused). |
| `{"type": "measure", "fresh": true}` | message | browser → Python | Forget the session's cache first — re-drive every point. |

## TargetExplorerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `features`, `x_feature`, `y_feature` | traits | both ways | The plottable features and the current axes. Switching an axis clears the gate. |
| `dots` | trait (list) | Python → browser | `{fx, fy}` per target in the current feature space. |
| `hist` | trait (dict) | Python → browser | 20-bin distribution backdrops for the current axes (`{"x": [...], "y": [...]}`, peak-normalized) so thresholds are set against the data, not blind. |
| `gate` | trait (dict) | browser → Python | The operator's intent: `{x: [lo, hi], y: [lo, hi], lasso: [[x, y], ...]}` — any piece may be absent. Thresholds AND lasso gate together. |
| `gated_mask` | trait (list) | Python → browser | **Display output only.** Which dots pass the gate. Python recomputes the real decision from `gate` whenever `explorer.gated` is read, and heals this trait if anything scribbled over it. |
| `{"type": "hover", index}` | message | browser → Python | Ask for a cell's crop; answered via the `hover` trait (crops are cached). |

Python-side extras: `save_gate(path)` / `load_gate(path)` persist the whole
gate (axes + thresholds + lasso) — a repeat experiment's thresholds, one
file away.

## AcquisitionGalleryReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `rows` | trait (list) | Python → browser | Snapshot of acquired pairs `{low_src, high_src, low_title, high_title, position_label}`. Published when the run commits. |
| `{"type": "row", index, entry}` + 2 buffers | message | Python → browser | One freshly acquired pair (both PNGs as buffers). |
| `gate_count`, `default_count` | traits | Python → browser | How many targets pass the gate; the count box's starting value. |
| `verdicts` | trait (list) | Python → browser | Per-row curation: `"good"` / `"bad"` / null — the operator's QC record. |
| `{"type": "acquire", count}` | message | browser → Python | Acquire `count` random gated targets. The count is validated in Python (a positive whole number) before anything moves. |
| `{"type": "verdict", index, value}` | message | browser → Python | Set one row's verdict (validated; out-of-range or unknown values are ignored). |

`picked` / `records` (plain Python attributes, not traits) commit only when
the whole run succeeds, and starting a new run clears them — and the
verdicts — first: a failed re-run can never leave the previous run posing
as "the result". `save_curation(root)` writes the verdicts to
`curation.json` in the run folder.

## RunStatusReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `rows` | trait (list) | Python → browser | The checklist: `{label, state: "ok"|"todo"|"warn", detail}` per step. |

Built by `refresh(globals())` from the notebook's own variables; it never
touches hardware. (The matplotlib edition prints the same rows via
`workflow.print_run_status(globals())`.)

## CalibrationReportReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `report` | trait (dict) | Python → browser | The dict `finish_calibration_check` returns (sites, means, scatter). |
| `acceptable_um` | trait (float) | Python → browser | Optional tolerance; when set, the panel states outright whether the calibration is good enough (0 = no verdict). |

## Embedding outside Jupyter, later

Three things to know when the time comes:

1. anywidget models speak the Jupyter widgets comm protocol; hosts exist
   for plain web pages (`@anywidget/...` front-end packages and the
   ipywidgets HTML manager) — the traits/messages above are the whole
   surface a host must carry, including binary buffers on custom messages.
2. The React runtime is already vendored and page-isolated; a website
   build may keep it as-is or swap `REACT_PRELUDE` in `_support.py` for
   its own bundle — nothing else changes.
3. The image mathematics (compositing, cropping, pairing) lives in the
   matplotlib widget modules and is imported by the Python side here —
   a web front end never re-implements it; it only displays the PNGs it
   is handed. A host that processes messages concurrently also gets
   working mid-run cancellation for free (see the `cancel` message).
