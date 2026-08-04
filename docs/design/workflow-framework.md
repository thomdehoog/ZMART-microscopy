# A framework for workflows

Status: design note, nothing built yet. It describes the structure we would like
the operator window to have, and the reasoning behind each part of it, so that
the shape is agreed before anyone writes code against it.

The operator window it describes lives at
`workflows/target_acquisition/webapp-ui/` on the branch
`claude/one-checkout`. Where this note refers to a file by name, that is where
to find it.

---

## What this is, and who it is for

The operator window is the page somebody sits in front of while they drive an
experiment. It offers a few named ways of working — acquire a set of targets,
take an overview and stop, look at a run you already have — and walks you
through each of them a step at a time.

This note is about the machinery underneath that: how one of those named ways
of working is written down, what it is allowed to assume, and what it must be
handed. We call one of them a **workflow**.

There are two reasons to care about getting this right.

The first is that **workflows should be shareable**. Somebody builds one that
suits their experiment, and hands it to a colleague in another lab whose
operator window then offers it too. That only works if a workflow is a
self-contained thing rather than a set of edits scattered through the page.

The second is that **workflows should be easy to write with an assistant's
help**. If writing one means understanding the whole page, then only the
people who already understand the whole page can write one. If it means filling
in a small, closed form, far more people can — and a mistake in that form can be
caught and explained rather than quietly breaking the window.

Everything below follows from those two aims.

---

## Nothing here is about microscopes

The structure is deliberately free of any particular subject. The same shape
should carry a microscope run, an analysis pass over data acquired last month,
or a lesson with a video and a quiz in it. Microscopy appears in this note only
as a worked example, because it is the example we have.

That is not an aspiration. It is the test: if anything in the core of the
framework has to know what a microscope is, the boundary has been drawn in the
wrong place.

---

## The shape on screen

Four regions, and they do not change from workflow to workflow.

```
┌──────────────┬────────────────────────────────┬──────────────┐
│  chooser     │                                │              │
│  ──────────  │                                │              │
│              │                                │   channel    │
│  rail        │          main area             │              │
│   1 ▸        │                                │  the current │
│   2 ▸        │   whatever the current step    │  step's      │
│   3 ▸        │   puts here                    │  controls    │
│   …          │                                │              │
└──────────────┴────────────────────────────────┴──────────────┘
```

- **The chooser**, at the top left, is where you pick a workflow.
- **The rail**, below it, lists the steps of the one you picked and shows where
  you are in them.
- **The main area** is the large middle. A step decides what goes there. In a
  microscope run it is usually a picture of the stage drawn to scale; in an
  analysis run it might be a table; in a lesson it might be a video.
- **The channel** is the narrower column on the right, and it holds the controls
  belonging to whichever step you are standing on.

There is one channel rather than two because a second one would take width away
from the main area in order to show controls for a step nobody is looking at. A
step with nothing to control gives the main area the whole width.

---

## The rule that decides everything else

**Only the things a workflow genuinely cannot supply for itself live outside
it.** Everything else is either part of the workflow or a reusable part it draws
on.

Applied honestly, that leaves a surprisingly small core.

---

## The core: six things

These are the six, and each is here because no workflow could provide it from
the inside.

1. **Loading.** Something has to find a workflow and start it. A workflow cannot
   load itself.
2. **The regions.** A place to choose, a place to walk, a place to show, a place
   to control. Every workflow needs somewhere to be.
3. **Where you are.** Which step is current, which are reachable, which are
   finished. If two workflows each owned this, the rail could contradict itself.
4. **State that outlives a step.** Progress has to survive walking away from a
   step and coming back. No step can arrange that from inside itself, because it
   is not running when you are somewhere else.
5. **The contract.** One written description of what a step is handed and what it
   must declare. It is the single document both sides read.
6. **The render loop.** Putting a panel on screen when you arrive at a step and
   taking it off again when you leave.

```
src/core/
  contract.js     what a step is handed, and what it must declare
  load.js         find a workflow, resolve its names, refuse it with a reason
  state.js        the run document — the only thing that persists
  ordering.js     numbering, reachability, and what has gone out of date
  regions.js      the chooser, the rail, the main area, the channel
  mount.js        the render loop and the panel lifecycle
```

Nothing in `core/` knows what a microscope, a cell or a lesson is. If a change
to one of those six files needs a word from a particular subject, that is the
signal that something has leaked in and wants pushing back out.

---

## The catalogue: reusable parts

