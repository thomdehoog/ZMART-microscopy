# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `DATA_LAYOUT.md`, which has been brought
into line with the code and should be trusted.

---

## Read this first: a large folder no longer loses positions — but it is still slow

**Fixed.** A large folder used to draw only part of the specimen and say nothing about
the rest: above about six hundred and eighty positions the others never appeared at
all. A folder of nine hundred positions showed six hundred and eighty-one of them, and
a folder of two thousand showed six hundred and eighty-six. The ceiling did not rise
with the size of the folder, so at forty thousand positions an operator would have been
looking at roughly **1.7% of their specimen** while the viewer presented it as the whole
thing. That was the most serious thing in this document, and it was a correctness
problem rather than a slow one.

Stores are now handed to the engine in groups, and each group is allowed to finish being
read before the next is offered. Measured on this machine with `check_scale.py`:

| positions | arrived before | arrived now | seconds now |
| --------- | -------------- | ----------- | ----------- |
| 900       | 681            | **900**     | 32.7        |
| 2 000     | 686            | **2 000**   | 585.5       |

Read the second row for what it says about *both* halves. Every position arrives, which
is the fault being fixed. It takes nearly ten minutes, which is the fault that remains —
and the ten minutes is not waiting for the disk, as the profile further down shows.

The code is in `frontend/src/engine.js` — `handOverWhatIsWaiting` and the two callers
that queue rather than hand over directly — and it is pinned by
`tests/test_many_positions_arrive.py`, which turns the group size right down so the
pacing can be watched happening over forty positions in a few seconds.

Three things about it are worth carrying forward:

- **The burst was in the layer's constructor, not in `syncSources`.** An earlier audit
  proposed pacing the loop in `syncSources`, and that loop is not the one that bursts —
  it handles positions arriving *one at a time* during a live run, which never
  overwhelms anything. When a folder is opened cold the layer does not exist yet, so it
  is built by `makeLayer` from a description that already carries **every** position in
  `source`, and the engine reads the lot inside the constructor. So the layer is now
  built with only a first group and fed the rest afterwards. Pacing `syncSources` alone
  would have left a cold open exactly as broken as it was.
- **There is no separate path for a cold open.** The number of positions waiting simply
  *is* the size of the group: during a run that is one, which costs nothing beyond what
  happened before; opening a finished folder it is forty thousand, which becomes many
  groups. Nothing anywhere asks whether the data is live.
- **Why it happened at all, since the explanation is not the obvious one.** Reading one
  store means about four small requests, a browser will only hold six conversations with
  one address at a time, and beyond a few thousand queued requests it refuses to start
  any more — `net::ERR_INSUFFICIENT_RESOURCES`, in its own words. The engine records a
  position whose requests were refused as unreadable and leaves it out. Nothing was
  wrong with the data: every store it gave up on read back perfectly well afterwards,
  one at a time. Nothing was wrong with the server either — it was never answering more
  than seven requests at once during a thousand-position open, and was idle for two
  thirds of the wait.

**What this does not fix is speed, and it was never going to.** Nine hundred positions
take half a minute to open and then draw at twelve frames in five seconds, with a nudge
of a brightness slider costing about ten milliseconds. Every position is still read;
they are merely read in an orderly fashion. The answer to speed is item 0 — have the run
write into a single store, so there are not forty thousand of them to read. The other
candidate, handing the engine only the positions in view, was rejected; item 1 says why.

---

### Where the half-minute actually goes, profiled

The obvious guess is that a slow cold open means waiting for the disk or the network. It
does not, and it is worth knowing that before anyone spends a day on faster transport.
During a thousand-position open the server never answered more than seven requests at
once and sat idle for two thirds of the wait. The time is spent on the browser's main
thread, doing arithmetic.

A sampled profile of an eight-hundred-position cold open, with the page built without
minification so the names mean something (`npx vite build --minify false`), puts about a
third of the whole thing in one cluster:

| what | self time, of 16.5 s |
| --- | --- |
| `getRenderLayerTransform` | 1.83 s |
| `homogeneousTransformSubmatrix` | 1.50 s |
| the cached recompute driving them | 1.40 s |
| matrix `multiply` | 0.84 s |
| `CoordinateSpaceCombiner.update` | 0.74 s |

**The mechanism, which is waste rather than work.** Every position that finishes loading
registers its own coordinate space with a combiner shared by the whole scene, and the
combined space is rebuilt on the spot — walking every space registered so far. The
combined space genuinely changes each time, because the specimen's bounding box grows by
one position. And every change makes **every render layer already present recompute where
it sits in space**. Three render layers per position and eight hundred positions means
those transforms are recomputed some hundreds of thousands of times to reach answers that
differ by a hair.

**What holding it still would be worth, measured rather than argued.** Suppressing the
rebuild for the whole load and doing it once at the end — an upper bound, not a shippable
arrangement:

| positions | as it is | space held |
| --------- | -------- | ---------- |
| 400       | 3.2 s    | 2.9 s      |
| 800       | 14.8 s   | **7.3 s**  |

So roughly half at eight hundred, and more as the folder grows, since it is a square
being cut down. What is left after that is close to linear at about nine milliseconds a
position.

**It was deliberately not built, and here is the reasoning.** Three things weigh against
it. It does not change the shape: at nine milliseconds a position, forty thousand
positions would still be several minutes, so it postpones the problem rather than solving
it. It does nothing for the drawing rate — twelve frames in five seconds at nine hundred
positions is untouched, because that is the cost of thousands of render layers taking part
in every frame rather than the cost of loading them. And there is no supported way to ask
Neuroglancer to hold its coordinate space still, so it means replacing a method on an
internal object of theirs at run time: something that works today and can break silently
on a version bump, in the one place we chose not to rewrite.

**What does answer all three is item 0**, and it answers them by removing the situation
rather than managing it: a run written into one store never registers forty thousand
coordinate spaces, because there is one. The square cannot hurt what does not accumulate.
For folders that *are* laid out one store per position, the honest position is that they
open as slowly as they open; the measurements above are what you would start from if that
ever becomes unacceptable.

---

### How sources should be fed: the decisions

Reached in conversation and settled. The reasoning follows; these are the
conclusions, so that none of it has to be argued again. The first three are now built —
they are kept here because the reasoning is what stops them being undone by accident.

- **Three situations, three answers, none a substitute for another.** Loading a
  finished folder deliberately → batching. Navigating a very large run → hand the
  engine only the positions in view. Looking at the whole specimen at once → one
  object that stands for all of it, which is the overview acquisition or a stitched
  image. **Only the first is built.**
