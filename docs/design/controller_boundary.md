# Where the operator window meets the microscope

Written 2026-07-31. This is about one line in the software: the place where the
window an operator clicks in stops describing what should happen and something
else goes and makes it happen on a real instrument.

Today that line has a pretend microscope on the far side of it. One day it will
have a real one. The question this note answers is what to settle now so that
today's pretending turns out to have been a rehearsal for the real thing rather
than something that has to be pulled out and replaced.

**How to read this.** Three kinds of statement are mixed together here and they
are always labelled.

- **Exists** — code on this branch, which you can open and read.
- **On `claude/live-tiles-mvp`** — code that was deliberately taken out when this
  repository was narrowed to the viewer and the writer. It is still there on that
  branch and can be read with `git show claude/live-tiles-mvp:<path>`.
- **Proposal** — not built anywhere, offered here for a decision.

Nothing in this note has been built. Nothing was merged or moved to write it.

---

## The three pieces and the words for them

It helps to fix the vocabulary first, because the same word means different
things in different corners of this project.

The **driver** is the piece that speaks a particular microscope's own language.
There is one per instrument, and it is where all the vendor's quirks live — LAS X
for the Leica, something quite different for a mesoSPIM. It knows how to move
that stage, capture from that camera, and save a file in that instrument's own
way.

The **controller** is one small, unchanging set of commands that every driver
answers to. It does not do any work itself. It takes what you asked for and hands
it to whichever driver is currently plugged in. Its whole value is that a
workflow written against it runs on any microscope that has a driver.

The **workflow** is the experiment: focus here, scan this area, look at what came
back, image the interesting things. It is written once, in terms of the
controller, and it never mentions a vendor.

The **operator window** is what a person looks at and clicks in.

The phrase in the original question — *"the driver ultimately is the smart
controller, and that will be the back end of the interface"* — is worth
untangling against those four. The driver is where the intelligence about a
particular instrument lives, and that is right. But the thing the window should
be talking to is not the driver, and it is not quite the controller either. It is
the workflow, which is the only one of the three that knows what a *run* is. That
distinction turns out to be the whole of section 2, so it is worth holding on to.

---

## 1. What the boundary looks like today

**On `claude/live-tiles-mvp`**, in
`application/parts/microscope/mock.js`. The file opens by
saying exactly what it is meant to be, and the intent is good:

> The seam where the microscope goes. […] When the live driver arrives it
> implements this same shape and `main.js` imports that instead; if wiring it
> means editing a widget, the seam leaked.

Behind that comment are twelve things the window can ask for. Listed plainly, and
grouped by what they actually are:

*Opening and closing a session* — `connect`, `disconnect`, `setOrigin`. Each
takes no arguments and comes back with a short sentence such as
`"session open · run folder created"`.

*Reading a setting off the instrument* — `captureJob("overview")` or
`captureJob("target")`, which comes back with `"5x · 1.30 µm/px · 2 channels"`.

*A whole focus procedure* — `measureFocus({strategy, metric, points, zFixed,
reuse})`, which measures a sharpness sweep at several places and fits a surface
through the answers. This one returns real structure: the fitted surface, the
measured points, and how well it fits.

*A whole scan* — `scanOverview({onProgress})`, which reports a running count of
tiles as they land and finally returns `"40 / 40 tiles"`.

*Analysis and bookkeeping* — `detectAll(settings)`, `confirmSelection(gated)`,
`acquire(cellIds)`, `saveResults()`.

*Two things that are not requests at all* — `detects(settings, cell)` and
`testTile(settings, {col, row})` are ordinary functions that answer immediately
out of the synthetic sample. They are on the same object as the rest, and the
file also exports a table of previous focus surfaces.

**Is that a deliberate set or accidental growth?** It is deliberate. Somebody sat
down and wrote one method per button, in the order the buttons appear, and said
so in the file header. The set has not sprawled.

But it is not a set of *microscope* operations. Reading down it, only about four
of the twelve are things an instrument does. `scanOverview` is a whole
experiment; `saveResults` is file writing; `detectAll` is image analysis, which on
a real run is done by a separate segmentation engine and not by the microscope at
all. And the last three members — `detects`, `testTile`, and the table of old
surfaces — are the accidental part: they answer out of the mock's own imaginary
specimen, so a real implementation of this seam would have nothing to put there.

Two things are missing that a real microscope will need, and their absence is
worth naming now rather than discovering later. **Nothing in the list moves the
stage or reads where it is**, so the window has never had to think about the
difference between asking for a position and finding out where you ended up. And
**nothing in the list can fail or be stopped.** Every method resolves; there is no
argument, no return value and no error anywhere on the seam that carries the
sentence "that did not work". Section 4 comes back to this.

