# What to do next

A hand-over list, in the order worth doing it. Each item says what the problem is, what
is already known about it, and how you would know it was finished.

The design decisions behind all of this are in `DATA_LAYOUT.md`, which has been brought
into line with the code and should be trusted.

---

## Read this first: a large folder is drawn wrong, and says nothing

**Above about six hundred and eighty positions, the rest of the specimen never
appears, and there is nothing on screen to say so.** A folder of nine hundred
positions shows six hundred and eighty-one of them. A folder of two thousand shows
six hundred and eighty-six. The ceiling does not rise with the size of the folder,
so at forty thousand positions an operator would be looking at roughly **1.7% of
their specimen**, with the viewer presenting it as though it were the whole thing.

This is a correctness problem rather than a slow one, and it is the most serious
thing in this document.

**Why it happens.** Every position of a row is handed to the engine at the same
moment, and each one means about four small requests. A browser will only hold six
conversations at a time, and beyond a few thousand queued requests it refuses to
start any more — it says so in its own words, `net::ERR_INSUFFICIENT_RESOURCES`.
The engine records the positions whose requests were refused as unreadable and
leaves them out. Nothing is wrong with the data: the stores it gave up on read back
perfectly well afterwards, one at a time. Nothing is wrong with the server either —
it was never answering more than seven requests at once during a thousand-position
open, and was idle for two thirds of the wait.

**Where the fix belongs, which is not where it first appears to belong.** The audit
proposed pacing the loop in `syncSources` (`frontend/src/engine.js:224`). That loop
is not the one that bursts. It handles positions arriving *one at a time* during a
live run, which never overwhelms anything. When a folder is opened cold the layer
does not exist yet, so it is built by `makeLayer` from a description that already
carries **every** position in `source` (`frontend/src/scene.js:143`), and the engine
resolves the lot inside the constructor. Pacing `syncSources` alone would leave the
cold open exactly as it is. Any fix has to give the new layer a small first batch and
then feed it the rest — which is most of the machinery a viewing window needs anyway,
so the two pieces of work should be done as one rather than twice.

**Pacing was measured to work**: fed in batches of two hundred, with each batch
allowed to finish, a thousand-position folder loaded a thousand of a thousand and a
two-thousand-position folder two thousand of two thousand, with no failures at all.
It cures the silence. It does not make a large folder usable — see the next section.

---

### Two ways out, and why only one of them is the cure

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
folder two thousand of two thousand, with no failures at all.

But be clear about what it is. **Batching is a stopgap, not the answer.** It still
resolves every one of forty thousand positions, merely spread over time — still some
hundred and sixty thousand requests, still minutes before the first pixel, for a
specimen of which only a small part can be on screen at once. It makes unnecessary
work orderly rather than removing it.

### And there is a case neither of them can help

Both batching and a viewing window assume the view holds a few positions at a time.
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

The answer for navigation is item 1 below: **hand the engine only the positions in
view, and extend as the operator moves.** Then forty thousand positions cost whatever is being looked
at, and the browser's queue is never near its limit — so batching stops being needed
rather than being made to work. Do not build batching as a thing of its own; the place
it has to go is the same place the viewing window goes, and building it twice would be
the waste.

The catch is *where* it has to go, which is not where it first appears. See above:
the burst is not in `syncSources` but in the layer's construction, which is handed
every position at once. A fix in `syncSources` alone would leave a cold open exactly
as broken as it is now.

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

The sensible order is therefore: batch first, because it is the cure and it is
measured; then, if a large folder is still slower than it should be, measure whether
HTTP/2 buys enough to justify the dependency.

**What is not worth doing:** reaching past HTTP with a reader of our own inside the
engine. That is deep surgery on the one piece we chose specifically not to rewrite,
and the whole reason this viewer exists is that Neuroglancer already handles data of
this size well.

---

## Done since the last hand-over

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

## Start here: six auditors, in parallel