- ~~**Batching is one adaptive path, not a special case for cold opens.**~~ Built that
  way. The number of positions waiting *is* the batch size. During a run that is one,
  which costs nothing beyond what happened before; opening a finished folder it is forty
  thousand, which becomes many batches. Nothing branches on whether the data is live.
- ~~**Build the pacing where the layer is created**~~, not only where sources are added
  later — the burst is in the constructor. Done, and it was the half that mattered:
  pacing only the later additions would have left a cold open exactly as it was. The
  a large folder quick, and what makes it quick is item 0: a run that wrote into one
  store gives the engine one source instead of forty thousand.
- **Batching does not make a large folder quick.** It stops positions being lost, and
  that is all it does — nine hundred positions still take half a minute to open and
  still draw at twelve frames in five seconds. Speed comes from there being fewer
  stores in the first place; see item 0.
- **HTTP was not a choice and is not the problem.** Measure HTTP/2 before adopting it,
  and do not mistake it for a fix — see below.

### The reasoning behind those, and the two ways out

The ceiling is a **browser** limit, not a server or network one. During a
thousand-position open the server was never answering more than seven requests at
once and was idle for two thirds of the wait. What runs out is the browser's own
queue of outstanding fetches.

That matters because it rules out the explanation people reach for first. Nobody
chose HTTP here: Neuroglancer addresses data by URL and fetches it with the browser's
own machinery, and a browser cannot read a folder off the disk in any case — that is
a security boundary, not a preference. Even the desktop window is a browser engine.
So something has to serve the bytes, and one useful thing falls out of it: the same
viewer opens data on this disk, on a mapped share, or on a machine down the corridor,
with nothing changed but the address.

**Batching — feed the engine positions in groups, and let each group finish.** This
stops the silent loss, and it is measured: in batches of two hundred, a
thousand-position folder loaded a thousand of a thousand, and a two-thousand-position
folder two thousand of two thousand, with no failures at all. **This is now built**;
what follows is the reasoning it was built from, kept so that the shape of it is not
lost.

**Build it as one path, with the batch size adapting.** It is tempting to treat
batching as something needed only when a finished folder is opened, and therefore as
a special case that might be skipped. It is better understood as simply *how sources
are fed*: hand it however many positions there are, and let it feed them in groups.
During a run that is one position, which is a single group and costs nothing extra.
Opening a folder of forty thousand is many groups. Same code, no branch on whether
the data is live, and the live path stays exactly as cheap as it is today.

And it is wanted whatever else changes. However few stores a run produces, the moment
several are offered at once the pacing is what keeps any of them from being refused, so
this does not become dead code if item 0 succeeds — it simply has less to do.

**Where it is the right answer rather than a workaround: loading a finished folder on
purpose.** Offline you genuinely do want every position, and you mean it — the whole
specimen, ready to scroll through. There is nothing to trim and no view to narrow to.
The only question is the rate they go in at, and pacing them is what turns "the browser
refuses and thirty-nine thousand of them silently vanish" into "they all arrive, in
order, and you can watch it happen". That is the mechanism the case requires.

**The batch size must adapt, so that one path serves both ways of working.** A
smart-microscopy run hands it a single position, which is a batch of one and costs
nothing beyond what happens today. A finished folder hands it forty thousand, which
becomes many batches. Neither is a special case and there is no branch on whether the
data is live — the number of positions waiting is simply the size of the batch, and
during a run that number is usually one.

What batching does *not* do is make a large folder quick, and it should not be
expected to. It still
resolves every one of forty thousand positions, merely spread over time — still some
hundred and sixty thousand requests, still minutes before the first pixel, for a
specimen of which only a small part can be on screen at once. It makes unnecessary
work orderly rather than removing it.

### And there is a case neither of them can help

Batching assumes the view holds a few positions at a time.
That is true while navigating, and false the moment the operator zooms out to see the
whole specimen: the view then genuinely contains all forty thousand, and pacing or
windowing cannot help, because all of them really are needed.

Only one thing makes that view cheap, and it is not a change to how sources are fed:
**a single object that represents the whole specimen.** There are two, and both
already exist as decisions rather than as work to invent.

The **overview acquisition** is the first, and it is why the shape of a
smart-microscopy run matters here. An overview is a deliberately low-resolution scan
of everything — one store, or a few — so the zoomed-out view is not forty thousand
target scans composited, it is the overview. The resolution hierarchy is in the
acquisition, not in the file.

A **stitched image** is the second, for data that is finished: one global pyramid, so
zooming out reads a handful of coarse pieces that already stand for the whole thing.
That is Decision 1b in `DATA_LAYOUT.md`, and this is the argument for it that is about
capability rather than tidiness.

So, plainly:

| what the operator is doing | what makes it affordable |
|---|---|
| navigating in detail | only the positions in view |
| watching positions arrive | nothing — they come one at a time already |
| looking at the whole specimen | one object that represents all of it |

Worth adding what is *not* a problem: a single very large store. There is nothing to
batch — one source, and its pyramid does the work. That is the case Neuroglancer was
built for and it is already fine.

So there are three cases, and the answer to two of them turned out to be the same one.
Loading a finished folder deliberately: batching, so nothing is lost. Navigating a very
large run, and looking at the whole specimen at once: **one object that stands for all of
it**, which for a smart-microscopy run means the run wrote into a single store (item 0),
and otherwise means the overview. Then forty thousand positions cost whatever is being looked
at, and the browser's queue is never near its limit — so batching stops being what keeps
the viewer honest and goes back to being the ordinary way sources are handed over.

The catch was *where* the batching had to go, which is not where it first appeared. The
burst is not in `syncSources` but in the layer's construction, which was handed every
position at once; a fix in `syncSources` alone would have left a cold open exactly as
broken as it was. `handOverWhatIsWaiting` in `engine.js` is where the pacing now lives.

**HTTP/2 — the same HTTP, many requests multiplexed down one connection.** Instead
of six conversations at a time there are a hundred or more, so the queue drains far
faster and probably never reaches the limit that is currently being hit.

Worth knowing, and worth measuring before adopting, but it is **not** the cure and
should not be mistaken for one:

- It treats the symptom. Forty thousand sources would still be resolved before the
  first pixel, for a specimen of which only a small part can be seen at once. The
  work is unnecessary at any speed.
- Python's standard library does not speak it, so it means a dependency — against a
  deliberate decision recorded in `server.py` to stay installable from conda with
  nothing exotic.
- And the limit reached is on *outstanding fetches*, not only on connections. More
  concurrency drains the queue faster but does not obviously raise that bound, so
  the improvement is likely rather than certain. Measure before believing it.