Two facts about how much of this is really in use, because they change how much
weight the file can bear:

- **The window does not import it.** `src/main.js` — the three thousand lines that
  actually run — contains no reference to the backend at all. It fakes its own
  work inline with timers. The branch's own `ARCHITECTURE.md` says so in a table:
  `backend/mock.js` is *"built, not yet imported by the app"*.
- **Almost none of it is tested.** The one unit test that imports the mock uses
  only `detects`, the synchronous rule. Every asynchronous method on the seam is
  unexercised.

So the honest summary of question 1 is this: a careful and quite short list of
operations exists, written with the right instincts, and it is a description of
the *run* rather than of the *microscope*. It is a design sketch that nothing
depends on yet — which is a good position to be in, because it means changing it
is nearly free.

### For comparison, the boundary that already exists and works

**On `claude/live-tiles-mvp`**, in `zmart_controller/`. This is the piece the
question calls the controller, and it is worth reading before designing anything
new, because it is the small deliberate set the mock is not:

`get_instruments` · `set_instrument` · `disconnect` · `set_origin` · `get_xyz` ·
`set_xyz` · `get_actuators` · `get_state` · `set_state` · `get_procedures` ·
`run_procedure` · `get_acquisition_options` · `acquire` · `get_info`

Fourteen commands, and every one of them is something a microscope does. The
pattern running through them is *discover, then apply*: ask what this instrument
offers, then pass your choice back. `get_actuators()` tells you that this
particular Z axis can be driven by a motor or by a galvo; `set_xyz(..., with_actuators={"z": "z-galvo"})`
picks one. Nothing is assumed about the instrument that was not first asked.

This surface has been driven against a real Leica Stellaris 5, and it has a
complete pretend instrument behind it — `zmart_drivers/mock/mock_driver.py` —
that the test suite and an example notebook run against with no hardware in the
room.

---

## 2. Could the mock and the real thing be interchangeable?

This is the important question, and the project already has a worked answer to it
in a different corner, so it is worth starting there.

### The pattern that already works here

**Exists**, in `viz_studio/options/`. The viewer needed to compare three different
drawing engines. Rather than write three viewers, one interface was declared — it
is written down in `viz_studio/options/contract.md` — and each engine implements
it. A viewer is opened the same way, told to move the same way, and asked the
same questions, whichever engine is underneath. The page cannot tell which it has.

The contract states plainly *why* the discipline is worth its cost:

> Three viewers with three different interfaces cannot be compared: any
> difference you feel might be the engine, or might be the way somebody happened
> to wire it up. Three viewers behind an identical interface, driven by the same
> page and measured by the same tests, differ only in the thing being compared.

Adding a fourth engine is one line in a list. That is the shape the question is
asking about, and it does work here.

### Where the same pattern already exists for the microscope

It exists too, and this is the part most worth knowing: **the interchangeable
boundary the question asks for is already built, and it is the controller.**

**On `claude/live-tiles-mvp`**: a driver is a set of functions registered under a
short identity — vendor, microscope, API. `zmart_controller/registry.py` keeps
that register; `zmart_controller/layer.py` forwards each command to whichever
driver was chosen. The real Leica driver and the pretend one register the same
way and answer the same fourteen commands. Choosing between them genuinely is one
line, and the offline test suite runs the whole workflow against the pretend one.

So the answer to "could the mock and the real thing be interchangeable" is not
"they could, with work". Underneath the workflow, **they already are**.

### Why today's window mock is nevertheless not that

Because it is a mock of a different thing. It stands in for the whole run — the
microscope, the workflow's decisions, the synthetic specimen, and the analysis
engine, all four at once. And that has a consequence that is easy to miss:

**When the window runs against this mock, none of the code that will run against
a real microscope is exercised.** Not the focus fitting, not the scan loop, not
the file naming, not the segmentation. A test that passes against this mock has
tested the window's own buttons and nothing else. Compare that with the pattern
in `viz_studio/options/`, where the point is that *the same code* runs against
every option.

There is a second symptom of the same thing. Counting what is on the two branches,
this project now has **four separate pretend microscopes**, and no two of them
answer the same set of commands:

| the pretend microscope | where it lives | what it stands in for |
|---|---|---|
| `mock_driver.py` | `zmart_drivers/mock/` | one driver, behind the real controller |
| `SimulatedSession` in `_simulation.py` | the workflow | a whole connected session, alongside the real one |
| `_hijack.py` + `_mock_provider.py` | the workflow | the real path on a LAS X simulator, with only the pixels swapped |
| `mock.js` | the operator window | the whole run |

