# The layer-stack probe: measuring whether three layers can be stacked in one view

This folder holds the harness that settled a design question, and it is built to
be run again rather than to be read once. The question, the numbers and the
verdict are in **`viz_studio/LAYER_STACK.md`** — read that first. This file
explains how to run it and what each piece is for.

The question is the one `LAYERS.md` describes: the plate layout at the bottom,
the tiles the operator chose for this run above it, and the acquisition on top
with room nobody has imaged drawn see-through, so that the two layers below show
through it. All three are layers *inside* the drawing engine, which is what makes
this a different investigation from the sandwich probe next door — that one asked
whether the engine could sit underneath a second drawing surface, and this one
asks what the engine will do with several layers of its own.

## Running it

```
npm --prefix viz_studio/layer_stack/page install
npm --prefix viz_studio/layer_stack/page run build
python viz_studio/layer_stack/measure.py --out somewhere --data somewhere/stores
```

It writes a folder of photographs and a `results.json` beside them, and prints a
readable summary as it goes. On a machine with no graphics card the whole run
takes about eight minutes, and seven of those are question 4 writing plate-sized
images four times over.

`--only "part of a name"` runs a single measurement, which is what you want while
working on one. The names are the headings it prints.

`--data` says where to keep the little acquisitions the measurements are made
against. They are written if the folder is not there and reused if it is, so
working on one measurement does not mean writing every store again each time.
`--rewrite-stores` writes them again anyway, which you need after changing
`make_stores.py`.

## What is here

| | |
| --- | --- |
| `measure.py` | Drives everything. One function per question, and a summary at the end. |
| `make_stores.py` | The little acquisitions the measurements are made against, written by this project's own writer. Grouped by the question each was made for. |
| `page/` | The probe page: a stack of image layers inside one flat view, told what to build by its address. |
| `photographs/` | What the run in `LAYER_STACK.md` actually saw, kept so the document can be read without running anything. |

The server is not here. It is `viz_studio/sandwich/probe_server.py`, shared with
the sandwich probe rather than copied, because it does exactly what is needed
already: it hands over the built page and the images, it can be told to answer
slowly, and it keeps a note of every request it answered.

## The page, and how to open it by hand

The page takes the whole stack from its address, so one build serves every
measurement. Serve it and open, for example:

```
?layers=[{"store":"under","shader":"green"},{"store":"over","shader":"red"}]&bg=%233060a0&cx=512&cy=512&umpp=2
```

| word in the address | what it chooses |
| --- | --- |
| `layers` | the stack, **bottom first**, as a small piece of JSON. Each entry names a `store` and a `shader`, and may carry an `opacity` and a `source` of its own |
| `bg` | the colour behind everything |
| `cx`, `cy` | where to look, in micrometres on the specimen |
| `umpp` | how much specimen one screen pixel covers, in micrometres |

Units are micrometres everywhere, because that is what the operator's stage and
the store's own description both speak.

The shaders are listed and explained in `page/src/stack.js`. The two families
that matter are the **see-through** ones, which draw a voxel of nought as nothing
at all so that whatever is underneath shows through, and the **opaque** ones,
which draw everywhere the image reaches so that a measurement can be shown what
the see-through version hides.

## Two habits worth keeping

Both cost this project time before they were learned, and both are why the
answers in `LAYER_STACK.md` can be trusted.

**Read the picture, never the engine's opinion of itself.** Everything in the
report came from a photograph. While this harness was being built the engine
reported three hundred frames drawn, every layer loaded and every piece of image
found, with a completely black window — its drawing surface was nine hundred
pixels wide and nought high. Only looking at the picture found it. There is one
place in the page that asks the engine how many layers it thinks it is drawing;
it is used for diagnosis and never for a verdict, and in one measurement it
disagreed with the photograph.

**Break it on purpose and check that the check notices.** Every question that
asserts something is run again with the thing it depends on deliberately broken:
the see-through shader made opaque, the recorded corner of an image written down
a hundred micrometres wrong. A check that has never been seen to fail is not
evidence of anything.

## One thing to set that is easy to miss

**An image layer in this engine opens at an opacity of one half, not one.** The
opacity is multiplied into whatever alpha the shader emits, so two layers stacked
at their defaults blend into a mixture rather than one covering the other. Every
layer here is given an explicit opacity, and anything built on this arrangement
should do the same.