The sensible order was therefore: batch first, because it is the cure and it is
measured; then, if a large folder is still slower than it should be, measure whether
HTTP/2 buys enough to justify the dependency. The batching is done, so HTTP/2 is now a
live question rather than a premature one — but read the third point above before
spending a day on it, and read item 0 first, because a run that wrote into one store has
far fewer requests to multiplex in the first place.

**What is not worth doing:** reaching past HTTP with a reader of our own inside the
engine. That is deep surgery on the one piece we chose specifically not to rewrite,
and the whole reason this viewer exists is that Neuroglancer already handles data of
this size well.

---

## Start here: two things, and they are the important ones

Everything else in this document is worth doing and none of it is worth doing first. These
two are, and they are related: the first changes what the viewer is asked to open, and the
second says what opening it costs.

### A. Write the run into one OME-Zarr as it goes

**This is no longer a question, it is the aim.** `DATA_LAYOUT.md` Decision 1b states it, the
measurements behind it are in this document under item 0, and the viewer's side of it is
built and tested. What is missing is the thing that writes.

The short version of why: what costs the viewer is the *number of separate stores*, not the
amount of data behind them. One store describing about 137 GB reaches the screen in 1.4
seconds on 38 requests; three hundred separate positions covering a far smaller specimen
take 2.4 seconds on 1 125 requests and then draw at a quarter of the rate. Writing into one
store as the run goes gets that benefit with **no copy and no extra step** — the tile is
written once, where it belongs.

Read item 0 below for the full evidence and for what the viewer already does. What has
changed since item 0 was written is that the two things it listed as still needing a
decision have both been decided, in `DATA_LAYOUT.md`:

- **How large to make the image.** Sized to the ground the experiment means to cover, or —
  where the experiment does not say — **the stage's own travel limits**. Declared size is not
  occupied size (a declared 4 TiB image measured 59 MiB on disk), so this can be generously
  over-estimated. The origin goes at the low corner and growth only ever goes outward,
  because growing backwards would shift every chunk index and invalidate everything already
  written. With the stage limits as the canvas, growth becomes impossible rather than merely
  rare, since the stage cannot reach outside them.
- **The one constraint that makes concurrent writing safe: tiles must begin and end on chunk
  boundaries in y and x.** This is the real cost of the change and it falls entirely on the
  writing side. Two tiles sharing a chunk file both read it, each adds its own tile, and each
  writes the whole chunk back — so the second erases the first, silently. Measured: tiles
  straddling chunk edges lost up to **75% of a tile's voxels**, with no error and no warning.
  Choose the chunk size and the tile step together; watch overlap especially, since a few per
  cent of overlap that is not a whole number of chunks puts two tiles in one chunk; and where
  neither is possible, serialise the writes for tiles that share chunks.

There is one genuinely open piece, and it is work rather than a decision: **the pyramid has
to be kept up to date as tiles land**, during the run rather than after it. It is bounded — a
tile only affects the levels above its own position — but somebody has to write it.

Where the writer belongs is also still open, and is the first thing to settle: the mesoSPIM
writes its own OME-Zarr today and our driver copies the frame files it produced, so this is
either a conversion step after acquisition or a change to what the driver writes. That
choice decides everything about how the code is shaped.

**How you would know it was finished.** A run writes one store; the viewer is pointed at it
and shows the specimen growing tile by tile as they land, with the run announcing
`{"wrote_image_in_place": true}`; and a test writes several tiles concurrently and asserts
every voxel of every tile survived. `check_writing_into_one_store.py` already does the
viewer half of that and is the place to start reading.

### B. Measure what one open folder costs in memory

Closing an acquisition now gives back everything the server remembered about it, so a
session that moves from folder to folder no longer accumulates. **Nothing is forgotten while
a folder stays open**, which is deliberate — it is what keeps the viewer quick — and it
leaves a question nobody has answered: what does *one* folder of forty thousand positions
cost, and at what point does a machine give up?

Four things are remembered per store, all keyed on its path on disk: what it contains, how
many frames are written, the brightness measured from its pixels, and the small description
files handed to the page. Three of them hold one entry per store. Find the growth law and
the ceiling, and say it in megabytes per thousand positions so an operator can be told what
a folder will cost before opening it — which is exactly what Decision 5 asks the interface to
do.

The browser tab is a separate question and a real one, since it holds decoded image rather
than metadata. Worth measuring in the same sitting but do not conflate the two numbers.

This is audit brief 4 below, and the half about closing is now done; what is written there
is the remaining half.

---

## Done since the last hand-over

**Positions are no longer lost.** This is the first of audit 3's three walls, and the
one that was a correctness problem rather than a slow one. Stores are handed to the
engine in groups of two hundred, each group allowed to finish being read before the next
is offered, and the burst that did the damage — the layer's constructor, handed every
position at once — is paced along with everything else. Nine hundred positions now
arrive nine hundred of nine hundred where six hundred and eighty-one arrived before. The
section at the top of this document has the numbers and the reasoning; `engine.js` has
the code and a long note above it saying why it is shaped the way it is.

Two things worth knowing if you touch it. The pacing is **one path with no special
case** — during a run the number of positions waiting is one, so a single position goes
in immediately and the live path costs exactly what it cost before. And the test that
pins it (`tests/test_many_positions_arrive.py`) turns the group size down to five so
that pacing can be watched happening over forty positions in thirteen seconds rather
than over a thousand in several minutes; it checks both that every position arrives
*and* that they arrived in groups, the second being the positive control without which
it would be testing nothing.

**The cold open was ninety minutes because we measured every position and used
almost none of it.** This was the worst number in the system and the first of the
six audits below has now been run against it. The diagnosis in the previous
hand-over was half right and the correction is what mattered.

Judging one store's brightness costs about 86 milliseconds for a store shaped the
way `DATA_LAYOUT.md` asks for. Of that, reading the pixels off the disk is 17
milliseconds and the arithmetic afterwards is 74 — so the expensive part was never
the reading. But the real fault was larger and simpler than either. Several
positions of the same acquisition type merge into a **single row** in the panel,
and a row carries one brightness window and one histogram. The server measured
every store it met and then, for all but the first of each row, threw the answer
away: the merge wanted only the store's address and how many frames it had, and
both of those follow from the store's name without touching a pixel.

On a folder of a thousand positions that was a thousand measurements to fill in
one row. Measured here on three hundred positions, before and after, over the same
data: **126.3 seconds to 1.31 seconds**, with three stores measured instead of
three hundred. The description the panel receives is byte-for-byte identical — not
similar, identical — because the discarded measurements were never reaching the
screen in the first place. At forty thousand positions this is roughly fifty-seven
minutes down to about twelve seconds.

