# Does a commit decide the picture, when the picture comes from the real writer?

This folder holds one browser test. It opens a real Neuroglancer on a real run,
photographs the screen, and asks a single question:

> A position has been imaged and every one of its files is on disk, complete and
> correct — but nobody has published it yet. Is it on the operator's screen?

The answer must be no, and it must stay no until the position is committed. That
is the promise the whole live-publication design rests on, and it is the kind of
promise that is easy to state and easy to lose.

## What is different about this test

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

## The three steps

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

## What the server refuses, and why it is refused there

The rule is that a position becomes visible only once it has been committed.
Files on disk mean nothing. A server that handed over pixels the moment they were
written would break that rule however careful the viewer was, so the rule is
enforced at the one place every reader has to come through: this server refuses
every piece of image belonging to a position whose committed revision is still
zero.

Two things about that refusal matter.

It reads the answer from `RunManifest`, the run's own publication record, not from
a list kept by hand. A hand-kept list is a second opinion about what is published,
and a gate that can drift away from the thing it is testing is not a gate.

And it works out *which* position a piece belongs to using
`zmart_live.coarse.contributors_to`, the same production function the publisher
uses to decide which pieces a commit must rebuild. Nothing here re-derives the
geometry. A piece of image the server cannot account for at all is refused rather
than served, because a piece nobody can attribute might belong to a position
nobody has published.

Every answer is sent with `Cache-Control: no-store`. Without it the browser can
answer a later question from its own memory of an earlier refusal, and the picture
stops being evidence about what the server was willing to serve.

## The run itself

Two neighbouring positions of one confocal mosaic, written at this project's own
frame size — 1152 pixels square, which is nine stored pieces of 128 across — with
a single plane and one colour. The storage plan chooses a 128-pixel overlap, and
each position gives the shared strip to one neighbour rather than both, so the
run-wide picture shows 2048 pixels of specimen across and 1024 down:

* **A** is the left tile, shown from x=0 to x=1024.
* **B** is the right tile, shown from x=1024 to x=2048.

The viewer opens **one** image: the run's seamless overview at
`views/overview-seamless.ome.zarr`. That is the rule `zmart_live/scene.py` exists
to protect — the drawing engine is handed one source per view and never one per
position. It also makes the question fair: because both positions live in one
image whose declared extent covers them both from the first moment, "B is not
drawn" cannot be satisfied by a layer that simply never opened. The layer is there
throughout, and only the pieces behind its right-hand half change.

The page draws into a box of 1024 by 512, so at two specimen pixels per screen
pixel the mosaic fills it exactly: the left half of the box is always A's ground
and the right half is always B's, in every photograph and at every step.

## Proving the test can fail

A passing test tells you nothing until you have watched it fail for the right
reason. `check-the-production-test-can-fail.mjs` runs the whole sequence three
times: once honestly, and once for each of two deliberate faults, each aimed at
one half of the middle step's claim.

* **B is published early.** During the step that expects B hidden, B is committed
  by the real publisher — which goes and inspects the files and moves the record
  only because what it finds justifies it. No image changes. The claim that B is
  not on the screen must catch this.
* **The server refuses everything.** It behaves as though nothing had ever been
  published, so the screen goes black. B is still not drawn, so the first claim
  still holds; the claim that A is still there must catch it.

Both have been run and both go red, on the assertions they were aimed at. The
photographs of the broken runs are kept in `photographs/deliberately-broken-*/`,
apart from the honest ones, so that a black screen can never end up filed under a
name that says the test passed.

## Running it

Everything runs from the operator page's folder, because that is where the
JavaScript packages live.

```
cd workflows/target_acquisition/webapp-ui

# the test itself, about 45 seconds
npx playwright test --config ../../../zmart_live/tests/browser/production/playwright.config.mjs

# the test, plus both deliberate faults, about three minutes
node ../../../zmart_live/tests/browser/production/check-the-production-test-can-fail.mjs
```

To look at the run yourself rather than through the test, start the server by hand
and open the address it prints:

```
python -m zmart_live.tests.browser.production.production_run \
    --folder /tmp/a-real-run --port 8792 --publish-the-first-position
```

Then drive it with the control requests listed at the top of `production_run.py`:
`publish`, `write-everything-except-the-commit`, `commit`, and `state`.

## Two things worth knowing before you change anything

**The picture carries no voxel size.** The run-wide picture the publisher writes
is a plain Zarr array: no voxel size, no units, no axis names. Turning a run into
an image a viewer can interpret is the job of `zmart_live/scene.py`, and it is not
part of what this test checks. So the page's own aiming — which reads the voxel
size out of the store — finds nothing to work with, and the test says where to
look instead: which axes go on screen, where the middle of the mosaic is, and how
many specimen pixels fall in one screen pixel. Nothing else about the page is
changed, and the page is shared with the older test rather than copied.

**Only one zoom level is served.** The publisher writes the run-wide picture at
full resolution only, so the engine fetches full-resolution pieces and shrinks
them itself. That is what a viewer would genuinely do today. A picture with
zoomed-out copies of its own would raise a further question worth a test of its
own — a single zoomed-out piece can cover two positions at once, so it cannot be
half published — and mixing that question in here would make neither of them
clear.
