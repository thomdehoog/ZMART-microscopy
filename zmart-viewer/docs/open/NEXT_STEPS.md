# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `docs/how_it_works/DATA_LAYOUT.md`, which has been brought
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

The code is in `app/page/src/engine.js` — `handOverWhatIsWaiting` and the two callers
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
That is Decision 1b in `docs/how_it_works/DATA_LAYOUT.md`, and this is the argument for it that is about
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

**This is no longer a question, it is the aim.** `docs/how_it_works/DATA_LAYOUT.md` Decision 1b states it, the
measurements behind it are in this document under item 0, and the viewer's side of it is
built and tested.

**The writer now exists too, and what is missing has moved.** `zmart_storage/canvas.py`
declares a run's images empty at the start, writes each tile straight into its place,
lengthens the run in time as moments are recorded, and keeps the smaller copies of the
image up to date as it goes. It has its own tests, and `zmart-viewer/tests/
test_canvas_written_live.py` drives it against a real browser to check that a run written
this way actually appears on screen while it is being written — which is the claim that
matters and the one the engine's own account of itself cannot settle.

What is missing now is the **acquisition using it**. Nothing in `zmart_controller` or
`workflows` calls `TileCanvases` yet; the only callers are its tests and a measurement
script. So the remaining work is not "build a writer" but "have the run write through this
one", which also means deciding where a run's canvases are created and who announces to
the viewer once a tile has landed. `docs/how_it_works/DATA_LAYOUT.md` records the decision that our driver
copies frame files and does not touch zarr, so this is either a conversion step or a
change to what the driver writes — that choice is still open and is the first thing to
settle.

The short version of why: what costs the viewer is the *number of separate stores*, not the
amount of data behind them. One store describing about 137 GB reaches the screen in 1.4
seconds on 38 requests; three hundred separate positions covering a far smaller specimen
take 2.4 seconds on 1 125 requests and then draw at a quarter of the rate. Writing into one
store as the run goes gets that benefit with **no copy and no extra step** — the tile is
written once, where it belongs.

Read item 0 below for the full evidence and for what the viewer already does. What has
changed since item 0 was written is that the two things it listed as still needing a
decision have both been decided, in `docs/how_it_works/DATA_LAYOUT.md`:

- **How large to make the image.** Sized to the ground the experiment means to cover, or —
  where the experiment does not say — **the stage's own travel limits**. Declared size is not
  occupied size (a declared 4 TiB image measured 59 MiB on disk), so across the specimen this
  can be generously over-estimated. The origin goes at the low corner and growth only ever
  goes outward, because growing backwards would shift every chunk index and invalidate
  everything already written. With the stage limits as the canvas, growth becomes impossible
  rather than merely rare, since the stage cannot reach outside them. **Depth is the one
  exception and it has since been measured:** declare `z` to the depth the run means to image,
  not to the stage's travel, or the brightness measurement comes back empty. See the first
  entry under "Done since the last hand-over" for the numbers.
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

One thing this section leaves out, and it is the operator's question rather than an oversight:
a run that means to stitch later needs its tiles kept apart with their overlap intact, which a
single canvas cannot do, since one image holds one value per voxel. Item 0b below is about that
case — letting an operator correct where a tile sits, on the layout that keeps the tiles. It
also records, at length, an arrangement that would have given both at once and does not work,
so that the next person does not spend a week rediscovering why.

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

**A generously declared depth does cost something, and it is not the clock — it is the
brightness measurement.** This was the open question left by the last session, and the
argument behind it was half right. The reasoning went: time can be declared generously
because a moment nothing was written to takes no space, but depth is the one axis the
smaller copies do *not* shrink, and the coarsest copy is what gets read to judge how
bright an image should look — so a generous depth ought to cost something real. It does.
It simply costs it in a different currency than anyone expected, and the measurement is
in `measure_declared_room.py`.

**What it does not cost.** Not disk: the same four tiles occupied 482 MB whether the
canvas around them was declared at the size imaged or thirty-two times larger, in every
axis. And not time either — a generous depth measured 64 ms against 77 ms for an honest
one, which is if anything slightly *quicker*. The reason it is quicker is the same fault
seen from the other side: the read is bounded to four planes either way, and on a
generous canvas three of those four land in places nothing was written, so there is
nothing to unpack. It is faster because it is reading emptiness. So the half of the
argument about the clock is answered, and there is nothing there.

**What it does cost.** The reader takes four planes spread evenly through the declared
depth, each cropped to a square about the middle. That is exactly right for an ordinary
stack, where every plane holds specimen, and it is a trap on a canvas, where most of the
declared depth was never imaged. Those four planes sit a third of the declared depth
apart, so a band of specimen is certain to be caught only while it is thicker than that
gap — while the declared depth is **no more than about three times the depth imaged.**
Measured on a canvas imaging sixty-four planes with the specimen in the middle, where a
run puts it:

| declared depth | times imaged | of the sample, imaged | window that came out |
| --- | --- | --- | --- |
| 64   | 1×   | 100% | (3557, 4194) |
| 192  | 3×   | 25%  | (3275, 4027) |
| 224  | 3.5× | 0%   | **(0, 1)** |
| 2048 | 32×  | 0%   | **(0, 1)** |

