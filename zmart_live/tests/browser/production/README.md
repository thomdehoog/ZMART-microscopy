# Does a commit decide the picture, when the picture comes from the real writer?

This folder holds three browser tests. Each opens a real Neuroglancer on a real
run, photographs the screen, and asks one form of a single question:

> Some pixels have been imaged and every one of their files is on disk, complete
> and correct — but nobody has published them yet. Are they on the operator's
> screen?

The answer must be no, and it must stay no until the commit is made. That is the
promise the whole live-publication design rests on, and it is the kind of promise
that is easy to state and easy to lose.

The three tests differ only in *what* is waiting to be published, and the reason
there are three is worth reading before anything else here. The first test images
two tiles at one moment in time, and it passes. A run of that shape happens to be
the one shape in which two quite different mistakes are both invisible, and the
other two tests are the smallest runs that can see them. See **Two ways the gate
can be right about the wrong thing**, below.

## What this folder is not: it is not the application path

This needs saying at the top, because everything below could be read as evidence
about the viewer an operator actually uses, and it is not.

The server in this folder is written in this folder. It is not
`zmart-viewer/backend`. Nothing here goes through `ViewRoute`, nothing here
discovers a scene the way the application discovers one, and nothing here uses the
production refresh — the page is told to go back to the store by calling
Neuroglancer's own internal `invalidateCache()` on each of its readers, by hand,
from the test. A real viewer is not driven that way.

What these tests genuinely prove is narrower than "the application is safe", and
it is still worth having. Every pixel on screen was written, inspected and
committed by `LivePublisher` — the production writer — and a real drawing engine
is watched while a manifest-aware gate is applied. The application backend now
uses the shared `zmart_live.gateway` and has a real-HTTP regression that withholds
and then byte-routes the same chunk. What is **still not** proved here is the full
browser chain through that backend, scene discovery, and automatic production
refresh. This suite and the backend integration test cover different boundaries;
neither should be described as the other.

## What is different about these tests

There is an older test one folder up, `commit-gates-the-picture.spec.mjs`, which
asks exactly the same question. It is a good test and it left one honest gap,
written down as finding 4 of `docs/design/codex-review-findings.md`: it writes its
two positions with a small purpose-built writer of its own. Nothing the browser
saw there had passed through `zmart_live/coordinator.py`, so if
`LivePublisher` had stopped publishing in the right order, that test would have
gone on passing.

Here every position on screen was written, inspected and committed by
`LivePublisher.write_and_publish` — the same call a real acquisition makes. The
pixels, the zoomed-out copies, both run-wide pictures, the arrangement and the
commit all come from production code. Nothing in this folder writes an image or
moves the publication record itself.

## The first test, step by step

```
publish position A                      ->  A is drawn.  B is not.
write position B, stopping one step
  short of the commit                   ->  A is still drawn, just as brightly.
                                            B is still not drawn.
commit position B                       ->  both are drawn.
```

The middle step is the whole point, and it is also where a test like this quietly
goes wrong. "B is not drawn" is satisfied perfectly by a completely black
screen — by a page that never opened, an engine that never started, a run that was
never served. So the middle step always makes **both** claims at once: B is not
drawn, *and* A still is, and just as much of A as before. A black screen fails the
second claim on the spot.

### Why the middle step writes more than the pixels

If the middle step only wrote B's pixels into B's own store, B would be invisible
for a reason that has nothing to do with commits: there would simply be nothing to
draw in the picture the viewer is reading. The gate — the thing under test — would
never have been asked a question.

So the middle step runs the publisher's ordered sequence and stops one step short.
B's pixels land, both run-wide pictures are rebuilt to include them, the
arrangement is written, and the commit is not made. B's pixels are now genuinely
sitting in the very image the browser is reading. The only thing between them and
the screen is that nobody has published B.

That is not an artificial state. It is the state a microscope passes through for a
moment on every position it images, and the state it would be left in for good if
the software stopped between writing and committing.

The last step then calls `publish` on its own. Between the middle step and the
last one **not one byte of image changes**; the commit is the entire difference.

### The list of steps checks itself

Stopping a sequence part-way through means performing its steps one at a time,
and a copied list like that can quietly fall behind the method it copies. So
before the server starts, `production_run.py` reads what
`LivePublisher.write_and_publish` actually does and refuses to run if the two have
drifted apart. Reading the code is a blunt way to check; it is the right one,
because the alternative is a silent and confident test of the wrong thing.

## Two ways the gate can be right about the wrong thing

Both of these were real faults in this server. Both were found by a reviewer,
reproduced here by a browser test that went red, and then fixed. They are written
down at length because neither is obvious, and because a run of two tiles at one
moment — which is what the first test images — cannot see either of them.

### A stop on the tile slider is not a tile

