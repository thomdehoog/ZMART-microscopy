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

## Streaming: why messages and not growing traits

A trait update always retransmits the whole value. Appending tile 25 to a
trait list would resend tiles 1–24 as well — megabytes per update, growing
with the square of the count, on the same channel the operator watches.
So streamed lists follow one rule everywhere:

- each **new** item is sent once, as a custom message
  `{"type": <kind>, "index": <position>, "entry": <item>}`;
- the matching trait holds the **full snapshot**, refreshed when a browser
  view sends `{"type": "sync"}` (every view does, on mount) and at natural
  commit points (end of a run, a reload);
- every image inside an entry is a PNG data URL kept under a fixed pixel
  budget (about 1.5 million pixels), so no single update can stall the
  channel.

A front end therefore renders `trait ∪ streamed messages`, replacing its
local list wholesale whenever the trait changes. That is exactly what the
shared `useStream` hook in `_support.py` does.

## Common to every widget

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `status` | trait (str) | Python → browser | One plain-language line for the operator. Errors land here too (`"failed: ..."`). |
| `busy` | trait (bool) | Python → browser | True while a hardware run is in progress; buttons disable on it. |
| `{"type": "sync"}` | message | browser → Python | "I just mounted — publish the full snapshot traits." |

Button-triggered runs are debounced: a request arriving within 2 seconds of
the previous run's end is ignored (clicks queue in the browser while Python
is busy, and would otherwise start a second hardware run the moment the
first finishes). Scripted runs (`gallery.acquire(...)`, `picker.measure()`)
share the same busy flag and debounce bookkeeping. A *refused* run (empty
gate, no points) never arms the debounce.

## OverviewViewerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `tiles` | trait (list) | Python → browser | Snapshot of tile entries: `{src, x0, y0, w, h, label}`, positions and sizes in frame micrometres. |
| `{"type": "tile", index, entry}` | message | Python → browser | One freshly acquired tile. |
| `channels` | trait (list) | both ways | Per-channel display state: `{color, palette, visible, lo, hi}`. The browser edits it; Python recomposites every tile PNG in response (malformed entries fall back to defaults). |

## FocusPickerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `points` | trait (list) | both ways | The picked focus points `{x, y}` (frame µm). Editing them invalidates a fitted surface. |
| `squares` | trait (list) | Python → browser | Overview tile markers `{x, y, fill}`; `fill` carries the fitted-z tint. |
| `measured` | trait (list) | Python → browser | Autofocus results so far, `{x_um, y_um, z_um}`. |
| `heatmap` | trait (dict) | Python → browser | The fitted surface as `{src, x0, y0, w, h}`. |
| `{"type": "measure"}` | message | browser → Python | Autofocus every point (cached results reused). |
| `{"type": "measure", "fresh": true}` | message | browser → Python | Forget the session's cache first — re-drive every point. |

## TargetExplorerReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `features`, `x_feature`, `y_feature` | traits | both ways | The plottable features and the current axes. Switching an axis clears the gate. |
| `dots` | trait (list) | Python → browser | `{fx, fy}` per target in the current feature space. |
| `gate` | trait (dict) | browser → Python | The operator's intent: `{x: [lo, hi], y: [lo, hi], lasso: [[x, y], ...]}` — any piece may be absent. Thresholds AND lasso gate together. |
| `gated_mask` | trait (list) | Python → browser | **Display output only.** Which dots pass the gate. Python recomputes the real decision from `gate` whenever `explorer.gated` is read, and heals this trait if anything scribbled over it. |
| `{"type": "hover", index}` | message | browser → Python | Ask for a cell's crop; answered via the `hover` trait (crops are cached). |

## AcquisitionGalleryReact

| Name | Kind | Direction | Meaning |
|---|---|---|---|
| `rows` | trait (list) | Python → browser | Snapshot of acquired pairs `{low_src, high_src, low_title, high_title}`. Published when the run commits. |
| `{"type": "row", index, entry}` | message | Python → browser | One freshly acquired pair, mid-run. |
| `gate_count`, `default_count` | traits | Python → browser | How many targets pass the gate; the count box's starting value. |
| `{"type": "acquire", count}` | message | browser → Python | Acquire `count` random gated targets. The count is validated in Python (a positive whole number) before anything moves. |

`picked` / `records` (plain Python attributes, not traits) commit only when
the whole run succeeds, and starting a new run clears them first — a failed
re-run can never leave the previous run posing as "the result".

## Embedding outside Jupyter, later

Three things to know when the time comes:

1. anywidget models speak the Jupyter widgets comm protocol; hosts exist
   for plain web pages (`@anywidget/...` front-end packages and the
   ipywidgets HTML manager) — the traits/messages above are the whole
   surface a host must carry.
2. React currently loads from the esm.sh CDN inside each widget's ESM
   module, with a visible fallback note when the browser is offline. A
   website build would bundle React instead — only `REACT_PRELUDE` in
   `_support.py` needs to change.
3. The image mathematics (compositing, cropping, pairing) lives in the
   matplotlib widget modules and is imported by the Python side here —
   a web front end never re-implements it; it only displays the PNGs it
   is handed.