Past that, every sampled value is a zero, and the volume window, the histogram and the
contrast slider's Auto button all come back as `(0, 1)` — no usable range at all, with
nothing on screen or in a log to say why. A stage travels a few millimetres in z where a
stack is a few hundred microns, so declaring the travel is routinely ten to fifty times
the imaged depth. That is not near the bound; it is far past it.

Width is forgiving in the same measurement, and for a pleasant reason — the crop is taken
*about the middle*, and the middle of the travel is roughly where a specimen sits. Eight
times too much y and x still gave a sound window.

So `docs/how_it_works/DATA_LAYOUT.md` and the `canvas_shape` docstring now say the same qualified thing:
declare y and x to the stage's travel as before, and declare **z to the depth the run
means to image**. Depth never needed the generosity anyway — the reason to over-declare
is that the stage may wander further across the specimen than planned, and a run always
knows the stack it asked for.

**One thing found alongside it, not acted on, and worth someone's attention.** Every
canvas our own writer produces declares a brightness window of `start: 0, end: 65535` —
the whole range a 16-bit camera can express — because `Channel` fills the window in with
the type's limits when the caller leaves it out. The viewer honours a declared window for
the plane view, so the flat view of a canvas opens with the full 16-bit ramp while the
pixels sit between about 200 and 4 000 counts. That is the specimen rendered in the
bottom six percent of the ramp: the "real acquisitions come out black" failure that
`contrast.py` exists to prevent, arriving by the one route that module cannot defend
against, since a declared window is meant to be trusted. `Channel`'s own docstring says
the opposite of what the code does — *"Left out, the viewer measures one from the pixels,
which costs a read"* — so this is a disagreement between a docstring and its code rather
than a considered choice. Nothing in the suite catches it because every browser test that
photographs pixels passes an explicit `window=(0, 4000)`. The fix is to leave `start` and
`end` out of the block when the caller gave no window, so the viewer measures as the
docstring promises; it wants a test that opens a canvas written without one.

**A timelapse declares its length up front and fills it in, exactly as the room in space
is declared.** This settled in two steps within one session, and the second step reversed
the first, so it is worth reading as one story rather than as a change of mind.

The writer originally took a number of moments and declared that many at the start. That
was wrong in the way it was being used: the store claimed moments that had never been
imaged and the time slider ran out over frames that did not exist. The first fix was to
make the run lengthen itself — declare one moment and raise the length by one as each
frame lands — so that the store always said exactly what it held.

That fix treated the symptom. The real fault was that nothing stopped the operator
reaching a moment that was never imaged, and both halves of *that* are now fixed
independently: `written_timepoints` reads how far the images on disk reach and stops the
slider there, and the viewer opens a timelapse at its first moment rather than half way
along. (It stops at the *furthest* moment written rather than at a count of them, so a
canvas imaged at chosen moments still offers the empty ones in between — see the
docstring, which sets out why that is the lesser of the two mistakes.)
Once those exist, a store may declare whatever room it likes and the operator sees little
beyond what was recorded — so lengthening bought nothing that was still needed, while
costing something real. Changing an array's shape changes the key the engine files
decoded pieces under, so a viewer following the run re-reads the frame on screen every
time the length moves, once per moment for the whole run.

So a run now declares comfortably more moments than it could record — ten thousand is the
figure the docstring suggests — and writes into them. A moment nothing was written to
occupies no space on disk, which is checked rather than assumed: room for ten thousand
moments costs the same on disk as room for two. A frame past the declared end is refused
with an error, the same way a tile past the edge of the canvas is, rather than silently
making room — silently making room would be the lengthening arrangement again, only
harder to see. `docs/how_it_works/DATA_LAYOUT.md` carries the reversal and why the objection it originally
recorded is spent.

A time axis is also now **always** declared, where before it was left out for a run of a
single moment. That omission was a workaround for the engine drawing the wrong axes when a
time axis was present, and that is fixed: the engine is now handed the axes that measure
distance, whatever else an image has.

With that workaround gone and the length no longer moving, a store's description does not
change at all once a run has started. It only gains pieces of image.

**"Nothing has been written yet" is an answer about this moment, not for good.** Counting
the frames of a timelapse can fail to give a number for two quite different reasons, and
both used to arrive as the same answer, so both were remembered the same way: for good. A
folder holding more pieces than it is sensible to look through will never hold fewer, so
giving up on it once is right. A store that simply has not been written to yet is empty
only for the moment — it is a live run about to produce its first frame. Keeping that
answer left the viewer believing the run was empty for the rest of the session, and the
viewer meets a store at whatever moment the operator opens the folder, which during a run
is often before the first frame lands. The two are now separate answers inside
`stores.py` and only the first is kept.