The publisher writes two run-wide pictures. The seamless one crops each tile so
that no piece of specimen appears twice, and it is the one an operator navigates
by. The other keeps every pixel every tile recorded, overlaps included, so that
somebody can look at whether the microscope agreed with itself along a seam. Since
two overlapping tiles hold two genuinely different measurements of the same place,
that second picture gives each tile a *stop* on a slider and the operator steps
between them.

There is deliberately not one stop per position. On a real run that would be a
slider with five thousand stops, nearly all of them empty wherever the operator
happens to be looking. Instead the stops are shared out like the squares of a
chessboard: tiles far enough apart that they cannot possibly overlap are given the
same stop. With this project's frame size and overlap there are four stops in
total, however large the run grows.

That sharing is the right arrangement, and it has a consequence that is easy to
miss. **A stop names a scattering of tiles across the whole mosaic, not one
tile.** In a row of three, the first and the third tile share a stop. This server
used to read the stop out of a piece's address and stop there — so it called the
third tile's pixels the first tile's, and handed them over the moment the first
tile was committed, with the third still unpublished. Watching the screen with
three tiles in a row, the third tile was fully drawn, and the server's own tally
showed every one of its pieces served under the first tile's name.

The fix is that a piece of that picture is attributed by its stop **and** the
ground it covers together. Asking which of the tiles at that stop actually
photographed that ground gives exactly one answer, because the publisher refuses
to write the picture at all unless tiles sharing a stop share no specimen.

### A position is not published all at once

A position is committed one moment in time at a time. Once its first moment has
been published, "has this position been published?" is answered yes for ever
after — including for a second moment written a second ago that nobody has
committed. This server used to ask exactly that question, so the second moment
went straight to the screen. A run holding a single moment can never notice.

The fix is that the gate looks up a position **and** a moment together. The moment
is not guessed: every stored piece carries it as one of the numbers in its address.
Which moments of a position have actually been committed is read out of the run's
own history of publications, where an entry that names no moment is the one that
introduced the position and therefore made its first moment visible.

## What the server refuses, and why it is refused there

The rule is that pixels become visible only once they have been committed. Files
on disk mean nothing. A server that handed them over the moment they were written
would break that rule however careful the viewer was, so the rule is enforced at
the one place every reader has to come through: this server refuses every piece of
image belonging to a moment of a position that has not been committed.

Three things about that refusal matter.

It reads the answer from `RunManifest`, the run's own publication record, not from
a list kept by hand. A hand-kept list is a second opinion about what is published,
and a gate that can drift away from the thing it is testing is not a gate.

What it looks up is a position and a moment together, never a position on its own,
for the reason given just above.

And it works out *which* position and moment a piece belongs to from the piece's
own address, using production geometry rather than any rule invented here: the
moment is one of the numbers in the address; the position comes from
`zmart_live.coarse.contributors_to` for the seamless picture — the same production
function the publisher uses to decide which pieces a commit must rebuild — and
from the tile slider's stop together with the ground covered for the picture that
keeps every overlapping pixel. Nothing here re-derives the geometry. A piece of
image the server cannot account for at all is refused rather than served, because
a piece nobody can attribute might belong to something nobody has published.

Every answer is sent with `Cache-Control: no-store`. Without it the browser can
answer a later question from its own memory of an earlier refusal, and the picture
stops being evidence about what the server was willing to serve.

## The runs themselves

Every run here is a row of neighbouring positions from one confocal mosaic,
written at this project's own frame size — 1152 pixels square, which is nine
stored pieces of 128 across — with a single plane and one colour. The storage plan
chooses a 128-pixel overlap, so the stage moves 1024 pixels between tiles. How
many tiles the row holds, and how many moments in time each of them holds, are
chosen when the server starts: `--tiles-in-a-row` and `--moments`.

**Two tiles, one moment**, for the first test. Each position gives the shared
strip to one neighbour rather than both, so the seamless picture shows 2048 pixels
of specimen across and 1024 down: **A** from x=0 to x=1024, **B** from x=1024 to
x=2048. The page draws into a box of 1024 by 512, so at two specimen pixels per
screen pixel the mosaic fills it exactly, and the left half of the box is always
A's ground while the right half is always B's, in every photograph and at every
step.

**Three tiles, one moment**, for the test about the tile slider. A, B and C sit
side by side, and A and C land on the same stop — the whole point. That test opens
the picture that keeps every overlapping pixel, at that shared stop, where each
tile's *whole* 1152-pixel frame is kept rather than cropped. The row therefore
reaches 3200 pixels across and 1152 down. At three and an eighth specimen pixels
per screen pixel it fills the width of the box: A occupies the leftmost 369 pixels
of it, C the rightmost 369, and the 287 pixels between them are ground that no
tile at this stop photographed, which stay black throughout. B sits at a different
stop and is not on screen at all.

**Two tiles, two moments**, for the test about moments. Both are published at the
first moment, and B alone is published at the second. That test opens the seamless
picture at the second moment, where the same halves mean the same things.

