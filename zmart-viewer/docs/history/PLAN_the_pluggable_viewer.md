# The pluggable viewer: the shape, and the smallest way to get there

Written 3 August 2026 after a day on the microscope computer, then rewritten
against two independent critiques. The first draft proposed seven phases
including an interface rewrite. Both reviewers cut it, and one of its central
proposals turned out to be the un-enforced middle. What follows is what survived.

## The shape

```
one box
────────────────────────────
the operator's drawing        ← application
the picture                   ← the plug
the operator's drawing        ← application
────────────────────────────
one view, in micrometres
```

The application owns the box, both outer layers and the view. The plug is handed
a run and a view and draws the picture. It is never told which workflow it is in,
which step, or what the operator has done.

That shape is sound and is not in question. What follows is about the contract
around it, and about how little needs changing.

---

## The rules, after review

**What the box owes.** Three of the day's faults were the application's — passing
no coverage record, handing a drawing to a slot declared invisible, and disabling
the whole panel when a plug failed. The plug's list had nowhere to catch them:

> The application owns the view, the frame, the facts about the file, the
> operator's choices, and the arrangement. It never asks a plug a question it has
> already answered itself, and it never hands a plug work whose result it has
> been told is invisible.

**What a plug owes.**

1. **Speak micrometres, and say which.** Name the frame rather than the unit.
   Two corrections from review: the *corner-of-voxel* convention is **not**
   settled against us — the NGFF issue is still open and `VOXEL_PLACEMENT.md`
   records a deliberate position, not a fault. And handedness must **not** be
   fixed in the plug contract: `docs/how_it_works/CONTROLS.md` leaves it to the instrument, on
   purpose. The recorded mirror fault was in **x**, not y. Rotation has never
   been a fault here and cannot be — a shear is not expressible in the formats
   this project reads or writes. Keep it as a note, not as history.

   **z needs the same treatment and does not have it.** `setPlane(z)` means
   different things per engine: one computes a plane index from each image's own
   first voxel, the other writes an absolute global position.

2. **Composite.** What the plug has not drawn lets through what is behind it.
   Where the *data* is absent it should be told, in micrometres, rather than
   inferring it from brightness — an intensity test cannot tell ground nobody
   imaged from ground imaged and genuinely dark, which on a photon counter is a
   real measurement.

3. **Say when it has drawn**, and separately **whether it has finished**. The
   second does not exist. Review corrected me: it is **not** aspirational —
   neuroglancer has `viewer.isReady()`, deck.gl has `Layer.isLoaded` and
   `Deck.onLoad`, and both viewers already own an end-of-frame hook to poll from.
   It is the cheapest item here and it addresses the failure this project keeps
   meeting: blank and loading look alike.

4. **Declare what it cannot do.** Keep `drawsUnder` / `drawsUnderBecause`.
   **Do not** make it throw — `parked/contract.md` already decided the opposite for a
   stated reason (the arrangement stays genuinely the one described, so the
   comparison is not a lie), and a throw would leave the button showing a state
   the viewer is not in. A `declares` record is not needed for two booleans and
   two engines; it costs the same when a fourth question arrives.

5. **Fail alone.** Mostly the box's rule, and fixed today. The plug's half —
   an open settles or rejects in bounded time and can be told to stop — is
   deferred: the observed dead end was fixed at the application level.

6. **One reader is the authority.** The first draft said *a plug is told, never
   guesses*. That does not survive contact with neuroglancer, which reads the
   store through its own datasource layer and cannot be stopped: the option
   already contains three independent readers of the same file, and the
   half-voxel correction is applied *after* the engine has read. Reworded:

   > One reader is the authority. A plug that cannot stop its engine reading must
   > reconcile its engine's answer against the authority and **report a
   > disagreement rather than absorb it**.

   That is implementable on both engines, and the half-voxel fix already is it.

---

## What review killed, and why

**The shared reader as a phase — cut.** It would be authoritative for the Viv
plugs and advisory for neuroglancer, which cannot be stopped reading. That is the
un-enforced middle: the comparison's fairness is dissolved and the "one answer"
guarantee is not obtained.

**The bake-off-versus-product dilemma — false, and I put it badly.** The repo
already draws the line: duplicate what is about the *engine*, share what is not.
Gestures are shared on exactly that argument, and `brightness.js` **already is** a
shared reader whose own docstring makes the case. Facts about a file were always
on the shared side. The real cost of sharing is that `parked/RESULTS.md` must be
re-measured — a cost, not a matter of integrity.

**My supporting anecdote was wrong**, and the truth is a better argument: the two
engines' `imagedBounds` are **byte-identical**. It is the *harness* that adds the
origin and the two engines that do not. One reader right, two identical copies
wrong by the store's origin.

