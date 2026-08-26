# The operator window: steps on the left, modules in the middle and right

Written 2026-07-31, recording the shape the smart-microscopy operator window is
meant to take. Most of it describes an intention rather than something already
built. The section called "The one thing to get right early" is the part that
matters most, and the section at the end says how much of this exists so far and
where to find it.

---

## The shape

The window has three parts. The framework that holds them, and decides how they sit on
screen, is what the rest of this note calls the shell.

**Down the left, the workflow's steps**, numbered one to however many there are —
the step rail. Above them, the choice of workflow, which is what decides the list
of steps. A workflow is a sequence of steps pieced together, and the steps are
ordinary things that can be arranged in any order that makes sense — that is what
makes new workflows cheap to build rather than a programming job.

**In the middle and on the right, two modules.** The canvas is usually the middle
one. The right one is usually a panel of controls and readings. They sit side by
side, and the divider between them can be dragged, so an operator who wants more
picture can have it and one who wants more detail can have that instead. Either can
be collapsed out of the way entirely.

**Each step decides what those two modules hold.** Not every step wants both. Setting
up the microscope wants only the panel, which then has the window to itself.
Acquiring wants only the canvas. Choosing where to image wants both — the picture to
look at and the controls to act with.

**And a step hands on what it produced.** The positions chosen in one step are what
the next step acquires; the overview taken in one step is what the next one picks
targets from. The right-hand panel of step four is filled in from what steps one to
three worked out. That is the whole reason for having a sequence rather than a set of
unrelated screens.

---

## Where this is going, much later

Once steps are genuinely interchangeable pieces, an assistant could help an operator
put a new workflow together — suggesting the next step, filling in what it needs from
what has already been decided, and saying when a sequence cannot work because
something it depends on is never produced.

That is a long way off. It is written down because it changes one decision that has
to be taken now, and would be expensive to take later.

---

## The one thing to get right early

**A step must declare what it needs and what it produces, as plain data.**

There are two ways to build the hand-on between steps, and from the operator's side
they look identical.

The tempting way is for a step simply to read whatever it likes from somewhere the
whole page can see, and write back whatever it likes. It works immediately, it needs
no design, and every step ends up quietly depending on things nobody wrote down.

The other way is for a step to state, in a form the program can read: *these are the
things I need before I can run, and these are the things I will produce.* Choosing
positions needs an overview and produces a list of positions. Acquiring needs a list
of positions and produces images.

The difference does not show for a long time, and then it decides everything:

- **A sequence can be checked before it is run.** If step four needs positions and
  nothing before it produces any, that can be said at the moment the workflow is put
  together rather than discovered halfway through an experiment on a live specimen.
- **Steps can be reordered and reused** without somebody reading all of their code to
  find out what they touch.
- **And the assistant above becomes possible at all.** Something can only suggest
  which step comes next if it can see what each step needs. Dependencies hidden
  inside code are invisible to it — and to a human reading the workflow six months
  later, which is the more immediate benefit.

This costs very little now: a short declaration beside each step. Retrofitting it
means untangling every dependency that grew in the meantime, which is one of those
jobs that never quite gets done.

---

## Two smaller things worth settling in the same spirit

**A step says which modules it wants; it does not lay them out.** "I need the canvas
and a panel of these controls" is the step's business. How wide they are, which is
collapsed, and what happens when the window is narrow is the shell's business, and
an operator's preference. Keeping those apart means a step never has to think about
window sizes, and the layout can be improved once for every workflow at a time.

**The canvas is a module like any other.** It is the biggest and the most important,
but it fills a slot in the same way the panel does. That keeps the shell simple and
means a step that wants two panels, or a panel where the canvas usually goes, needs
no special case.

---

## What exists today

The step rail, the workflow chooser, the canvas and the channel beside it are
built and working in this folder, and steps hand their results on. The source
is arranged as the shape this note asked for: `framework/` is the shell — an
engine that runs any workflow and knows none — and `workflows/` holds one
folder per workflow, each a `flow.js` and its steps. `ARCHITECTURE.md` says how
it is put together, and `workflows/README.md` maps the folders.

The canvas itself is still built behind one interface in `viz_studio/options/`,
with the engines to choose between, and this page opens it through that
interface.

What is **not** built is the declaration described above. Steps declare what
they still need before they may run (`ready`), but not yet what they produce —
results are still handed on by arrangement rather than by statement.