(All four are on `claude/live-tiles-mvp`.) Each was a sensible thing to build on
its own day. Together they mean there is no single answer to "what does it mean
to run this without a microscope", and four places to keep in step when the
controller gains a command.

### Proposal: the window talks to the workflow, and the one mock stays at the driver

**Proposal.** Two seams, not one, and the pretending happens at the lower one.

```
  operator window  ──►  the workflow  ──►  the controller  ──►  a driver
                    ▲                                        ▲
                    │                                        │
             one declared set of                     real Leica driver,
             run operations, always                  or mock_driver — one
             the real workflow code                  line chooses
```

Concretely, and stated as what changes rather than as an architecture:

1. **The window's seam is a set of run operations, and it has exactly one
   implementation.** That implementation calls the real workflow. There is no
   second, pretend version of it.
2. **Demo mode moves down a layer.** Running without hardware means registering
   the pretend driver instead of the real one. Everything above — the focus
   fitting, the scan loop, the file naming, the segmentation — is the code that
   will run on the bench.
3. **`mock.js` stays where it is, as a drawing aid, and gets an expiry.** While
   the window's design is still moving, being able to click through it with no
   Python running at all is genuinely useful, and taking that away now would slow
   the design down for no gain. What it must not do is grow: it should not
   acquire new methods, it should not be described as "the seam", and no widget
   should be written that only ever meets it.

**What this costs and what it buys.** It costs the JS mock's future: the plan in
`ARCHITECTURE.md` — *"backend/mock.js today, backend/live.js later — same shape"* —
is replaced by *one* implementation rather than two. It buys the property the
question is really after: every test of the window runs the same workflow code the
microscope will run, and the switch to real hardware is the one line that already
exists in the registry.

**Is today's mock a good rehearsal?** Partly, and the part that is good is the
part that was thought about hardest: one object, one method per operation, every
method awaited, the window never touching hardware itself. That instinct is
right and should be kept. What is not a good rehearsal is where the line was
drawn and what was put behind it. That is fixable now at a cost of a few
afternoons, because nothing imports the file.

---

## 3. Where the live data goes

During a run, tiles are written to disk and the viewer has to be told. Who says
so?

### What the live-tiles branch settled, and why

**On `claude/live-tiles-mvp`**, `application/src/live/overview.js` explains the
problem at length, and it is a real one:

> Nothing on disk announces a new tile. The run declares its images at the very
> start, at their full final size, and the tiles are written into room that was
> already reserved for them — so the description of the images is exactly the
> same before and after a tile arrives.

That property is deliberate and good: it is what lets a viewer open a run that is
still going. But it means asking "has the image changed?" has no useful answer.
On that branch the page therefore goes and looks: the scan step calls
`picture.tileMayHaveLanded()` after every reported position, the picture waits at
least a second between actual reads so a fast scan cannot flood it, and while the
picture is on screen a timer nudges it every 1.5 seconds regardless.

### What this branch has that changes the answer

**Exists**, and it is newer than the code above, so the sentence "nothing on disk
announces a new tile" is now true only of the images themselves.

`zmart_storage/coverage.py` writes a record beside the images saying where the run
has actually imaged. It has two parts: `tiles.jsonl`, one line appended for every
tile that safely lands, and `regions.json`, a short summary rebuilt at most once a
second carrying — among other things — how many tiles have been written, when it
was last updated, and whether the run has finished. So there *is* now a small
file that changes when a tile lands, and reading it costs one request.

`viz_studio/backend/announcements.py` goes further and turns the question around.
Instead of anyone inferring from the disk, whatever is driving the microscope
posts to `/api/announce` and every open viewer window is told to look again. The
module says why plainly:

> The application driving the microscope does not have to infer anything. It
> called for the acquisition and it waited for the write to finish, so it knows.

Three details of it are already settled and worth not re-deciding. The message
carries no detail — it says only *something changed*, and the page then re-reads
the disk, so the disk stays the single description of the experiment that has to
be right. There is exactly one exception, a flag meaning *the image went into a
store you already have open*, which exists because that is the one change the page
genuinely cannot see for itself. And a folder watcher runs as a fallback for
instruments that write files and have never heard of any of this.

### Proposal: the workflow announces, once per tile

**Proposal**, and a small one.

**Not the controller.** The controller's job is to forward one command to one
driver. It does not know a viewer exists, it does not know a run is in progress,
and giving it an address to post to would put a user interface's concern inside
the vendor-agnostic layer. That is exactly the coupling the controller was built
to avoid.

**Not the page asking repeatedly.** It works, and it is what the live-tiles
branch does, but it is guessing where something already knows. `announcements.py`
makes the same argument and calls the watching *"the weaker mechanism of the two"*.