**A timelapse opens at its beginning rather than half way along.** The engine opens every
axis in the middle, which is right for the axes that measure the specimen — the middle of
a stack is a sensible plane to start on — and wrong for time, which is read from the
start. It also showed on screen. An image that declares its whole intended length before
those moments have been imaged has genuinely empty moments in the middle, so opening in
the middle opened on a black screen with the recorded data sitting at the beginning,
unseen and with nothing to say so. Measured on a store declaring three moments with only
the first imaged: the view opened blank, and moving to the first moment showed the
specimen. Our own writer no longer produces that shape, but an instrument that plans its
length up front does, and being handed one is ordinary.

This is also the case the browser tests did not previously cover. Every other test of a
growing store watches tiles land while somebody is looking, which is the harder case;
opening the viewer on data written *before* it started shares none of that path, since
there is no announcement to act on and nothing decoded too early to let go of. Two tests
now open on data already written — an ordinary canvas, which always worked and is now
pinned, and the part-recorded timelapse, which drew nothing at all before.

**The two sliders are placed the way the thing they move through lies.** Depth stands
upright along the right-hand edge, the way a stack of planes is pictured; time lies along
the bottom, the way a recording is. They were two identical bars stacked in the bottom
corner, which told the operator nothing about which was which — with a hand on the stage
and both on screen, reaching for the right one meant stopping to read the labels.
Standing depth on end also makes it as long as the window allows, which is the difference
between picking out one plane of a few hundred and hunting for it. It is still one
control used twice; only the direction it runs in changes.

**One test had been failing on a switch that works.** Coming back from the volume view to
the plane was checked by asking whether the shader still emitted alpha. That stopped
being the right question when the flat view began emitting alpha itself, so that unimaged
ground comes out transparent and rows can be seen together. Both views emit alpha now,
for two different reasons. What separates them is the opacity control, which exists only
in the volume shader — seeing through the fog to the structure inside is the point of
that view, and a single plane has nothing to see through. The test asks that instead, in
both directions.

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
way `docs/how_it_works/DATA_LAYOUT.md` asks for. Of that, reading the pixels off the disk is 17
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
- **`docs/how_it_works/DATA_LAYOUT.md` promises something the code does not do.** The guidance at
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
is a real cost that Decision 2 in `docs/how_it_works/DATA_LAYOUT.md` had not accounted for: the engine files
decoded image under a key that includes the array's shape, so when the shape genuinely
changes the frame on screen is fetched again. It is bounded and it is once per growth, but
it is not free. `docs/how_it_works/DATA_LAYOUT.md` now says so.

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
in `docs/how_it_works/DATA_LAYOUT.md`, and require that every finding be **measured rather than reasoned** —
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

A seventh was proposed — what one image standing for the whole specimen costs to view —
and it has since been measured rather than assumed. The next section has the numbers, and
they are the reason several of the items above matter less than they once did.

---

## 0. Write the run into one OME-Zarr, not one per position — **decided**

**This is the aim, not a proposal.** It is recorded as Decision 1b in `docs/how_it_works/DATA_LAYOUT.md`, and
what the next session should do about it is set out under "Start here" at the top of this
document. What follows is the evidence, kept here because it is worth reading before
building anything on top of it.

> **There may be a way to have this without giving up the overlap**, which this section
> and Decision 1b both treat as the unavoidable price. `docs/how_it_works/TILES_IN_ONE_STORE.md` measures
> it: keep every tile whole in one image, each in a slot of its own, and place them where
> they truly belong when the picture is *read* rather than when it is written. Measured at
> about four times a plain read and, unlike stitching on the spot, **flat as the tile count
> grows** — the same cost per piece at 576 tiles as at 16, and the same picture voxel for
> voxel. It is not built, and one question about the coarse copies is still open, but it is
> the first arrangement measured that does not force a choice between one store and keeping
> the overlap. Read it before acting on the paragraphs below.

The two questions this section used to leave open — how large to make the image, and how to
write into it safely from more than one place at once — have both since been answered. See
"Start here", or `docs/how_it_works/DATA_LAYOUT.md` for the full reasoning.

**What costs the viewer is the number of separate stores, not the amount of data behind
them.** That sentence is the whole finding, and `measure_one_stitched_store.py` is the
evidence:

| | config | first pixel | requests | stores | drawing layers | frames in 5 s |
|---|---|---|---|---|---|---|
| one whole-specimen store, 4 096³ voxels (~137 GB) | 0.6 s | **1.4 s** | **38** | 1 | **5** | **255** |
| 300 separate positions (a few megabytes) | 0.6 s | 2.4 s | 1 125 | 300 | 302 | 62 |

That one store describes a specimen thousands of times larger and opens faster, on a
thirtieth of the requests, and then draws four times as smoothly. Every wall in audit 3
is a cost per store, so one store has none of them.

**Copying a finished folder into one image means copying everything**, which is the honest
objection to that way of arriving at it: reading every tile and writing several hundred
gigabytes out again, with both copies on disk while it runs, plus the pyramid — which is
cheaper than it sounds, adding about 14% since each level is an eighth of the one below.
That route is not offered here, and Decision 1b in `docs/how_it_works/DATA_LAYOUT.md` records why.