The change is small: the call that reads pixels moved inside the branch that
creates a row. The measuring script is kept as `measure_cold_open.py`, and it
reports how many stores were read as well as how long it took — so if the saving
is ever lost again, running it says so in as many words rather than leaving
somebody to notice a folder is slow. What is left of the server's cold open is linear and modest, about
0.35 milliseconds a position, so on the order of fourteen seconds at forty
thousand — at which point the wall becomes the engine's own fan-out rather than
anything of ours, which is exactly the question audit 3 below was written to
settle.

**Four things the same audit turned up that were deliberately not acted on**, each
because it is a decision for the operator rather than a defect to fix:

- **The brightness arithmetic does far more work than it needs to.** It converts
  the camera's 16-bit whole numbers into 64-bit decimals, checks each one for being
  a real number, and then puts millions of them in order three separate times. A
  16-bit camera can only produce 65 536 different values, so counting how many of
  each there are gives the same percentiles by a much shorter route — verified
  identical on forty stores, not merely close. It is about twelve times cheaper.
  After the fix above this applies to only a handful of stores per folder, so the
  saving is now small; what it would buy is removing the worst case, which is a
  store with a large coarsest pyramid level at around 211 milliseconds.
- **`DATA_LAYOUT.md` promises something the code does not do.** The guidance at
  the `omero` section tells whoever writes a store that supplying a display window
  saves the viewer a read of the pixels. It does not: the window is honoured for
  the flat view, but the volume window and the histogram are still worked out from
  pixels regardless. Either make it true — which would give a well-written
  acquisition an instant cold open, and is worth having — or correct the document.
  This is the same drift the closing caution of this file warns about.
- **A row's brightness comes from whichever of its positions sorts first by name.**
  That was already so and nothing has changed, but the fix makes it plain instead
  of hiding it behind forty thousand measurements that were discarded. For a mosaic
  the first position is a corner of the specimen, which may be dim and unrepresentative.
  Sampling a handful of positions spread through the run and combining them would
  cost about seven tenths of a second **however large the folder** — a fixed price,
  because it is a fixed number of stores. Worth an hour on real data first, to see
  whether the window that comes out today is actually wrong.
- **Parallelising the brightness pass is not worth building.** Measured on this
  machine: threads flatten at about 1.4× however many are used, because the work is
  arithmetic and Python lets only one thread do arithmetic at a time; four separate
  processes give 3.3× on four cores. So the ceiling is the processor, not the
  opening of files — a useful thing to know. But three minutes is worse than twelve
  seconds for a great deal more machinery, so this belongs in the drawer rather than
  in the code.

**The scale of the target, measured at last.** Two audits ran against synthetic folders of
up to forty thousand positions. The per-chunk path is flat — 0.21 ms median at forty
thousand, unchanged from a thousand — which is the part that belongs to Neuroglancer and
the part that is fine. Everything expensive is ours. Three costs grew with the square of
the number of positions open; two are fixed (see below), and the third is in `engine.js`
and is not. The worst single figure is the cold open: about ninety minutes at forty
thousand positions, spent reading pixels to judge brightness one store at a time.

**Two quadratics removed.** Looking again at a watched folder checked each image found
against a *list* of images already known, which walks the list — fifteen seconds a look at
forty thousand positions, and it runs whenever anything is announced. Asked of a set now:
four thousand positions take forty-one milliseconds. And the per-position frame counts were
rebuilt into a new list for every position added, the same fault as the addresses beside
them.

**A caution worth carrying.** Fixing the addresses that way first introduced a worse bug:
the row borrowed its list from the remembered measurement of a store rather than owning one,
so extending in place grew the remembered copy a little on every answer. Two pre-existing
tests caught it. The general shape: a shared structure is safe to copy from and unsafe to
extend, and swapping one for the other is exactly where that stops being true.

**The play button on the sliders threw and nobody noticed.** An earlier split moved the
slider into a file of its own and left the constant it needed behind in the shell, so
pressing play raised an error inside the handler and the view sat still. No test pressed it —
they all drive the slider directly. Worth fixing properly: nothing in the suite fails when
the page raises an uncaught error, and a listener for that in `tests/conftest.py` would have
caught this and will catch the next one.


Recorded here rather than deleted, because the *reasons* are worth keeping and because
two of these were long-standing bugs whose shape is easy to reintroduce.

**The slice view drawing only its own background** — solved, and it was none of the four
suspects. The magnification is chosen by the engine the first moment it believes it knows
what space the picture lives in, and it is careful afterwards to preserve the physical
scale when the voxel size changes. We hand it layers before the images have loaded, so
for a moment there are layers and no axes; the engine takes that as settled, has no voxel
size to work from, falls back to one voxel being one metre, and picks its usual default
of one voxel to a pixel — meaning one *metre* to a pixel. The real axes then arrive and it
faithfully keeps that scale. A specimen a tenth of a millimetre across ends up a
ten-thousandth of a pixel wide. The fix waits for the axes and lets the engine choose
again. `localPosition` was innocent.

**A new acquisition going unnoticed for a whole session** — this was still live, and it
happened about two times in five. A folder's modification time moves when something is
*created* inside it, not when a file already there is rewritten; writers (zarr included)
create the description file early and empty and fill it in later, so the folder looked
unchanged at exactly the moment it became readable. Now the description file is looked at
too.

**Tests that can see a blank screen** — `tests/pixels.py` photographs the middle of the
image and measures it, with a companion test that blanks the panel on purpose to prove
the check can fail.

**Caching follows whether the run is finished.** Nothing is kept while the instrument is
writing; finished data is kept for a year. Worth knowing, because it surprised us:
returning to somewhere you have been costs no fetch *either way* — what makes it free is
the engine's own memory of decoded pieces, not the browser's HTTP cache.

**A growing timelapse now reaches the engine.** This was item 1 of the last hand-over
and the only thing standing in the way of a run being watched properly. The cause was
not where the last session was looking. Handing a data source its own address back does
make the engine resolve the store again — that part was right — but the engine keeps its
own memory, inside the page, of everything it has ever worked out about a store, and the
resolving was answered out of that memory. Nothing reached the disk. That memory has no
time limit and no size limit, the engine never releases an entry once made, and no
instruction the server can send in a header can reach it. So the viewer now drops what is
remembered about that one store first, and only then asks. What is dropped is only what
was *read*; the decoded image is kept under a separate arrangement and is left strictly
alone.