The target is real and it is not met: **forty thousand positions, forty terabytes.** Two
audits at that scale have run and their findings are folded into the items below, but they
covered the backend and the frontend only broadly. Put an agent on each of these briefs,
because everything found so far was in a place nobody was looking.

**The first of the six has now been run, and it is worth saying what that cost.** One
auditor, working alone on a quiet machine, took about twenty minutes and found the largest
single saving in the project so far. Running all six at once was tried and abandoned: this
machine has four processors, and six agents each driving their own browser and their own
server spend most of their time measuring each other rather than the viewer. If you want
them in parallel, give them a bigger machine or accept that every timing they report is
worthless; otherwise run them one at a time, which is what produced the result above.
Findings expressed as counts — of requests, of measurements, of renders — survive
contention and are worth asking for either way.

Of the five left, **the engine boundary (3) is the one to do next**, because the cold open
is now short enough that the engine's own fan-out is what stands between the viewer and a
large finished folder, and its answer decides whether item 1 further down is optional or
compulsory.

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
2. **The live path** — from a position being written to it appearing. Every cost paid per
   announcement, and whether any of it scales with how much is already open rather than with
   what actually changed.
3. ~~**The engine boundary**~~ — **done, and the answer is that the wall is the engine's.**
   Item 1 below is therefore **compulsory, not optional.** The audit confirmed it the
   strongest way available: with our own code taken out of the path entirely and positions
   added through Neuroglancer's own calls, the same ceiling and the same times appeared,
   within noise. In a sampled profile of a thousand-position cold open, our whole
   `syncLayers` pass came to 718 milliseconds out of twenty seconds — and 711 of those were
   inside the engine's own `addDataSource`, which we merely call. Our own arithmetic was
   about eight milliseconds. There is nothing cheap to fix on our side.

   Three separate walls were measured, and they have to be beaten together:

   - **Positions are silently lost above about 680.** See the section at the top of this
     document.
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
4. **Memory** — what the server holds after a long run and what the browser tab holds. Four
   caches never evict, and one keys on a folder number that never repeats, so opening and
   reopening leaks outright. Find the real ceiling and say when a machine gives up.
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

## 1. Hand the engine only the sources it needs

**Start here, and it is a measurement before it is a change.**

**This is no longer optional, and it is no longer a measurement.** Audit 3 has been run and
its findings are above: the wall is inside Neuroglancer, it is three walls rather than one,
and the worst of them is that positions beyond about six hundred and eighty are silently
dropped. The server's share of opening a large folder is now about twelve seconds at forty
thousand positions, so everything left is on the engine's side.

A viewing window answers all three walls at once, which is why it is the thing to build: the
number of positions the engine holds stays bounded, so it never reaches the ceiling where
positions are lost, never pays the cost that grows with the square of the number open, and
never ends up with thousands of drawing layers in a single frame.

**Stitching does not replace it.** For a finished folder, one stitched image is one source
and the problem disappears — but during a live run the positions arrive one at a time and
the count climbs past six hundred and eighty regardless, so the window is needed whatever is
decided about finished data. Stitching is worth measuring as an optimisation for finished
folders, not as a substitute.

**Build the pacing described at the top of this document as part of this**, rather than
separately. Feeding positions in bounded batches and extending as the operator navigates are
the same mechanism, and a window that lets the operator jump across the specimen would burst
past the browser's limit in exactly the same way if the feeding were not paced.

A row currently takes every position of its acquisition type at once. Each source is
resolved when it is added — roughly four small metadata requests — through a browser that
allows six connections at a time. At a few hundred positions that is fine. At several
thousand it is thousands of round trips before the first pixel.

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

**Measure before building either.** Time to first pixel with a few thousand sources on
one layer. Synthetic sparse stores cost almost nothing on disk, so this is cheap. Our own
code paths were measured to five thousand and made linear; the engine side at that scale
is still unmeasured, and it would be a shame to build the harder of the two answers and
find the easy one was enough.

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
minutes with `-n 3` — 327 tests, 8 skipped where there is no GPU or no mesoSPIM data, and
no `xfail` left. Nothing uncommitted.

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
