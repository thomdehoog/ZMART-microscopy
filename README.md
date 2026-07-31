# ZMART-viewer

A viewer for the large, three-dimensional, multi-channel images a light-sheet or
confocal microscope produces — including while the microscope is still producing
them.

It is built on [neuroglancer](https://github.com/google/neuroglancer), which does
the hard part: it fetches only the pieces of an image you are actually looking at,
so a four-hundred-gigabyte specimen feels no heavier than a small one, and it draws
in true three dimensions on the graphics card. Neuroglancer's own interface is
switched off. Everything you see — the sliders, the channel controls, the scale bar
— is a [React](https://react.dev) interface of ours, so how the tool looks and
behaves is ours to change.

**It cannot talk to your microscope.** Places you mark are saved to a file beside
the image data, and the control software reads them from there. That separation is
deliberate and it is tested: it means this can be opened on anybody's data, on any
machine, including one next to a running experiment, with no possibility of
disturbing the instrument.

## See it working, without any data of your own

This is the quickest way to find out whether the tool suits you, and it needs no
microscope and no files:

```
python -m pip install -e ".[dev]"
python -m playwright install chromium
npm --prefix viz_studio/frontend install
npm --prefix viz_studio/frontend run build
python viz_studio/run_demo.py
```

That writes a small pretend specimen — three colours, forty-eight planes — and
opens it. Everything the controls do, you can try on that.

The two `npm` steps build the page itself, which is not kept in the repository
because it is generated. They take a couple of minutes the first time and are not
needed again unless you change the interface.

## Your own data

```
python viz_studio/run_demo.py --data /path/to/your/run
```

Point it at a single `.ome.zarr` store or at a folder holding many of them — both
work, so you do not have to know which you have. A mesoSPIM transfer is usually the
second kind: one store per tile and channel, each carrying its own position on the
stage, which is what lets them be drawn as one specimen rather than as a pile of
separate pictures.

A window of its own rather than a browser tab needs `pywebview`, which comes with
the install above. Without it the page still serves and prints an address you can
open in any browser.

## What is on screen

The image fills the window. Depth runs up the right-hand edge, the way a stack of
planes is pictured; time runs along the bottom, the way a recording is. Each slider
appears only if the image really has that axis with more than one step along it, so
a still picture is given no time slider and a single plane no depth slider. Each has
a play button that steps through on its own.

Everything else is one bar down one edge that folds away when you want the whole
screen for the specimen: what is open, the channels inside it, and the brightness
and colour controls for whichever channel you have picked.

`viz_studio/README.md` describes all of it properly.

## Watching a run as it happens

A run can write straight into images declared, empty, at the start — one per
acquisition type, sized to the ground the experiment means to cover. Nothing is
copied afterwards and the viewer holds the same few images from the first moment.
`zmart_storage` is the writer that does this. When it has written a tile, the run
says so, and the picture fills in on screen without the page reloading.

**Tiles have to butt up: the stage steps by a whole tile, and a run whose tiles
would overlap is refused when the images are declared.** Everything goes into one
image per acquisition type, and an image holds a single value per voxel, so an
overlapping tile would simply replace part of the one before it with nothing about
the picture to show for it. What that costs is real and worth knowing: microscopists
often acquire with a little overlap so that the two recordings of the shared strip
can afterwards be compared to work out where the stage *actually* put each tile.
Without overlap there is no such comparison, so a seam left by a stage that is
slightly off stays there. That is the accepted trade — resolving overlap properly
needs a real stitcher, this project has none, and a half-kept overlap that nobody
ever resolves would cost storage and complication for no correction at all.

The writer can produce either generation of the OME-Zarr format, chosen with its
`ome_zarr_version` argument. It writes `0.4` unless you ask otherwise, because that
is what almost every other tool can read today; `0.5` is the newer standard and is
where the format is going. Nothing an operator sees changes between them, and the
viewer reads both.

`viz_studio/DATA_LAYOUT.md` records how a run should be stored and why, with the
measurements behind each decision. Read it before changing anything about the layout
— several of the obvious-looking choices were tried and rejected for reasons that
are written down there.

## Running the tests

```
python -m pytest zmart_storage/tests     # the writer, about half a minute
python -m pytest viz_studio/tests        # the viewer, about eighteen minutes
```

The viewer's suite opens a real browser and looks at the pixels that came out. That
is slower than asking the engine whether it thinks it drew something, and it is the
only thing that catches the fault this project keeps meeting: a picture that is
silently absent, with everything reporting itself content.

Run it one test at a time unless the machine has more than four processors. Three
at once is much quicker where there is room, and where there is not, the browser
tests fail on starvation rather than on faults — which reads exactly like a real
problem and is not one.

## What is not finished

Written down because finding out for yourself is worse:

- **An overview and a target scan share one set of brightness and visibility
  controls**, so they cannot be adjusted apart. This is the next thing worth fixing
  and it is pinned by a failing test rather than left to be discovered.
- **A folder of many separate positions is slow to open** — around ten minutes for
  two thousand. Every position does arrive and none is lost; it simply takes that
  long. A run written into one image per acquisition type opens in seconds, which is
  the arrangement to prefer.
- **A run cannot be resumed.** Pointing the writer at a folder that already holds
  images is refused rather than allowed to overwrite them.

## Licence

MIT. See `LICENSE`.