Two things came out of it that are worth carrying forward. Dropping that memory makes the
next question genuinely reach the disk, so doing it on every announcement would mean four
small requests per position per announcement — thousands, on a row holding a store for
every place the microscope visited. It is therefore done only for a row whose frame count
has actually moved, and there is a test with a positive control on both halves. And there
is a real cost that Decision 2 in `DATA_LAYOUT.md` had not accounted for: the engine files
decoded image under a key that includes the array's shape, so when the shape genuinely
changes the frame on screen is fetched again. It is bounded and it is once per growth, but
it is not free. `DATA_LAYOUT.md` now says so.

**The channel from server to page** — built, as server-sent events. See below for what
was deliberately not done with it.

Also: the mesoSPIM tests are reachable through `ZMART_MESOSPIM_STORE` instead of naming
one PC's folder; the slice background is black; and `--dist loadfile` keeps whole test
files on one worker.

---

## The scale audits: three run, three left

*This was the "start here" of the last hand-over, and three of the six have since been
done. It is still the right way to find what nobody is looking at, but read the two items
above first — they are what the next session should actually begin with.*

The target is real and it is not met: **forty thousand positions, forty terabytes.** Two
audits at that scale have run and their findings are folded into the items below, but they
covered the backend and the frontend only broadly. Put an agent on each of these briefs,
because everything found so far was in a place nobody was looking.

**Three of the six have now been run** — the cold open (1), the live path (2) and the
engine boundary (3). What is left is memory (4), the per-chunk path (5) and the interface
under load (6).

**It is worth saying what running one costs.** One
auditor, working alone on a quiet machine, took about twenty minutes and found the largest
single saving in the project so far. Running all six at once was tried and abandoned: this
machine has four processors, and six agents each driving their own browser and their own
server spend most of their time measuring each other rather than the viewer. If you want
them in parallel, give them a bigger machine or accept that every timing they report is
worthless; otherwise run them one at a time, which is what produced the result above.
Findings expressed as counts — of requests, of measurements, of renders — survive
contention and are worth asking for either way.

Of the three left, **memory (4) is the one to do next**, and it is item B under "Start here"
at the top of this document.

Give each of them the figures already measured, tell them not to re-litigate the decisions
in `DATA_LAYOUT.md`, and require that every finding be **measured rather than reasoned** —
synthetic sparse stores cost almost nothing to fabricate, so an unmeasured claim has no
excuse. Ask for file:line, the growth law, the cost at 1 000 / 10 000 / 40 000 positions, a
concrete fix, and a plain statement of which findings are theoretical rather than reachable.

The briefs, chosen so they do not overlap:

1. ~~**The cold open**~~ — **done; see "Done since the last hand-over" above.** It was not
   what it looked like: the cost was measuring every position and using almost none of the
   answers, and removing that took the server's part of the cold open from roughly
   fifty-seven minutes to about twelve seconds at forty thousand positions. The four
   findings that came with it and were left undone are listed above.
2. ~~**The live path**~~ — **done, and it favours one store.** `measure_the_live_path.py`
   times one announcement in both layouts, with varying amounts already open. The question
   was whether the cost of noticing one new thing grows with how much is already there,
   because a cost of that shape is invisible in a short test and painful by the end of a
   real acquisition.

   | already open | a position arriving | | a tile landing in one store | |
   |---|---|---|---|---|
   | | requests | seconds | requests | seconds |
   | 10 | 7 | 0.02 s | 23 | 0.54 s |
   | 100 | 7 | 0.05 s | 22 | 0.30 s |
   | 400 | 7 | **0.26 s** | 22 | **0.31 s** |

   **Requests are level in both**, which is the half that is already right: neither layout
   pays more round trips as the run goes on. The per-store re-read that used to cost six
   thousand requests at a thousand positions is gone and stays gone.

   **The seconds are not level for one store per position.** A position arriving costs
   0.02 s when ten are open and 0.26 s when four hundred are — thirteen times as much for
   forty times the positions. That is the same growth that makes a cold open superlinear,
   appearing in the live path: each position added makes the engine rework where everything
   sits in space. Extrapolating is unwise, but the direction is not in doubt, and a run of
   tens of thousands of positions would feel it.

   **One store is flat**, at about three tenths of a second whatever has already been
   written, which is the property that lets a viewer be left running for a whole
   experiment.

   Two things to know about the twenty-two requests. They are what letting go costs: the
   pieces on screen are fetched again, and that number follows the size of the window
   rather than the size of the specimen — which is why it does not move between rows. But
   they are paid on **every** announcement, so a run announcing several times a second
   would be refetching the view several times a second. It is bounded and it is small, but
   if a run announces very often it is worth announcing less often rather than making this
   cheaper.
3. ~~**The engine boundary**~~ — **done, and the answer is that the wall is the engine's.**
   Item 1 below is therefore **compulsory, not optional.** The audit confirmed it the
   strongest way available: with our own code taken out of the path entirely and positions
   added through Neuroglancer's own calls, the same ceiling and the same times appeared,
   within noise. In a sampled profile of a thousand-position cold open, our whole
   `syncLayers` pass came to 718 milliseconds out of twenty seconds — and 711 of those were
   inside the engine's own `addDataSource`, which we merely call. Our own arithmetic was
   about eight milliseconds. There is nothing cheap to fix on our side.

   Three separate walls were measured. **The first of them is now down**; the other two
   are what item 0 removes, by there being one store rather than tens of thousands.

   - ~~**Positions are silently lost above about 680.**~~ **Fixed** — stores are handed
     over in groups now. See the section at the top of this document.
   - **Each extra position costs more than the last.** Adding two hundred positions takes
     2.8 seconds to an empty row, 19.8 seconds when eight hundred are already open, and 323
     seconds when eighteen hundred are. Loading a complete two-thousand-position mosaic
     takes eight minutes and forty-nine seconds. So feeding positions in gently cures the
     silence but not the slowness.
   - **Even fully loaded, it will not draw.** With a thousand positions open the viewer
     managed 24 frames in five seconds where a hundred positions managed 302, and a single
     step of a contrast slider cost 191 milliseconds against 16. Three drawing layers are
     created per position and every one of them takes part in every frame. This is the
     finding that settles it: no arrangement of the *loading* helps, because the trouble
     is still there once loading has finished. The engine has to be holding fewer
     positions.

   Two useful negatives came out of the same audit. **The size of the folder description is
   not a problem** and that concern can be closed: two megabytes of text at forty thousand
   positions, which a browser unpacks in six milliseconds. And **a figure recorded further
   down this document should be distrusted** — the cold open of "8.7 s and 2 936 requests at
   a thousand positions" was almost certainly measured on an incomplete mosaic, since a
   thousand positions cannot be fully read in that many requests. Any harness used above a
   few hundred positions must report how many positions actually arrived alongside how long
   it took, or a folder that got faster by giving up sooner will read as an improvement.

   One caveat carried honestly: the machine had no graphics card and rendered in software,
   so the frame times are pessimistic. What better hardware cannot change is the shape —
   three drawing layers per position, each recomputed whenever the shared coordinate space
   moves, grows with the number of positions however fast the card is.