**The workflow, at the point where a tile has just landed.** There is already a
hook in exactly the right place. **On `claude/live-tiles-mvp`**,
`workflow/_capture_run.py::capture_positions` takes an `on_record` callback,
described as being called *"right after each acquisition completes — this is how
the interactive widgets show every image the moment it exists instead of waiting
for the whole run"*. Announcing is one more thing to do there: one HTTP post,
which returns how many windows heard it, and nought is a perfectly ordinary
answer meaning nobody has the viewer open.

This satisfies the "prefer a better design to a guard" rule rather than working
against it. The page's timer, the coverage file's timestamp and the folder
watcher are all ways of *detecting* something that could simply be *said*. Saying
it removes the need for the rest to be reliable — they can stay as the fallback
for instruments that do not say anything, which is what they were written for.

One thing genuinely undecided, and I will not pretend otherwise: **whether
`zmart_storage`'s coverage recorder should announce by itself.** It already knows
when a tile has safely landed, so it would be automatic for everyone. Against
that, it would tie the writer to a viewer's address, and the writer is currently
usable by anything. I have no measurement either way. The workflow is the safer
first answer because it can be undone.

---

## 4. What an operator sees when the microscope says no

A stage that will not move. A camera still busy with the last frame. A connection
that drops in the twentieth minute of a two-hour run. The window's job at that
moment is to say what happened and what to do about it.

### Is there anywhere for that information to come from?

**In the window's mock, no.** Nothing on that seam can fail. Every method
resolves. The connection checks are worth looking at closely, because they show
the shape of the gap: **on `claude/live-tiles-mvp`**, `lib/microscopes.js` lists
six checks an operator would want before a run — the microscope is reachable, the
credentials were accepted, the API version, the stage responds, the objectives
were listed, the storage is writable — and the comment beside them is exactly
right about why they matter:

> an autofocus that fails an hour into a run because the storage path was never
> writable is a bad way to find out.

But every one of those checks is written as a function that always returns a
success string. There is no failing branch anywhere. The window has a place to
*show* six answers and no way to receive a bad one. In the whole of `main.js`
there is a single `catch`, around opening the live picture.

**Underneath, yes — and it is better than it needs to be.** The controller's
contract on failure is specific, and it is stated in `zmart_controller/layer.py`:

> Failure is reported by raising: driver ops raise exceptions (`ValueError` for
> caller mistakes, `RuntimeError` for instrument failures or refusals) and never
> encode failure in a returned dict; the controller catches nothing and
> propagates driver exceptions to the caller unchanged.

That distinction is not bookkeeping. It is the difference between the two
sentences an operator needs to be able to tell apart: *you asked for something
this instrument cannot do* and *the instrument tried and would not*. The first is
fixable by the person at the keyboard; the second usually is not. The information
is already there, at the bottom, for free.

And the run above it already turns that into something a window can show. **On
`claude/live-tiles-mvp`**, `workflow/webapp/_flow.py` catches every failure and
broadcasts one small message naming the step, the state (`running`, `done`,
`failed`) and a sentence. Its own refusals — you have not connected yet, finish
the previous step first — are written for the operator to read rather than as
stack traces. The same file also refuses a step whose prerequisite has not
happened, independently of what the page believes, so a confused browser cannot
drive the instrument out of order.

### Proposal: every operation has the same three endings

**Proposal.** Whatever the window's seam ends up being, each operation ends in one
of exactly three ways, and all three are part of the declared boundary rather
than something that escapes it:

- **it is running**, and may report progress;
- **it finished**, with a value;
- **it did not**, with a sentence written for an operator and a note of whose
  fault it was — the request, or the instrument.

That last distinction is free, because the controller's exception types already
carry it. It costs one line at the point where an exception is turned into a
message; it cannot be recovered later if the two kinds have already been flattened
into one string.

**What I am deliberately not proposing**, in keeping with "prefer a better design
to a guard":

*No connection monitor.* Nothing in the controller reports the health of a link,
and `Session.closed` says so honestly — it *"deliberately says nothing about an
unexpected transport failure the driver has not observed yet"*. A dropped
connection surfaces when the next command fails, and that is the honest moment.
A heartbeat would only let the window find out slightly sooner, at the cost of a
mechanism that can itself be wrong.

*No retries on the boundary.* A stage that refused to move is a fact an operator
should see, not a thing to try again quietly. If a particular driver knows that a
particular command is worth repeating, that belongs in the driver, where the
knowledge is.