Most steps are not special. Connecting to an instrument, opening a run that
already exists, reviewing a gallery, exporting a table — these appear in many
workflows and should be written once.

```
src/catalogue/
  steps/      parts that are a step
  views/      parts that fill the main area
  lib/        parts that are neither — geometry, fitting, formatting
```

The catalogue is **shared, versioned, and not privileged**. It is a library a
workflow draws on, not a layer the workflow has to negotiate with. A workflow
names the parts it uses and gets them; it names nothing else and gets nothing
else.

The versioning matters more than it looks. If workflows copy parts out of the
catalogue instead of naming them, every correction has to be carried by hand
into each copy, and nothing announces when one has been forgotten. That has
already happened in this project: the operator page held its own snapshot of the
three drawing engines, and two faults that had been fixed once were still
present there — a run of several colours showed only its first colour, and a
second acquisition was drawn nearly a millimetre from where it belonged. Naming
a version is what makes a mismatch something the window can refuse rather than
something a person has to notice.

---

## A workflow is a folder

We call it a **bundle**, meaning simply a folder that holds everything belonging
to one workflow. Copy the folder and you have moved the workflow.

```
workflows/target_acquisition/
  workflow.json     the wiring: which steps, in what order, revisited how
  steps/            the steps only this workflow uses
  views/            the views only this workflow uses
  README.md         what it is for, written for the person who will run it
```

A bundle that only rearranges parts already in the catalogue has no `steps/` or
`views/` folder at all. It is one small file, it contains no code, and it
therefore cannot break the window it is opened in. That is the case worth
optimising for, because it is the common one.

---

## The manifest

`workflow.json` is the **manifest** — a short file that says what the workflow is
and what it is made of. Nothing in it is code.

```json
{
  "name": "Target acquisition",
  "blurb": "overview, detect, select, acquire",
  "catalogue": 1,

  "steps": [
    "connect", "optics", "carrier", "scanfields", "focus",
    "overview", "detect", "select",
    { "step": "./steps/curate", "after": "select" },
    "save", "disconnect"
  ],

  "revisiting": {
    "default":    { "editable": true,  "downstream": "ask" },
    "carrier":    { "editable": false, "because": "The positions were placed against this carrier." },
    "scanfields": { "editable": true,  "downstream": "stale" },
    "acquire":    { "editable": false }
  }
}
```

`catalogue` is the version of the shared library this workflow was written
against. A window holding a different one says so at load rather than behaving
oddly later.

A step named as a bare word comes from the catalogue. A step named as a path
comes from the bundle. There is no separate list of requirements to keep in step
with the actual contents, because such a list is a fact written down twice, and
facts written down twice drift apart in silence.

---

## What a step declares

A step is mostly data. It says what it is called, why it is there, what it needs
before it may run, what it produces, and what it does.

```js
export default {
  id:    "focus",
  title: "Focus strategy",
  why:   "Choose how this run keeps every image sharp across the sample.",

  reads:    ["carrier", "scanfields"],
  produces: "focus",
  cost:     "cheap",

  view:  "canvas",
  ready: (run) => run.focus.points.length >= 3 ? null : "Measure three points",

  async run(ctx) { … },
  panel: { mount(host, ctx) { … } },
};
```

`ready` returns `null` when the step may go ahead, and otherwise a short phrase
explaining what is still missing, which is shown to the person running it. The
step decides, and the core only asks — nothing in `core/` knows that fitting a
surface through measured points needs at least three of them.

`reads` and `produces` are what let the core work out, without anybody
maintaining a list by hand, that changing the carrier unsettles the scan fields
and everything that followed from them.

**A step imports nothing.** Everything it needs arrives in the `ctx` it is
handed, and `ctx` is assembled from what the workflow named. This single
property is doing a great deal of work:

- It is why a bundle can be copied to another machine. There is no relative path
  reaching back into somebody else's folder layout to be wrong about.
- It is why a workflow that never names an instrument has no instrument in its
  `ctx` — not as a rule it is asked to respect, but as an absence. A workflow
  that only reads data cannot move a stage, because there is nothing there to
  move it with.
- It is why the surface an author has to understand is small and closed.

---

## State, and what survives

Two kinds, and keeping them apart is most of the trick.

**Durable state** is what a step produced: the carrier that was chosen, the
fields that were drawn, the surface that was fitted, the cells that were kept. It
lives in the **run document**, it is plain data that can be written to a file,
and it is saved, resumed, and carried alongside the results.

**Transient state** is which sub-tab was open, how far a list was scrolled, a
half-typed number. It lives in the panel and may be lost when you walk away.
Losing it is a small annoyance; losing the other would be a lost afternoon.