**A smart-microscopy run does not need it — it can write into the one store as it goes.**
The tile is written once instead of twice, and the viewer holds a single source from the
very first moment. This is the operator's suggestion and it is the better answer.

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
  as the canvas no tile can ever land outside it. See `docs/how_it_works/DATA_LAYOUT.md`.
- **The pyramid has to be kept up to date as tiles land**, which is real work during the
  run rather than after it. It is bounded — a tile only affects the levels above its own
  position — but somebody has to write it. **Still open, and it is the main piece of work.**
- **Tiles must land on chunk boundaries**, which was not known when this section was written
  and is the constraint that makes concurrent writing safe at all. Tiles straddling chunk
  edges lost up to 75% of a tile's voxels, silently. See "Start here" above.

---

## 0b. Moving a tile after it has been acquired — **the plan, one route that works, one dead end**

This is the operator's question, and it is a good one because it pulls in two directions at
once. Tiles are acquired overlapping **on purpose**, so that somebody can afterwards compare
two recordings of the same strip of specimen and work out where the stage really put each one.
Correcting that placement is stitching, and it is a scientific need rather than a convenience:
where a tile actually sits is part of the measurement. But a single image holds one value per
voxel, so a canvas cannot keep both recordings, and once tiles are written into one they are no
longer things that can be moved.

The section below says what to build, and then records at length an arrangement that looked
elegant and does not work — because it took three reviews to find the reason, and somebody will
otherwise think of it again.

### What a tile being movable actually requires

**Neuroglancer places each data source separately, and a layer may hold many.** So a tile you
can move is a tile that is its own source. A single array is one grid with one placement; there
is no way to say "shift this corner of this array by thirty pixels". This is the whole
constraint, and everything else follows from it.

That points at the layout we already have. Decision 1 keeps one store per position, each
carrying in its own metadata the size of a voxel and where on the stage it begins — and that is
already a set of separately placeable pieces. Nothing new has to be invented on disk for a tile
to be movable. What is missing is only the moving.

**A nudge is a change of metadata, not of pixels.** Every OME-Zarr image says where it sits in
its `coordinateTransformations`. Changing where a tile sits means changing numbers in a small
text file: no image is rewritten and nothing is re-encoded. Four details matter, all four were
got wrong in the first draft of this plan, and they were only found by reading the engine's own
source — so they are written down here rather than rediscovered.

- **The translation is stored per pyramid level, not once per image.** The mesoSPIM data we have
  carries a scale and a translation on *every* level, so moving a tile is several consistent
  edits rather than one. There is an optional whole-image transform that would make it a single
  edit, but it is widely ignored by other readers, so it cannot be the interoperable answer.
- **The numbers are in micrometres, and the order in the list is load-bearing.** The scale must
  come first; a translation written before it is silently scaled by the voxel size.
- **What the engine offers for editing is not where the tile is. It starts empty.** The zarr
  reader folds the acquired position into how it addresses the image and hands the editable
  placement over as *no movement at all*. So what an operator adjusts is a **correction on top
  of** the acquired position, never the position itself. This is better than it sounds: keeping
  the acquired position alongside the adjustment, which the plan wanted anyway, falls out for
  free rather than having to be arranged.
- **The conversion is simple, once the above is understood.** One unit of that correction is one
  full-resolution voxel, so the new stored value is the acquired micrometres plus the correction
  times the voxel size. Saving therefore means reading the tile's own metadata and adding to it,
  not copying a number out of the engine. Getting this wrong gives a tile that moves by the
  right-looking number and the wrong distance, which is a fault that survives a long time.

**Overlapping in the view mostly comes for free, with one correction to an earlier claim.** Two
tiles that are separate sources may sit over the same ground and the engine draws both, blending
the later over the earlier. An earlier draft said the operator could turn one tile's opacity
down to compare them; that is **not** true, because brightness, contrast, colour and opacity all
belong to the *row* rather than to each store in it, so turning one down turns them all down.
What is available per tile is showing and hiding, which gives a clean flip between two
alignments and is enough to judge one by eye. A true fade needs each tile to be its own row,
which costs a row per tile in the panel and pushes every contrast change out to all of them —
worth deciding before building, not during.

One small gift: the reader already draws an outline around each image it opens, so tiles come
with their own boundaries marked. That is a genuinely useful thing to see while aligning, and
nobody has to build it.

### The plan

**Stage 1 — one day, and it can kill the whole idea.** Before any of the rest, prove on screen
that a tile can be moved and that a source can be taken away again. Two overlapping single-tile
stores opened as one row; change one source's placement from the page and **photograph the
result to show the picture moved**; confirm both are drawn where they overlap; then remove that
source and confirm the picture changes back, that nothing is left waiting, and that a source
added *afterwards* still arrives. The fixtures for all of it already exist —
`test_writing_into_one_store.py` writes a store with a translation and `tests/pixels.py`
photographs the screen.

Three things make this the first stage rather than a formality.

