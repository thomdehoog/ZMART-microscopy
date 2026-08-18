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

- **load data** — opens the load window (described below), where scenes are
  loaded, built from raw data, or replayed. Left out when a workflow is
  deciding what to show (see `--no-open-button`).
- **display settings** — the histogram, black and white points, opacity and colour
  for whichever channel is picked out below. There is one set of these rather than
  one per channel: you adjust one channel at a time, and with sliders on every row
  only two or three channels fitted on a screen.
- **image data** — every acquisition open, with its channels under it. Click a
  channel to adjust it, use the eye to hide it, and the × to close an
  acquisition you are done with.
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

## The load window

The **load data** button opens a window with three tabs. In its list, one
click selects a row and highlights it, the way your operating system's own
file choosers work; a double click steps into a folder. The **Choose
folder…** button opens the system's chooser where one is available.

- **load existing scene** — the tab the window starts on. Walk to a scene
  built earlier, select it, press Open, and it appears exactly as it was.
- **build new scene** — for raw data straight from the microscope: a folder
  holding one OME-Zarr per position. Building reads as three numbered steps:
  choose the raw data, say where the scene is saved, and build. A scene is
  assembled by linking the raw data into a virtual OME-Zarr, so nothing is
  copied; ticking *include a hard copy of the low-resolution overview* also
  computes the zoomed-out picture once and keeps it as files (well under one
  percent of the data), which we recommend — the survey then opens
  instantly. A progress bar follows the build, and the finished scene waits
  for your own click on Show.
- **other** — everything else the viewer can read, opened directly: demo
  data, test runs, a scene from somewhere unusual. A folder of raw grid
  positions can also be **replayed** here: instead of appearing all at once,
  its positions land on screen one at a time through the very doorway the
  microscope uses during smart microscopy — a dress rehearsal for a live
  run, on data already on disk. The replay writes a real run into a
  `replays` folder beside the dataset, so it can be opened again later.
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

| Path | What it is |
|---|---|
| `frontend/` | The React + neuroglancer app (built into `frontend/dist`). |
| `backend/demo_data.py` | Makes the demo OME-Zarr volume. |
| `backend/server.py` | The small local web server (built page + image data + a JSON command endpoint). |
| `backend/launcher.py` | Opens the studio in a native desktop window (pywebview). |
| `backend/browsercheck.py` | Automated rendering check in a real headless browser. |
| `run_demo.py` | One command: make the demo volume and open the window. |
| `DATA_LAYOUT.md` | How a run is written to disk and shown, and why. The design record. |
| `NEXT_STEPS.md` | What is known to be unfinished or wrong, and what to pick up next. |
| `TESTING.md` | How to run the tests, and what each group of them is for. |
| `INDEX.md` | The map, if you are new: which document answers which question. |

## How the pieces talk

```
  Python (analysis, microscope control, writes OME-Zarr)
      │  serves image chunks over HTTP  +  small JSON commands
      ▼
  backend/server.py  ──►  one local address (http://127.0.0.1:8848)
      ▲
      │  reads image chunks, sends commands
  frontend (React UI + neuroglancer engine)  ──►  shown in a native window
```

Python stays the brain and the hands; the window is the eyes and the controls.
The image data travels as OME-Zarr files (only the visible pieces are fetched);
commands and results travel as small messages.
