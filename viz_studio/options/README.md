# The canvas: one viewer, written for several drawing engines

The canvas is the picture of a run that an operator pans and zooms. It is being
written more than once — once for each drawing engine worth considering — and
every version is kept behind the same small interface, so that the versions can
be compared with each other and swapped for one another without anything above
them noticing.

`contract.md` beside this file is that interface, in full, and is the thing to
read first. The short version is that an engine is a folder holding a `viewer.js`
which exports exactly one function, `openViewer`, and hands back a small handle
for driving the picture: where the view is, which plane of the stack, which
colours, and two slots for the application's own drawing — one beneath the
picture and one above it.

```
options/
  contract.md          the interface, and the five things that are not negotiable
  viv-under/           the picture underneath, the operator's drawing on a
                       second surface above it
  viv-inside/          one surface, with the picture and the operator's drawing
                       as layers in it
  harness/src/         the parts of the page that drive an engine and belong to
                       no single one of them — at present, the two gestures
```

## What is here, and what is not

This is a **part** of the canvas, brought over so that it could be put inside the
operator window and tried there. The whole of it — a third engine built on
neuroglancer, the page that drives all three side by side, and the measurement
suite that photographs each one and fills in a table of results — lives on the
branch `claude/viewer-only`, and the two halves have deliberately not been merged.

Two consequences are worth knowing before you read further.

**One engine is missing on purpose.** The third, `neuroglancer-under`, does part
of its work in a background program the browser must fetch as a file of its own,
and the operator page is delivered to the microscope as a single self-contained
file with everything folded inside it. Those two cannot both be true.
`workflows/target_acquisition/webapp-ui/src/canvas/engines.js` says this again
where somebody wiring an engine in will meet it.

**`contract.md` describes rather more than is here.** It talks about the
measurement suite, the results table, and the page that flips between three
engines with a keystroke. None of those are on this branch. Everything it says
about the *interface* holds exactly, which is the part that matters when writing
against it.

## Where it is used

`workflows/target_acquisition/webapp-ui` opens it as a workflow of its own, called
**Viewer on its own**, with one step and nothing else in it. That is the first
place the canvas has been put inside the real operator window, and it is
deliberately separate from target acquisition so that a question about the
picture stays a question about the picture. The page's own README says how to
point it at a run.