**Taking a source away has never been done here, and the engine offers no plain way to do it.**
`engine.js` says in as many words that only additions are made. The engine itself has no
"remove" call either; the only route is to hand a source an empty address, which it treats as an
instruction to let go — and it declines to do so for the last source in a row, keeping an empty
placeholder instead. That is workable, since the row will always hold something else, but it is
a behaviour of a setter rather than a documented way in, so it should be pinned by a test that
counts the sources rather than one that merely looks for tiles on screen.

**And taking one away has a plausible way to wedge the whole viewer.** The loop that paces
sources waits for everything it is holding to finish being read. A source removed while it is
still loading may leave that wait with nothing left to announce, and because it is one shared
loop for the whole scene, all further feeding would stall — silently, with no error anywhere.
This is the single most likely bug in the plan, which is why it belongs on day one.

**An earlier draft proposed proving the transform by hand in the engine's own Source tab.** That
panel does exist and does have a translation row, but this viewer is built with the engine's
controls switched off, so it cannot be reached with the mouse. It can be opened from the page in
two lines. Worth knowing before relying on it: opening that panel builds a full editing grid for
*every* source in the row, so it must only ever be opened on a row holding the tiles being
adjusted, never on one still holding a whole run.

If any of the three fails, stop and say so. Everything below assumes they work.

**Stage 2 — nudging, on the layout we already have.** One store per position, overlap intact,
which is what the mesoSPIM writes today and what Decision 1 describes. Select a tile, move it
with the arrow keys or by dragging, coarse and fine. Persist the new translation into that
tile's own metadata, with two cautions. The write must be atomic — a new file moved into place,
never an edit in place, so an interrupted save cannot leave a tile with no position at all. And
the acquired position must be kept alongside the adjusted one, because a stitch that turns out
wrong has to be undoable and because the position the stage reported is itself a measurement.

Two pieces of plumbing come with it, and neither is free. The server has exactly one write today
— the targets file, into its own directory — so writing inside an *open data folder* is a new
kind of permission and needs the same guard the reads have, plus a list of which file may be
written and nothing else. And a tile whose position changed on disk will not be noticed: the
viewer re-reads a store only when its frame count moves, which a nudge does not touch. That is
the third appearance of one fault — a growing timelapse, a tile written in place, and now a
position edited in place — and the answer each time is the same: the writer says what it did.

**Stage 3 — a stitched image, if and when it is wanted.** Once the placements are right, writing
one image from them is the sanctioned answer that already exists in `docs/how_it_works/DATA_LAYOUT.md`: an honest
copy, made deliberately, that any tool can read and any backup can carry. It costs disk and a
step that has to run. That is the price, and it is worth paying for data that will be looked at
for years — but it is a separate piece of work and nothing above depends on it.

### What must not happen: this is not the rejected viewing window

Item 1 below rejects the viewer keeping its own idea of what is on screen and feeding the engine
only those positions. If tiles are ever opened *because of where the camera is pointing*, this
becomes that, and the reasoning there applies unchanged. So the rule is: **the tiles to be
adjusted come from something the operator did — this tile, or align around here — and the set
never changes as the view moves.** Whoever builds it will reach for the viewport, because that
is the easy thing, and that is why the rule is written here.

If there has to be a ceiling on how many tiles may be adjusted at once, it is refused **by name
and by count**, the way `library.py` already refuses a folder holding more than one acquisition
type. Decision 5's objection is to the viewer silently showing less than the operator asked for,
not to a refusal that says what it is refusing.

And the ceiling has to count **everything already in the scene, not the tiles being added** —
which is the opposite of what an earlier draft said. The reason is the cost documented at the
top of this file: every position registers its own place with a shared record of the scene's
extent, and every change to that record makes every layer already present work out again where
it sits. Adding a tile does that once. **So does every single press of an arrow key.** A
handful of tiles beside one image is nothing; the same handful added to a row already holding
forty thousand positions would recompute the whole scene on every nudge. Adjusting is therefore
sensible on a modest run and must be refused on a very large one, and the number that decides
it is how much is already open.

### Carving a canvas back into movable tiles — **this direction works**

There are two ways to have one store and movable tiles, they run in opposite directions, and
only one of them fails. It is worth being careful here, because the first draft of this section
condemned both and that was wrong.

**The direction that fails** is taking tiles that have already been acquired and building a
canvas out of them without copying — the next section, and it fails on where those tiles happen
to sit.

**The direction that works** is the reverse: **we** write the canvas, so we choose where the tile
boundaries fall, and they fall on chunk boundaries because we put them there. The canvas is then
the data, and each tile can be offered back to the viewer as an image in its own right — the
same chunk files under a second set of names, with a small description saying "one tile, this
shape, sitting here". We already serve the image ourselves, so this is a rule in the server
rather than anything on disk: a request for the view's chunk `(0, 0, 0)` is answered with the
canvas's chunk `(i, j, k)`. Nothing is read, decoded or copied. The engine sees an ordinary
little OME-Zarr per tile and places each one separately, which is all it needs to let them move.

**And the chunk boundaries only constrain the carving, not the moving.** Once a tile is an image
of its own, where it sits is a number in its description, not a position in a grid — so it can be
nudged by any amount at all, including a fraction of a voxel. The first draft ran these two
together and concluded that a store could not have both. It can.