In every case the viewer opens **one** image, never one per position. That is the
rule `zmart_live/scene.py` exists to protect — the drawing engine is handed one
source per view, because every source it is handed becomes a layer that takes part
in every frame for as long as the viewer is open. It also makes each question
fair: because every position lives in one image whose declared extent covers them
all from the first moment, "this one is not drawn" cannot be satisfied by a layer
that simply never opened. The layer is there throughout, and only the pieces
behind part of it change.

## Proving the tests can fail

A passing test tells you nothing until you have watched it fail for the right
reason. Each of these three tests makes its claim in the same three steps, and the
middle step always makes **two** claims at once rather than one:

```
the thing under test is not written yet   ->  the rest of the run is drawn.
it is written, and not committed          ->  the rest of the run is still drawn,
                                              just as brightly — and the new thing
                                              is not.
it is committed                           ->  now it is drawn too.
```

The second half of that middle step is not decoration. "It is not drawn" is
satisfied perfectly by a completely black screen: by a page that never opened, an
engine that never started, a run that was never served. Insisting in the same
breath that everything else is still on screen, and still as bright as it was, is
what stops a black screen passing for a working gate.

`check-the-production-test-can-fail.mjs` therefore runs two deliberate faults
against every one of the three tests, one aimed at each half of its middle step.

* **Something is published early.** During the step that expects it hidden, it is
  committed by the real publisher — which goes and inspects the files and moves
  the record only because what it finds justifies it. No image changes. The claim
  that it is not on the screen must catch this.
* **The server refuses everything.** It behaves as though nothing had ever been
  published, so the screen goes black. The thing under test is still not drawn, so
  the first claim still holds; the claim that everything else is still there must
  catch it.

All six have been run and all six go red, on the assertions they were aimed at.
Each fault is run against only the test it is aimed at, because a fault that makes
one test go red says nothing about the two it never touched. Before any of them
runs, the script asks the runner for the titles of every test in this folder and
refuses to continue if a fault names one that no longer exists — otherwise a
reworded title would silently run nothing at all and be recorded as a success,
which is the most comfortable and most misleading answer this file could give.

The photographs of the broken runs are kept in
`photographs/deliberately-broken-*/`, apart from the honest ones, so that a black
screen can never end up filed under a name that says the test passed.

## Running it

Everything runs from the operator page's folder, because that is where the
JavaScript packages live.

```
cd workflows/target_acquisition/webapp-ui

# all three tests, a little under two minutes
npx playwright test --config ../../../zmart_live/tests/browser/production/playwright.config.mjs

# one of them on its own, about half a minute
npx playwright test --config ../../../zmart_live/tests/browser/production/playwright.config.mjs \
    --grep "sharing a slider stop"

# the three tests, plus all six deliberate faults, about five minutes
node ../../../zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs
```

To look at a run yourself rather than through the tests, start the server by hand
and open one of the two addresses it prints:

```
python -m zmart_live.tests.browser.production.production_run \
    --folder /tmp/a-real-run --port 8792 \
    --tiles-in-a-row 3 --moments 2 --publish-the-first-position
```

Then drive it with the control requests listed at the top of `production_run.py`:
`publish`, `write-everything-except-the-commit`, `commit`, and `state`. Each of
the first three takes a position and, if the run has more than one moment, a
moment as well — `?position=A&moment=1`.

## Three things worth knowing before you change anything

**The pictures carry no voxel size.** The run-wide pictures the publisher writes
are plain Zarr arrays: no voxel size, no units, no axis names. Turning a run into
an image a viewer can interpret is the job of `zmart_live/scene.py`, and it is not
part of what these tests check. So the page's own aiming — which reads the voxel
size out of the store — finds nothing to work with, and each test says where to
look instead: which axes go on screen, where the middle of the mosaic is, how many
specimen pixels fall in one screen pixel, and which moment and which stop on the
tile slider to sit at. Nothing else about the page is changed, and the page is
shared with the older test rather than copied.

**Only one zoom level is served.** The publisher writes both run-wide pictures at
full resolution only, so the engine fetches full-resolution pieces and shrinks
them itself. That is what a viewer would genuinely do today. A picture with
zoomed-out copies of its own would raise a further question worth a test of its
own — a single zoomed-out piece can cover two positions at once, so it cannot be
half published — and mixing that question in here would make neither of them
clear.

**Every run here is one row.** The positions sit side by side along a single row
of the scan pattern, which keeps the picture on screen easy to read and is enough
for every question asked here. A mosaic several rows deep would share stops on the
tile slider in two directions at once rather than one. Nothing about the
attribution in `production_run.py` assumes a single row — it asks which tile at a
stop covers a piece of ground, whatever shape the grid is — but no test in this
folder has watched a screen and confirmed it.
