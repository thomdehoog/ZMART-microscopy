# ZMART Viz Studio

A visualization tool for large, three-dimensional, multi-channel microscopy
images — the kind the Stellaris and mesoSPIM produce — that runs as its own
desktop window and is built entirely from web technology, so **you** own how it
looks and behaves.

Under the hood it uses [neuroglancer](https://github.com/google/neuroglancer)
as the image engine (it streams only the pieces of a huge volume you are
looking at, so even very large data feels light, and it does true 3-D), wrapped
in a [React](https://react.dev) interface that is entirely ours to shape. The
analysis stays in Python; this tool is the view and the controls.

It does not talk to the microscope, and cannot. Places you mark on an image are
saved to a file beside the data, and the control application reads them from
there. That separation is deliberate: it means the viewer can be opened on
anybody's data, on any machine, including one sitting next to a running
experiment, with no possibility of it disturbing the instrument.

## What is on screen

The image fills the window. Two sliders move you through it, and each is placed to
match the direction the thing it moves through lies in: **depth (Z) stands upright
along the right-hand edge**, the way a stack of planes is pictured, and **time (T)
lies along the bottom**, the way a recording is. That way you can reach for the
right one without stopping to read the labels, which matters when both are on
screen and one hand is on the stage.

Each appears only if the image really has that axis with more than one step along
it, so a still picture gets no time slider and a single plane no depth slider. Each
has a play button that steps through on its own. A scale bar sits in the top-right
corner and follows the zoom.

Everything else is one bar of controls down one edge, which folds away when you
want the whole screen for the specimen. It has up to four parts:

- **load data** — choose a folder to show. Left out when a workflow is deciding
  what to show (see `--no-open-button`).
- **display settings** — the histogram, black and white points, opacity and colour
  for whichever channel is picked out below. There is one set of these rather than
  one per channel: you adjust one channel at a time, and with sliders on every row
  only two or three channels fitted on a screen.
- **image data** — every acquisition open, with its channels under it. Click a
  channel to adjust it, use the eye to hide it, drag an acquisition by its grip
  to change which is drawn on top.
- **selection** — the places you have marked. Off unless asked for (`--select`).

## Opening your own data

Point the viewer at a folder of OME-Zarr stores:

```
python run_demo.py --data /path/to/your/run
```

That may be a single `.ome.zarr` store or a folder holding many of them — both
work, so you do not have to know which you have. If nothing is found, the viewer
says so and suggests the folder above or below.

A few things worth knowing:

- **A folder being written to is fine.** Positions that appear while you are
  watching are picked up on their own, usually within a second, and a timelapse
  growing in time extends its own slider as frames arrive.
- **Many positions can be shown as one picture, without copying any of them.** A
  folder of a few thousand stores is slow to open as a few thousand pictures,
  because the drawing engine gives each of them part of every frame. If the run has
  a *view* built beside it — a small file saying which piece of the picture is which
  piece of which tile — the viewer opens it as one image instead, and the number of
  positions stops mattering: a hundred and six thousand four hundred draw at the
  same rate and open in the same second. Nothing is copied; the tiles stay exactly
  as the microscope wrote them and stay readable by anything else. The top-level
  `README.md` shows how to build one, under "One picture out of many stores".
- **One folder, one acquisition.** What you open becomes a single heading in the
  panel, named after the folder you chose, and every store in it feeds it — the
  positions of a tiled overview are pieces of one specimen, so they are drawn as
  one picture. Which stores belong together is read from the stores themselves,
  not from their names: an overview and a close-up target scan were taken at
  different magnifications, and that is recorded inside each store where nobody
  can rename it. If the folder you pick already holds two of them, the viewer
  says so and lists both, so you can point it at the one you wanted.
- **A second kind of scan appearing during a run gets its own heading.** While a
  run is being watched, a target scan written into the same folder as the overview
  is not added to it — it is a different picture at a different magnification, and
  merging the two would leave you one row, one eye and one set of brightness
  controls for both. It appears as a heading of its own instead, named after the
  kind of scan, with its own controls and its own close button.
- **Names are used for labels, not for grouping.** `Ch488` in a store's name gives
  a row its name and its false colour, and `Tile0` and the filter block keep the
  labels short and distinct (that is also what `--tiles` and `--filter` select on).
  `DATA_LAYOUT.md` records how a run is written to disk and why.
- **Put the controls on the left** with `--panel-side left`, if that side is easier
  to reach at your microscope.
- **Show the selection list** with `--select` if you want to mark places.
- **Say `--static` for a run that has finished.** The viewer then stops looking for
  new acquisitions and new frames, and lets your browser keep its own copy of the
  image — which is what makes moving around yesterday's data feel instant. Leave it
  off while an experiment is still producing data, or new acquisitions will not
  appear until you reopen the viewer.
- **Set the brightness yourself** with `--range LOW,HIGH` if the measured one does
  not suit your specimen. Without it the viewer uses the window your store asks
  for, or measures one from the smallest copy of the image.
- **If the viewer will not start, it is usually the port.** The viewer answers on
  8848, and it cannot start if something else on the machine is already using that
  number — most often a copy of the viewer you left open. It will say so and
  suggest what to do. To run a second one alongside the first, or to get past
  other software that has taken 8848, give it another number:

  ```
  python run_demo.py --data /path/to/your/run --port 8849
  ```

  Any free number between 1024 and 65535 will do, and `--port 0` lets the machine
  pick one for you and prints which it chose.

## Try the demo (no microscope needed)

The demo makes a small pretend 3-D, three-colour volume so you can try
everything with no hardware.

```bash
# 1. Set up the environment (Python + the build tools)
conda env create -f environment.yml
conda activate zmart-viz

# 2. Build the viewer page (once)
npm --prefix frontend install
npm --prefix frontend run build

# 3. Launch it
python run_demo.py
```

A native window opens on the demo volume. On Windows it uses the built-in
WebView2 engine (Chromium), so the 3-D rendering runs on your graphics card. If
a native window cannot open, the address is printed so you can open it in a
browser instead.

## Try the time slider

If your data is a timelapse — the same specimen imaged repeatedly — the viewer
offers a **T** slider under the image to step through the frames, in exactly the
same way the **Z** slider steps through the planes of a stack. Each slider
appears only when the image actually has that axis, so a single-moment volume
shows just Z, and a flat overview shows neither. Nothing to configure.

To see it on the demo, ask for a few frames:

```bash
python run_demo.py --timepoints 5
```

That writes a second demo store beside the ordinary one (your single-volume demo
is left alone) in which the cells drift a little and one marker brightens while
the other fades, so moving the slider visibly does something.

## Marking targets for the control application

Draw a point or a box around something interesting and give it a name. The marks
are saved to `zmart-annotations.json`, in the same folder as the images, a moment
after you make them — there is no save button to remember.

The viewer does not move the microscope, and cannot. It has no connection to an
instrument at all. Acting on a target — driving the stage there, starting an
acquisition — belongs to the control application, which reads that same file. The
separation is deliberate rather than unfinished: it means this viewer can be
opened on anyone's data, on any machine, including one sitting next to a running
experiment, with no possibility of it disturbing anything.

## Telling an open viewer that new data has arrived

If you are writing the script that runs the experiment, this is the part that
concerns you. When an acquisition has finished writing, say so:

```python
import json, urllib.request

def announce(port=8848):
    """Tell an open viewer to look again. Returns how many windows were told."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=json.dumps({}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as answer:
        return json.load(answer)["told"]
```

Every open window then re-reads what is on disk, so a new position appears and a
timelapse that has gained a frame gets a longer time slider. You do not have to
say *what* changed — the viewer reads that from the files, which keeps the data on
disk the single description of the experiment that has to be right.

The answer tells you how many windows heard you. Nought is not an error; it means
nobody has the viewer open, and your script should carry on regardless.

Announcing is not compulsory. The server also watches the folder and notices
changes on its own, which is what makes the viewer work with a microscope that
writes its own files and has never heard of ZMART. But announcing is better: the
watching can only ever *infer* that a write has finished, and your script knows.

To put a whole new folder on screen — rather than nudge the viewer about one it is
already showing — post the path to `/api/stores/open` instead.

## Check that it really renders

The acceptance test drives a real headless browser and asserts that pixels
arrived, not merely that the page loaded. It needs a one-time browser download:

```bash
playwright install chromium
python backend/browsercheck.py     # 0 = rendered, 1 = did not, 2 = could not run
```

It prints a per-check table and writes a screenshot to `backend/_check/render.png`.
Read the `RESULT:` line rather than the exit status alone — exit 2 means the
check could not run (page not built, no browser), which is neither a pass nor a
regression.

If your machine restricts where executables may run (AppLocker/SRP, common on
managed lab PCs), send the browser download somewhere allowed *before* the two
commands above, or Chromium will download fine and then fail to start with
`spawn UNKNOWN`:

```bash
set PLAYWRIGHT_BROWSERS_PATH=C:\some\allowed\path\ms-playwright
```

If the machine already has a Chromium and you would rather use that one — because
the download is blocked, or the browser it wants is not the one that is there —
name it and both the check above and the test suite will use it:

```bash
set ZMART_CHROMIUM=C:\some\allowed\path\chrome.exe
```

## What is here

The tool is three parts that meet over HTTP: a **writer** that puts images on
disk, a **server** that answers for them, and a **page** — the GUI — that draws
them. Each part runs without the others knowing its internals, which is why any
of them can be worked on alone. Everything not listed here is a test, a
measurement script, or a document.

### The server — `backend/`, and `building/` for transfers

What runs on your machine and answers the browser's requests.

| Path | What it is |
|---|---|
| `backend/server.py` | The heart: one local web server for the built page, the image data, and the small JSON commands. `make_server(...)` is the entry point. |
| `backend/stores.py` | Reads what an image on disk *is* — axes, sizes, zoomed-out copies, which generation of zarr — so the page can be told before it asks for a single pixel. |
| `backend/linking.py` | Answers for a **linked view**: a picture that was never written down. It looks a requested piece up in the view's map and hands over the position's own file, unchanged. |
| `backend/library.py` | Knows which acquisitions live in the opened folder, so the panel can list them. |
| `backend/contrast.py` | Measures how bright an image is, from its smallest copy, so it opens looking sensible rather than black. |
| `backend/announcements.py` | Tells an open viewer that a live run has grown, so the picture fills in while the microscope is still going. |
| `backend/live_config.py` | The settings for that live following. |
| `backend/launcher.py` | Opens the studio in a native desktop window instead of a browser tab (optional; needs pywebview). |
| `backend/browsercheck.py` | Checks the browser can really draw what the engine needs. |
| `backend/demo_data.py` | Makes the demo specimen. Only the demo needs it. |
| `run_demo.py` | One command: make the demo specimen and open the window. |
| `building/` | The other way of serving: a **transfer** from another microscope — tiles at awkward positions, in awkward pieces — is shown as one picture by *assembling* each requested piece from the tiles' own chunks, nothing rewritten. `serve_a_transfer.py` is the entry point; `composer.py` assembles, `mosaic.py` places tiles where the micrometres say, `declare.py` describes the virtual picture, `served.py`/`server.py` answer for it, `check.py` and `check_the_pyramid.py` prove it against the tiles. |

### The writer — `../zmart_storage/`

What an acquisition imports to put images on disk. It never talks to the
viewer; it writes files the viewer (and napari, and Fiji) can read.

| Path | What it is |
|---|---|
| `../zmart_storage/canvas.py` | The foundation: declares and writes OME-Zarr images — the picture, its zoomed-out copies, its channels, where it sits on the stage. |
| `../zmart_storage/positions.py` | A run's writer: each position lands as its own image and the one picture grows over them. `start_a_run(...)` is what an acquisition calls. |
| `../zmart_storage/linked.py` | Builds **linked views** — one picture that is a list of pointers into the positions, with nothing copied at full size. `link_the_tiles(...)` after a run, `start_a_growing_view(...)` during one. |
| `../zmart_storage/cropped.py` | The older arrangement that copies tiles into a trimmed canvas. Still the measured control the linked view is proven against. |
| `../zmart_storage/coverage.py` | The record of which ground a run has imaged, kept beside the images. |

### The GUI — `frontend/`

The page the operator sees. The browser never runs these files directly:
`npm --prefix frontend install && npm --prefix frontend run build` compiles
them into `frontend/dist/`, and that folder is what the server serves. A fresh
checkout without `dist/` has a working server and no page.

| Path | What it is |
|---|---|
| `frontend/src/main.jsx`, `src/App.jsx` | The page itself and its layout. |
| `frontend/src/NeuroglancerView.jsx` | Hosts the neuroglancer drawing engine inside the page. |
| `frontend/src/engine.js`, `src/scene.js` | The glue to the engine: builds its layers from what the server describes, applies every setting, keeps the state. |
| `frontend/src/LayerPanel.jsx` | The control bar: acquisitions, channels, brightness, contrast, opacity, colours. |
| `frontend/src/AxisSlider.jsx` | The depth and time sliders. |
| `frontend/src/ScaleBar.jsx` | The scale bar that follows the zoom. |
| `frontend/src/TargetsPanel.jsx` | Marking places for the control application to read. |
| `frontend/src/live-refresh.js` | Listens for the server's announcements and refreshes a live run. |
| `frontend/src/engine-chrome.css` | How it all looks. |
| `frontend/package.json` | Declares the JavaScript dependencies (`package-lock.json` pins them). |

### The documents

| Path | What it is |
|---|---|
| `DATA_LAYOUT.md` | How a run is written to disk and shown, and why. The design record. |
| `LINKING_INSTEAD_OF_COPYING.md` | Showing a run without copying it: what is built, measured, and still open. |
| `HANDOVER_overlapping_runs.md` | The map of the other documents, if you are picking this work up. |
| `NEXT_STEPS.md` | What is known to be unfinished or wrong, and what to pick up next. |
| `TESTING.md` | How to run the tests, and what each group of them is for. |
| `INDEX.md` | The map, if you are new: which document answers which question. |

## How the pieces talk

```
  the writer (zmart_storage — an acquisition, or your own script)
      │  puts OME-Zarr images on disk; never talks to the viewer
      ▼
  images on disk  ◄─────────────┐
      │                         │ a linked view's pieces are the
      ▼                         │ positions' own files, handed over
  backend/server.py  ──►  one local address (http://127.0.0.1:8848)
      ▲       (backend/linking.py answers for linked views;
      │        building/ assembles transfers piece by piece)
      │  reads image pieces, sends commands
  frontend (React UI + neuroglancer engine)  ──►  shown in a native window
```

Python stays the brain and the hands; the window is the eyes and the controls.
The image data travels as OME-Zarr pieces (only the visible ones are fetched),
and the browser never learns whether a piece was read from a written picture,
handed over from a position's own file, or assembled on the spot — which is why
ten thousand positions open exactly as fast as one. Commands and results travel
as small messages.