There is a second route that is also not a fork, and is held in reserve: we compile the engine
as a library rather than using the published application, so a reader of our own could be
registered in our build that presents one array as many placeable pieces directly. It is more
code for the same result, and Decision 6 in `docs/how_it_works/DATA_LAYOUT.md` asks for a plain use of the engine
over a clever one, so the server rule is the one to try first.

**What no arrangement reaches, in either direction, is the overlap.** If the canvas kept one
value per voxel where two tiles met, the second recording of that strip is not hidden or
compressed away — it was never written. Moving tiles then aligns how things *look*: a seam can
be made to sit right by eye, and a bare gap opens behind whichever tile was moved. What cannot be
done is *computing* the correction, because that means comparing two recordings of the same
ground and only one was kept. That is a fact about one value per voxel, not about the engine or
the format, and no coordinate trick touches it.

So the choice is not "one store or movable tiles". It is **whether the stitch is computed from
the data or adjusted by hand.** Adjusted by hand: write the one canvas and carve views out of
it. Computed: the overlap has to survive somewhere — separate tiles, or the margins kept beside
the canvas.

### The dead end: acquired tiles linked into a canvas — **rejected, with reasons**

The idea was attractive enough to be worth recording. Keep the tiles as the data, and build the
single navigable image not as a copy but as a second set of names for the same chunk files, by
hard-linking them — a hard link being two directory entries pointing at one file on disk, so no
bytes move. The specimen would then reach the viewer as one image, fast, while every tile
remained a separately movable thing, and nothing would be duplicated.

It does not work, and the reasons are worth keeping because each one is a fact about the format
rather than an opinion.

- **A tile's corner does not land on a chunk boundary, and cannot be made to.** Where a tile sits
  is a stage position in micrometres: a real number with real error. Its position in the canvas
  is that divided by the voxel size, which is not a whole number of chunks. To link anything you
  would have to round each tile to the nearest chunk, deliberately misplacing it by up to half a
  chunk — around a hundred times *larger* than the sub-voxel error the whole exercise exists to
  correct. **This alone is fatal, and note what it does and does not say:** it is about tiles
  that arrived at positions nobody chose. When we write the canvas ourselves the boundaries are
  ours to place, which is why the previous section stands while this one does not.
- **The rule an earlier draft gave was also simply wrong.** It asked that each tile's
  non-overlapping middle be a whole number of chunks. Those middles do not fit together: between
  two of them there is a gap the width of the overlap, so a canvas built from them has a hole at
  every seam. The condition that does the intended work is on the *step* from one tile to the
  next, with each tile contributing its leading part and its far-side overlap discarded — and
  even then the previous point stands.
- **Almost none of the pyramid could be shared anyway.** A zoomed-out level can only be a
  renaming if the step divides by the chunk size *and* by the zoom factor, so with a common chunk
  size the second level already needs fifty per cent overlap and the third needs none at all. In
  practice the coarse levels are all new bytes, not the few per cent claimed.
- **The overlaps a chunk-aligned step allows are not the ones anybody uses.** With a 2048-pixel
  camera and 256-pixel chunks the available overlaps are 12.5%, 25%, 50% and so on. The ordinary
  10% is not among them.
- **It fights our own writing rule, in a way that loses data.** `docs/how_it_works/DATA_LAYOUT.md` requires each
  piece to be written to a temporary name and moved into place. Moving a file into place replaces
  the *name*, not the file — so the first time a tile chunk is rewritten the sanctioned way, the
  tile points at the new file and the canvas quietly goes on showing the old one, with nothing
  to say so. And in the other direction, writing into a canvas chunk that is still linked would
  overwrite the acquired tile. A design in which the ordinary correct way of writing corrupts
  the relationship is not one to build on.
- **It fails on the storage this actually runs on.** The real mesoSPIM data is read from a mapped
  network drive, and hard links across such shares are often refused outright. Portable drives
  formatted for exchange do not have them at all. And an ordinary copy — most backup tools, most
  archive formats — silently splits the two names apart, after which a nudge changes one and not
  the other, with nothing on screen or on disk to reveal it.
- **A store holding several images side by side is not as portable as it sounds.** OME-Zarr has
  defined layouts for multiple images, and a group of tiles beside a fused image is not one of
  them. A reader given the path to a particular image reads it perfectly well; no reader will
  *discover* them from the top of the store.

What survives from it is the honest version, which is Stage 3 above: if one navigable image is
wanted, write it, once, deliberately, as a real copy.
---

## 1. Hand the engine only the sources it needs — **rejected; do not build this**

> **Do not start here, whatever the paragraphs below say.** A viewing window — the viewer
> keeping its own idea of what is on screen and feeding the engine only those positions — was
> turned down, and for a reason that survives the argument for it: deciding which pieces of
> image to fetch from where the view is, is precisely what Neuroglancer already does, and
> better than we would. Keeping our own copy of that knowledge is how this project has got
> into trouble before.
>
> There is also a second objection, which is Decision 5 in `docs/how_it_works/DATA_LAYOUT.md`: a viewer that
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

