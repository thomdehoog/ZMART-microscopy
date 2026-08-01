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

`workflows/target_acquisition/webapp-ui` opens it as a workflow of its own,
called **Canvas demonstration**, with two steps: the same run drawn by Viv, and
then drawn by neuroglancer. Each step has a button for each of the three layers —
the operator's drawing beneath, the acquisition, the operator's drawing above —
so that what each layer contributes can be seen by taking it away. That is the
first place the canvas has been put inside the real operator window, and it is
deliberately separate from target acquisition so that a question about the
picture stays a question about the picture. The page's own README says how to
point it at a run.

## Two things using it turned up, which belong in the interface

Both were found by driving these engines from the operator page and measuring
what reached the screen, not by reading them. Both are gaps in the interface
rather than faults of any one engine, so they are written here rather than fixed
in the copies — the copies are a snapshot and are due to be refreshed from
`claude/viewer-only`, which would throw away anything changed in them.

They are recorded here rather than in `contract.md` for one reason: `contract.md`
is the shared statement of the interface and the branch it came from is being
worked on right now, so the two are better reconciled deliberately than by two
people editing the same paragraphs at once.

**1. Opening with no acquisitions hangs one engine for ever.** `openViewer` is
given a list of acquisitions to draw, and an empty list is a real thing to ask
for: it is what an operator sees before a run has started, laying positions out
on an empty plate, with the carrier and the planned positions drawn and nothing
in the middle. Measured from the page: `viv-under` opens that way in about 190 ms
and `viv-inside` in about 40 ms, both of them then honouring both drawing slots
and both view controls perfectly. `neuroglancer-under` never finishes opening at
all — still not ready after thirty seconds, with its own elements built inside
the box and its promise unsettled.

The reason is one line of it. That option waits for the engine to say what space
the picture lives in before it goes on, and the engine works that out from the
image layers it has been given. Watched directly, with no layers the engine's
coordinate space stays at rank zero for as long as anybody looks — twelve
readings over six seconds, all zero — so the wait never ends.

Two things follow, and the second is the larger of them. The interface has no
statement about what an empty list of acquisitions means, and it should have one.
And **the interface has no way to abandon an `openViewer` that never finishes**:
a page that gives up can take what the engine built out of the page, but whatever
the engine is still doing out of sight goes on until the page is left. A cheap
answer to both might be a `signal` on `openViewer`, or an engine saying up front
whether it can draw nothing.

**2. Handing a slot `null` does not always clear what was drawn there.**
`drawUnder(paint)` and `drawOver(paint)` take `null` to mean the application has
nothing for that slot. `contract.md` says an option may then skip laying a
surface down, which is the right thing when nothing has ever been drawn. It says
nothing about a slot that had something in it a moment ago, and two of the three
options clear a surface only on their way to painting it — so a drawing handed
`null` after the fact stays on the screen until the viewer is closed. Measured:
the operator's drawing covered 3.4% of the box, the slot was handed `null`, and
it still covered 3.4%. `viv-inside` clears either way.

On the page this is the difference between a button that turns a layer off and a
button that appears not to work, so the page works around it by handing a drawing
that paints nothing rather than `null` — which costs the surface that `null` was
there to save. `…/src/canvas/panel.js` explains that in place. The interface
should say plainly that a slot handed `null` leaves nothing on screen, and all
three options should honour it.
