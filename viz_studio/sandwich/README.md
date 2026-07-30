# The sandwich probe: measuring whether two stacked layers stay lined up

This folder holds the harness that settled a design question, and it is built to
be run again rather than to be read once. The question, the numbers and the
verdict are in **`viz_studio/SANDWICH.md`** — read that first. This file explains
how to run the thing and what each piece of it is for.

## Running it

```
npm --prefix viz_studio/sandwich/page install
npm --prefix viz_studio/sandwich/page run build
python viz_studio/sandwich/measure.py --out somewhere/to/put/the/results
```

It writes a folder of photographs and a `results.json` beside them, and prints a
readable summary as it goes. The whole run takes about three minutes on a machine
with no graphics card.

`--only "the name of one measurement"` runs a single one, which is what you want
while working on it. The names are the headings it prints.

There is a shorter version that runs as an ordinary test:

```
python -m pytest viz_studio/tests/test_the_margins_stay_even.py
```

That one checks the four things that must stay true — the single-canvas control
comes out at zero, the proposed arrangement matches it, the arrangement that
ought to fail does fail, and a turned view is caught — and skips politely on a
machine that cannot open a browser.

## What is here

| | |
| --- | --- |
| `measure.py` | Drives everything. One function per question, and a summary at the end. |
| `make_stores.py` | The two little acquisitions the measurements are made against, written by this project's own writer. One imaged edge to edge, one sparse in the way a real run is sparse. |
| `probe_server.py` | Serves the page and the images, and adds the two things only a measurement needs: it can be told to wait before answering, and it keeps a note of every request it answered. |
| `page/` | The probe page itself: the engine underneath, the operator's sheet on top, and the control that draws both in one canvas. |
| `photographs/` | What the run in `SANDWICH.md` actually saw, kept so the document can be read without running anything. |

The reading half of the margin test is **not** here. It lives in
`viz_studio/tests/margins.py`, beside `pixels.py`, because it is a general check
for any two-layer arrangement rather than a part of this investigation.

## The page, and how to open it by hand

The page takes its arrangement from its address, so one build serves every
measurement. Serve it and open, for example,
`?arrangement=sandwich&follow=pointer&store=square&voxels=1024`.

| word in the address | what it chooses |
| --- | --- |
| `arrangement=sandwich` | the engine underneath, the operator's sheet on top |
| `arrangement=one-canvas` | both layers in one canvas — the control |
| `follow=presented` | the sheet is repainted from the frame the engine has just drawn |
| `follow=pointer` | the sheet is repainted the instant the mouse moves |
| `follow=compromise` | the hole follows the engine, the operator's own rectangle follows the mouse |
| `store=square` / `store=sparse` | which of the two acquisitions to open |
| `bounded=1` | give the engine only the part of the window covering ground the run imaged |
| `axes=…` | which way round the flat view is drawn; see `page/src/sandwich.js` |

## If you are adding a measurement

Two habits are worth keeping, and both cost this project a session before they
were learned.

**Read the picture, never the engine's opinion of itself.** Everything in
`SANDWICH.md` came from a photograph of the screen. The one exception reads pixels
out of the engine's drawing surface at the end of a frame, which is still looking
rather than asking.

**Break it on purpose and check that the check notices.** `measure.py` ends with
a measurement that does exactly that: it moves the hole a couple of pixels away
from where it belongs, and turns the view, and reports what the checks say. A
check that has never been seen to fail is not evidence of anything.
