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
  neuroglancer-under/  the same arrangement as viv-under, drawn by neuroglancer
  harness/src/         the parts of the page that drive an engine and belong to
                       no single one of them — at present, the two gestures
```

## What is here, and what is not

This is a **part** of the canvas, brought over so that it could be put inside the
operator window and tried there. The rest of it — the page that drives all three
side by side, and the measurement suite that photographs each one and fills in a
table of results — lives on the branch `claude/viewer-only`, and the two halves
have deliberately not been merged.

All three `viewer.js` files here, and `harness/src/gestures.js` beside them, are
copies taken from that branch at commit `1e6b4f5`, unchanged. That commit is
worth writing down, because the branch keeps moving and a copy with no date on it
is very hard to compare with anything later. To see what has changed since:

```bash
git diff 1e6b4f5 claude/viewer-only -- viz_studio/options/viv-under/viewer.js
```

Two consequences are worth knowing before you read further.

**All three engines are here, and the third one costs something.**
`neuroglancer-under` does part of its work in background programs that the
browser will only start from files of their own. The operator page was until
recently delivered to the microscope as a single self-contained file with
everything folded inside it, and those two cannot both be true. What was settled
is that the page is still folded into one file and the two background programs
sit beside it, so what reaches the microscope is a small folder rather than a
single file. Folding them in was tried first, and it fails twice over — once
silently, which is the kind of failure this project keeps meeting.
`workflows/target_acquisition/webapp-ui/README.md` records what was tried and
what each attempt did, and `…/src/canvas/engines.js` says the short version where
somebody wiring an engine in will meet it.

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