**"The page paints into an invisible slot" — overstated.** Not unconditional, and
the cost is one extra full-size canvas held on the GPU plus a sub-millisecond
clear per *scheduled* frame. A correctness smell, not a frame-rate problem.

**"z and t are lost on every engine change" — latent, not live.** The page never
calls `setPlane` or `setMoment`, and the harness already carries plane, moment and
channels across an engine change. But there is a **worse fault underneath**, and
it is probably the answer to today's mystery:

> **The two engines disagree about the default plane.** Viv opens at plane 0;
> neuroglancer opens every axis in the middle. On a 256-plane stack, pressing an
> engine button changes which slice you are looking at, with nobody calling
> `setPlane` at all.

Making the view one record does not fix that. A **default** has to be named.

**And no fixture can see it.** Every store in the tree is `shape=(1, …)` — one
plane, one moment. `setPlane` and `setMoment` are exercised by nothing. The
fixture the first draft proposed would not have caught it either.

---

## Brightness, corrected

The arithmetic was checked and the first draft was right that min/max is wrong,
but understated it. `brightness.js` takes min/max over **one arbitrary chunk**:
with data at 200–1400 and one stuck pixel at 60000 in that chunk, a mid pixel
renders at **1.0%** grey against **19.5%** under the constant it replaces. About
19× darker. The defect is the **sampling** as much as the statistic.

Two things nobody had noticed:

- Raising `low` to 200 makes background **vanish** on neuroglancer, because its
  shader keys alpha on `v > 0`. The window choice feeds the transparency test.
- The path only runs when a store has **no `omero` block at all**. A store with
  `omero` but no `start`/`end` silently gets 0–4095 and never consults the pixels.

Order of precedence: what the operator chose, else what the store declares, else
what the pixels say, else **nothing** — draw it and say the window was not
measured. No constant survives that.

---

## The plan

Roughly two days. Then stop and use it.

1. **Commit the working tree**, minus the three `TEMPORARY INSTRUMENTATION`
   blocks.
2. **Point both Viv engines at `brightness.js`** and delete their local range
   readers. Committing as things stand would make **Viv** the dark one, because
   `brightness.js` reads the sharpest level and `viv-under` still reads the
   smallest.
3. **Percentiles, 1.0 and 99.9**, over the chunk `brightness.js` has already
   read — about six lines, and it kills the stuck-pixel case without a phase.
4. **A staleness check** in `run_tests.py` and `conftest.py`. The harness bundle
   is rebuilt only when *missing*, so editing an engine and running the suite
   measures yesterday's code. The pattern to copy already guards `app/page/dist`.
5. **The writer bug — item one by value.** Every ZMART store on disk is stacked
   at the origin by anything built on `ngff-zarr`. About two lines in
   `zmart_storage/canvas.py` plus a read-back test, and it affects data already
   written.
6. **Make the foreign-store test green** — teach `boot()` to honour
   `coverage: null` as `parked/contract.md` already permits — and add a placement
   assertion in micrometres. That is the only regression net for two of today's
   four fixes.
7. **Name the default plane** in the contract, and give one fixture more than one
   z plane. Without the fixture nothing here is testable.
8. **`getView()` → `{centre, zoom, z, t}`**, and the harness carries all four.
9. **`if (!viewer.drawsUnder) drawUnder(null)`** at the two call sites.
10. **Freeze `viv-inside`** out of the live set — the page has already dropped
    it. Keep the folder and its `parked/RESULTS.md` column with a dated note.

**Cut for now:** the shared reader, the `declares` record, the abort signal, the
operator contrast control (three to four days, and the page is a bench that is
not yet driving an instrument), and the geometric edge ramp.

**Cheapest deferred item, revisit first:** the "have I finished" poll. Both
engines can answer it today.

---

## For the owner

1. Does neuroglancer stay? Three of its four "declines" were environmental and
   are fixed. Only the opaque canvas is real, and it is declared honestly.
2. Is `parked/RESULTS.md` re-measured, or frozen with a note?
3. Do the operator's channel and window choices outlive a session?
4. Does the intensity-based transparency stay until a geometric answer exists?

## Risk accepted by cutting

Origin and description readers can still drift between two engines — mitigated by
there being two rather than three, and by the placement assertion in step 6
running against both. Blank and loading stay ambiguous, which is a test-harness
cost rather than an operator one. An operator wanting a manual window has none;
two hours buys number boxes over the `setChannel` that already exists. A store
whose stuck pixels fall outside the sampled chunk still opens dark.