From that follows the rule that makes moving back and forth safe:

> **A panel keeps nothing that has to survive.** It is built from the run
> document each time it is shown, and it writes every durable thing straight
> back. Click away and return and you find the same thing, because it was read
> from the run rather than remembered.

The run document is keyed by each step's `produces`, so `run.focus` belongs to
the focus step and nothing else writes there. One owner per fact, applied to
state.

One detail worth carrying over from the page as it exists: a panel should
*update itself* rather than being torn down and rebuilt whenever something
changes, because rebuilding destroys the field somebody is typing into. Build on
arrival, update in place, write on change.

---

## Going back to an earlier step

This is the part that most needs deciding in advance, because it is where a
framework either protects somebody's afternoon or quietly discards it.

Walking back to an earlier step asks three separate questions, and it helps to
keep them apart.

**1. What comes up on screen?** Which view fills the main area, which panel sits
in the channel, and how each of them is configured. This is the workflow's
business, and it belongs in the `revisiting` table.

**2. May it be changed again?** The same step can reasonably be editable in a
teaching run and read-only in a production run. Also the workflow's business.

**3. What happens to the work that came after it?** This one is different, and
the framework keeps a floor under it.

### Why the third question is not left to the workflow alone

Some results are cheap to make again and some are not. Refitting a surface
through points you already measured costs nothing. Re-photographing a living
sample forty minutes later is not the same photograph: it has bleached, or
drifted, or died. Those are not the same kind of thing and cannot share one
policy.

So **each step declares what its own result costs to redo**, and that
declaration travels with the step wherever it is used:

| `cost` | what the core does when something upstream changes |
| --- | --- |
| `cheap` | quietly marks the result out of date and lets it be redone |
| `slow` | asks first, naming what would be thrown away and how long it took |
| `irreversible` | never discards it. Keeps the result, marks it as made under earlier settings, and locks the upstream step instead |

The last row is why locking and invalidating both have to exist, and it is
already present in the page today in one place: the scan-field editor stops
being editable once something later has been done, because positions were placed
against those areas and must not have them move out from under them. That is the
right behaviour, written by hand, in one panel, where nothing else can reuse it.
Making it a declared property is the whole change.

### The rule that makes shared workflows safe

**A workflow may make revisiting stricter than the step asks, never looser.**

Turning an editable step into a read-only one is always allowed. Turning a step
the catalogue marked `irreversible` into one whose results are silently discarded
is refused when the workflow is loaded, with the reason named.

This is what makes a bundle from another lab something you can accept without
reading every line of it. Its author never had to think about your sample, and
this rule means they did not need to.

`because` is worth filling in whenever something is locked. A greyed-out control
with no explanation is the thing that makes people believe the software is
broken.

---

## Loading, and failing usefully

When a workflow is opened, the loader resolves every name in the manifest — the
bundle's own folder first, then the catalogue — and then checks that what it
found makes sense together. It either starts, or it refuses and says exactly
why:

- `step "curate" reads "focus", which nothing before it produces`
- `step "acquire" is marked irreversible; this workflow may not set downstream: discard`
- `no step named "segment" in this bundle or in catalogue v1`
- `this workflow was written for catalogue v2; this window has v1`

Refusing at load rather than partway through matters most for the long jobs. Told
at the start that a workflow cannot run here, you lose a moment. Told at the
seventh step, you may have lost the sample.

It matters for a second reason too. A clear refusal is something an author — or
an assistant helping them — can act on immediately, without anybody else being
involved. A message of that quality is worth more than a page of documentation.

---

## Two worked examples

### A microscope run

```
workflows/target_acquisition/
  workflow.json    steps: connect, optics, carrier, scanfields, focus,
                          overview, detect, select, ./steps/curate,
                          save, disconnect
  steps/curate/    step.js  panel.js
```

Everything but the curation step comes from the catalogue. The main area holds a
picture of the stage drawn to scale from the carrier step onwards, because from
that point everything happens on a stage. The channel holds the carrier's
controls, then the scan fields', and so on.

### An analysis pass, with no instrument at all

```
workflows/segment_and_count/
  workflow.json    steps: open-run, detect, review, export-table
```

No `steps/` folder, no code, four parts from the catalogue. The main area holds
a picture for the first three steps and a table for the last. There is no
instrument in this workflow's `ctx`, so nothing in it can drive one.

