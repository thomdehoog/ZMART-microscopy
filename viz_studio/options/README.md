# Comparing three ways to draw the flat view

Three viewers, one interface, one measurement suite. `viz_studio/OPTIONS.md` says
why; `contract.md` beside this file says exactly what an option has to do;
`RESULTS.md` holds the numbers.

```
options/
  contract.md              the interface, restated beside the code — read this first
  RESULTS.md               the table, one column per option
  harness/                 the page that drives any option, and the shapes it draws
  neuroglancer-under/      option A: neuroglancer underneath, the operator's drawing on top
  viv-under/               option B: Viv and deck.gl underneath, the same way up
  viv-inside/              option C: one canvas, with Viv's layers and the operator's in it
  measure/                 the suite, run against each option in turn
  measurements/            what the last run produced: photographs and full readings
```

## How the three are laid out inside

The three `viewer.js` files are written to the same plan, so that reading one
after another is easy and a difference between them stands out. Each has its
sections in this order, with the same headings:

| | |
| --- | --- |
| `openViewer` | the one thing the file exports, and what it refuses |
| the surfaces | two canvases for A and B, one for C |
| opening the acquisitions | addresses, voxel sizes, and where to look first |
| the little program that runs on the graphics card | how stored numbers become colour |
| what the engine is asked to draw | the layers, and what is deliberately not asked for |
| micrometres in, micrometres out | the one place an engine's own units are converted |
| the operator's own drawing | where the page's two drawing functions are called |
| going back to the store | what "a tile may have arrived" comes to for this engine |
| the handle | everything a page may call, and nothing else |

Option A has no "what the engine is asked to draw" section of its own, because
neuroglancer builds its layers from the description it is handed rather than from
a list this file makes each frame; that happens inside `start`.

**Two of the files share code by copying it.** Five helpers are word for word the
same in `neuroglancer-under/viewer.js` and `viv-under/viewer.js`, because those
two are the same arrangement with a different engine in the middle and the parts
that are not about the engine have to stay identical. Copies can drift, so each
file says which five they are and asks that both be changed together.

Putting them in one shared module instead would be the obvious cure, and it has
not been done, because it is a real decision rather than a tidy-up. A shared
module means one edit changes two columns of the results table at once, which is
exactly the kind of silent coupling this comparison exists to avoid — the numbers
would move together and nobody would know whether that was the engines or the
shared file. If the comparison is ever settled and one option is chosen, sharing
becomes plainly right; while all three are being weighed, the copies are honest.

**And all three share one more block the same way.** The four little functions
that read a run's own description of its colours — under the heading "What the
run says about its own colours" — are word for word the same in every option,
because reading a description is not a property of a drawing engine and three
options that read it differently would look like three engines behaving
differently. `contract.md` §6 says what they are for.

## Running it

Build the page once. It borrows the viewer's own installed packages rather than
keeping a second copy, so the engine being compared is the exact version the
viewer ships:

```
npm --prefix viz_studio/frontend install       # only if you have not already
npm --prefix viz_studio/options/harness run build
```

Then take the measurements:

```
python viz_studio/options/measure/run.py --option neuroglancer-under
python viz_studio/options/measure/run.py --option all
```

It writes photographs and a full set of readings into `measurements/`, and brings
the table in `RESULTS.md` up to date. It takes about three minutes per option on a
machine with no graphics card. Rather more than half a minute of that is
measurement 7, which takes its reading five times over and reports the middle one
— a single reading of the drawing rate is worth very little, and `RESULTS.md`
says why under row 7.

## Looking at it yourself

The harness is an ordinary page. Serve it and open it with a word in the address
to choose the option — **no rebuild between one option and the next**, which is
the whole point:

```
python - <<'EOF'
import sys; sys.path.insert(0, "viz_studio/options/measure")
from data_server import Ledger, make_measurement_server
from pathlib import Path
import acquisitions
data = Path("/tmp/zmart-options"); acquisitions.write_them_all(data)
server = make_measurement_server(
    port=8850, site_dir=Path("viz_studio/options/harness/dist"),
    data_dir=data, ledger=Ledger())
print("http://127.0.0.1:8850/?option=neuroglancer-under&draw=carrier&store=scattered")
server.serve_forever()
EOF
```

The words the address takes:

| | |
| --- | --- |
| `option=` | which of the three draws the picture |
| `store=` | `square`, `lopsided`, `sparse`, `scattered`, `fine`, `colours`, or the pair `survey` and `detail` |
| `alsoStore=` | a second acquisition, opened beside the first and drawn over it. `store=survey&alsoStore=detail&draw=none&bounded=0&channels=fromTheStore` is the ordinary shape of a run — a wide coarse scan in green with a fine one in red over the part of it worth looking at closely |
| `channels=fromTheStore` | say nothing to the option about the run's colours, so that it reads the run's own description instead. Worth trying with `store=colours`, which is recorded in two |
| `draw=carrier` | the operator's real drawing, all on one sheet above the picture with holes cut in it |
| `draw=threeLayers` | the same scene taken apart into the three layers of `THE_CANVAS.md`: the carrier and a background pattern beneath the picture, the tiles above it |
| `draw=margin` | the measuring instrument: a sheet with a hole cut around the picture |
| `draw=none` | nothing over the picture at all |
| `positions=` | how many tile rectangles the operator laid out |
| `bounded=0` | give the engine the whole window instead of only the imaged ground |
| `data=` | where the acquisitions are served from |

**Press `o` to change engine without losing the view.** The centre, the
magnification, the plane, the moment and the channel settings are all carried
over, so the same view can be looked at through two engines one after the other —
which is the only way to see a difference that is small. Try it with
`draw=threeLayers`: the ground beneath the picture is plainly there under either
Viv option and plainly absent under neuroglancer, whose canvas is opaque. The
corner of the window says which engine is drawing and what it does with the bottom
layer.

One pair cannot be swapped this way and the page says so rather than going blank.
The two Viv options are installed from two different lists of packages, and deck.gl
refuses to have two versions of itself alive in one page; asked to change from one
straight to the other, the harness puts the working engine back on the same view
and writes the reason in the corner. Pressing `o` again reaches the third. A fresh
page reaches any of them.

## The checks

`viz_studio/tests/test_the_options_hold_together.py` holds the promises every
option has to keep — micrometres, two gestures, addresses passed in, two viewers
on one page, the engine kept behind its adapter, an honest answer about whether
the bottom layer is really beneath the picture, a run's own colours being read
when the page says nothing about them, a wide survey and a detailed scan landing
in the same place, and an operator's drawing at the wrong *size* being noticed
rather than passing as well lined up. Run them with a browser required, so that a
machine which could have drawn does:

```
ZMART_REQUIRE_BROWSER=1 python -m pytest viz_studio/tests/test_the_options_hold_together.py
```