4. **Memory** — what the server holds after a long run, and what the browser tab holds.
   Half of this is now dealt with: closing an acquisition drops everything remembered about
   its stores, so opening one folder after another no longer keeps them all until the viewer
   is quit. What is left is the harder half. Nothing is forgotten while a folder stays open,
   which is right — it is what keeps the viewer quick — but it means a single folder of forty
   thousand positions has a memory cost nobody has measured. Find that ceiling and say when a
   machine gives up. The browser tab is untouched by any of this and is its own question.
5. **The per-chunk path** — everything between a chunk request arriving and bytes leaving.
   It is the one path measured flat so far, which makes it the one worth defending: find what
   would make it not flat, and what the ceiling is in requests per second.
6. **The interface under load** — what a contrast drag, a group reorder and a mode switch
   cost with forty thousand positions open, and what the panel does per render. An earlier
   audit found sixty-one milliseconds of work per slider event at that scale, on the same
   thread the engine draws with.

A seventh, if there is room: **what a stitched image costs to make and to view**, measured
rather than assumed. Several of the items above are only worth doing if stitching turns out
not to be the better answer for finished data.

---

## 0. Write the run into one OME-Zarr, not one per position — **decided**

**This is the aim, not a proposal.** It is recorded as Decision 1b in `DATA_LAYOUT.md`, and
what the next session should do about it is set out under "Start here" at the top of this
document. What follows is the evidence, kept here because it is worth reading before
building anything on top of it.

The two questions this section used to leave open — how large to make the image, and how to
write into it safely from more than one place at once — have both since been answered. See
"Start here", or `DATA_LAYOUT.md` for the full reasoning.

**What costs the viewer is the number of separate stores, not the amount of data behind
them.** That sentence is the whole finding, and `measure_one_stitched_store.py` is the
evidence:

| | config | first pixel | requests | stores | drawing layers | frames in 5 s |
|---|---|---|---|---|---|---|
| one fused store, 4 096³ voxels (~137 GB) | 0.6 s | **1.4 s** | **38** | 1 | **5** | **255** |
| 300 separate positions (a few megabytes) | 0.6 s | 2.4 s | 1 125 | 300 | 302 | 62 |

The fused store describes a specimen thousands of times larger and opens faster, on a
thirtieth of the requests, and then draws four times as smoothly. Every wall in audit 3
is a cost per store, so one store has none of them.

**Fusing a finished folder means copying everything**, which is the honest objection to
it: reading every tile and writing several hundred gigabytes out again, with both copies
on disk while it runs, plus the pyramid — which is cheaper than it sounds, adding about
14% since each level is an eighth of the one below. If the tiles land on chunk boundaries
and no blending of overlaps is wanted, the coarsest work can be avoided by hard-linking
the tile files under the fused array's chunk names, so no bytes move; blending overlaps
rules that out.

**But a smart-microscopy run does not have to fuse anything — it can write into the one
store as it goes.** The tile is written once instead of twice, and the viewer holds a
single source from the very first moment. This is the operator's suggestion and it is the
better answer.

**The one condition — measured, and now built.** The engine remembers every piece of
image it has decoded, including the pieces it found empty, with no time limit. A tile
written into a place the viewer has already looked at is therefore not noticed at all —
the picture stays empty and **not one request is made**.
`check_writing_into_one_store.py` demonstrates it, and the viewer now handles it: an
announcement may carry `{"wrote_image_in_place": true}`, and on hearing it the viewer asks
the sources to let go of what they have decoded. The tile then appears, on nine requests.
Nine, not nine thousand — only the pieces actually on screen are fetched again, so the
cost does not grow with the specimen. Pinned by `tests/test_writing_into_one_store.py`.

**What a run has to do, which is one line.** Announce as it already does, and add that
flag when the image went into a store the viewer may already have open:

```
POST /api/announce   {"reason": "a tile was written", "wrote_image_in_place": true}
```

**The flag is off by default, and that matters as much as the feature.** For the ordinary
layout — one store per position — it is not true, and a viewer that let go on every
announcement would spend a long run refetching image it already had, which is exactly the
waste all of this exists to avoid. Nothing on disk distinguishes the two cases: same
store, same name, same size. So the writer, which is the only one that knows, says which
it did. An earlier attempt worked it out from the scene instead of being told, and the
second test in that file caught it throwing the view away every time a neighbour arrived.

That is the same lesson as the growing timelapse, one level down. The engine's memory is
the right thing almost always and has to be released deliberately in the one case where
the disk has changed underneath it. There the viewer drops what it had *read* about a
store; here it would drop what it had *decoded* from one.

**What was still open when this was written, and where it now stands:**

- ~~**The shape has to be known when the store is created.**~~ **Decided.** Sized to the
  ground the experiment means to cover, or the stage's travel limits where it does not say.
  Declared size is not occupied size, so over-estimating is free, and with the stage limits
  as the canvas no tile can ever land outside it. See `DATA_LAYOUT.md`.
- **The pyramid has to be kept up to date as tiles land**, which is real work during the
  run rather than after it. It is bounded — a tile only affects the levels above its own
  position — but somebody has to write it. **Still open, and it is the main piece of work.**
- **Tiles must land on chunk boundaries**, which was not known when this section was written
  and is the constraint that makes concurrent writing safe at all. Tiles straddling chunk
  edges lost up to 75% of a tile's voxels, silently. See "Start here" above.

---

## 1. Hand the engine only the sources it needs — **rejected; do not build this**

> **Do not start here, whatever the paragraphs below say.** A viewing window — the viewer
> keeping its own idea of what is on screen and feeding the engine only those positions — was
> turned down, and for a reason that survives the argument for it: deciding which pieces of
> image to fetch from where the view is, is precisely what Neuroglancer already does, and
> better than we would. Keeping our own copy of that knowledge is how this project has got
> into trouble before.
>
> There is also a second objection, which is Decision 5 in `DATA_LAYOUT.md`: a viewer that
> shows less than it was given has to be right about what the operator wanted, and when it is
> wrong it is wrong invisibly. That is the same failure as the silent ceiling at the top of
> this document, only deliberate.
>
> **The problem it was solving is real** — a large folder of separate positions draws slowly,
> and the measurements below are sound. The answer is item 0: fewer stores, because the run
> wrote into one. That makes the engine's work smaller rather than making our code cleverer.
>
> Kept because the analysis of *where* the cost sits is accurate and useful, and because
> somebody will propose this again.