*Stopping cleanly is a different thing from failing, and it is already solved.*
**On `claude/live-tiles-mvp`**, `capture_positions` asks a `cancel` question
before every move and raises `RunCancelled` if the answer is yes, so a stopped run
is never mid-move or mid-save, and reads downstream as unfinished rather than as
a shorter success. That design should be kept exactly as it is. The window's seam
needs a way to ask for it, which today's mock has no notion of.

---

## 5. The one or two decisions that are cheap now and expensive later

Two. Both are cheap today only because so little depends on the seam.

### Decision one: the boundary hands back values, not sentences

Today, **on `claude/live-tiles-mvp`**, most of the mock's methods return a phrase
meant to be read: `"5x · 1.30 µm/px · 2 channels"`, `"origin at 0.0, 0.0 µm"`,
`"40 / 40 tiles"`. The window prints it.

That is comfortable while the far side is imaginary and it becomes a problem the
moment it is not. A real controller returns a state dictionary the driver owns; it
does not write English, and it should not be asked to. So either the sentence gets
written somewhere in the middle — in which case the wording of the operator's
window is buried in the plumbing, where nobody looks for it and it cannot be
translated or reworded — or every place that displays a result has to be rewritten
at the moment the real instrument arrives, which is precisely the throwing-away
this note exists to avoid.

There is a worked example of the cost already in the tree. **On
`claude/live-tiles-mvp`**, `lib/microscopes.js` carries this comment beside a
number it had to pull back out of a sentence:

> a number living only inside a sentence meant for reading is a number nothing can
> use — which is how the overview tile size came to be typed a second time
> somewhere else.

**The decision:** an operation returns what it measured or did, in ordinary
numbers and names, and the window turns that into the sentence the operator reads.
Today that is roughly ten return statements in one file that nothing imports.
Later it is every widget and every test.

**This is a "do not foreclose" decision, not a "prepare for the future" one.** It
builds nothing. It only declines to bake presentation into the wrong layer.

### Decision two: one pretend microscope, and it sits at the driver

This is section 2, stated as a decision. **Where the pretending happens decides
what the tests are worth.**

If the pretending stays at the top — a fake that stands in for the whole run —
then every widget written from here on is written against something no real
microscope will ever be, the four existing pretend microscopes become five, and
the day the instrument is attached is the day most of this code runs for the first
time.

If the pretending sits at the driver, where the registry already puts it, then the
window, the workflow, the focus fitting, the file naming and the scan loop are all
exercised by every test, and the real instrument changes one registration.

**The decision, in one sentence:** demo mode means a different driver, not a
different window.

The cost of taking it now is small and specific: the JS mock stops being the
planned future seam and becomes a drawing aid with a known end, and demo mode is
served through the workflow rather than around it. The cost of taking it later is
that every widget written in between has to be re-pointed and re-tested, and each
one will have quietly grown a dependency on something the mock does that a
microscope does not.

### What I am deliberately not recommending

A note on the second principle — *not foreclosing something is nearly free;
preparing for it builds machinery for a use that does not exist yet.*

Both decisions above are of the first kind. They remove something or decline to
add it. Neither builds machinery.

These would be the second kind, and none of them should be built now:

- **A general capability description**, so the window can ask a microscope what it
  can do and draw itself accordingly. The controller's `get_*` calls already
  answer that question for the one instrument in the room, and there is exactly one
  driver written. Build it when there are two microscopes with genuinely different
  answers.
- **A second real implementation of the window's seam.** With one implementation
  there is nothing to keep in step. Two would need a shared description, a test
  that both satisfy it, and somebody to keep all three honest.
- **A declaration of what each step needs and produces.** This is the one thing
  `application/WORKFLOW_SHELL.md` argues *should* be
  settled early, and this note does not disagree with it. But that is a decision
  about how steps hand work to each other, which is a level above the microscope
  boundary. It is mentioned here only so that the two are not confused: the
  boundary in this note sits directly beneath the shell described there, and
  nothing proposed here makes that declaration harder to add.

---

## What to read next

**On this branch:** `viz_studio/options/contract.md` for the one-interface-many-engines
pattern that section 2 is modelled on; `zmart_storage/coverage.py` and
`viz_studio/backend/announcements.py` for section 3;
`application/WORKFLOW_SHELL.md` for the operator window
this boundary sits beneath.

**On `claude/live-tiles-mvp`:** `zmart_controller/README.md` for the fourteen
commands and the discover-then-apply pattern; `zmart_drivers/mock/mock_driver.py`
for what a complete driver looks like; `application/parts/microscope/mock.js`
for the seam as it stands; `application/workflows/target_acquisition/webapp/_flow.py`
for a run that already turns failures into sentences an operator can read.
