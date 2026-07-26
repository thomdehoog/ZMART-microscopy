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

The image fills the window. Along the bottom are sliders for moving through the
planes of a stack (Z) and the frames of a timelapse (T); each appears only if the
image actually has that axis, and each has a play button that steps through on its
own. A scale bar sits in the top-right corner and follows the zoom.

Everything else is one bar of controls down one edge, which folds away when you
want the whole screen for the specimen. It has up to four parts:

- **load data** — choose a folder to show. Left out when a workflow is deciding
  what to show (see `--no-open-button`).
- **display settings** — the histogram, black and white points, opacity and colour
  for whichever channel is picked out below. There is one set of these rather than
  one per channel: you adjust one channel at a time, and with sliders on every row
  only two or three channels fitted on a screen.
- **image data** — every acquisition type open, with its channels under it. Click a
  channel to adjust it, use the eye to hide it, drag an acquisition type by its grip
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

- **A folder being written to is fine.** Acquisitions that appear while you are
  watching are picked up on their own, usually within a second, and a timelapse
  growing in time extends its own slider as frames arrive.
- **Names carry meaning.** A store called `overview_pos001.ome.zarr` is read as
  the "overview" acquisition type at position 1, and every position of one
  acquisition type is gathered under one heading. `DATA_LAYOUT.md` explains the
  naming and why it was chosen.
- **Put the controls on the left** with `--panel-side left`, if that side is easier
  to reach at your microscope.
- **Show the selection list** with `--select` if you want to mark places.

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

## What is here

| Path | What it is |
|---|---|
| `frontend/` | The React + neuroglancer app (built into `frontend/dist`). |
| `backend/demo_data.py` | Makes the demo OME-Zarr volume. |
| `backend/server.py` | The small local web server (built page + image data + a JSON command endpoint). |
| `backend/launcher.py` | Opens the studio in a native desktop window (pywebview). |
| `backend/browsercheck.py` | Automated rendering check in a real headless browser. |
| `run_demo.py` | One command: make the demo volume and open the window. |
| `PLAN.md` | The design and the reasoning behind every choice. |
| `SPIKE_RESULTS.md` | What the spike proved, and the one open question. |

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