**What follows was written when this was the plan.** Audit 3 has been run and
its findings are above: the wall is inside Neuroglancer, and it is three walls rather than
one. The first — positions beyond about six hundred and eighty being silently dropped — has
been beaten by handing the stores over in groups. The other two are still there: each extra
position costs more than the last, and even fully loaded a large folder will not draw at a
usable rate. The server's share of opening a large folder is now about twelve seconds at
forty thousand positions, so everything left is on the engine's side.

A viewing window would answer both of the remaining walls: the number of positions the engine
holds stays bounded, so it never pays the cost that grows with the square of the number open,
and never ends up with thousands of drawing layers in a single frame.

**Note what this argument got wrong about writing into one store.** It says that during a
live run positions arrive one at a time and the count climbs past six hundred and eighty
regardless, so a window is needed whatever is decided about finished data. That is true of
one store *per position*, and it is exactly what item 0 changes: a run writing into a single
image adds no stores as it goes, so the count never climbs at all. The two are not
alternatives at different stages — one of them removes the problem the other manages.

**The pacing is already built, and the window goes in the same place.** Feeding positions in
bounded groups and extending as the operator navigates are the same mechanism: the pacing
decides *how fast* positions go in, the window decides *which*. `handOverWhatIsWaiting` in
`engine.js` is the first half, and a window that lets the operator jump across the specimen
will hand it a couple of hundred positions at a time — which is exactly the burst the pacing
already handles.

A row still takes every position of its acquisition type. Each source is read when it is
added — roughly four small metadata requests — through a browser that allows six connections
at a time. At a few hundred positions that is fine. At several thousand it is thousands of
round trips before the first pixel, and the pacing makes those orderly without making them
fewer.

The engine remembers each answer afterwards, and during a live run the positions arrive
one at a time, so the cost is spread and invisible. The case that hurts is opening a large
finished folder cold.

That remembering is the same memory described under the growing-timelapse work above, so
the two items meet here. Anything that makes a store be read again pays this cost afresh
for that store, which is why the re-read is confined to a row whose frame count has
actually moved. If you change how sources are added, keep that confinement — widening it
is the easiest way to turn a few hundred requests into a few thousand without noticing.

Two answers, and they are complementary: add sources for what is in view and extend as
the operator navigates; and prefer a stitched image for finished data, which is one
source instead of thousands.

**The measuring asked for here has been done**, and `check_scale.py` is the tool that does
it: it writes a throwaway folder of whatever size you name, opens the viewer on it, and
reports how many positions actually arrived alongside how long it took and how smoothly it
then draws. Run it before and after any change to this, on the machine you actually use.

Note that `tests/pixels.py` now gives you a way to time *first pixel* rather than first
chunk, which is the number that actually matters here.

### The same cost, arriving a second way: a timelapse across many positions

This has now been measured, and it is the thing standing between the viewer and a run of
the size it is meant for. **Read the numbers before deciding what to build.**

The frame count that decides whether a store is read again belongs to the *row*, and it
is the highest count across all the positions merged into that row (`server.py`, where
the rows are built). That is right for the time slider — it should reach as far as the
position furthest along — but it means one position gaining a frame moves the whole row's
count, and every store on the row is read again, not just the one that grew.

Measured on this machine, with two channels and two pyramid levels per position, on
stores small enough to be sparse. The cost being counted is round trips for the small
files describing each store, and that count follows the number of positions and channels,
not the size of the image — so these figures stand for a 400 GB run just as well as for
the few megabytes actually written.

| positions | opening the folder cold | one frame landing on one position |
| --------- | ----------------------- | --------------------------------- |
| 10        | 0.4 s, 40 requests      | 0.1 s, 60 requests                |
| 50        | 0.7 s, 224 requests     | 0.4 s, 300 requests               |
| 200       | 2.0 s, 572 requests     | 6.2 s, 1 200 requests             |
| 1 000     | 8.7 s, 2 936 requests   | 18.5 s, 6 000 requests            |

The frame-landing column is exact — six requests per position, every time. The cold-open
column wobbles by a few per cent between runs, since what the engine asks for while it is
still working out what it is looking at depends a little on what arrives first.

Read the last row twice. At a thousand positions, **one frame arriving at one position
costs more than opening the whole folder from cold** — and it does so every time any
position advances. A run writing a frame every few seconds would never finish catching up
with itself. This is on localhost, where a round trip is as cheap as it will ever be.

The shape is linear in the number of positions, so a run twice the size costs twice as
much; there is no cliff to be surprised by, and no threshold below which the problem
disappears. At a hundred positions it is barely noticeable, which is why it was not
noticed.

**This is now fixed, and the fix is worth understanding rather than just noting.** The
figures above are what it used to cost. Here is the same table afterwards:

| positions | one frame landing, before | after            |
| --------- | ------------------------- | ---------------- |
| 10        | 0.1 s, 60 requests        | 0.1 s, 6 requests |
| 50        | 0.4 s, 300 requests       | 0.1 s, 6 requests |
| 200       | 6.2 s, 1 200 requests     | 2.4 s, 6 requests |
| 1 000     | 18.5 s, 6 000 requests    | 6.6 s, 6 requests |

Six requests, whatever the size of the run. The cost of noticing a frame no longer has
anything to do with how many positions are open, which is the property that matters — a
run twice the size now costs the same rather than twice as much.

**How, and why it is not the change the previous note proposed.** That note suggested
having the announcement name the stores that had changed. That would have worked, but it
cuts against a decision made deliberately in `announcements.py`: the message says only
*something changed*, and the page then reads the disk, because the disk is what is true
and two descriptions of the world would have to be kept in step. That reasoning is sound
and was worth keeping.

It turned out not to be necessary. The count of frames written is worked out **per store**
already, in the course of building the answer to "what is open" — and was then thrown away,
collapsed into a single figure for the whole row. The row's figure is the highest across
its positions, which is exactly what the time slider needs and exactly no use for deciding
which position moved. So the per-store counts are now kept as well, alongside the list of
stores and in the same order, and the viewer compares each store against what it last saw.
Nothing was added to the announcement; the page still learns everything from the same
read of the disk it was already doing. The information had been there all along.

