# The ZMART web interface

The target-acquisition run from `zmart_microscopy_v4_react.ipynb`, in a
plain browser — no Jupyter, no code on screen. Each numbered section of
the page is one notebook step with a button and a sentence explaining what
it does for your experiment; the interactive panels (the live overview
map, the focus picker, the cell explorer, the acquisition gallery) are the
same widgets the notebook shows.

## Try it without a microscope

```
cd workflows/target_acquisition
python run_webapp.py --demo
```

Open the printed address (http://127.0.0.1:8765). The demo drives a
simulated microscope imaging a synthetic sample — the very same one the
offline notebook tests execute — so every step behaves like the real run:
discovery really segments the tiles, and Acquire really "images" the
cells you gated.

## On the microscope PC

```
python run_webapp.py --analysis-repo C:/code/smart-analysis
```

The live command imports the workflow bootstrap in that same process to
register the Leica adapter, then every operation is performed through the
public `zmart_controller.Session` surface. The website does not call driver
functions directly.

Two things the notebook also asks of you still apply: select the overview
job in LAS X before step 3a and the target job before step 3b (the page
reminds you), and end the session with the Disconnect step.

## Safety notes

- The server binds to 127.0.0.1: the page is reachable only from the
  machine it runs on. Do not expose it to the network — it drives a
  real microscope and has no login of its own.
- State-changing routes require JSON and reject non-loopback browser
  origins. This prevents an unrelated webpage from using a cross-origin
  "simple" form/text request to press localhost's hardware buttons.
- Cancel is immediate here: unlike a busy notebook kernel, the server
  processes a Cancel click the moment it arrives, and the run stops
  cleanly before its next stage move.
- Hardware steps are ordered and one-shot: the server refuses a later
  step until its prerequisite completed, requires Set origin before any
  coordinates are cached, and coalesces duplicate clicks instead of
  queuing a second scan.
- Everything is offline: the page loads no fonts, scripts, or styles from
  the internet, exactly like the notebooks.

## How it works (for maintainers)

`workflow/react/PROTOCOL.md` documents each widget's traits and messages
and was written as the seam for exactly this front end. The pieces here:

- `_host.py` — holds the live widgets, mirrors trait changes and streamed
  messages to every open tab (server-sent events; image bytes fetched as
  binary), and applies browser edits through the same entry points a
  notebook comm update uses. All state-touching work runs on one worker
  thread — the notebook's one-at-a-time world — except cancel, which is
  applied immediately. The work queue is bounded and hardware/snapshot
  messages are coalesced so a confused or hostile local client cannot
  build a backlog of stale runs.
- `_flow.py` — the notebook's cells as guarded steps, calling the same
  public `workflow.*` and `zmart_controller` functions in the same order.
  It enforces that order independently of the page and never lets a
  duplicate pending action reach hardware.
- `_page.py` — the single HTML page, including the small JavaScript
  stand-in for anywidget's model. Live events are buffered while an
  initial/reconnect snapshot is applied, so an older snapshot cannot
  overwrite newer run state.
- `_server.py` — a standard-library HTTP server; no framework.