Note that **`detect` is the same part in both**. Finding cells needs images, not
hardware. In the microscope run its findings feed the next acquisition; here they
are simply reported. One implementation, no branch inside it, because it was
never handed an instrument to ask about.

### A lesson

```
workflows/photosynthesis/
  workflow.json    steps: watch, ./steps/quiz, summary
  steps/quiz/      step.js  panel.js
```

The main area holds a video, then the questions, then the summary. Going back to
the video keeps your answers, because they live in the run document under
`answers` rather than inside the panel. Redoing the quiz is `cheap`, so the
framework simply lets you.

Nothing in `core/` had to change to make this possible, which is the point of the
whole arrangement.

---

## Writing workflows with an assistant's help

One of the aims was that an assistant should be able to build a workflow without
being able to break the window. The structure gives that in three ways.

**There are only two things to write.** A manifest, which is data, and a step
folder, which is code confined to itself. Everything else is sealed.

**What is sealed is genuinely out of reach.** The layout, the render loop, the
drawing engines, the coordinate arithmetic, the instrument's limits, the
ordering rules. A step author never converts a coordinate, never touches the
page outside their own panel, and cannot move a stage past a limit. Each of those
is a whole category of mistake that is now impossible rather than discouraged.

**Declared beats written.** `reads`, `produces`, `cost`, `ready` and `revisiting`
are all data the core interprets. Something writing data can be wrong in ways the
loader can catch and explain. Something writing control flow can be wrong in ways
nobody catches until an experiment is halfway through.

---

## What this would change about the page as it stands

The current page has the right shape on screen and a different shape underneath.
Getting from one to the other is a sequence of changes that each leave it
working. In rough order:

1. **Write the contract first.** Nothing else is decidable until it exists, and it
   doubles as the brief given to anybody writing a step.
2. **Lift the shell out of `main.js`.** That file is about 134 KB and is
   currently most of the application. The browser suite is the check, and it is a
   good one, because the page is nearly all picture and driving it has repeatedly
   caught what reading the source did not.
3. **Close the three facts that are defined twice** — the surface fitting, the
   sweep and peak rules, and the synthetic sample all exist both inline in
   `main.js` and in the modules beside it. `main.js` is what runs and the modules
   are what the tests cover, so today the suite can stay green while the page
   misbehaves. This is a live hazard rather than tidying.
4. **Give each step its own `run(ctx)`** and remove the `mode` switch in
   `main.js`, one arm at a time. After this, adding a workflow needs no change to
   the shell — which is a claim the page already makes about itself, and which
   was tested once and found to be untrue.
5. **Settle the vocabulary.** The same thing is currently called a *widget* (the
   folder, and 19 mentions in `ARCHITECTURE.md`), a *panel* (the step field, the
   page's own element names) and a *module* (the prose in `frame/steps.js`). One
   word, and it should be **panel**, because that is what the data model and the
   page already use and therefore the cheapest to converge on.
6. **Make the run one document keyed by `produces`,** and derive what has gone
   out of date from `reads`. This is where moving back and forth stops being
   arranged by hand.
7. **Add the loader and the manifest,** and move the existing workflows into
   bundles.

The canvas demonstration is the workflow to test each stage against, for the same
reason it was useful before: it is the one that is not a microscope run, so it
finds the assumptions the shell is quietly making.

---

## What is not decided yet

Written down so they are not mistaken for settled.

- **Where the catalogue lives when workflows are shared between machines.** A
  version number in the manifest says which one is wanted; it does not yet say
  how a window obtains it.
- **How a view is configured from the manifest.** A workflow reasonably wants to
  say which layers of a picture are showing when you return to a step. If the
  manifest names layers directly, layer names become part of the shared contract
  and renaming one quietly breaks older bundles. The alternative is that the view
  names its own settings and the workflow only turns them on and off, which is
  less flexible and keeps the vocabulary inside the version number. Not yet
  chosen.
- **What an empty main area means.** There are three states — no view at all, a
  view with nothing in it yet, and a view with something in it — and only the
  third is currently specified anywhere. This is not hypothetical: asking the
  present canvas for a picture with no acquisitions in it never finishes, which
  is exactly the case of somebody laying out positions on an empty plate before a
  run has started.
- **Whether a step may itself be a list of steps.** Steps and workflows are the
  same shape in the sense that matters, since both declare rather than drive, so
  nesting is tempting. It is left out for now: ordering, reachability and
  readiness would all have to be answered recursively, and the flat rail would
  stop being able to show where you are. The existing ability for a step to
  number itself `3a` and `3b` covers the real case, which is one job that turns
  out to be two.