**One earlier step, kept because the reasoning still applies.** A store holding two
channels feeds two rows, and each row was forgetting and re-reading that store separately,
so the second threw away the files the first had just fetched. Forgetting is now shared
across the whole pass. On its own that took a thousand positions from 8 000 requests to
6 000 — real, and nowhere near enough, which is what sent us looking for the per-store
counts.

**What is left in that 6.6 s**, since it is no longer requests for descriptions: it is the
cost of building the answer to "what is open" for a thousand positions and handing the
resulting scene back through the panel. That is the same cost as opening the folder cold,
and it belongs to this item rather than to the timelapse — see the measurement above.

The measuring script is kept as `measure_many_positions.py`: it writes sparse timelapse
stores at a given number of positions, opens the viewer on them, grows one position by a
frame and counts what that sets off. Every figure in both tables comes from running it.

**Do not reach for a time limit or a size limit on what the engine remembers.** That is
the usual answer to a cache growing stale, and it is the wrong one here: a limit is what
you use when you cannot tell whether something has changed, and we can tell. It would make
the viewer slower and buy nothing. For the same reason there is nothing to tidy up when a
viewer closes — that memory lives in the page and goes when the page goes.

---

## 2. Move `build_config` out of `server.py`

About 120 lines of domain reasoning — how stores become rows, how positions merge, how
masks become their own kind — inside a closure in the HTTP module, reachable only over
HTTP. A `layers.py` taking a `Library` would make it testable without a server.

Two independent reviews raised it, and it has now cost us twice. A real bug once lived
there unseen (two runs silently drawn into one row). And when tracking down the missed
acquisition above, it was the first place suspected purely because nothing could examine
it directly — the fault was actually in `Library.revision()`, and getting there took a
server traced from the inside because neither piece could be questioned on its own.

---

## 3. The rest of the assertions that cannot fail

A review found roughly twenty. Three of the worst were fixed along the way; these remain:

- `test_masks_luts_and_refresh.py::test_it_can_be_put_back_to_a_flat_colour` — no
  assertion at all, and it waits for the *absence* of a colour map, which is the state it
  starts in.
- `test_open_and_close.py::test_the_selection_list_is_absent_unless_asked_for` — two
  `count() == 0` checks and no positive control; passes against a blank page.
- `test_under_stress.py::test_nothing_outside_an_open_folder_is_reachable` — eight cases
  that all pass if the path guard returns `None` unconditionally. Needs one assertion that
  a *legitimate* path resolves.

The pattern to apply: pair every "nothing happened" with proof the action landed. There
are now three worked examples of it in the suite (`test_a_blank_panel_would_be_noticed`,
the revision tests, and the cache tests) if you want the shape.

---

## 4. Smaller things worth doing

- **Consider revalidation instead of no-store for live data.** During a run the browser
  is told to keep nothing, which is simple and certainly correct. A middle course exists:
  let it keep a copy but require it to check, so an unchanged piece comes back as a short
  "still good" with no data. That needs the server to answer conditional requests, which
  it does not today. Only worth it if re-reading during a run ever shows up as a real
  cost — it has not been measured, and on localhost it may never matter.
- **Give the folder watcher a way to be switched off.** It exists as a safety net for
  writers that do not announce (see below). A workflow that *does* announce is paying for
  a directory scan a second for nothing.

---

## A deliberate deviation from the last hand-over

The previous list said to delete `Library.revision()` and the folder watching once the
push channel existed. The channel is built and the page no longer polls — but the
watching was **kept**, moved server-side.

The reasoning: a mesoSPIM writes its own OME-Zarr, and an operator may open the viewer on
a folder being filled by something that has never heard of us. In both cases nothing will
announce, and looking is the only way to notice. Deleting it would have removed the only
mechanism that works without the writer's cooperation — and it would have thrown away the
fix above, which was made in the same session.

What the objection was really about has been addressed: the *page* no longer asks several
times a second. The server looks once on its own behalf, however many windows are open,
and announces through the same channel. On finished data it does not run at all.
`Library.revision()` also still earns its keep as the fingerprint that lets the answer to
"what is open" be reused rather than rebuilt.

If you disagree, the thing to change is `FolderWatcher` in `announcements.py`; nothing
else depends on it.

---

## Where things stand

Branch `claude/napaly-neuroglancer-progress-jo0b8h`. The whole suite passes in about five
and a half minutes with `-n 3` — 328 tests, 8 skipped where there is no GPU or no mesoSPIM
data, and no `xfail` left. Nothing uncommitted.

**The order the next session should read this in.** Read "Start here" at the top, which is
the whole of what to do next. Item 0 — writing the run into a single OME-Zarr — is now
decided rather than proposed, and most of the difficulty described in the items below
disappears rather than being solved once a run does that. Item 1, the viewing window, is
**rejected**; the folders that are already laid out as one store per position are handled by
the batching that is built, and they will simply be slower to open than a run written into
one store, which is accepted rather than engineered around. See Decision 5 in
`DATA_LAYOUT.md`.

**How the viewer learns about new data, as it now stands.** There is no browser polling:
`/api/revision` is gone and answers 404, and a test asserts an idle viewer asks for
nothing at all. The page holds a connection open (`/api/events`) and the server speaks
down it when something changes. Two things make it speak: `POST /api/announce`, which is
the control application saying it has finished writing, and — only for live data — a
watcher that looks at the folder itself.

That watcher is the part still under discussion. The argument for keeping it is that the
mesoSPIM writes its own OME-Zarr and will never call our endpoint, so for the instrument
that exists today it is the only path. The argument against, which the operator has made
and which is sound, is that the loop belongs in the script running the acquisition: that
script knows what it wrote, whereas the watcher infers "finished" from modification
times — something a timestamp cannot actually say, and which has already given a wrong
answer twice. If you remove it, remove it *after* checking something announces, and
expect the mesoSPIM path to need the announcement wired into whatever drives it.

Two decisions are made but unbuilt, and both are in `DATA_LAYOUT.md`: **who writes the
OME-Zarr** (the mesoSPIM writes its own; our driver copies frame files and does not touch
zarr, so a writer is either a conversion step or a change to what the driver writes), and
**where a measurement belongs** — a table of intensities per object is neither pixels nor
geometry, and will come up the first time somebody classifies pixels.

One caution about the documentation, carried over from the last hand-over because it is
still the right caution. Twice in that session a conclusion was written into
`DATA_LAYOUT.md` before it was built, and both times it read as done. If you change
behaviour, check the document says so — and if it already says so, check the code agrees.