**It is larger than "move one function", which is why it has not been done in passing.**
Counted on 2026-07-31, `make_server` is about 560 lines, and `build_config` is only the
last of them. Five functions live inside that one call and share a single piece of state
between them — the brightness measured for each store, which one of them fills in, one
reads, one decides is out of date and one throws away when an acquisition is closed. That
shared state is what keeps the five nested inside one call rather than standing on their
own — a *closure*, which is just a function that can still see the variables of the
function it was written inside. It is also why moving any one of them out alone would
either leave the state behind or make a second copy of it. What this actually wants is
a small object holding the measurements, with those five as its methods, and `layers.py`
taking that object and a `Library`. That is a real change with real risk, and it deserves
a session of its own rather than being done on the way past something else.

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
- **Consider whether `frames=` should still default to one.** A timelapse is now expected
  to declare comfortably more moments than it could record, and the default of one is
  right only for a run that is not a timelapse at all. Nobody is harmed by it — a run that
  means to record a timelapse has to say so anyway, and is refused with a clear error if
  it writes past what it declared — but a default that suits the *other* kind of run is
  worth a second look once something in `zmart_controller` is actually creating canvases.
  Note the one reason not to simply default it large: a store declaring ten thousand
  moments is handed to other OME-Zarr tools too, and those do not count what was written
  the way our viewer does, so a still image would show them a ten-thousand-frame slider.
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

Branch `claude/viewer-only`. Measured on 2026-07-31 with `ZMART_REQUIRE_BROWSER=1`:
**542 passed, 10 skipped and 2 `xfail`s in twenty minutes**, run one test at a time,
ending green. All ten skips say why and every one of
them is a piece of equipment this sandbox does not have — a graphics card, a real
acquisition through `ZMART_TEST_STORE`, a mounted mesoSPIM transfer, the opt-in search
for the browser's limit — except one, which is a measurement that has nothing to
measure on the option that draws no bottom layer and says so.

The writer has a suite of its own under `zmart_storage/tests`: **86 passed in about
thirteen seconds** on the same day. That number is worth writing down, because a figure
of "109 passed, 1 skipped" has been passed along in hand-over notes and does not match
this branch, where there are 86 tests in total and none of them skips.

**The run before it ended in a failure, and this is what that was.** It came in at 519
passed and 33 skipped, and the failure was not a broken viewer: nothing was red. The
twenty-six tests in
`test_the_options_hold_together.py` opened a browser of their own instead of taking the
one the shared fixtures hand out, and Playwright allows only one of its ordinary
connections to be alive in a thread at a time — so twenty-four of them skipped, and the
strict setting quite correctly failed a run in which part of the picture was never
looked at. `drive.Harness` now accepts a browser to borrow, the fixture lends it the
suite's own, and those tests run: **25 passed, 1 skipped**, the one skip being a
deliberate and explained one. The same run also showed that neither `run_tests.py` nor
the CI job built the page those tests open, so both now do; without that the skip came
back on any fresh checkout.

**One test in the viewer's suite is intermittent, and it is worth knowing before it
surprises somebody.** `test_masks_luts_and_refresh.py::test_a_new_acquisition_is_noticed_
quickly_and_quietly` asserts that the target list is saved at most once in the three
seconds after the page settles, and it occasionally sees two saves. It failed once in a
full serial run and once in three runs on its own; it then passed six times out of six
when the same three seconds were watched directly, and every one of those runs showed a
single `POST` and nothing else. So the second save is real but infrequent, and it has not
been pinned down.

Two things to note about it. It is **not** the load sensitivity described below — it
happens on an idle machine, and it is a count of requests rather than a threshold on a
timing. And it is worth treating as a possible fault in the page rather than assuming the
test is wrong: a list being saved twice when nothing was drawn is the same shape as the
play button that threw where nobody was pressing it. The place to look is whatever
triggers a save after the list is first read.

**`-n 3` needs more than four cores, and the way it fails is misleading.** Running three
at once is much quicker where there is room for it, and the previous hand-over recommended
it without qualification. On a four-core machine there is not room, and the failures that
result look like faults in the viewer rather than like a machine running out of breath.
Measured here on four cores: three parallel runs produced four different failures between
them, no two runs failing the same test, and every one of them passed when run on its own.
The tracebacks say plainly what was happening —

- `Page.screenshot: Timeout 30000ms exceeded` in the volume-view test. That is not an
  assertion about the picture at all; the browser could not produce a screenshot within
  thirty seconds, because three of them were ray-casting volumes in software at once.
- `coming back asked the server again for 34 of the 413 pieces it had already sent`, where
  the test allows eight. The engine's memory of decoded pieces was being evicted under
  pressure from the other browsers, so it genuinely had to fetch them again.

Neither is a fault to chase. If you have the cores, use `-n 3`; if you do not, run the
suite plainly and give it the eighteen minutes. What you should not do is take a single
parallel failure at face value — run that test on its own first, which takes a minute and
will usually pass.

