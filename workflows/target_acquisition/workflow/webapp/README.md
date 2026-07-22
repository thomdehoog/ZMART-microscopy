# The ZMART web interface

The target-acquisition run from `zmart_microscopy_v4_react.ipynb`, in a
plain browser — no Jupyter, no code on screen. Each numbered section of
the page is one notebook step with a button and a sentence explaining what
it does for your experiment; the interactive panels (the live overview
map, the focus picker, the cell explorer, the acquisition gallery) are the
same widgets the notebook shows.

## Try it without a microscope

The quickest way is a double-click on `start_website_demo.bat` (Windows) in
`workflows/target_acquisition` — it starts the server and opens the page in
your browser by itself. The same from a terminal:

```
cd workflows/target_acquisition
python run_webapp.py --demo --open
```

Without `--open`, open the printed address (http://127.0.0.1:8765)
yourself. The demo drives a
simulated microscope imaging a synthetic sample — the very same one the
offline notebook tests execute — so every step behaves like the real run:
discovery really segments the tiles, and Acquire really "images" the
cells you gated.

## On the microscope PC

The recommended way is a double-click on `start_website.bat` in
`workflows/target_acquisition`: it starts the local server and opens the
page in the browser (one process does both; there is no separate frontend).
Each microscope PC keeps its own choices — which Python environment to use
and where the analysis repository lives — in a small file named
`start_website.local.bat` next to the launcher. That file is written once
per machine and is ignored by git, so pulling repository updates never
overwrites it. Example content:

```bat
set "PYTHON=C:\ProgramData\MinicondaZMB\envs\zmart-microscopy\python.exe"
set "ZMART_ARGS=--analysis-repo C:\path\to\smart-analysis"
```

The equivalent PowerShell command, if you prefer to see what runs:

```powershell
Set-Location "path\to\ZMART-microscopy\workflows\target_acquisition"
& "C:\...\envs\zmart-microscopy\python.exe" .\run_webapp.py --open `
  --analysis-repo "path\to\smart-analysis"
```

Keep the console window open while using the website. To stop safely, first
press **Disconnect** in the website and then press **Ctrl+C** in the console.
Saved experiment files remain on disk.

Use `--experiment organoid-screen` to choose the experiment folder name.
The website workflow adds the experiment hash and organizes every acquisition
under that folder.

The live command imports the workflow bootstrap in that same process to
register the Leica adapter, then every operation is performed through the
public `zmart_controller.Session` surface. The website does not call driver
functions directly.

Two things the notebook also asks of you still apply: select the overview
job in LAS X before step 3a and the target job before step 3b (the page
reminds you), and end the session with the Disconnect step.

**Restart workflow** sits beside Connect in step 1 and becomes available after
the session connects. It safely disconnects the current session, clears the
website's steps, widgets, positions, images, segmentation, and selections, and
returns to step 1; files already written remain on disk. A browser refresh or
temporary stream reconnect deliberately preserves an active run and is not a
restart.

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