**Both of those tests were looked at, and only one of them wanted changing.** The
suggestion was the same for each: have them wait on the engine's own account of what it
has drawn, the way the `timelapse_page` fixture already does, instead of on a threshold
tuned for a quiet machine. It was right about one and wrong about the other, and the
difference is worth keeping so that nobody re-attempts the second.

**The volume test now waits on the engine, and it was worth doing.** It used to sleep a
flat four seconds after switching to the volume view, on the reasoning that a ray-cast
needs longer than a slice. Measured, the volume is ready in about a quarter of a second,
so the four seconds was mostly idling — slow when it passed, and not necessarily generous
enough when the machine was busy, which is the worst of both. It now waits for the
drawing layers to report that what they need has arrived.

One detail in it is load-bearing. Switching to the volume view does not *replace* the
drawing layers, it adds to them — eleven while showing slices, fourteen while showing a
volume, one extra per image on screen. So asking only "has everything arrived?" straight
after the click is answered *yes* by the slice layers, which are still loaded and still
satisfied, and the test would photograph the panel before the volume existed. Waiting for
the count to grow first is what makes the rest of the condition mean the volume.

**The re-fetch test was left exactly as it is, because the change does not work.** The
theory was that its ceiling of eight re-fetched pieces was a threshold problem. It is not.
Measured over nine journeys, taking the mark after waiting for the engine to settle rather
than after a fixed two and a half seconds gave **the same answer every single time** — the
count came out 0, 4 or 8 depending on the run, and identical under both ways of measuring.
There is no timing artefact to remove.

What is actually happening is that the engine genuinely lets go of about one coarse plane
on some journeys. The eight pieces are always the same shape — one z plane at one pyramid
level, both channels, four tiles — which is a coherent thing to release rather than a sign
that nothing is kept. The test's allowance is a proportion of the outbound traffic
(`went_away // 50`), which for these journeys lands between seven and ten, so it sits right
on top of a spread of nought to eight and is decided by which side of the line a run falls.
It failed here once at eight against an allowance of seven, and then passed six times out
of six run alone and twice more beside another browser test.

So the ceiling is not tuned for an unloaded machine; it is tuned to a real behaviour whose
spread it barely clears. If it becomes a nuisance, the thing to change is the allowance —
it should be a plain statement about how much the engine may let go of, which the shape of
the re-fetches suggests is one plane — and **not** the waiting, which has been measured and
makes no difference. Leaving it alone remains defensible: the test still asks the right
question, and the docstring already says what it is really guarding against is the whole
return leg arriving again rather than a stray piece or two.

**The two `xfail`s, because both are real gaps and neither is a flaky test.**
Both are marked strict, so each will announce itself the moment somebody fixes what it
is waiting for.

The first is `test_the_drawing_rate_should_barely_depend_on_how_many_positions_are_open`,
in `test_the_drawing_keeps_up.py`. It states the drawing rate the viewer ought to keep
when ten times as many positions are open, which it does not: the cost per position is
paid on every frame. The cause and the fix are the architectural change described further
up this document.

The second is `test_each_acquisition_type_gets_a_row_of_its_own`. The viewer still gathers
every image in a folder
into a single row, as though they were positions of one acquisition. Both are drawn now
that unimaged ground is transparent, but they share one row's contrast, colour and
visibility — so an overview and a target scan cannot be adjusted apart, which is
something an operator will want to do almost immediately. The grouping in `stores.py`
assumes a folder of positions and has to learn that one image can be a whole acquisition
type. That is the natural next piece of work on the panel.

**Setting a machine up to run the browser tests.** They need the viewer page built
(`npm --prefix app/page install && npm --prefix app/page run build`) and a Chromium that
Playwright can launch. Without the build the browser tests skip, and a build older than
the source is a hard failure rather than a skip — that check exists because a session was
once spent drawing confident conclusions from a bundle two days stale.

**The order the next session should read this in.** Read "Start here" at the top, which is
the whole of what to do next. Item 0 — writing the run into a single OME-Zarr — is now
decided rather than proposed, and most of the difficulty described in the items below
disappears rather than being solved once a run does that. Item 1, the viewing window, is
**rejected**; the folders that are already laid out as one store per position are handled by
the batching that is built, and they will simply be slower to open than a run written into
one store, which is accepted rather than engineered around. See Decision 5 in
`docs/how_it_works/DATA_LAYOUT.md`.

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

Two decisions are made but unbuilt, and both are in `docs/how_it_works/DATA_LAYOUT.md`: **who writes the
OME-Zarr** (the mesoSPIM writes its own; our driver copies frame files and does not touch
zarr, so a writer is either a conversion step or a change to what the driver writes), and
**where a measurement belongs** — a table of intensities per object is neither pixels nor
geometry, and will come up the first time somebody classifies pixels.

One caution about the documentation, carried over from the last hand-over because it is
still the right caution. Twice in that session a conclusion was written into
`docs/how_it_works/DATA_LAYOUT.md` before it was built, and both times it read as done. If you change
behaviour, check the document says so — and if it already says so, check the code agrees.
